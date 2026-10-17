"""Title/artist normalization, alternate title forms, and junk-version rejection.

Proven by the live build:
  * MAL titles look like "Romanji (日本語)" and Spotify often carries ONLY the
    Japanese form inside the parens -> the inner-paren content must become a
    separate search/compare form.
  * Full-width characters (：、！（）～) appear in MAL and in Japanese track
    names -> NFKD/NFKC folding is required before any comparison.
  * Direct MAL links occasionally point at TV-size/live/acoustic versions;
    those names must be recognized and rejected in favor of a full version.
"""
import re
import unicodedata

# Versions we never want in an openings playlist when a studio full exists.
BAD_NAME = re.compile(
    r"tv[\s\-]*size|size ver|\bshort ver|live at|\blive\b|live version|the live|"
    r"acoustic|instrumental|karaoke|off ?vocal|\bremix\b|bootleg|\btour\b|"
    r"\bcover\b|strings version|orchestral|remastered single|dj[\s\-]?"
    r"|\d+(?:st|nd|rd|th)[\s\-]*(?:anniversary|live)",
    re.I)

_PAREN = re.compile(r"[（(]([^（）()]{1,80})[)）]")
_TILDE = re.compile(r"\s*[~～][^~～]*[~～]?\s*")


def norm(s: str) -> str:
    """Fold width/accents, lowercase, drop punctuation noise outside CJK."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("’", "'")
    s = re.sub(r"[（(].*?[)）]", " ", s)
    s = re.sub(r"[~～].*?[~～]", " ", s)
    s = re.sub(r"[^0-9a-z\u3000-\u9fff\uac00-\ud7af'&+ -]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_keep_parens(s: str) -> str:
    """Normalization WITHOUT dropping paren content (for exact-eq of alt forms)."""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^0-9a-z*'&+?!.\- （）()\u3000-\u9fff\uac00-\ud7af]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def title_alts(title: str) -> list[str]:
    """Alternate search/compare forms of a MAL OP title, best first.

    "Guren no Yumiya (紅蓮の弓矢)" -> itself, "Guren no Yumiya", "紅蓮の弓矢".
    Also strips "~...~" subtitle segments (e.g. "02~ｵｰ・ﾂｰ~").
    """
    forms = [title]
    no_tail = re.sub(r"\s*[（(][^（）()]*[)）]\s*$", "", title).strip()
    if no_tail and no_tail not in forms:
        forms.append(no_tail)
    no_tilde = _TILDE.sub(" ", no_tail or title).strip()
    if no_tilde and no_tilde not in forms:
        forms.append(no_tilde)
    for inner in _PAREN.findall(title):
        inner = inner.strip()
        if inner and inner not in forms:
            forms.append(inner)
    return forms


def title_match(mal_title: str, spotify_name: str) -> bool:
    """True when any alt form of the MAL title eq-or-contains the Spotify name."""
    ns = norm(spotify_name)
    if not ns:
        return False
    for alt in title_alts(mal_title):
        na = norm(alt)
        if not na:
            continue
        if na == ns or (len(na) >= 4 and (na in ns or ns in na)):
            return True
        # exact match of a kept-parens form (Japanese title with （）)
        ka = norm_keep_parens(alt)
        if ka and ka == norm_keep_parens(spotify_name):
            return True
    return False


def artist_tokens(artist: str) -> list[str]:
    """Searchable name tokens from a MAL artist string.

    Strips parenthetical readings ("Hiroshi Kitadani (きただにひろし)"),
    splits on , / & × x, keeps tokens long enough to be discriminative.
    """
    t = re.sub(r"[（(][^（）()]*[)）]", " ", artist or "")
    parts = re.split(r"[,&/×]|\bx\b|\s+", t)
    toks = [norm(p) for p in parts]
    return [x for x in toks if len(x) > 2][:5]


def artist_match(mal_artist: str, spotify_artists: str) -> bool:
    names = " ".join(norm(a) for a in re.split(r",", spotify_artists or ""))
    toks = artist_tokens(mal_artist)
    if not toks:
        return True
    return any(tk in names for tk in toks)


def is_bad_version(name: str, album: str = "") -> bool:
    return bool(BAD_NAME.search((name or "") + " " + (album or "")))
