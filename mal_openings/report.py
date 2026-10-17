"""Report writers: review.csv + review.md (the human audit surface)."""
import csv

CSV_FIELDS = ["show", "op_mal_title", "op_mal_artist", "spotify_name",
              "spotify_artist", "album", "length", "track_id", "flag"]


def _fmt_len(dur_s) -> str:
    try:
        d = int(dur_s)
    except (TypeError, ValueError):
        return ""
    return f"{d // 60}:{d % 60:02d}" if d else ""


def write_review_csv(path: str, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_review_md(path: str, rows: list[dict], gaps: list[dict],
                    no_ops: list[str], user: str, status: str) -> None:
    """rows: resolved (track present). gaps: unresolved song rows.
    no_ops: shows whose MAL theme page lists no openings."""
    n_planned = len(rows)
    lines = [f"# Anime Openings — {user}'s {status} list",
             f"Planned: **{n_planned} tracks** from "
             f"{len({r['show'] for r in rows})} shows.",
             f"Unresolved: {len(gaps)} songs | shows without openings on MAL: "
             f"{len(no_ops)}", ""]
    cur = None
    for r in rows:
        if r["show"] != cur:
            cur = r["show"]
            lines.append(f"\n### {cur}")
        mark = "  ⚠" if r["flag"] not in ("mal-id",) else ""
        lines.append(f"- {r['spotify_name']} — {r['spotify_artist']} "
                     f"({_fmt_len(r['length'])}) [{r['flag']}]{mark}")
    if gaps:
        lines.append("\n---\n## Not in playlist (couldn't resolve this pass)")
        lines += [f"- {g['show']}: {g['op_mal_title']} — {g['op_mal_artist']} "
                  f"[{g['flag']}]" for g in gaps]
    if no_ops:
        lines.append("\n## No openings found on MAL")
        lines += [f"- {s}" for s in no_ops]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
