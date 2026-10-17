"""Checkpoint/fresh semantics regression tests.

Bug #6 (2026-10-17, reported by @morvayo): `--fresh` only cleared the list
stage; extract/resolve silently reused cached pages despite the help text
"Ignore existing checkpoints". These tests pin the corrected behavior AND
the intentional non-destruction (files stay until overwritten; playlist_state
is out of scope).
"""
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request

from mal_openings import pipeline
from mal_openings.logkit import setup_logger


class _Boom:
    """Force extract/resolve to fail on the first fetch so tests stay offline
    and fast: the fresh decision happens BEFORE any network call."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        raise urllib.error.URLError("offline test fixture")

    def __call__(self, *a, **k):
        raise urllib.error.URLError("offline test fixture")


ITEMS = [{"mal_id": 1, "title": "Test Show", "type": "TV", "row": 1}]
THEMES = {"1": {"mal_id": 1, "title": "Test Show", "type": "TV",
                "ops": [{"title": "OP One", "artist": "Band", "spotify_id": None}]}}


class TestFreshCheckpoints(unittest.TestCase):
    def setUp(self):
        self.wd = tempfile.mkdtemp(prefix="mo-fresh-test-")
        setup_logger(workdir=self.wd)

    def tearDown(self):
        shutil.rmtree(self.wd, ignore_errors=True)

    def _seed(self):
        p = os.path.join(self.wd, "themes.json")
        with open(p, "w") as f:
            json.dump({"999999": {"mal_id": 999999, "title": "Stale Cached Show",
                                  "type": "TV", "status": "ok", "ops": []}}, f)
        return p

    def test_extract_default_reuses_checkpoint(self):
        tp = self._seed()
        with open(tp) as f:
            before = json.load(f)
        orig = pipeline.mal.get_openings
        pipeline.mal.get_openings = lambda mid: (_Boom(), []) [1]  # offline-safe empty
        try:
            pipeline.stage_extract(self.wd, ITEMS)
        finally:
            pipeline.mal.get_openings = orig
        with open(tp) as f:
            after = json.load(f)
        self.assertIn("999999", after, "default run must reuse the cached entry")

    def test_extract_fresh_drops_checkpoint_from_working_set(self):
        tp = self._seed()
        orig = pipeline.mal.get_openings
        pipeline.mal.get_openings = lambda mid: []
        try:
            out = pipeline.stage_extract(self.wd, ITEMS, fresh=True)
        finally:
            pipeline.mal.get_openings = orig
        self.assertNotIn("999999", out, "--fresh must ignore cached themes")
        self.assertIn("1", out, "--fresh run must contain the freshly fetched id")

    def test_resolve_fresh_rebuilds_master(self):
        mp = os.path.join(self.wd, "master.json")
        stale = [{"mal_id": 999999, "show": "Stale Show", "op_title": "Old OP",
                  "op_artist": "Old Band", "track": {"id": "x"}, "flag": "mal-id"}]
        with open(mp, "w") as f:
            json.dump(stale, f)

        class NoClient:  # parse-only path, still offline-safe
            pass

        out = pipeline.stage_resolve(self.wd, ITEMS, THEMES, None, fresh=True)
        self.assertEqual([r["show"] for r in out], ["Test Show"],
                         "--fresh resolve must rebuild master.json from the input songs only")
        self.assertEqual(out[0]["flag"], "parse-only (no spotify client)",
                         "fresh rebuild must actually run the song, not reuse a row")
        # the pre-existing stale row was NOT final: after a fresh rebuild it
        # must not exist in the checkpoint anymore
        with open(mp) as f:
            on_disk = json.load(f)
        self.assertEqual(len(on_disk), 1, "stale row gone after --fresh rebuild")

    def test_fresh_keeps_playlist_state_untouched(self):
        pp = os.path.join(self.wd, "playlist_state.json")
        with open(pp, "w") as f:
            json.dump({"id": "abc", "url": "u", "added": ["spotify:track:x"]}, f)
        orig = pipeline.mal.get_openings
        pipeline.mal.get_openings = lambda mid: []
        try:
            pipeline.stage_extract(self.wd, ITEMS, fresh=True)
        finally:
            pipeline.mal.get_openings = orig
        self.assertTrue(os.path.exists(pp),
                        "--fresh must never delete playlist_state (external object, not cache)")


if __name__ == "__main__":
    unittest.main()
