from __future__ import annotations

import re

from sqlalchemy import func, select

from papervisor.core.sanitizers import clean_token as _clean_token
from papervisor.db.models import Paper
from papervisor.db.session import get_session


_AUTHOR_SPLIT_RE = re.compile(r"\s*(?:,|;|\band\b|\s&\s)\s*", flags=re.IGNORECASE)


def _norm_limit(limit: int, *, default: int = 250, max_value: int = 1000) -> int:
    try:
        n = int(limit)
    except Exception:
        n = int(default)
    if n <= 0:
        n = int(default)
    return min(n, int(max_value))


def _dedupe_case_insensitive(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def list_author_suggestions(*, limit: int = 250) -> list[str]:
    """Return individual author tokens split from Paper.authors."""

    limit_n = _norm_limit(limit, default=250, max_value=1000)
    # Over-fetch because one Paper.authors field can yield many tokens.
    fetch_limit = min(max(limit_n * 10, 500), 5000)

    with get_session() as session:
        rows = (
            session.execute(
                select(Paper.authors)
                .where(Paper.authors.is_not(None))
                .where(func.length(func.trim(Paper.authors)) > 0)
                .order_by(func.lower(Paper.authors).asc())
                .limit(int(fetch_limit))
            )
            .scalars()
            .all()
        )

    tokens: list[str] = []
    for raw in rows:
        s = _clean_token(str(raw or ''))
        if not s:
            continue
        # Common separators: comma/semicolon, and sometimes " and ", " & ".
        parts = _AUTHOR_SPLIT_RE.split(s)
        for p in parts:
            p = _clean_token(p)
            if len(p) < 2:
                continue
            tokens.append(p)

    tokens = _dedupe_case_insensitive(tokens)
    tokens.sort(key=lambda x: x.lower())
    return tokens[: int(limit_n)]


def list_publisher_suggestions(*, limit: int = 250) -> list[str]:
    limit_n = _norm_limit(limit, default=250, max_value=1000)
    fetch_limit = min(max(limit_n * 3, 250), 5000)
    with get_session() as session:
        rows = (
            session.execute(
                select(Paper.publisher)
                .where(Paper.publisher.is_not(None))
                .where(func.length(func.trim(Paper.publisher)) > 0)
                .order_by(func.lower(Paper.publisher).asc())
                .limit(int(fetch_limit))
            )
            .scalars()
            .all()
        )
    out = [_clean_token(r) for r in rows]
    out = [r for r in out if r]
    out = _dedupe_case_insensitive(out)
    return out[: int(limit_n)]


def list_journal_suggestions(*, limit: int = 250) -> list[str]:
    limit_n = _norm_limit(limit, default=250, max_value=1000)
    fetch_limit = min(max(limit_n * 3, 250), 5000)
    with get_session() as session:
        rows = (
            session.execute(
                select(Paper.journal)
                .where(Paper.journal.is_not(None))
                .where(func.length(func.trim(Paper.journal)) > 0)
                .order_by(func.lower(Paper.journal).asc())
                .limit(int(fetch_limit))
            )
            .scalars()
            .all()
        )
    out = [_clean_token(r) for r in rows]
    out = [r for r in out if r]
    out = _dedupe_case_insensitive(out)
    return out[: int(limit_n)]
