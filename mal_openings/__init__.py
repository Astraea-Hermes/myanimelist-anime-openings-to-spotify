"""mal-openings — MyAnimeList openings → Spotify playlist.

Zero third-party dependencies (stdlib only, Python >= 3.11).
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
