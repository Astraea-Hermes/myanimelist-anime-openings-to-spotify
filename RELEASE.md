# Release Policy

How this project decides when and what to ship. It's a rule I hold myself to,
not a suggestion box.

## What a release is

A release is **a claim that the state tagged is usable**. That's the whole
weight of it: git keeps history moving on `main` with no ceremony, but a tag
says "we stand behind this exact commit." So releases happen when that claim
becomes true and meaningful — not on a schedule, and not per-merge.

## When we ship

| Trigger | Version bump | Notes |
|---|---|---|
| User-visible bug fix on `main`, verified | patch `0.1.x` | the `--fresh` checkpoint fix (v0.1.1) was this case |
| In-scope feature accepted and merged | minor `0.x.0` | per CONTRIBUTING scope law; features need usage evidence or a strong community pull, not just a good idea |
| Behavior that changes a documented contract (CLI flags, workdir file formats) | minor at least | README + `--help` updated in the same PR, always |
| MAL or Spotify changed their pages/APIs (breaks-for-everyone class) | emergency patch, same day | this is the most likely reason this repo ever needs to ship fast — scraping is a dependency on someone else's HTML |
| Docs-only, tests-only, internal refactor | **no release** | `main` carries it; nobody needs a "version" for prose |

There is no calendar release. A quiet month with no triggers means there is
nothing to claim, and shipping a version just to look alive devalues the tags
that matter.

## Bar before any tag is created

1. Full test suite green (`python3 -m unittest discover -s tests`), CI green
   on `main` at the exact commit to be tagged.
2. The changes since the last release are each linked to a closed issue or
   documented decision — release notes are written *from the issue trail*,
   never from memory.
3. `VERSION` in `mal_openings/config.py`, `version` in `pyproject.toml`, and
   the git tag all match the same string, and `--version` prints it.
4. A real end-to-end run against at least one live MAL user list with the
   tagged tree (not the workdir) succeeds through report generation; the
   playlist-creation stage is exercised whenever Spotify endpoints changed.
5. No secrets, tokens, or real users' scraped data in the tree (CI stdlib
   guard plus a manual grep).

## How a release happens

Annotated tag (`git tag -a vX.Y.Z`), pushed, then a GitHub Release whose body
is: what changed, *why it matters in one line each*, who reported/fixed
(thanks by name), and a `git diff` range link for the honest record. Tag
points at the verified commit, always created after the checklist, never
retroactively.

## Version number honesty

We are `0.x` and stay `0.x` until the CLI surface and workdir formats are
frozen by real usage. A `1.0.0` claim means: I will preserve `--flag` names
and `themes.json`/`review.csv` shapes across upgrades, or say otherwise loudly
in a release note first. Breaking the contract inside `0.x` is announced the
same way — tags exist to be trustworthy, not decorative.

## Deprecation

A released version is never deleted. Superseded tags stay fetchable forever;
old releases stay listed with a pointer to what replaced them. If a version
turns out to be broken, we ship a fix and mark the release, not the history.
