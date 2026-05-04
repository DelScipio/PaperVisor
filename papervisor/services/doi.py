from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html import unescape
from typing import Any, Callable
from urllib.parse import quote
from xml.etree import ElementTree

import fitz  # PyMuPDF
import requests

from papervisor.core.sanitizers import strip_html_tags as _strip_tags


_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DoiMetadata:
    doi: str
    title: str
    authors: str
    year: str
    journal: str
    publisher: str
    isbn: str
    url: str
    volume: str
    issue: str
    pages: str
    abstract: str


_TAG_RE = re.compile(r'<[^>]+>')


def _normalize_doi(raw: str) -> str:
    s = (raw or '').strip()
    if not s:
        return ''
    # Common user inputs: "doi:10..." or full resolver URLs.
    s = re.sub(r'^doi\s*:\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^https?://(dx\.)?doi\.org/', '', s, flags=re.IGNORECASE)
    return s.strip()


def extract_doi_from_pdf(file_path: str, *, max_pages: int = 2) -> str | None:
    try:
        doc = fitz.open(file_path)
    except Exception:
        return None

    try:
        pages = min(max_pages, doc.page_count)
        for i in range(pages):
            text = str(doc.load_page(i).get_text("text") or '')
            if not text.strip():
                continue

            # PDFs frequently split DOIs across line breaks.
            for candidate_text in (
                text,
                text.replace('\n', ''),
                re.sub(r"\s*/\s*", "/", text.replace('\n', ' ')),
            ):
                match = _DOI_RE.search(candidate_text)
                if match:
                    doi = match.group(0)
                    return doi.strip().rstrip('.,);]')
        return None
    finally:
        doc.close()


def extract_doi_from_text(text: str) -> str | None:
    if not text:
        return None
    match = _DOI_RE.search(text)
    if not match:
        return None
    doi = match.group(0)
    return doi.strip().rstrip('.,);]')


def _first(values: list[Any] | None) -> Any | None:
    if not values:
        return None
    return values[0]


def fetch_crossref_metadata(doi: str, *, timeout_s: float = 6.0) -> DoiMetadata:
    cleaned = _normalize_doi(doi)
    if not cleaned:
        raise ValueError('DOI is required')

    url = f'https://api.crossref.org/works/{quote(cleaned)}'
    try:
        resp = requests.get(url, timeout=timeout_s, headers={'User-Agent': 'PaperVisor/0.1'})
    except Exception as e:
        raise ValueError(f'Crossref lookup failed (network error: {e})')
    if resp.status_code >= 400:
        raise ValueError(f'Crossref lookup failed ({resp.status_code})')

    try:
        payload = resp.json()
    except Exception as e:
        raise ValueError(f'Crossref lookup failed (invalid JSON: {e})')
    message = payload.get('message') or {}

    title = ''
    title_list = message.get('title')
    if isinstance(title_list, list) and title_list:
        title = str(title_list[0] or '')

    author_parts: list[str] = []
    authors = message.get('author')
    if isinstance(authors, list):
        for a in authors:
            if not isinstance(a, dict):
                continue
            given = str(a.get('given') or '').strip()
            family = str(a.get('family') or '').strip()
            full = ' '.join([p for p in [given, family] if p])
            if full:
                author_parts.append(full)
    authors_str = '; '.join(author_parts)

    year = ''
    published = message.get('published-print') or message.get('published-online') or message.get('created')
    if isinstance(published, dict):
        date_parts = published.get('date-parts')
        if isinstance(date_parts, list) and date_parts:
            first = _first(date_parts)
            if isinstance(first, list) and first:
                year = str(first[0])

    journal = ''
    container = message.get('container-title')
    if isinstance(container, list) and container:
        journal = str(container[0] or '')

    publisher = str(message.get('publisher') or '')

    isbn = ''
    isbns = message.get('ISBN')
    if isinstance(isbns, list) and isbns:
        isbn = str(isbns[0] or '')

    url = str(message.get('URL') or '').strip()
    volume = str(message.get('volume') or '').strip()
    issue = str(message.get('issue') or '').strip()
    pages = str(message.get('page') or '').strip()

    abstract_raw = str(message.get('abstract') or '')
    abstract = _strip_tags(abstract_raw)

    return DoiMetadata(
        doi=cleaned,
        title=title,
        authors=authors_str,
        year=year,
        journal=journal,
        publisher=publisher,
        isbn=isbn,
        url=url,
        volume=volume,
        issue=issue,
        pages=pages,
        abstract=abstract,
    )


def _empty_metadata(doi: str) -> DoiMetadata:
    return DoiMetadata(
        doi=doi,
        title='',
        authors='',
        year='',
        journal='',
        publisher='',
        isbn='',
        url='',
        volume='',
        issue='',
        pages='',
        abstract='',
    )


def _merge_metadata(base: DoiMetadata, incoming: DoiMetadata) -> DoiMetadata:
    """Fill missing fields in base with values from incoming."""
    return DoiMetadata(
        doi=base.doi or incoming.doi,
        title=base.title or incoming.title,
        authors=base.authors or incoming.authors,
        year=base.year or incoming.year,
        journal=base.journal or incoming.journal,
        publisher=base.publisher or incoming.publisher,
        isbn=base.isbn or incoming.isbn,
        url=base.url or incoming.url,
        volume=base.volume or incoming.volume,
        issue=base.issue or incoming.issue,
        pages=base.pages or incoming.pages,
        abstract=base.abstract or incoming.abstract,
    )


def _fetch_semantic_scholar_metadata(doi: str, *, timeout_s: float = 6.0) -> DoiMetadata:
    cleaned = _normalize_doi(doi)
    if not cleaned:
        raise ValueError('DOI is required')

    # Docs: https://api.semanticscholar.org/api-docs/graph
    fields = ','.join(
        [
            'title',
            'authors',
            'year',
            'venue',
            'journal',
            'abstract',
            'url',
            'externalIds',
            'publicationDate',
            'volume',
            'issue',
            'pages',
        ]
    )
    url = f'https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(cleaned)}?fields={quote(fields)}'
    try:
        resp = requests.get(url, timeout=timeout_s, headers={'User-Agent': 'PaperVisor/0.10.5'})
    except Exception as e:
        raise ValueError(f'Semantic Scholar lookup failed (network error: {e})')
    if resp.status_code == 404:
        return _empty_metadata(cleaned)
    if resp.status_code >= 400:
        raise ValueError(f'Semantic Scholar lookup failed ({resp.status_code})')

    try:
        payload = resp.json() or {}
    except Exception as e:
        raise ValueError(f'Semantic Scholar lookup failed (invalid JSON: {e})')

    title = str(payload.get('title') or '').strip()
    year = str(payload.get('year') or '').strip()
    abstract = str(payload.get('abstract') or '').strip()
    paper_url = str(payload.get('url') or '').strip()

    # Prefer journal name when available; fallback to venue.
    journal = ''
    j = payload.get('journal')
    if isinstance(j, dict):
        journal = str(j.get('name') or '').strip()
    if not journal:
        journal = str(payload.get('venue') or '').strip()

    author_parts: list[str] = []
    authors = payload.get('authors')
    if isinstance(authors, list):
        for a in authors:
            if isinstance(a, dict):
                name = str(a.get('name') or '').strip()
                if name:
                    author_parts.append(name)
    authors_str = '; '.join(author_parts)

    volume = str(payload.get('volume') or '').strip()
    issue = str(payload.get('issue') or '').strip()
    pages = str(payload.get('pages') or '').strip()

    # Try to keep DOI canonical.
    ext = payload.get('externalIds')
    if isinstance(ext, dict):
        cleaned = str(ext.get('DOI') or cleaned).strip() or cleaned

    return DoiMetadata(
        doi=cleaned,
        title=title,
        authors=authors_str,
        year=year,
        journal=journal,
        publisher='',
        isbn='',
        url=paper_url,
        volume=volume,
        issue=issue,
        pages=pages,
        abstract=abstract,
    )


def _pubmed_lookup_pmid_by_doi(doi: str, *, timeout_s: float = 6.0) -> str | None:
    cleaned = _normalize_doi(doi)
    if not cleaned:
        return None
    term = quote(f'{cleaned}[DOI]')
    url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&term={term}'
    try:
        resp = requests.get(url, timeout=timeout_s, headers={'User-Agent': 'PaperVisor/0.10.5'})
    except Exception:
        return None
    if resp.status_code >= 400:
        return None
    try:
        payload = resp.json() or {}
        ids = (((payload.get('esearchresult') or {}).get('idlist')) or [])
        if isinstance(ids, list) and ids:
            pmid = str(ids[0] or '').strip()
            return pmid or None
    except Exception:
        return None
    return None


def _fetch_pubmed_abstract_by_pmid(pmid: str, *, timeout_s: float = 6.0) -> tuple[str, str, str]:
    """Returns (title, journal, abstract) from PubMed XML; empty strings on failure."""
    pmid = str(pmid or '').strip()
    if not pmid:
        return '', '', ''

    url = f'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id={quote(pmid)}'
    try:
        resp = requests.get(url, timeout=timeout_s, headers={'User-Agent': 'PaperVisor/0.10.5'})
    except Exception:
        return '', '', ''
    if resp.status_code >= 400:
        return '', '', ''

    try:
        root = ElementTree.fromstring(resp.text)
    except Exception:
        return '', '', ''

    def _text(path: str) -> str:
        el = root.find(path)
        if el is None:
            return ''
        return ''.join(el.itertext()).strip()

    title = _text('.//ArticleTitle')
    journal = _text('.//Journal/Title')

    parts: list[str] = []
    for abs_el in root.findall('.//Abstract/AbstractText'):
        chunk = ''.join(abs_el.itertext()).strip()
        if not chunk:
            continue
        label = str(abs_el.attrib.get('Label') or abs_el.attrib.get('NlmCategory') or '').strip()
        if label and chunk.lower().startswith(label.lower()):
            parts.append(chunk)
        elif label:
            parts.append(f'{label}: {chunk}')
        else:
            parts.append(chunk)
    abstract = '\n'.join(parts).strip()
    return title, journal, abstract


def _fetch_pubmed_metadata(doi: str, *, timeout_s: float = 6.0) -> DoiMetadata:
    cleaned = _normalize_doi(doi)
    if not cleaned:
        raise ValueError('DOI is required')

    pmid = _pubmed_lookup_pmid_by_doi(cleaned, timeout_s=timeout_s)
    if not pmid:
        return _empty_metadata(cleaned)

    title, journal, abstract = _fetch_pubmed_abstract_by_pmid(pmid, timeout_s=timeout_s)
    return DoiMetadata(
        doi=cleaned,
        title=title,
        authors='',
        year='',
        journal=journal,
        publisher='',
        isbn='',
        url='',
        volume='',
        issue='',
        pages='',
        abstract=abstract,
    )


def fetch_doi_metadata(
    doi: str,
    *,
    timeout_s: float = 6.0,
    include_semantic_scholar: bool = True,
    include_pubmed: bool = True,
    should_continue: Callable[[], bool] | None = None,
) -> DoiMetadata:
    """Fetch metadata for a DOI with fallbacks.

    Strategy:
    - Crossref first
    - If fields are still missing (especially abstract), try Semantic Scholar
    - If still missing abstract, try PubMed (via DOI→PMID)
    """
    cleaned = _normalize_doi(doi)
    if not cleaned:
        raise ValueError('DOI is required')

    meta = _empty_metadata(cleaned)
    provider_errors: list[str] = []

    if should_continue is not None and not should_continue():
        raise ValueError('DOI lookup canceled')

    # 1) Crossref
    try:
        meta = _merge_metadata(meta, fetch_crossref_metadata(cleaned, timeout_s=timeout_s))
    except Exception as ex:
        provider_errors.append(f'Crossref: {ex}')
        logger.warning('DOI metadata: Crossref failed for %s: %s', cleaned, ex)
        # Keep going to fallbacks.
        pass

    # 2) Semantic Scholar
    if include_semantic_scholar and (not meta.abstract or not meta.title or not meta.authors):
        if should_continue is not None and not should_continue():
            raise ValueError('DOI lookup canceled')
        try:
            meta = _merge_metadata(meta, _fetch_semantic_scholar_metadata(cleaned, timeout_s=timeout_s))
        except Exception as ex:
            provider_errors.append(f'Semantic Scholar: {ex}')
            logger.warning('DOI metadata: Semantic Scholar failed for %s: %s', cleaned, ex)
            pass

    # 3) PubMed (mostly for abstract)
    if include_pubmed and not meta.abstract:
        if should_continue is not None and not should_continue():
            raise ValueError('DOI lookup canceled')
        try:
            meta = _merge_metadata(meta, _fetch_pubmed_metadata(cleaned, timeout_s=timeout_s))
        except Exception as ex:
            provider_errors.append(f'PubMed: {ex}')
            logger.warning('DOI metadata: PubMed failed for %s: %s', cleaned, ex)
            pass

    # If nothing came back, raise a clearer error.
    if not any([meta.title, meta.authors, meta.year, meta.journal, meta.publisher, meta.abstract, meta.url]):
        if provider_errors:
            detail = '; '.join(provider_errors[:3])
            raise ValueError(f'DOI lookup failed (no providers returned metadata; {detail})')
        raise ValueError('DOI lookup failed (no providers returned metadata)')

    if provider_errors:
        logger.info('DOI metadata: fallback path used for %s (%s)', cleaned, '; '.join(provider_errors[:3]))

    return meta
