"""Self-contained Spotify OAuth: PKCE authorization-code flow over a loopback
redirect, token cache at ~/.config/mal-openings/auth.json (mode 0600), and
automatic refresh. No third-party auth libraries.

The user must register the EXACT redirect URI (default
http://127.0.0.1:8399/callback) in their Spotify app's Redirect URIs list.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from . import config, logkit

AUTH_BASE = "https://accounts.spotify.com"
TOKEN_URL = AUTH_BASE + "/api/token"
AUTHORIZE_URL = AUTH_BASE + "/authorize"
DEFAULT_PORT = 8399
SCOPES = "playlist-read-private playlist-modify-private playlist-modify-public"


class AuthError(RuntimeError):
    pass


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def load_cache() -> dict | None:
    return config.read_json(config.auth_path())


def save_cache(d: dict) -> None:
    config.write_json(config.auth_path(), d, private=True)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict | None = None

    def do_GET(self):  # noqa: N802 (http.server API)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(parsed.query)
        type(self).result = {k: v[0] for k, v in q.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if "code" in q:
            self.wfile.write(b"<h2>mal-openings: login OK.</h2>"
                             b"<p>You can close this tab.</p>")
        else:
            self.wfile.write(b"<h2>mal-openings: login failed; see terminal.</h2>")

    def log_message(self, format, *args):  # silence
        pass


def run_pkce_login(client_id: str, port: int = DEFAULT_PORT,
                   open_browser: bool = True) -> dict:
    """Interactive login: opens browser, waits for the loopback redirect,
    exchanges the code, writes the cache. Returns the token dict."""
    logger = logkit.get_logger()
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

    _CallbackHandler.result = None
    httpd = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    logger.info("[auth] listening on %s", redirect_uri)
    logger.info("[auth] if your browser does not open, visit this URL yourself:")
    print("\n  " + url + "\n", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    deadline = time.time() + 300
    try:
        while _CallbackHandler.result is None and time.time() < deadline:
            time.sleep(0.25)
    finally:
        httpd.shutdown()
        httpd.server_close()

    res = _CallbackHandler.result
    if res is None:
        raise AuthError("no redirect received within 5 minutes — did you complete "
                        "the login in the browser and is the port free?")
    if "code" not in res:
        raise AuthError(f"Spotify returned an error: {res.get('error', res)}")
    if res.get("state") != state:
        raise AuthError("state mismatch on callback — possible CSRF, aborting")

    tok = _token_request(client_id, {
        "grant_type": "authorization_code",
        "code": res["code"],
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    })
    tok["client_id"] = client_id
    tok["redirect_uri"] = redirect_uri
    save_cache(tok)
    logger.info("[auth] token saved to %s (0600)", config.auth_path())
    return tok


def _token_request(client_id: str, fields: dict) -> dict:
    body = urllib.parse.urlencode({"client_id": client_id, **fields}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=25))
    except urllib.error.HTTPError as e:
        raise AuthError(f"token endpoint HTTP {e.code}: "
                        f"{e.read().decode(errors='replace')[:200]}") from e
    out = {
        "access_token": d["access_token"],
        "refresh_token": d.get("refresh_token"),
        "token_type": d.get("token_type", "Bearer"),
        "scope": d.get("scope", SCOPES),
        "expires_at": time.time() + int(d.get("expires_in", 3600)) - 60,
    }
    return out


def ensure_token(cache: dict | None, client_id: str | None) -> str:
    """Return a valid access token, refreshing from cache when needed.

    Raises AuthError when there is no usable cache or refresh fails — the CLI
    turns that into a 'run --auth first' message.
    """
    logger = logkit.get_logger()
    if not cache or "access_token" not in cache:
        raise AuthError("not logged in — run: mal-openings --auth")
    if cache.get("expires_at", 0) > time.time():
        return cache["access_token"]
    cid = client_id or cache.get("client_id")
    if not cid:
        raise AuthError("token expired and no client id configured "
                        "(--client-id, MALOP_CLIENT_ID, or config.json)")
    if not cache.get("refresh_token"):
        raise AuthError("token expired and no refresh token — run: mal-openings --auth")
    logger.info("[auth] refreshing token…")
    new = _token_request(cid, {
        "grant_type": "refresh_token",
        "refresh_token": cache["refresh_token"],
    })
    # Spotify may rotate the refresh token; keep the old one if absent.
    new["refresh_token"] = new.get("refresh_token") or cache["refresh_token"]
    new["client_id"] = cid
    new["redirect_uri"] = cache.get("redirect_uri", "")
    save_cache(new)
    return new["access_token"]
