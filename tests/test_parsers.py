"""Synthetic unit tests for the MAL parsers — one per known markup trap.

Fixtures replicate the exact HTML shapes observed on live theme pages
(anchor+popup shape, plain-text shape, nested tables, full-width chars,
HTML entities). Stdlib unittest only:  python3 -m unittest
"""
import html as H
import json
import unittest
from unittest.mock import patch

from mal_openings.mal import MalError, extract_openings, get_user_list, parse_user_list
from mal_openings.normalize import title_alts, title_match, artist_tokens

# ---------------------------------------------------------------- fixtures

POPUP_SCRIPT = """
      <script>
        const playButtonImage = '/images/oped-play-circle.svg';
        function controlPreview(oped_id) { nowPlaying = ''; }
      </script>"""


def anchor_shape_page():
    """Shape 1: <a href="javascript:openMusicLinkPopup(id, title, artist,
    spotify_track_id)"> with theme-song-title span + filled spotify_url input.
    (AoT 16498, live 2026-10.)"""
    return (
        '<div class="theme-songs js-theme-songs opnening">' + POPUP_SCRIPT + """
      <table border="0" width="100%"><tr><td width="8%"><div class="oped-preview-button"></div></td>
          <td width="84%"><span class="theme-song-index">1:</span>&nbsp;<a href="javascript:openMusicLinkPopup('36013', 'Guren\\x20no\\x20Yumiya\\x20\\x28\\u7D05\\u84EE\\u306E\\u5F13\\u77E2\\x29', 'Linked\\x20Horizon', '7FzhSDmKqNyIOK3FcwiqHo');"><span class="theme-song-title">&quot;Guren no Yumiya (紅蓮の弓矢)&quot;</span></a><span class="theme-song-artist"> by Linked Horizon</span>&nbsp;<span class="theme-song-episode">(eps 1-13)</span><input type="hidden" id="spotify_url_36013" value="https://open.spotify.com/track/7FzhSDmKqNyIOK3FcwiqHo" />
          </td></tr><tr><td width="8%"><div class="oped-preview-button"></div></td>
          <td width="84%"><span class="theme-song-index">2:</span>&nbsp;<a href="javascript:openMusicLinkPopup('36015', 'Jiyuu\\x20no\\x20Tsubasa', 'Linked\\x20Horizon', '2VtK9Fj9OS11cYb0cCvLwK');"><span class="theme-song-title">&quot;Jiyuu no Tsubasa (自由の翼)&quot;</span></a><span class="theme-song-artist"> by Linked Horizon</span>&nbsp;<span class="theme-song-episode">(eps 14-25)</span><input type="hidden" id="spotify_url_36015" value="https://open.spotify.com/track/2VtK9Fj9OS11cYb0cCvLwK" />
          </td></tr></table>
        </div>
      <div class="theme-songs js-theme-songs ending">
        <table><tr><td><span class="theme-song-index">1:</span>&nbsp;<span class="theme-song-title">&quot;Huge Diamonds&quot;</span><span class="theme-song-artist"> by SCANDAL</span></td></tr></table>
      </div>"""
    )


def plain_text_shape_page():
    """Shape 2: song rows are plain quoted text; spotify_url_<id> input is
    EMPTY; no anchor, no theme-song-title span. (Bleach 21, live 2026-10.)"""
    return (
        '<div class="theme-songs js-theme-songs opnening">' + POPUP_SCRIPT + """
      <table border="0" width="100%"><tr><td width="8%">
            <div class="oped-preview-button oped-preview-button-gray"></div></td>
          <td width="84%"><span class="theme-song-index">1:</span>&nbsp;&quot;We Are! (ウィーアー!)&quot;<span class="theme-song-artist"> by Hiroshi Kitadani (きただにひろし)</span>&nbsp;<span class="theme-song-episode">(eps 1-13)</span><input type="hidden" id="spotify_url_85133" value="" />
          </td></tr><tr><td width="8%">
            <div class="oped-preview-button oped-preview-button-gray"></div></td>
          <td width="84%"><span class="theme-song-index">2:</span>&nbsp;&quot;Break Up&quot;<span class="theme-song-artist"> by Angela Aki</span>&nbsp;<span class="theme-song-episode">(eps 25-38)</span><input type="hidden" id="spotify_url_85134" value="" />
          </td></tr></table>
      </div>
      <div class="theme-songs js-theme-songs ending">
        <span class="theme-song-artist"> by NOT THE OP</span>
      </div>"""
    )


def nested_table_page():
    """The container-end trap: tables nest INSIDE the opening container, and
    an ending container begins right after — rows after the first </table>
    inside the opening container MUST still parse, and nothing from the
    ending container may leak in."""
    return (
        '<div class="theme-songs js-theme-songs opnening">'
        '<table><tr><td>'
        '<span class="theme-song-title">&quot;First OP&quot;</span>'
        '<span class="theme-song-artist"> by Alpha Band</span>'
        '</td></tr></table>'
        '<table class="inner-nested"><tr><td>'  # nested table, still openings
        '<span class="theme-song-title">&quot;Second OP&quot;</span>'
        '<span class="theme-song-artist"> by Beta Band</span>'
        '<input type="hidden" id="spotify_url_99" '
        'value="https://open.spotify.com/track/AAAAAAAAAAAAAAAA" />'
        '</td></tr></table>'
        '</div>'
        '<div class="theme-songs js-theme-songs ending">'
        '<span class="theme-song-title">&quot;Ending Track&quot;</span>'
        '<span class="theme-song-artist"> by ZZZ Should Not Appear</span>'
        '</div>'
    )


def popup_only_page():
    """Anchor carries the popup call with the track id while the visible
    spotify_url input is missing/empty — id must still come from arg #4."""
    return (
        '<div class="theme-songs js-theme-songs opnening">'
        '<span class="theme-song-index">1:</span>'
        '<a href="javascript:openMusicLinkPopup(\'123\', \'Song%20Title\', '
        '\'Artist\', \'QQzw2W0zFEEe1HQL5IueIv\');">'
        '<span class="theme-song-title">&quot;Song Title&quot;</span></a>'
        '<span class="theme-song-artist"> by Artist Name</span>'
        '<input type="hidden" id="spotify_url_123" value="" />'
        '</div>'
    )


def user_list_page(items):
    """The animelist page embeds the list as HTML-escaped JSON in the
    list-table's data-items attribute."""
    blob = H.escape(json.dumps(items), quote=True)
    return (f'<html><body><table class="list-table" data-items="{blob}" '
            f'data-server="1"><tr><td>rows render here too</td></tr>'
            f'</table></body></html>')


def tile_user_list_page(items):
    """Synthetic tile-view list page with optional progress and tag cells."""
    blob = H.escape(json.dumps(items), quote=True)
    return (f'<html><body><table class="list-table" data-items="{blob}" '
            'data-server="1"><tbody>'
            '<tr class="list-table-data"><td class="title">Special</td>'
            '<td class="progress">1 / 1</td></tr>'
            '<tr class="list-table-data"><td class="title">ONA entry</td>'
            '<td class="tags"><span>watch-later</span></td></tr>'
            '</tbody></table></body></html>')


# ---------------------------------------------------------------- tests

class TestOpeningParsers(unittest.TestCase):
    def test_anchor_shape_extracts_ids(self):
        ops = extract_openings(anchor_shape_page())
        self.assertEqual(len(ops), 2, "ED rows must not be included")
        self.assertEqual(ops[0]["title"], "Guren no Yumiya (紅蓮の弓矢)")
        self.assertEqual(ops[0]["artist"], "Linked Horizon")
        self.assertEqual(ops[0]["spotify_id"], "7FzhSDmKqNyIOK3FcwiqHo")
        self.assertEqual(ops[1]["spotify_id"], "2VtK9Fj9OS11cYb0cCvLwK")

    def test_plain_text_shape_empty_id(self):
        ops = extract_openings(plain_text_shape_page())
        self.assertEqual(len(ops), 2)
        self.assertEqual(ops[0]["title"], "We Are! (ウィーアー!)")
        self.assertEqual(ops[0]["artist"], "Hiroshi Kitadani (きただにひろし)")
        self.assertIsNone(ops[0]["spotify_id"],
                          "empty spotify_url_ input must yield None, not ''")
        self.assertEqual(ops[1]["title"], "Break Up")

    def test_container_ends_at_next_js_theme_songs_not_first_table(self):
        ops = extract_openings(nested_table_page())
        titles = [o["title"] for o in ops]
        self.assertEqual(titles, ["First OP", "Second OP"],
                         "rows inside a nested table must parse; rows in the "
                         "ending container must not leak into openings")
        self.assertEqual(ops[1]["spotify_id"], "AAAAAAAAAAAAAAAA")

    def test_popup_arg_id_when_input_empty(self):
        ops = extract_openings(popup_only_page())
        self.assertEqual(ops[0]["spotify_id"], "QQzw2W0zFEEe1HQL5IueIv")

    def test_dedupe_repeated_blocks(self):
        page = nested_table_page() + nested_table_page()
        ops = extract_openings(page)
        self.assertEqual(len(ops), 2, "identical repeats must dedupe")

    def test_fullwidth_and_entities(self):
        page = ('<div class="theme-songs js-theme-songs opnening">'
                '<span class="theme-song-title">&quot;Ｃｏｔｏｎａ&quot;'
                '&#32;〜風〜</span><span class="theme-song-artist"> by '
                'Yui&#32;Horie</span></div>')
        ops = extract_openings(page)
        self.assertEqual(ops[0]["artist"], "Yui Horie")
        self.assertTrue(ops[0]["title"].startswith("Ｃｏｔｏｎａ"))


class TestUserListParser(unittest.TestCase):
    def test_embedded_json_blob(self):
        items = [
            {"status": 2, "anime_id": 47, "anime_title": "AKIRA",
             "anime_title_eng": "Akira", "anime_media_type_string": "Movie"},
            {"status": 2, "anime_id": 16498, "anime_title": "Shingeki no Kyojin",
             "anime_title_eng": "Attack on Titan",
             "anime_media_type_string": "TV"},
        ]
        rows = parse_user_list(user_list_page(items))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["mal_id"], 16498)
        self.assertEqual(rows[1]["title"], "Attack on Titan")
        self.assertEqual(rows[0]["type"], "Movie")
        self.assertEqual([r["row"] for r in rows], [0, 1])

    def test_no_table_returns_empty(self):
        self.assertEqual(parse_user_list("<html>nothing</html>"), [])

    def test_tile_view_supports_tv_special_ona_missing_progress_and_tags(self):
        items = [
            {"status": 2, "anime_id": 901, "anime_title": "Special",
             "anime_title_eng": "Special Episode", "anime_media_type_string": "TV Special",
             "num_watched_episodes": 1},
            {"status": 6, "anime_id": 902, "anime_title": "ONA Entry",
             "anime_title_eng": "ONA Entry", "anime_media_type_string": "ONA",
             "tags": "watch-later"},
        ]

        rows = parse_user_list(tile_user_list_page(items))

        self.assertEqual(rows, [
            {"mal_id": 901, "title": "Special Episode", "type": "TV Special",
             "row": 0, "status": 2},
            {"mal_id": 902, "title": "ONA Entry", "type": "ONA",
             "row": 1, "status": 6},
        ])

    @patch("mal_openings.mal.fetch", return_value=user_list_page([]))
    def test_empty_requested_status_raises_clean_error(self, mock_fetch):
        with self.assertRaisesRegex(MalError, "^no list rows found"):
            get_user_list("synthetic-user", status="completed")

        mock_fetch.assert_called_once_with(
            "https://myanimelist.net/animelist/synthetic-user?status=2")


class TestNormalize(unittest.TestCase):
    def test_japanese_alt_form_extraction(self):
        alts = title_alts("Guren no Yumiya (紅蓮の弓矢)")
        self.assertIn("Guren no Yumiya", alts)
        self.assertIn("紅蓮の弓矢", alts,
                      "Spotify often carries ONLY the Japanese form")

    def test_tilde_subtitle_form(self):
        alts = title_alts("02~ｵｰ・ﾂｰ~")
        self.assertTrue(any("02" in a for a in alts))

    def test_title_match_across_forms(self):
        self.assertTrue(title_match("Guren no Yumiya (紅蓮の弓矢)", "紅蓮の弓矢"))
        self.assertTrue(title_match("The World", "the world"))
        self.assertFalse(title_match("Haru (晴る)", "unrelated song"))

    def test_fullwidth_fold(self):
        self.assertTrue(title_match("Ｃｏｔｏｎａ", "Cotona"))

    def test_artist_tokens_strips_reading_parens(self):
        toks = artist_tokens("Hiroshi Kitadani (きただにひろし)")
        self.assertIn("hiroshi", toks)
        self.assertIn("kitadani", toks)
        # parenthetical Japanese reading must NOT produce a token that
        # fails to match Spotify's romanized artist string
        self.assertTrue(all("(" not in t for t in toks))


if __name__ == "__main__":
    unittest.main()
