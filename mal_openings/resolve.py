"""Resolve one MAL opening (title, artist, optional direct track id) to a
Spotify track.

Strategy (proven in the live build, in cost order):
  1. MAL embeds DIRECT SPOTIFY TRACK IDs most of the time -> GET /tracks/{id}
     and sanity-check name+artist against the MAL row. A direct id that passes
     the check needs ZERO search quota — important because dev-mode search is
     hard-capped (~24h cooldown after bursts).
  2. If the linked id resolves to a TV-size/live/short version, search for the
     full version; keep the direct link only as fallback when nothing better.
  3. No id (or dead id) -> search fallback across TITLE ALT FORMS. MAL titles
     are "Romanji (日本語)" and Spotify often carries only the Japanese form,
     so the paren content must be tried as its own query (proven necessary).
     Candidates are scored; never prefer TV-size/live over a studio full.
"""
import time

from . import logkit
from .normalize import (artist_tokens, is_bad_version, norm, title_alts,
                        title_match)
from .spotify_api import SpotifyQuotaError

MIN_FULL_S = 110  # under this is TV-size-ish unless nothing else exists
SEARCH_SLEEP = 0.35
QUOTA_FLAG = "quota-unavailable (rerun after cooldown)"


def brief(t: dict) -> dict:
    return {
        "id": t.get("id", ""),
        "name": t.get("name", ""),
        "artist": ", ".join(a.get("name", "") for a in t.get("artists") or []),
        "album": (t.get("album") or {}).get("name", ""),
        "album_type": (t.get("album") or {}).get("album_type", ""),
        "dur_s": int((t.get("duration_ms") or 0) // 1000),
        "popularity": t.get("popularity", 0),
        "uri": t.get("uri") or f"spotify:track:{t.get('id','')}",
    }


def sanity_check(op_row: dict, track: dict) -> bool:
    """Direct-id must look like the same song MAL named.

    op_row keys: op_title / op_artist (the master.json row shape)."""
    name = track.get("name", "")
    album = (track.get("album") or {}).get("name", "")
    names = " ".join(norm(a.get("name", "")) for a in track.get("artists") or [])
    if not title_match(op_row["op_title"], name):
        return False
    toks = artist_tokens(op_row.get("op_artist", ""))
    if toks and not any(tk in names for tk in toks):
        return False
    if is_bad_version(name, album):
        return False
    if int(track.get("duration_ms") or 0) < MIN_FULL_S * 1000:
        return False
    return True


def _score(row: dict, t: dict, exact_bonus: int) -> float:
    nname = norm(t["name"])
    nT = norm(row["op_title"])
    names = " ".join(norm(a.get("name", "")) for a in t.get("artists") or [])
    s = float(exact_bonus)
    if nname == nT:
        s += 8
    elif nT and (nT in nname or nname in nT):
        s += 5
    toks = artist_tokens(row.get("op_artist", ""))
    if toks and any(tk in names for tk in toks):
        s += 3
    dur = int(t.get("duration_ms") or 0)
    s += 2 if dur >= 140000 else (-3 if dur < MIN_FULL_S * 1000 else 0)
    if (t.get("album") or {}).get("album_type") == "single":
        s += 1
    s += min(int(t.get("popularity") or 0) / 20.0, 2.5)
    if is_bad_version(t["name"], (t.get("album") or {}).get("name", "")):
        s -= 10  # demote, don't auto-drop: sometimes it is all that exists
    return s


def search_best(client, row: dict) -> tuple[dict | None, str]:
    """Search alt title forms; return (brief, note) of the best candidate.

    Stops early on a strong hit to conserve search quota.
    """
    queries_tried = 0
    best: tuple[float, dict] | None = None
    best_alt = ""
    if getattr(client, "search_cold", False):
        raise SpotifyQuotaError("search endpoint cooling down "
                                "(deferred to next rerun)")
    alts = title_alts(row["op_title"])
    artist = row.get("op_artist", "") or ""
    first_artist_token = artist.split(",")[0].strip() if artist else ""
    for T in alts:
        qs = []
        if first_artist_token:
            qs.append(f'track:"{T}" artist:"{first_artist_token}"')
        qs.append(f'track:"{T}"')
        if not first_artist_token:
            qs.append(f'"{T}"')
        for q in qs:
            if queries_tried >= 8:
                break
            try:
                items = client.search_tracks(q, limit=10)
            except SpotifyQuotaError:
                raise  # caller defers this row; don't hammer a cooled-down API
            queries_tried += 1
            time.sleep(SEARCH_SLEEP)
            for t in items:
                sc = _score({"op_title": T, "op_artist": artist}, t, 2)
                if best is None or sc > best[0]:
                    best = (sc, t)
                    best_alt = T
            if best and best[0] >= 13:
                break
        if best and best[0] >= 13:
            break
    if not best:
        return None, "no-search-hit"
    sc, t = best
    note = f"search(score={sc:.1f},alt='{best_alt}')"
    return brief(t), note


def resolve_op(client, row: dict, logger=None) -> dict:
    """row = master-style {"op_title","op_artist","spotify_id"|None}.
    Returns {"track": brief|None, "flag": str}."""
    logger = logger or logkit.get_logger()
    sid = row.get("spotify_id")
    direct: dict | None = None
    if sid:
        try:
            t = client.get_track(sid)
        except Exception as e:
            logger.warning("[resolve] /tracks/%s failed: %s", sid, e)
            t = None
        if t:
            if sanity_check(row, t):
                return {"track": brief(t), "flag": "mal-id"}
            direct = t  # keep as last resort (tv-size/live linked)

    full, note = None, None
    try:
        full, note = search_best(client, row)
    except SpotifyQuotaError as e:
        logger.warning("[resolve] search quota cooling down (%s)", e)
        if direct is not None:
            return {"track": brief(direct),
                    "flag": "mal-id-tv-only (deferred: " + QUOTA_FLAG + ")"}
        return {"track": None, "flag": "DEFERRED-" + QUOTA_FLAG}
    if full:
        if sid and direct is None:
            return {"track": full, "flag": "search (mal id dead)"}
        if direct is not None:
            return {"track": full, "flag": "swapped-to-full (mal link was tv/short)"}
        return {"track": full, "flag": note}

    if direct is not None:
        return {"track": brief(direct),
                "flag": "mal-id-tv-only (no full version found)"}
    return {"track": None, "flag": "UNRESOLVED"}
