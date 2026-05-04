from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
import xml.etree.ElementTree as ET

import fitz  # PyMuPDF
import requests

from papervisor.core.sanitizers import clean_isbn as _clean_isbn


_ISBN_RE = re.compile(r"(?:ISBN(?:-1[03])?:?\s*)?([0-9][0-9\-\s]{8,20}[0-9Xx])")

_USER_AGENT = 'PaperVisor/0.1'
_OPENLIBRARY_BOOKS_URL = 'https://openlibrary.org/api/books'
_OPENLIBRARY_SEARCH_URL = 'https://openlibrary.org/search.json'


@dataclass(frozen=True)
class IsbnMetadata:
    isbn: str
    title: str
    authors: str
    year: str
    publisher: str
    description: str = ''
    language: str = ''
    genres: str = ''
    publication_date: str = ''
    series: str = ''
    series_index: str = ''
    page_count: int | None = None


def extract_isbn_from_text(text: str) -> str | None:
    if not text:
        return None

    candidates: list[str] = []
    for match in _ISBN_RE.finditer(text):
        cleaned = _clean_isbn(match.group(1))
        if cleaned:
            candidates.append(cleaned)

    if not candidates:
        return None

    isbn13 = next((c for c in candidates if len(c) == 13), None)
    return isbn13 or candidates[0]


def extract_isbn_from_filename(filename: str) -> str | None:
    return extract_isbn_from_text(filename or '')


def extract_isbn_from_pdf(file_path: str, *, max_pages: int = 2) -> str | None:
    try:
        doc = fitz.open(file_path)
    except Exception:
        return None

    try:
        pages = min(max_pages, doc.page_count)
        for i in range(pages):
            text = str(doc.load_page(i).get_text('text') or '')
            isbn = extract_isbn_from_text(text)
            if isbn:
                return isbn
        return None
    finally:
        doc.close()


def _read_zip_text(zf: zipfile.ZipFile, path: str) -> str | None:
    try:
        with zf.open(path) as f:
            return f.read().decode('utf-8', errors='ignore')
    except Exception:
        return None


def extract_isbn_from_epub(file_path: str) -> str | None:
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            container_xml = _read_zip_text(zf, 'META-INF/container.xml')
            if not container_xml:
                return None

            try:
                root = ET.fromstring(container_xml)
            except Exception:
                return None
            rootfile = root.find('.//{*}rootfile')
            if rootfile is None:
                return None
            opf_path = rootfile.attrib.get('full-path')
            if not opf_path:
                return None

            opf_xml = _read_zip_text(zf, opf_path)
            if not opf_xml:
                return None

            try:
                opf_root = ET.fromstring(opf_xml)
            except Exception:
                return None
            # Try all identifier nodes, regardless of namespaces
            for node in opf_root.findall('.//{*}identifier'):
                txt = (node.text or '').strip()
                # Common patterns: 'urn:isbn:XXXXXXXXX'
                if 'isbn' in txt.lower():
                    isbn = extract_isbn_from_text(txt)
                    if isbn:
                        return isbn

            # Fallback: search the whole OPF text
            return extract_isbn_from_text(opf_xml)
    except Exception:
        return None


def _request_json_best_effort(*, url: str, params: dict[str, str] | None, timeout_s: float) -> dict[str, Any] | None:
    try:
        resp = requests.get(url, params=params, timeout=timeout_s, headers={'User-Agent': _USER_AGENT})
    except Exception:
        return None
    if resp.status_code >= 400:
        return None
    if not resp.content:
        return {}
    try:
        return resp.json()
    except Exception:
        return None


def _request_json_or_raise(*, url: str, params: dict[str, str] | None, timeout_s: float, label: str) -> dict[str, Any]:
    try:
        resp = requests.get(url, params=params, timeout=timeout_s, headers={'User-Agent': _USER_AGENT})
    except Exception as e:
        raise ValueError(f'{label} lookup failed (network error: {e})')
    if resp.status_code >= 400:
        raise ValueError(f'{label} lookup failed ({resp.status_code})')
    if not resp.content:
        return {}
    try:
        return resp.json()
    except Exception as e:
        raise ValueError(f'{label} lookup failed (invalid JSON: {e})')


def fetch_openlibrary_metadata(isbn: str, *, timeout_s: float = 6.0) -> IsbnMetadata:
    cleaned = _clean_isbn(isbn)
    if not cleaned:
        raise ValueError('ISBN is required')

    payload = _request_json_or_raise(
        url=_OPENLIBRARY_BOOKS_URL,
        params={
            'bibkeys': f'ISBN:{cleaned}',
            'format': 'json',
            'jscmd': 'data',
        },
        timeout_s=timeout_s,
        label='OpenLibrary',
    )
    data = payload.get(f'ISBN:{cleaned}') or {}
    if not isinstance(data, dict) or not data:
        raise ValueError('OpenLibrary: no results')

    title = str(data.get('title') or '')

    authors_str = ''
    authors = data.get('authors')
    if isinstance(authors, list):
        names = [str(a.get('name') or '').strip() for a in authors if isinstance(a, dict)]
        names = [n for n in names if n]
        authors_str = '; '.join(names)

    publisher = ''
    publishers = data.get('publishers')
    if isinstance(publishers, list) and publishers:
        first = publishers[0]
        if isinstance(first, dict):
            publisher = str(first.get('name') or '')

    year = ''
    publish_date = str(data.get('publish_date') or '')
    m = re.search(r'\b(\d{4})\b', publish_date)
    if m:
        year = m.group(1)

    # Optional richer fields
    description = ''
    desc_val = data.get('description')
    if isinstance(desc_val, dict):
        description = str(desc_val.get('value') or '')
    elif isinstance(desc_val, str):
        description = desc_val
    if not description:
        notes_val = data.get('notes')
        if isinstance(notes_val, dict):
            description = str(notes_val.get('value') or '')
        elif isinstance(notes_val, str):
            description = notes_val
    description = (description or '').strip()

    language = ''
    langs = data.get('languages')
    if isinstance(langs, list) and langs:
        first = langs[0]
        if isinstance(first, dict):
            key = str(first.get('key') or '').strip()
            if key:
                language = key.rsplit('/', 1)[-1]

    genres = ''
    subjects = data.get('subjects')
    if isinstance(subjects, list) and subjects:
        subject_names: list[str] = []
        for s in subjects[:12]:
            if isinstance(s, dict):
                n = str(s.get('name') or '').strip()
                if n:
                    subject_names.append(n)
            elif isinstance(s, str):
                n = s.strip()
                if n:
                    subject_names.append(n)
        genres = '; '.join(subject_names)

    publication_date = publish_date.strip()

    page_count: int | None = None
    try:
        n_pages = data.get('number_of_pages')
        if isinstance(n_pages, int):
            page_count = n_pages
        elif isinstance(n_pages, str) and n_pages.strip().isdigit():
            page_count = int(n_pages.strip())
    except Exception:
        page_count = None

    return IsbnMetadata(
        isbn=cleaned,
        title=title,
        authors=authors_str,
        year=year,
        publisher=publisher,
        description=description,
        language=language,
        genres=genres,
        publication_date=publication_date,
        page_count=page_count,
    )


def search_openlibrary_isbn(*, title: str, author: str | None = None, timeout_s: float = 6.0) -> str | None:
    """Best-effort ISBN discovery using OpenLibrary search.

    Returns the first plausible ISBN from the top search result.
    """

    t = (title or '').strip()
    if len(t) < 3:
        return None

    params = {
        'title': t,
        'limit': '5',
    }
    a = (author or '').strip()
    if a:
        params['author'] = a

    payload = _request_json_best_effort(url=_OPENLIBRARY_SEARCH_URL, params=params, timeout_s=timeout_s)
    if payload is None:
        return None
    docs = payload.get('docs')
    if not isinstance(docs, list) or not docs:
        return None

    best = docs[0]
    if not isinstance(best, dict):
        return None

    isbns = best.get('isbn')
    if not isinstance(isbns, list):
        return None

    for raw in isbns:
        cleaned = _clean_isbn(str(raw or ''))
        if cleaned:
            return cleaned
    return None
