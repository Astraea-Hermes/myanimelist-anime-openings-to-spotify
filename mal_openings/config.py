"""Paths, config resolution, and private-file IO (stdlib only)."""
import json
import os
import tempfile

APP_NAME = "mal-openings"
VERSION = "0.1.0"

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Sleep between MyAnimeList page fetches (politeness).
MAL_SLEEP = 1.1
MAL_TIMEOUT = 30


def app_dir() -> str:
    """~/.config/mal-openings (honors XDG_CONFIG_HOME)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


def auth_path() -> str:
    return os.path.join(app_dir(), "auth.json")


def config_path() -> str:
    return os.path.join(app_dir(), "config.json")


def read_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, obj, private: bool = False) -> None:
    """Atomic JSON write. private=True -> file mode 0600 (for tokens)."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)
            f.write("\n")
        if private:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def resolve_client_id(cli_value=None, config=None):
    """--client-id flag > MALOP_CLIENT_ID env > config.json > None."""
    if cli_value:
        return cli_value.strip()
    env = os.environ.get("MALOP_CLIENT_ID", "").strip()
    if env:
        return env
    cfg = config if config is not None else read_json(config_path(), {}) or {}
    cid = (cfg.get("client_id") or "").strip()
    return cid or None
