"""Pipeline orchestration with per-stage resumable checkpoints.

Workdir artifacts (all resumable — a crash or Ctrl-C mid-run leaves valid JSON
checkpoints and the rerun skips finished items):

  mal_list.json     stage 'list'     [{mal_id,title,type,row}, ...]
  themes.json       stage 'extract'  {mal_id: {status, ops:[...]}}
  master.json       stage 'resolve'  [{mal_id, show, op_title, op_artist,
                                       spotify_id, track, flag}, ...]
  review.csv/.md    stage 'report'
  playlist_state.json  stage 'playlist' {id, url, added:[uris]}
"""
import os
import time

from . import mal, report, resolve as resolve_mod
from .config import MAL_SLEEP, read_json, write_json
from .logkit import banner, get_logger, progress
from .spotify_api import (SpotifyError, item_track_uri, verify_private)


def _p(workdir: str, name: str) -> str:
    return os.path.join(workdir, name)


# ---------------------------------------------------------------- list
def stage_list(workdir: str, user: str, status: str, limit: int | None,
               skip_movies: bool, fresh: bool = False) -> list[dict]:
    logger = get_logger()
    path = _p(workdir, "mal_list.json")
    if not fresh and os.path.exists(path):
        items = read_json(path, None)
        if items is not None:
            logger.info("[list] reusing checkpoint %s (%d entries)", path, len(items))
            return items
    logger.info("[list] scraping MAL animelist for '%s' (status=%s)", user, status)
    rows = mal.get_user_list(user, status=status, limit=limit)
    if skip_movies:
        kept = [r for r in rows if "movie" not in r["type"].lower()]
        logger.info("[list] skipped %d movie entries", len(rows) - len(kept))
        rows = kept
    write_json(path, rows)
    logger.info("[list] %d entries -> %s", len(rows), path)
    return rows


# ---------------------------------------------------------------- extract
def stage_extract(workdir: str, items: list[dict], fresh: bool = False) -> dict:
    logger = get_logger()
    path = _p(workdir, "themes.json")
    done = read_json(path, None) or {}
    if fresh and done:
        logger.info("[extract] --fresh: ignoring cached themes.json, refetching all")
        done = {}
    banner("extract", len(items))
    n_new = 0
    try:
        for i, it in enumerate(items, 1):
            mid = str(it["mal_id"])
            if mid in done and done[mid].get("status") != "fetch_fail":
                progress(i, len(items), f"{it['title'][:44]} (cached)")
                continue
            ops = mal.get_openings(it["mal_id"])
            if ops is None:
                rec = {"status": "fetch_fail", "ops": []}
            else:
                rec = {"status": "ok" if ops else "no_ops", "ops": ops}
            done[mid] = {"mal_id": it["mal_id"], "title": it["title"],
                         "type": it["type"], **rec}
            write_json(path, done)
            n_new += 1
            sp = sum(1 for o in rec["ops"] if o.get("spotify_id"))
            progress(i, len(items),
                     f"{it['title'][:40]:<40} {rec['status']} ops={len(rec['ops'])} ids={sp}")
            time.sleep(MAL_SLEEP)
    finally:
        write_json(path, done)
    vals = list(done.values())
    logger.info("[extract] done: %d shows | ok=%d no_ops=%d fail=%d | %d new fetches",
                len(vals),
                sum(1 for v in vals if v["status"] == "ok"),
                sum(1 for v in vals if v["status"] == "no_ops"),
                sum(1 for v in vals if v["status"] == "fetch_fail"), n_new)
    return done


# ---------------------------------------------------------------- resolve
def _song_key(mid, op_title) -> str:
    return f"{mid}|{op_title.casefold()}"


def stage_resolve(workdir: str, items: list[dict], themes: dict,
                  client, fresh: bool = False) -> list[dict]:
    logger = get_logger()
    path = _p(workdir, "master.json")
    master = read_json(path, None) or []
    if fresh and master:
        logger.info("[resolve] --fresh: rebuilding master.json from scratch")
        master = []
    # Deferred rows (quota cooldown) are NOT final — drop them from the
    # checkpoint view so this rerun retries them; keep everything else.
    master = [r for r in master if not r.get("flag", "").startswith("DEFERRED-")]
    done_keys = {_song_key(r["mal_id"], r["op_title"]) for r in master}
    songs = [(it, o) for it in items
             for o in themes.get(str(it["mal_id"]), {}).get("ops", [])]
    banner("resolve", len(songs))
    n = 0
    try:
        for it, o in songs:
            key = _song_key(it["mal_id"], o["title"])
            if key in done_keys:
                n += 1
                progress(n, len(songs), f"{o['title'][:40]} (cached)")
                continue
            row = {"mal_id": it["mal_id"], "show": it["title"],
                   "op_title": o["title"], "op_artist": o["artist"],
                   "spotify_id": o.get("spotify_id")}
            if client is None:
                row["track"] = None
                row["flag"] = "parse-only (no spotify client)"
            else:
                try:
                    res = resolve_mod.resolve_op(client, row, logger)
                except SpotifyError as e:
                    logger.error("[resolve] spotify error on '%s': %s", o["title"], e)
                    row["track"] = None
                    row["flag"] = f"error: {e.status or e}"
                else:
                    row["track"] = res["track"]
                    row["flag"] = res["flag"]
            master.append(row)
            write_json(path, master)
            n += 1
            t = row.get("track") or {}
            progress(n, len(songs),
                     f"{it['title'][:24]:<24} | {o['title'][:28]:<28} | "
                     f"{row['flag'][:26]:<26} | {t.get('name', '—')[:30]}")
    finally:
        write_json(path, master)
    return master


# ---------------------------------------------------------------- report
def stage_report(workdir: str, items: list[dict], themes: dict,
                 master: list[dict], user: str = "", status: str = "") -> dict:
    logger = get_logger()
    order = {it["mal_id"]: it["row"] for it in items}
    resolved, gaps = [], []
    for r in master:
        t = r.get("track") or {}
        rec = {"show": r["show"], "op_mal_title": r["op_title"],
               "op_mal_artist": r["op_artist"],
               "spotify_name": t.get("name", ""), "spotify_artist": t.get("artist", ""),
               "album": t.get("album", ""), "length": t.get("dur_s", ""),
               "track_id": t.get("id", ""), "flag": r.get("flag", "")}
        if t.get("id"):
            rec["track_uri"] = t.get("uri") or f"spotify:track:{t['id']}"
        (resolved if t.get("id") else gaps).append(rec)
    # MAL list order: by list row of the show, then op title within a show
    show_pos = {}
    for m in master:
        show_pos.setdefault(m["show"], order.get(m["mal_id"], 999))
    resolved.sort(key=lambda x: (show_pos.get(x["show"], 999), x["op_mal_title"]))
    gaps.sort(key=lambda x: (show_pos.get(x["show"], 999), x["op_mal_title"]))

    no_ops = [themes[str(it["mal_id"])]["title"] for it in items
              if str(it["mal_id"]) in themes
              and themes[str(it["mal_id"])]["status"] == "no_ops"]
    report.write_review_csv(_p(workdir, "review.csv"), resolved + gaps)
    report.write_review_md(_p(workdir, "review.md"), resolved, gaps, no_ops,
                           user or "MAL user", status or "list")
    logger.info("[report] review.csv + review.md written (%d resolved, %d gaps, "
                "%d shows without OPs)", len(resolved), len(gaps), len(no_ops))
    return {"resolved": resolved, "gaps": gaps, "no_ops": no_ops}


# ---------------------------------------------------------------- playlist
def stage_playlist(workdir: str, client, resolved: list[dict],
                   name: str, description: str, dry_run: bool) -> dict:
    logger = get_logger()
    path = _p(workdir, "playlist_state.json")
    uris = list(dict.fromkeys(
        r["track_uri"] for r in resolved if r.get("track_uri")))
    if dry_run:
        logger.info("[playlist] DRY RUN — would create '%s' with %d tracks",
                    name, len(uris))
        return {"dry_run": True, "planned_uris": len(uris)}

    state = read_json(path, None) or {}
    if not state:
        pl = client.create_playlist(name, description, public=False)
        state = {"id": pl["id"], "url": pl["external_urls"]["spotify"],
                 "added": [], "snapshot_id": pl.get("snapshot_id")}
        write_json(path, state, private=False)
        logger.info("[playlist] created private playlist: %s", state["url"])

    added = set(state["added"])
    todo = [u for u in uris if u not in added]
    banner("playlist", len(todo))
    for i in range(0, len(todo), 100):  # API limit: <=100 per add call
        chunk = todo[i:i + 100]
        client.add_items(state["id"], chunk)
        added.update(chunk)
        state["added"] = sorted(added)
        write_json(path, state)
        progress(min(i + 100, len(todo)), len(todo),
                 f"added batch {i // 100 + 1} ({len(chunk)})")
        time.sleep(0.5)

    # ---- verify read-back == intended set, exactly ----
    rows = client.playlist_items(state["id"])
    got = [item_track_uri(r) for r in rows if item_track_uri(r)]
    got_set = set(got)
    want_set = set(uris)
    missing = want_set - got_set
    extra = got_set - want_set
    if missing or extra:
        if extra:
            logger.warning("[playlist] extra items on playlist: %d -> removing",
                           len(extra))
            for i in range(0, len(sorted(x for x in extra if x)), 100):
                client.remove_items(state["id"],
                                    sorted(x for x in extra if x)[i:i + 100])
            rows = client.playlist_items(state["id"])
            got_set = {item_track_uri(r) for r in rows if item_track_uri(r)}
            missing = want_set - got_set
        if missing:
            logger.error("[playlist] READ-BACK MISMATCH: %d intended tracks missing "
                         "— rerun with the same --workdir to retry", len(missing))
            raise SpotifyError(f"read-back mismatch: {len(missing)} missing")

    # ---- privacy: dev-mode `public` field is not trustworthy; anonymous read ----
    client.set_public(state["id"], False)
    priv = verify_private(state["id"])
    if priv is True:
        logger.info("[playlist] privacy verified by anonymous read (401/403)")
    elif priv is False:
        logger.warning("[playlist] anonymous read SUCCEEDED — playlist is "
                       "public despite the API field! Check manually.")
    state["total_items"] = len(got_set)
    state["private_verified"] = bool(priv)
    write_json(path, state)
    logger.info("[playlist] OK: %d tracks | %s", len(got_set), state["url"])
    return state
