"""Reusable string-cleaning helpers.

Centralises the many small ``_clean_*`` / ``_normalize_*`` functions that
were duplicated across ``services/settings.py``, ``services/user_settings.py``,
``services/tags.py``, ``services/patterns.py``, ``services/markers.py``,
``services/suggestions.py``, ``services/epub.py``, ``services/doi.py``,
``services/isbn.py`` and ``services/google_books.py``.
"""

from __future__ import annotations

import re
from html import unescape


# ---------------------------------------------------------------------------
# Pre-compiled patterns
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_ISBN_NON_DIGIT_RE = re.compile(r"[^0-9Xx]")
_JUNK_EDGE_CHARS = " \t\n\r\"'\u201c\u201d"


# ---------------------------------------------------------------------------
# Generic text cleaning
# ---------------------------------------------------------------------------

def clean_nul(value: str | None) -> str:
    """Strip NUL bytes and surrounding whitespace.

    This is the common pattern used by settings keys/values, pattern values,
    tag names, and similar user-supplied identifiers.
    """
    return str(value or "").replace("\x00", "").strip()


def clean_text(value: str | None) -> str:
    """Collapse whitespace and unescape HTML entities.

    Used when extracting human-readable text from EPUB / HTML / JATS content.
    """
    return unescape(_WS_RE.sub(" ", (value or "").strip()))


def clean_token(value: str | None) -> str:
    """Normalise whitespace and strip surrounding quote/junk characters.

    Used for search-suggestion tokens and autocomplete values.
    """
    s = str(value or "").strip()
    s = _WS_RE.sub(" ", s)
    return s.strip(_JUNK_EDGE_CHARS)


# ---------------------------------------------------------------------------
# HTML / markup stripping
# ---------------------------------------------------------------------------

def strip_html_tags(value: str | None) -> str:
    """Remove HTML / XML / JATS tags, collapse newlines, unescape entities."""
    if not value:
        return ""
    cleaned = _TAG_RE.sub("", value).replace("\n", " ").strip()
    return unescape(cleaned)


# ---------------------------------------------------------------------------
# ISBN cleaning
# ---------------------------------------------------------------------------

def clean_isbn(raw: str | None) -> str | None:
    """Extract a valid ISBN-10 or ISBN-13 from *raw*, or return ``None``.

    Strips everything except digits and ``X``, then validates the length.
    """
    s = (raw or "").strip()
    if not s:
        return None
    s = _ISBN_NON_DIGIT_RE.sub("", s).upper()
    if len(s) in {10, 13}:
        return s
    return None


# ---------------------------------------------------------------------------
# List normalisation
# ---------------------------------------------------------------------------

def normalize_list(
    values: list[str] | None,
    *,
    max_item_len: int = 0,
    strip_nul: bool = False,
) -> list[str]:
    """Strip, de-duplicate (case-insensitive), and optionally truncate items.

    Parameters
    ----------
    values:
        Raw list of strings.
    max_item_len:
        If > 0, truncate each item to this many characters (after stripping).
    strip_nul:
        If ``True`` also remove NUL bytes from each item (useful for tags).
    """
    if not values:
        return []

    out: list[str] = []
    for v in values:
        v = str(v or "").strip()
        if strip_nul:
            v = v.replace("\x00", "")
        if not v:
            continue
        if max_item_len > 0 and len(v) > max_item_len:
            v = v[:max_item_len].rstrip()
        out.append(v)

    # De-duplicate preserving insertion order.
    seen: set[str] = set()
    deduped: list[str] = []
    for v in out:
        key = v.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(v)
    return deduped
