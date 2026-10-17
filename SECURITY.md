# Security Policy

## Threat model (what "secure" means for this tool)

mal-openings is a local, stdlib-only CLI. Its entire network surface is:

1. **MyAnimeList public pages** — scraped read-only, throttled ~1 req/s.
2. **Spotify Web API** — calls made with *your own* token, to *your own* account.

There is no server component, no telemetry, no third-party endpoints, and no
dependency tree to inherit vulnerabilities from. OAuth tokens are stored only
in `~/.config/mal-openings/auth.json` (mode 0600) and are never written to
logs. Anything that breaks those guarantees is a security bug.

## Reporting a vulnerability

Please use **GitHub's private vulnerability reporting** — on this repo's
Security tab, "Report a vulnerability". Do not open a public issue.

You should get an acknowledgement within a few days (the maintainer polls
this repo on a schedule, so realistically faster), and a fix or reasoned
answer within 30.

## Scope examples

- Token/secret leakage into logs, output files, or network calls
- Code paths that could exfiltrate data to hosts other than the two above
- MAL-scraping behavior that would expose a *private* user's list
- Any change that would let a malicious MAL page execute code locally
