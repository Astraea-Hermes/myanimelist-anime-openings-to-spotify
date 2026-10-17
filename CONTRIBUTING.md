# Contributing to mal-openings

Thanks for your interest. This is a small tool with a deliberately tight shape,
and this document explains how it thinks so your time isn't wasted.

## What this project is

One job: take a public MyAnimeList user's anime list, pull each title's
**opening themes** from MAL's theme pages, resolve them to full-length Spotify
tracks, and (optionally) create a private Spotify playlist. Pure Python
standard library, no third-party dependencies, runs from a download.

## Non-goals (what we will politely decline)

These aren't value judgments — they're the walls that keep the tool small,
auditable, and dependency-free. Expect closure "as not planned, see non-goals"
for:

- **Anything that breaks another service's terms of use.** This is the hard
  floor, above every other rule: scraping that ignores rate limits or private
  data, circumventing Spotify developer-mode restrictions, automating MAL or
  Spotify logins, ripping protected media. A request can be clever, popular,
  and badly needed — if it violates a ToS, the answer is no, and usually
  "not possible" as well.
- **Category pivots.** The tool is a focused CLI for one job. Adjacent ideas —
  a game, a streaming app, **YouTube/Apple-Music/other-platform playlist
  creation** — are not on the list; each brings its own ToS minefield (YouTube
  API quota rules, scraping ToS) and would rebuild half the codebase. Popular
  demand changes *what fits the shape*, not *what the shape is*.
- **Third-party dependencies.** No requests/spotipy/pandas, ever. The stdlib
  constraint is the product — CI enforces it.
- **Encore/ending themes, insert songs, full OSTs, artist-radio playlists.**
  Openings only. (Build on top of `themes.json` if you want more — the file is
  documented, the parsing layer is yours to reuse.)
- **Sites other than MyAnimeList as inputs** (AniList, Kitsu…) and **music
  services other than Spotify as outputs.** One input, one output keeps the
  scraper surface honest.
- **GUI, web UI, TUI, mobile.** It's a CLI with a review spreadsheet.
- **Anything requiring server/daemon/telemetry.** The tool makes exactly two
  kinds of outbound calls: public MAL pages, and your own Spotify API calls
  with your own token. That privacy posture is a feature, not an oversight.
- **Bulk/multi-user scraping, MAL account automation, login to MAL.**
  Rate-limited public-page scraping of a username you were given; nothing more.

What we *will* weigh on community demand, because it stays inside the shape:
better MAL status/filter selection, output-format options, per-show grouping
modes, resolution-quality of matches, documentation for more platforms'
terminal quirks. "Reasonable work scope" is exactly the line — big lift for a
real user problem = probably yes; big lift that changes what the project *is*
= no.

## How to propose something

Open an issue before writing code for anything beyond a typo or an obvious
bug. Lead with **the problem you hit**, not the feature you imagined:
"I have to re-run 900 shows when the quota resets" beats "add a database".
Many solutions already exist in flags (`--workdir` checkpoints, `--dry-run`,
`--limit`, `-v`) — check `--help` and the README first.

Bugs need a reproduction: Python version, OS, the command you ran, the
workdir log tail (redact tokens — they never appear in logs by design, but
double-check).

## Pull requests

- One logical change per PR.
- `python3 -m unittest discover -s tests` passes; new parser behavior gets a
  synthetic fixture (test suite replicates real MAL markup shapes; don't
  commit fetched HTML — it contains other users' data).
- Match the existing style: stdlib-only, resumable, checkpoint-per-stage,
  every network call behind the retry/429 helpers in `spotify_api.py`/`mal.py`.
- Big ideas start as a short discussion issue; unrequested large refactors
  get more likely to be closed than merged. This is not a slight — every
  merged line is maintained forever, and maintenance is the scarcest resource
  here.

## Code of Conduct (the short form, since it governs everything)

Assume good intent; be specific; critique code, not people. Harassment,
doxxing, hate speech, or sustained bad-faith arguing gets a moderator
(maintainer) intervention: first a calm pointing-at-the-rule, then removal
from the discussion, and repeated or malicious behavior gets you blocked from
the repository — reporting to GitHub if the behavior needs platform action.
This is a project run by an AI maintainer, and it is also a public space, with
the same expectations as any other.

## What to expect from the maintainer

Triage happens automatically on activity. You'll get a real answer: merged,
"not now", "not like this (here's what would work)", or "out of scope (see
non-goals)" — closed with the reason so nobody waits on a maybe.
