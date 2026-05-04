from __future__ import annotations

import os
from typing import Any

import requests

from papervisor.core.sanitizers import clean_isbn as _clean_isbn
from papervisor.services.settings import get_google_books_api_key
from papervisor.services.isbn import IsbnMetadata


_GOOGLE_BOOKS_VOLUMES_URL = 'https://www.googleapis.com/books/v1/volumes'
_USER_AGENT = 'PaperVisor/0.1'


def _enabled() -> bool:
    # Default: enabled (can be disabled for privacy/offline installs).
    val = str(os.environ.get('PAPERVISOR_ENABLE_GOOGLE_BOOKS', '1')).strip().lower()
    return val not in {'0', 'false', 'no', 'off'}


def _get_api_key() -> str:
    return str(get_google_books_api_key() or '').strip() or str(os.environ.get('GOOGLE_BOOKS_API_KEY', '')).strip()


def _request_volumes(*, params: dict[str, str], timeout_s: float) -> tuple[requests.Response | None, str | None]:
    api_key = _get_api_key()
    if api_key:
        params = dict(params)
        params['key'] = api_key

    try:
        resp = requests.get(
            _GOOGLE_BOOKS_VOLUMES_URL,
            params=params,
            timeout=timeout_s,
            headers={'User-Agent': _USER_AGENT},
        )
    except Exception as e:
        return None, f'network error: {e}'

    return resp, None


def _request_volumes_json_best_effort(*, params: dict[str, str], timeout_s: float) -> dict[str, Any] | None:
    resp, _err = _request_volumes(params=params, timeout_s=timeout_s)
    if resp is None:
        return None
    if resp.status_code >= 400:
        return None
    if not resp.content:
        return {}

    try:
        return resp.json()
    except Exception:
        return None


def _request_volumes_json_or_raise(*, params: dict[str, str], timeout_s: float) -> dict[str, Any]:
    resp, err = _request_volumes(params=params, timeout_s=timeout_s)
    if resp is None:
        raise ValueError(f'Google Books lookup failed ({err})')

    if resp.status_code >= 400:
        raise ValueError(f'Google Books lookup failed ({resp.status_code})')

    if not resp.content:
        return {}

    try:
        return resp.json()
    except Exception as e:
        raise ValueError(f'Google Books lookup failed (invalid JSON: {e})')


def search_googlebooks_isbn(*, title: str, author: str | None = None, timeout_s: float = 6.0) -> str | None:
    """Best-effort ISBN discovery using Google Books.

    Uses the public Volumes API search endpoint to find an ISBN-13/10.

    Controlled by env var:
    - `PAPERVISOR_ENABLE_GOOGLE_BOOKS=0` disables this lookup.
    """

    if not _enabled():
        return None

    t = (title or '').strip()
    if len(t) < 3:
        return None

    a = (author or '').strip()

    def _request(q: str) -> dict[str, Any] | None:
        return _request_volumes_json_best_effort(
            params={
                'q': q,
                'maxResults': '5',
                'printType': 'books',
            },
            timeout_s=timeout_s,
        )

    # First try: structured query (usually more precise).
    query_parts = [f'intitle:{t}']
    if a:
        query_parts.append(f'inauthor:{a}')
    payload = _request(' '.join(query_parts))

    # Second try: plain query (often works better for messy metadata).
    if not payload or not isinstance(payload.get('items'), list) or not payload.get('items'):
        q2 = t if not a else f'{t} {a}'
        payload = _request(q2)
    if not payload:
        return None
    items = payload.get('items')
    if not isinstance(items, list) or not items:
        return None

    def _extract_identifiers(volume: dict[str, Any]) -> list[str]:
        vi = volume.get('volumeInfo')
        if not isinstance(vi, dict):
            return []
        ids = vi.get('industryIdentifiers')
        if not isinstance(ids, list):
            return []
        out: list[str] = []
        for ident in ids:
            if not isinstance(ident, dict):
                continue
            out.append(str(ident.get('identifier') or ''))
        return out

    # Prefer ISBN_13 if present.
    candidates: list[str] = []
    for v in items:
        if not isinstance(v, dict):
            continue
        for ident in _extract_identifiers(v):
            cleaned = _clean_isbn(ident)
            if cleaned:
                candidates.append(cleaned)

    if not candidates:
        return None

    isbn13 = next((c for c in candidates if len(c) == 13), None)
    return isbn13 or candidates[0]


def fetch_googlebooks_metadata(isbn: str, *, timeout_s: float = 6.0) -> IsbnMetadata:
    """Fetch basic book metadata by ISBN using Google Books.

    Returns fields that fit PaperVisor's current DB schema.
    """

    if not _enabled():
        raise ValueError('Google Books is disabled')

    cleaned = _clean_isbn(isbn)
    if not cleaned:
        raise ValueError('ISBN is required')

    params: dict[str, str] = {
        'q': f'isbn:{cleaned}',
        'maxResults': '5',
        'printType': 'books',
    }

    payload = _request_volumes_json_or_raise(params=params, timeout_s=timeout_s)

    items = payload.get('items')
    if not isinstance(items, list) or not items:
        raise ValueError('Google Books: no results')

    # Choose the first plausible volume.
    best = next((x for x in items if isinstance(x, dict)), None)
    if not isinstance(best, dict):
        raise ValueError('Google Books: invalid response')

    vi = best.get('volumeInfo')
    if not isinstance(vi, dict):
        raise ValueError('Google Books: missing volumeInfo')

    title = str(vi.get('title') or '').strip()

    authors_str = ''
    authors = vi.get('authors')
    if isinstance(authors, list):
        names = [str(a or '').strip() for a in authors]
        names = [n for n in names if n]
        authors_str = '; '.join(names)

    publisher = str(vi.get('publisher') or '').strip()

    year = ''
    published_date = str(vi.get('publishedDate') or '').strip()
    # Formats: YYYY, YYYY-MM-DD, YYYY-MM
    if len(published_date) >= 4 and published_date[:4].isdigit():
        year = published_date[:4]

    description = str(vi.get('description') or '').strip()
    language = str(vi.get('language') or '').strip()

    genres = ''
    cats = vi.get('categories')
    if isinstance(cats, list):
        parts = [str(c or '').strip() for c in cats]
        parts = [p for p in parts if p]
        if parts:
            genres = '; '.join(parts)

    page_count: int | None = None
    try:
        pc = vi.get('pageCount')
        if isinstance(pc, int):
            page_count = pc
        elif isinstance(pc, str) and pc.strip().isdigit():
            page_count = int(pc.strip())
    except Exception:
        page_count = None

    # Prefer returning an ISBN_13 if present.
    best_isbn = cleaned
    ids = vi.get('industryIdentifiers')
    if isinstance(ids, list):
        candidates: list[str] = []
        for ident in ids:
            if not isinstance(ident, dict):
                continue
            c = _clean_isbn(str(ident.get('identifier') or ''))
            if c:
                candidates.append(c)
        isbn13 = next((c for c in candidates if len(c) == 13), None)
        best_isbn = isbn13 or (candidates[0] if candidates else cleaned)

    return IsbnMetadata(
        isbn=best_isbn,
        title=title,
        authors=authors_str,
        year=year,
        publisher=publisher,
        description=description,
        language=language,
        genres=genres,
        publication_date=published_date,
        page_count=page_count,
    )


def fetch_googlebooks_cover(*, isbn: str, timeout_s: float = 8.0) -> tuple[bytes, str]:
    """Fetch a cover image for an ISBN using Google Books.

    Returns (bytes, ext) where ext is one of: .jpg/.png/.webp.
    """

    if not _enabled():
        raise ValueError('Google Books is disabled')

    cleaned = _clean_isbn(isbn)
    if not cleaned:
        raise ValueError('ISBN is required')

    params: dict[str, str] = {
        'q': f'isbn:{cleaned}',
        'maxResults': '5',
        'printType': 'books',
    }

    payload = _request_volumes_json_or_raise(params=params, timeout_s=timeout_s)

    items = payload.get('items')
    if not isinstance(items, list) or not items:
        raise ValueError('Google Books: no results')

    best = next((x for x in items if isinstance(x, dict)), None)
    if not isinstance(best, dict):
        raise ValueError('Google Books: invalid response')
    vi = best.get('volumeInfo')
    if not isinstance(vi, dict):
        raise ValueError('Google Books: missing volumeInfo')

    image_links = vi.get('imageLinks')
    if not isinstance(image_links, dict):
        raise ValueError('Google Books: no cover available')

    # Prefer best available resolution.
    img_url = (
        str(image_links.get('extraLarge') or '')
        or str(image_links.get('large') or '')
        or str(image_links.get('medium') or '')
        or str(image_links.get('thumbnail') or '')
        or str(image_links.get('smallThumbnail') or '')
    ).strip()
    if not img_url:
        raise ValueError('Google Books: no cover available')

    # Some URLs are http; allow requests to follow redirects.
    img_url = img_url.replace('http://', 'https://', 1)
    try:
        img_resp = requests.get(img_url, timeout=timeout_s, headers={'User-Agent': _USER_AGENT})
    except Exception as e:
        raise ValueError(f'Google Books: cover download failed ({e})')
    if img_resp.status_code >= 400 or not img_resp.content:
        raise ValueError(f'Google Books: cover download failed ({img_resp.status_code})')

    content_type = str(img_resp.headers.get('content-type') or '').lower()
    if 'png' in content_type:
        ext = '.png'
    elif 'webp' in content_type:
        ext = '.webp'
    else:
        ext = '.jpg'

    return img_resp.content, ext
