"""Text helpers shared across apps."""

import re
import unicodedata
from difflib import SequenceMatcher

_SPACES = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def clean_text(value):
    """Trim and collapse internal whitespace; keep case and spelling."""
    if value is None:
        return ""
    return _SPACES.sub(" ", str(value)).strip()


def normalize_name(value):
    """Comparison key for person names: lower-case, no punctuation, single spaces."""
    text = unicodedata.normalize("NFKC", clean_text(value)).lower()
    return _SPACES.sub(" ", _PUNCT.sub(" ", text)).strip()


def names_similar(a, b, threshold=0.85):
    a, b = normalize_name(a), normalize_name(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold
