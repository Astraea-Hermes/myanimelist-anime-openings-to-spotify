"""Command-line interface for mal-openings."""
import argparse
import os
import sys

from . import pipeline, spotify_auth
from .config import (VERSION, app_dir, auth_path, config_path, read_json,
                     resolve_client_id)
from .logkit import get_logger, setup_logger


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mal-openings",
        description="Build a Spotify playlist of opening themes for every show "
                    "on a MyAnimeList user's list.",
        epilog="Extraction (MAL parsing + review sheet) needs NO Spotify setup. "
               "Spotify login is only needed for --create-playlist.",
    )
    p.add_argument("--user", help="MyAnimeList username (public animelist)")
    p.add_argument("--status", default="completed",
                   help="List section: watching|completed|onhold|dropped|"
                        "plantowatch|all (default: completed)")
    p.add_argument("--limit", type=int, default=None,
                   help="Only the first N entries of the list")
    p.add_argument("--skip-movies", action="store_true",
                   help="Skip Movie entries when extracting openings")
    p.add_argument("--workdir", default="mal-openings-work",
                   help="Directory for checkpoints + reports "
                        "(default: ./mal-openings-work)")
    p.add_argument("--client-id", default=None,
                   help="Spotify app client id (else MALOP_CLIENT_ID env, "
                        f"else {config_path()})")
    p.add_argument("--auth", action="store_true",
                   help="Run the Spotify browser login and exit")
    p.add_argument("--auth-port", type=int, default=spotify_auth.DEFAULT_PORT,
                   help=f"Loopback port for --auth (default {spotify_auth.DEFAULT_PORT}; "
                        "must match a Redirect URI in your Spotify app)")
    p.add_argument("--create-playlist", action="store_true",
                   help="After resolution, create the private Spotify playlist "
                        "and add all resolved tracks")
    p.add_argument("--playlist-name", default=None,
                   help="Playlist title (default: \"Anime Openings — <user>\")")
    p.add_argument("--dry-run", action="store_true",
                   help="With --create-playlist: print the plan, write nothing "
                        "to Spotify")
    p.add_argument("--fresh", action="store_true",
                   help="Ignore all checkpoints in --workdir (list, themes, "
                        "resolved) and refetch; playlist_state is respected")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Debug logging on the console")
    p.add_argument("--version", action="version", version=f"mal-openings {VERSION}")
    return p


def cmd_auth(args) -> int:
    setup_logger(args.workdir if os.path.isdir(args.workdir) else None,
                 args.verbose)
    logger = get_logger()
    cid = resolve_client_id(args.client_id)
    if not cid:
        logger.error("[auth] no client id: pass --client-id, set MALOP_CLIENT_ID, "
                     "or write {\"client_id\": \"...\"} to %s", config_path())
        return 2
    os.makedirs(app_dir(), exist_ok=True)
    tok = spotify_auth.run_pkce_login(cid, port=args.auth_port)
    logger.info("[auth] logged in (expires ~1h, auto-refresh from %s)",
                auth_path())
    print("Login OK. Token cache:", auth_path())
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.auth:
        try:
            return cmd_auth(args)
        except spotify_auth.AuthError as e:
            print(f"login failed: {e}", file=sys.stderr)
            return 3

    if not args.user:
        print("error: --user is required (or use --auth)\n", file=sys.stderr)
        build_parser().print_usage(sys.stderr)
        return 2

    os.makedirs(args.workdir, exist_ok=True)
    setup_logger(args.workdir, args.verbose)
    logger = get_logger()
    logger.info("mal-openings %s | workdir=%s", VERSION, os.path.abspath(args.workdir))

    try:
        items = pipeline.stage_list(args.workdir, args.user, args.status,
                                    args.limit, args.skip_movies,
                                    fresh=args.fresh)
        themes = pipeline.stage_extract(args.workdir, items, fresh=args.fresh)

        client = None
        if args.create_playlist:
            from .spotify_api import SpotifyClient
            cache = read_json(auth_path())
            if not cache:
                logger.error("[spotify] --create-playlist needs login first: "
                             "run  mal-openings --auth --client-id <ID>")
                return 3
            cid = resolve_client_id(args.client_id)
            client = SpotifyClient(cache, cid)
            me = client.me()
            who = me.get("display_name") or me.get("id")
            logger.info("[spotify] logged in as %s", who)

        master = pipeline.stage_resolve(args.workdir, items, themes, client,
                                        fresh=args.fresh)
        result = pipeline.stage_report(args.workdir, items, themes, master,
                                       user=args.user, status=args.status)

        if args.create_playlist:
            name = args.playlist_name or f"Anime Openings — {args.user}"
            desc = (f"Opening themes from {args.user}'s MyAnimeList "
                    f"{args.status} list, built by mal-openings.")
            state = pipeline.stage_playlist(args.workdir, client,
                                            result["resolved"], name, desc,
                                            args.dry_run)
            if not args.dry_run:
                print(f"\nPlaylist: {state['url']}  "
                      f"({state.get('total_items', '?')} tracks, "
                      f"private={'yes' if state.get('private_verified') else 'check manually'})")
        else:
            print(f"\nDone (no Spotify writes). Review the sheet: "
                  f"{os.path.join(args.workdir, 'review.csv')}")
            print(f"Resolved {len(result['resolved'])} tracks, "
                  f"{len(result['gaps'])} unresolved. To push to Spotify: rerun "
                  f"with --auth (once) then --create-playlist.")
        return 0

    except KeyboardInterrupt:
        # Checkpoints are written per item — state on disk is clean.
        logger.warning("interrupted — rerun with the same --workdir to resume "
                       "from the last completed item")
        return 130
    except pipeline.mal.MalError as e:
        logger.error("[mal] %s", e)
        return 4
    except spotify_auth.AuthError as e:
        logger.error("[auth] %s", e)
        return 3
    except Exception as e:
        logger.error("failed: %s: %s", type(e).__name__, e)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
