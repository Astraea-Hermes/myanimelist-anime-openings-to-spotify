"""Minimal Spotify Web API client (stdlib only).

IMPORTANT — 2026 endpoint migration (verified live 2026-10-17): new dev-mode
apps are bound to the migrated playlist-item endpoints. The pre-2026
/playlists/{id}/tracks endpoints return 403 for them. This client therefore
uses ONLY:

  * POST   /me/playlists                     create playlist
  * POST   /playlists/{id}/items             add items  {"uris": [...], "position": n}
  * GET    /playlists/{id}/items             read items (response key "items",
                                             each row wraps the track in "track"...
                                             migrated shape: row["item"] or row["track"])
  * DELETE /playlists/{id}/items             remove items {"items": [{"uri": ...}]}
  * PUT    /playlists/{id}                   edit (e.g. {"public": false})
  * GET    /tracks/{id} / /tracks?ids=...    direct metadata
  * GET    /search?type=track...             fallback resolution

Dev-mode also reports public:true untrustworthily; privacy is checked by an
ANONYMOUS read, not by the field (see verify_private).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import logkit
from .spotify_auth import ensure_token, load_cache, AuthError

API = "https://api.spotify.com/v1"

# A 429 whose Retry-After exceeds this bound (observed live 2026-10: dev-mode
# search cooldowns of ~21h after bursts) is not worth sleeping through in one
# process — raise so the run checkpoints and a later rerun resumes.
MAX_WAIT_SECONDS = int(os.environ.get("MALOP_MAX_WAIT", "300"))


class SpotifyError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class SpotifyQuotaError(SpotifyError):
    """Rate-limited with a Retry-After longer than MALOP_MAX_WAIT."""


class SpotifyClient:
    def __init__(self, cache: dict | None, client_id: str | None = None):
        self._cache = cache or {}
        self._client_id = client_id
        # Once a 429 says the cooldown is longer than MAX_WAIT_SECONDS, stop
        # hammering /search for the rest of the run; direct-id lookups keep
        # working (they are quota-cheap) — that asymmetry is by design.
        self.search_cold = False

    # ---------------- transport ----------------
    def _token(self, force: bool = False) -> str:
        if force or self._cache.get("expires_at", 0) <= time.time():
            tok = ensure_token(self._cache, self._client_id)  # persists a new cache
            self._cache = load_cache() or self._cache
            return tok
        return self._cache.get("access_token", "")

    def call(self, path: str, method: str = "GET", body: dict | None = None,
             tries: int = 5) -> dict | None:
        """Authenticated call with 401-refresh-once and Retry-After-aware 429."""
        logger = logkit.get_logger()
        data = json.dumps(body).encode() if body is not None else None
        refreshed = False
        for k in range(1, tries + 1):
            headers = {"Authorization": "Bearer " + self._token(force=False)}
            if data is not None:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(API + path, data=data, method=method,
                                         headers=headers)
            try:
                raw = urllib.request.urlopen(req, timeout=25).read().decode()
                return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                payload = e.read().decode(errors="replace")[:300]
                if e.code == 401 and not refreshed:
                    refreshed = True
                    logger.warning("[spotify] 401 -> refreshing token once")
                    try:
                        self._token(force=True)
                        continue
                    except AuthError as ae:
                        raise SpotifyError(f"auth expired: {ae}", 401) from ae
                if e.code == 429:
                    ra = e.headers.get("Retry-After")
                    raw_wait = int(ra) if ra and ra.isdigit() else 10 * k
                    if raw_wait > MAX_WAIT_SECONDS:
                        if path.startswith("/search"):
                            self.search_cold = True
                        raise SpotifyQuotaError(
                            f"429 on {path}: Retry-After={raw_wait}s exceeds "
                            f"the {MAX_WAIT_SECONDS}s wait bound "
                            f"(raise MALOP_MAX_WAIT to sleep through it)") from e
                    logger.warning("[spotify] 429 on %s (Retry-After=%s) — waiting %ds "
                                   "(attempt %d/%d)", path, ra or "-", raw_wait,
                                   k, tries)
                    logkit.sleep_with_countdown(raw_wait, "Spotify 429")
                    continue
                if e.code == 404:
                    return None
                raise SpotifyError(f"HTTP {e.code} on {method} {path}: {payload}",
                                   e.code) from e
            except Exception as e:  # network hiccup
                if k == tries:
                    raise SpotifyError(f"network failure on {method} {path}: {e}") from e
                logger.warning("[spotify] %s on %s (retry %d/%d)", type(e).__name__,
                               path, k, tries)
                time.sleep(2 * k)
        raise SpotifyError(f"gave up after {tries} attempts: {method} {path}")

    # ---------------- reads ----------------
    def me(self) -> dict:
        return self.call("/me") or {}

    def get_track(self, track_id: str) -> dict | None:
        return self.call(f"/tracks/{urllib.parse.quote(track_id)}")

    def get_tracks(self, ids: list[str]) -> list[dict]:
        """Batch lookup (<=50 per call); unavailable ids come back as None."""
        out = []
        for i in range(0, len(ids), 50):
            chunk = ",".join(ids[i:i + 50])
            d = self.call("/tracks?ids=" + urllib.parse.quote(chunk)) or {}
            out.extend(d.get("tracks") or [])
            time.sleep(0.3)
        return [t for t in out if t]

    def search_tracks(self, query: str, limit: int = 12) -> list[dict]:
        d = self.call("/search?type=track&limit=%d&q=%s"
                      % (limit, urllib.parse.quote(query)))
        if d is None:
            return []
        return (d.get("tracks") or {}).get("items") or []

    # ---------------- writes (2026-migrated endpoints ONLY) ----------------
    def create_playlist(self, name: str, description: str,
                        public: bool = False) -> dict:
        """Create on the current user: POST /me/playlists (verified in live build)."""
        return self.call("/me/playlists", "POST",
                         {"name": name, "description": description,
                          "public": bool(public)}) or {}

    def add_items(self, playlist_id: str, uris: list[str],
                  position: int | None = None) -> dict:
        """Add tracks. Body key is `uris`; endpoint is /items (NOT /tracks)."""
        body: dict = {"uris": list(uris)}
        if position is not None:
            body["position"] = position
        return self.call(f"/playlists/{playlist_id}/items", "POST", body) or {}

    def playlist_items(self, playlist_id: str) -> list[dict]:
        """All item rows (follows pagination). Migrated field name: `items`."""
        rows: list[dict] = []
        url = f"/playlists/{playlist_id}/items?limit=100"
        while url:
            d = self.call(url.replace(API, "")) if url.startswith(API) else self.call(url)
            if d is None:
                break
            rows.extend(d.get("items") or [])
            nxt = d.get("next")
            url = nxt.replace(API, "") if nxt and nxt.startswith(API) else nxt
        return rows

    def remove_items(self, playlist_id: str, uris: list[str]) -> dict:
        """Delete via /items with body {"items":[{"uri":...}]} (NOT `uris`).

        Verified live 2026-10-17: DELETE removes EVERY occurrence of each URI
        (a URI duplicated on the playlist loses both copies in one call), and
        positional inserts via add_items(position=n) work on the migrated
        endpoint. This is why the pipeline dedupes track ids before adding.
        """
        return self.call(f"/playlists/{playlist_id}/items", "DELETE",
                         {"items": [{"uri": u} for u in uris]}) or {}

    def set_public(self, playlist_id: str, public: bool) -> dict:
        return self.call(f"/playlists/{playlist_id}", "PUT",
                         {"public": bool(public)}) or {}


def item_track_uri(row: dict) -> str | None:
    """Pull the track uri out of an item row (both 'track' and 'item' wrappers)."""
    for key in ("track", "item"):
        t = row.get(key)
        if isinstance(t, dict) and t.get("uri"):
            return t["uri"]
    return None


def verify_private(playlist_id: str) -> bool | None:
    """Anonymous read-back: 401/403 => private, 200 => public. None = network fail.

    The `public` FIELD is not trustworthy for dev-mode apps (observed true on
    private playlists); only the anonymous read is evidence.
    """
    logger = logkit.get_logger()
    try:
        req = urllib.request.Request(
            f"https://api.spotify.com/v1/playlists/{playlist_id}",
            headers={"User-Agent": "mal-openings"})
        urllib.request.urlopen(req, timeout=20)
        return False
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return True
        return None
    except Exception:
        return None
