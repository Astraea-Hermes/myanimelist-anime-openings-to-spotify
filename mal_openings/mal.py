"""MyAnimeList scraping: user list pages and per-title theme pages.

Two facts drive this module:
  * MAL has no public API for user anime lists; the animelist page embeds the
    list as an HTML-escaped JSON blob (`data-items` on the list table).
  * Theme pages mark openings with the container class
    ``theme-songs js-theme-songs opnening`` (MAL's own typo, kept as-is), and
    song rows appear in TWO shapes: an anchor carrying an
    ``openMusicLinkPopup('<oped_id>', '<title>', '<artist>', '<spotify_track_id>')``
    call plus a ``spotify_url_<oped_id>`` hidden input, or plain quoted text
    inside the container with an EMPTY ``spotify_url_<oped_id>`` input.
"""
import html as H
import json
import re
import time
import urllib.error
import urllib.request

from . import config, logkit

STATUS_NAMES = {
    "all": 7, "watching": 1, "completed": 2, "onhold": 3,
    "dropped": 4, "plantowatch": 6, "ptw": 6, "rewatching": 13,
}


class MalError(RuntimeError):
    pass


def _request(url: str, timeout: int = config.MAL_TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    resp = urllib.request.urlopen(req, timeout=timeout)
    return resp.read().decode("utf-8", "replace")


def fetch(url: str, tries: int = 3, sleep_between: float | None = None) -> str | None:
    """GET a MAL page as text. Returns None on persistent failure.

    Honors Retry-After on 429 with a visible countdown; polite backoff on
    403/5xx/network errors. ``sleep_between`` throttles retries.
    """
    logger = logkit.get_logger()
    for k in range(1, tries + 1):
        try:
            return _request(url)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                wait = min(int(ra) if ra and ra.isdigit() else 20 * k, 120)
                logger.warning("[mal] 429 from %s -> honoring Retry-After (%s), waiting %ds",
                               url, ra or "absent", wait)
                logkit.sleep_with_countdown(wait, "MAL 429")
            elif e.code == 404:
                logger.warning("[mal] 404: %s", url)
                return None
            else:
                logger.warning("[mal] HTTP %s on %s (try %d/%d)", e.code, url, k, tries)
                if k < tries:
                    time.sleep((sleep_between or 8.0) * k)
        except Exception as e:  # URLError, timeout, ...
            logger.warning("[mal] network error on %s: %s (try %d/%d)", url, e, k, tries)
            if k < tries:
                time.sleep((sleep_between or 4.0) * k)
    return None


# --------------------------------------------------------------------------
# user list
# --------------------------------------------------------------------------

_LIST_TABLE_RE = re.compile(
    r'<table[^>]*class="[^"]*list-table[^"]*"[^>]*\bdata-items="(\[.*?\])"', re.S)
_LIST_JSON_END = re.compile(r'"\s+data-server=')


def parse_user_list(page_html: str) -> list[dict]:
    """Extract rows from an animelist page's embedded JSON blob.

    Returns dicts: {"mal_id", "title", "type", "row", "status"}.
    """
    m = _LIST_TABLE_RE.search(page_html)
    if not m:
        return []
    blob = H.unescape(m.group(1))
    try:
        items = json.loads(blob)
    except ValueError:
        return []
    rows = []
    for n, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        mid = it.get("anime_id")
        if not mid:
            continue
        title = (it.get("anime_title_eng") or "").strip() or \
                (it.get("anime_title") or "").strip() or f"MAL#{mid}"
        rows.append({
            "mal_id": int(mid),
            "title": title,
            "type": (it.get("anime_media_type_string") or "").strip(),
            "row": n,
            "status": it.get("status"),
        })
    return rows


def get_user_list(user: str, status: str = "completed", limit: int | None = None) -> list[dict]:
    """Scrape https://myanimelist.net/animelist/{user}?status={n}."""
    status_code = STATUS_NAMES.get(str(status).strip().lower(), None)
    if status_code is None and str(status).isdigit():
        status_code = int(status)
    if status_code is None:
        raise MalError(f"unknown status '{status}' "
                       f"(use: {', '.join(STATUS_NAMES)} or a number)")
    url = f"https://myanimelist.net/animelist/{user}?status={status_code}"
    page = fetch(url)
    if page is None:
        raise MalError(f"could not fetch MAL list for user '{user}' "
                       f"(check the username and that the list is public)")
    rows = parse_user_list(page)
    if not rows:
        raise MalError("no list rows found on the animelist page — the list may be "
                       "private, empty for this status, or MAL changed its markup")
    if limit:
        rows = rows[:limit]
    return rows


# --------------------------------------------------------------------------
# theme pages -> openings
# --------------------------------------------------------------------------

# Opening containers (MAL's literal typo 'opnening' must be matched).
_OPN_START = re.compile(r'<div[^>]*class="[^"]*js-theme-songs[^"]*opnening[^"]*"[^>]*>')
# Any theme-songs container boundary (opening OR ending) marks the end of one.
_ANY_START = re.compile(r'<div[^>]*class="[^"]*theme-songs js-theme-songs ')
_SCRIPT = re.compile(r"<script[\s>][\s\S]*?</script>", re.I)

_ARTIST_RE = re.compile(
    r'<span class="theme-song-artist">\s*by\s+([^<]+?)</span>')
_TITLE_SPAN_RE = re.compile(
    r'<span class="theme-song-title">\s*[“"]?([^<]+?)[”"]?\s*</span>')
_TITLE_QUOTED_END_RE = re.compile(r'[“"]([^“”"<>]{2,140})[”"]\s*$')
_INDEX_SPAN_RE = re.compile(
    r'<span class="theme-song-index">(\d+(?:\.\d+)?)\s*:</span>')
_TRACK_URL_RE = re.compile(r'spotify\.com/track/([A-Za-z0-9]{16,24})')
_POPUP_ID_RE = re.compile(
    r"openMusicLinkPopup\(\s*'?\d+?'\s*,\s*'[^']*'\s*,\s*'[^']*'\s*,\s*'([A-Za-z0-9]{16,24})'")
_SPOTIFY_INPUT_EMPTY_RE = re.compile(
    r'id="spotify_url_\d+" value=""')


def _last(rx: re.Pattern, s: str) -> re.Match | None:
    """Last match of rx in s (the marker closest to the artist span)."""
    m = None
    for m in rx.finditer(s):
        pass
    return m


def _clean(s: str) -> str:
    s = H.unescape(s)
    s = s.replace("\u00a0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", s).strip().strip("“”\"").strip()


def extract_openings(page_html: str) -> list[dict]:
    """All opening songs from a /anime/{id}/theme page.

    Handles both known markup shapes and the nesting trap: the container ends
    at the NEXT ``js-theme-songs`` div, not at the first ``</table>``
    (tables nest inside the container).

    Returns [{"title", "artist", "spotify_id"|None, "index"|None}].
    """
    starts = [m.start() for m in _OPN_START.finditer(page_html)]
    bounds = [m.start() for m in _ANY_START.finditer(page_html)]
    songs: list[dict] = []
    for i in starts:
        after = [b for b in bounds if b > i]
        stop = after[0] if after else len(page_html)
        seg = _SCRIPT.sub("", page_html[i:stop])
        artist_marks = list(_ARTIST_RE.finditer(seg))
        for n, am in enumerate(artist_marks):
            artist = _clean(am.group(1))
            # title: the span before this artist (anchor shape), or the last
            # quoted fragment before it (plain-text shape).
            back = seg[max(0, am.start() - 900):am.start()]
            # LAST title marker before this artist span (closest row wins).
            tm = _last(_TITLE_SPAN_RE, back)
            if tm:
                title = _clean(tm.group(1))
            else:
                # plain-text shape: quoted fragment ending right at the artist
                # span; quotes arrive as &quot; entities on live pages.
                tm = _TITLE_QUOTED_END_RE.search(H.unescape(back).rstrip())
                title = _clean(tm.group(1)) if tm else ""
            if not title:
                continue
            # spotify id: hidden input following this row, else popup arg #4.
            nxt = artist_marks[n + 1].start() if n + 1 < len(artist_marks) else len(seg)
            fwd = seg[am.end():nxt]
            sid = None
            m = _TRACK_URL_RE.search(fwd)
            if m:
                sid = m.group(1)
            if sid is None:
                m = _POPUP_ID_RE.search(back)
                if m:
                    sid = m.group(1)
            idx = _last(_INDEX_SPAN_RE, back)
            songs.append({"title": title, "artist": artist,
                          "spotify_id": sid,
                          "index": idx.group(1) if idx else None})
    # dedupe repeated blocks (pages sometimes repeat the section)
    seen, out = set(), []
    for s in songs:
        k = (s["title"].casefold(), s["artist"].casefold(), s["spotify_id"])
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def get_openings(mal_id: int) -> list[dict] | None:
    """Fetch + parse one theme page. None = fetch failure, [] = no openings."""
    page = fetch(f"https://myanimelist.net/anime/{mal_id}/theme")
    if page is None:
        return None
    return extract_openings(page)
