# mal-openings

Build a Spotify playlist of every **opening theme** for the anime on a
MyAnimeList user's list. Point it at a MAL username, review the generated
spreadsheet, and — when it looks right — push it to your Spotify as a private
playlist.

Zero third-party dependencies: pure Python standard library, Python 3.11+.
Download, run, done.

## What it does

1. Scrapes your (public) MAL anime list — no MAL API key needed.
2. Scrapes each title's MAL theme page and pulls the **openings** (MAL's
   typo'd `opnening` containers and all), including the **direct Spotify
   track IDs MAL embeds** — which matters, see [dev-mode limits](#real-world-dev-mode-limits).
3. Resolves each opening to a full Spotify track (verifying the direct ID,
   falling back to search with romanji/Japanese title variants, refusing
   TV-size/live/acoustic when a studio version exists).
4. Writes `review.csv` / `review.md` so you can eyeball every pick.
5. Optionally creates a private Spotify playlist and adds the tracks, then
   reads it back to verify the exact set landed.

## Requirements

- **Python 3.11+** (stdlib only — nothing to `pip install`).
- A **Spotify Premium** account. Since the Feb 2026 developer-mode migration,
  Spotify requires Premium for development apps. (Pure MAL extraction +
  review sheet needs no Spotify account at all.)
- A free **Spotify developer app** — 3 minutes, steps below.
- **Your Spotify username added to the app's User Management allow-list.**
  Skip this and every API call returns 403, even with a perfect token.

### Spotify app setup

1. Go to <https://developer.spotify.com/dashboard> → *Create app*.
2. Name: anything (e.g. `mal-openings`). Description: anything.
3. **Redirect URIs** — add exactly:
   `http://127.0.0.1:8399/callback`
   (If you use `--auth-port`, the URI must match that port exactly.)
4. Under *Advanced Settings* check **Mode: Development** and save.
5. In **User Management → Add users**, add *your own* Spotify username.
   Anyone who will run the tool must be listed here.
6. Copy the **Client ID** from the app page.

## Quick start

```bash
# 1) one-time login (opens your browser; token cached at
#    ~/.config/mal-openings/auth.json, mode 0600)
python3 -m mal_openings --auth --client-id YOUR_CLIENT_ID

# 2) extract your completed list and see the review sheet (no Spotify writes)
python3 -m mal_openings --user YourMALuser --status completed --workdir ./work

# 3) resolved tracks become a private playlist
python3 -m mal_openings --user YourMALuser --status completed --workdir ./work \
    --create-playlist --playlist-name "My Anime OPs"
```

If you installed with `pipx install .` / `pip install .`, replace
`python3 -m mal_openings` with `mal-openings`.

Run the same command twice: completed stages and per-show fetches are
checkpointed in `--workdir` and skipped, so a crash, a `Ctrl-C`, or a Spotify
rate-limit pause loses no progress. `--fresh` ignores every checkpoint in the
workdir (list, theme pages, resolved tracks) and refetches from MAL;
`playlist_state.json` is always respected, since it records the actual Spotify
playlist, not a cache. To start from a truly empty slate, use a new
`--workdir`.

## CLI

Each option below is shown with its default behavior and an example. Extraction
examples need only a public MAL list. Spotify examples require the app setup
above and, where noted, a completed `--auth` login. The tool never writes to
Spotify unless `--create-playlist` is present; pair it with `--dry-run` to
preview the plan without creating a playlist or adding tracks.

| Option | Purpose | Example |
|---|---|---|
| `--user USER` | Read the public anime list for this MAL username. | `python3 -m mal_openings --user helah13 --limit 2 --workdir /tmp/mo` |
| `--status STATUS` | Choose `watching`, `completed` (default), `onhold`, `dropped`, `plantowatch`, or `all`. | `python3 -m mal_openings --user helah13 --status watching --limit 2 --workdir /tmp/mo-watching` |
| `--limit N` | Process only the first N entries in the selected list. | `python3 -m mal_openings --user helah13 --limit 2 --workdir /tmp/mo-limit` |
| `--skip-movies` | Leave Movie entries out when extracting opening themes. | `python3 -m mal_openings --user helah13 --limit 2 --skip-movies --workdir /tmp/mo-no-movies` |
| `--workdir DIR` | Store checkpoints, logs, and review reports in DIR. | `python3 -m mal_openings --user helah13 --limit 2 --workdir /tmp/mo` |
| `--client-id ID` | Supply your Spotify app's client ID; otherwise the CLI checks `MALOP_CLIENT_ID` and its config file. | `python3 -m mal_openings --user helah13 --limit 2 --workdir /tmp/mo --client-id "$SPOTIFY_CLIENT_ID"` |
| `--auth` | Open the Spotify browser login, cache the token, and exit. | `python3 -m mal_openings --auth --client-id "$SPOTIFY_CLIENT_ID"` |
| `--auth-port PORT` | Set the loopback port used during `--auth`; it must match the app's redirect URI. | `python3 -m mal_openings --auth --auth-port 8399 --client-id "$SPOTIFY_CLIENT_ID"` |
| `--create-playlist` | Create a private playlist and add resolved tracks (requires prior `--auth`). | `python3 -m mal_openings --user helah13 --limit 2 --workdir /tmp/mo --create-playlist --dry-run` |
| `--playlist-name NAME` | Set the playlist title; by default it is `Anime Openings — USER`. | `python3 -m mal_openings --user helah13 --limit 2 --workdir /tmp/mo --create-playlist --playlist-name "My Anime OPs" --dry-run` |
| `--dry-run` | With `--create-playlist`, show the playlist plan without writing to Spotify. | `python3 -m mal_openings --user helah13 --limit 2 --workdir /tmp/mo --create-playlist --dry-run` |
| `--fresh` | Refetch list, themes, and resolved tracks instead of reusing checkpoints in the workdir. | `python3 -m mal_openings --user helah13 --limit 2 --fresh --workdir /tmp/mo-fresh` |
| `-v`, `--verbose` | Print debug-level details to the console as well as the log. | `python3 -m mal_openings --user helah13 --limit 2 --verbose --workdir /tmp/mo-verbose` |

The extraction commands above are safe to rerun: use the same `--workdir` to
resume from checkpoints. `--fresh` deliberately refetches MAL pages.

## What's in the workdir

| file | contents |
|---|---|
| `mal-openings.log` | timestamped log of every run (also echoed to console) |
| `mal_list.json` | your scraped list entries (id, title, type) |
| `themes.json` | per-show openings straight from MAL (title, artist, embedded Spotify id) |
| `master.json` | every OP resolved to a Spotify track + flag |
| `review.csv` | one row per track: show, MAL OP, chosen Spotify track, length, flag |
| `review.md` | the human-readable version — ⚠ marks anything not taken from a direct MAL link |
| `playlist_state.json` | created playlist's id/URL + added URIs (used for resume + verification) |

Flags worth knowing: `mal-id` (track came from MAL's embedded Spotify link —
highest trust), `search(...)` (found via Spotify search),
`swapped-to-full (mal link was tv/short)` (MAL pointed at a TV size, a full
version was found), `tv-size-only available`, `UNRESOLVED`,
`quota-unavailable (rerun after cooldown)` (deferred; rerun later).

## Real-world dev-mode limits

Learned the hard way in a production run (2026-10), now designed around:

- **Search is hard-capped.** Bursts of `/search` calls get you a `429` with a
  `Retry-After` of ~21 hours. mal-openings therefore prefers MAL's *embedded
  direct track IDs* (which use the quota-cheap `/tracks` endpoint) and only
  searches when no ID exists. When the search cooldown hits, unresolved rows
  are marked `DEFERRED` and every later rerun retries exactly those.
- **Playlist item endpoints migrated (Feb 2026).** New dev apps get **403** on
  the old `GET/POST /playlists/{id}/tracks` endpoints. This tool uses only the
  new ones: `POST /me/playlists`, `POST/GET/DELETE /playlists/{id}/items`
  (verified live: old 403, new 200).
- **`public` field lies in dev mode.** A private playlist can report
  `public: true` via the API. The tool verifies privacy the honest way — an
  anonymous read that must come back 401/403 — and tells you the result.
- **`DELETE /items` removes every occurrence** of a URI, not one copy
  (verified live). Tracks are deduped before adding for this reason.
- Dev-mode apps self-report limits; if you hit a wall, the README of the
  Spotify Web API "Rate Limits" page is the current authority.

## Troubleshooting

| symptom | cause / fix |
|---|---|
| every call **403** | your Spotify username is not in the app's User Management allow-list — or an old endpoint is being used (this tool shouldn't) |
| **429** on search | daily/burst quota — cooldown can be ~24h; rerun later, deferred rows resume automatically |
| **401** | token expired and refresh failed → rerun `--auth` |
| `no list rows found` | list is private or empty for that status, or MAL markup changed — run with `-v` and check `mal-openings.log` |
| login browser doesn't open | the URL is printed in the terminal; open it manually. Port conflict? use `--auth-port` and update your app's Redirect URI to match exactly |
| playlist shows `public: true` | dev-mode reporting quirk — the tool's anonymous verification is what counts |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Synthetic fixtures replicate every real MAL markup trap: both theme-page
shapes, the `opnening` typo, nested tables inside the container, the
next-`js-theme-songs` container-end rule, empty `spotify_url_` inputs,
popup-call track IDs, HTML entities, and full-width characters.

## Privacy

- Nothing is sent anywhere except MyAnimeList (public pages) and Spotify
  (your own API calls). No telemetry, no analytics.
- Tokens live only in `~/.config/mal-openings/auth.json`, mode `0600`;
  secrets are never written to logs.
- MAL scraping is throttled (~1s between page fetches) with a normal UA.

## License

MIT — see [LICENSE](LICENSE).
