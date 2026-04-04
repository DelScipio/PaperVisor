from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from papervisor.core.protocols import IsbnDiscoveryProvider, IsbnMetadataProvider
from papervisor.services.doi import extract_doi_from_pdf, fetch_crossref_metadata
from papervisor.services.epub import extract_epub_metadata
from papervisor.services.google_books import fetch_googlebooks_metadata, search_googlebooks_isbn
from papervisor.services.isbn import (
    extract_isbn_from_epub,
    extract_isbn_from_filename,
    extract_isbn_from_pdf,
    fetch_openlibrary_metadata,
    search_openlibrary_isbn,
)


_ISBN_DISCOVERY_PROVIDERS: dict[str, IsbnDiscoveryProvider] = {
    'openlibrary': search_openlibrary_isbn,
    'google': search_googlebooks_isbn,
}

_ISBN_METADATA_PROVIDERS: dict[str, IsbnMetadataProvider] = {
    'openlibrary': fetch_openlibrary_metadata,
    'google': fetch_googlebooks_metadata,
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportMetadata:
    title: str
    doi: str | None
    authors: str | None
    year: str | None
    journal: str | None
    publisher: str | None
    isbn: str | None

    description: str | None
    language: str | None
    genres: str | None
    publication_date: str | None
    series: str | None
    series_index: str | None
    page_count: int | None

    abstract: str | None
    url: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    keywords: str | None

    metadata_ok: bool


def extract_import_metadata(*, file_type: str, file_path: Path, original_filename: str) -> ImportMetadata:
    """Best-effort metadata extraction for a newly imported file."""

    saved = Path(file_path)

    title = saved.stem
    doi: str | None = None
    authors: str | None = None
    year: str | None = None
    journal: str | None = None
    publisher: str | None = None
    isbn: str | None = None

    # Rich, type-specific fields
    description: str | None = None
    language: str | None = None
    genres: str | None = None
    publication_date: str | None = None
    series: str | None = None
    series_index: str | None = None
    page_count: int | None = None

    abstract: str | None = None
    url: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    keywords: str | None = None

    metadata_ok = False
    ft = (file_type or 'paper').lower()

    if ft == 'paper' and saved.suffix.lower() == '.pdf':
        detected = extract_doi_from_pdf(str(saved))
        if detected:
            try:
                doi_meta = fetch_crossref_metadata(detected)
                doi = doi_meta.doi
                title = doi_meta.title or title
                authors = doi_meta.authors or None
                year = doi_meta.year or None
                journal = doi_meta.journal or None
                publisher = doi_meta.publisher or None
                isbn = doi_meta.isbn or None
                url = doi_meta.url or None
                volume = doi_meta.volume or None
                issue = doi_meta.issue or None
                pages = doi_meta.pages or None
                abstract = doi_meta.abstract or None
                metadata_ok = True
            except Exception:
                doi = detected

    if ft == 'book':
        # Provider priority is configurable in Admin → API.
        try:
            from papervisor.services.settings import (
                get_book_isbn_discovery_providers,
                get_book_metadata_fetch_providers,
            )

            isbn_discovery_providers = get_book_isbn_discovery_providers()
            metadata_fetch_providers = get_book_metadata_fetch_providers()
        except Exception:
            isbn_discovery_providers = ['openlibrary', 'google']
            metadata_fetch_providers = ['openlibrary', 'google']

        # 1) Try reading metadata directly from EPUB when possible.
        if saved.suffix.lower() == '.epub':
            try:
                em = extract_epub_metadata(str(saved))
                if em.title.strip():
                    title = em.title.strip()
                if em.authors.strip():
                    authors = em.authors.strip()
                if em.year.strip():
                    year = em.year.strip()
                if em.publisher.strip():
                    publisher = em.publisher.strip()
                if em.isbn.strip():
                    isbn = em.isbn.strip()
                if em.doi.strip():
                    doi = em.doi.strip()
                if any(
                    [
                        em.title.strip(),
                        em.authors.strip(),
                        em.publisher.strip(),
                        em.year.strip(),
                        em.isbn.strip(),
                        em.doi.strip(),
                    ]
                ):
                    metadata_ok = True
            except Exception:
                logger.debug('Failed to extract EPUB metadata from %s', saved, exc_info=True)

        # 1b) If this is a PDF "book" and we still don't have a DOI, try extracting one.
        # This lets us use Crossref as a fallback to discover an ISBN.
        if not doi and saved.suffix.lower() == '.pdf':
            try:
                doi = extract_doi_from_pdf(str(saved)) or None
            except Exception:
                doi = None

        # 2) Try ISBN detection from filename/PDF/EPUB identifiers.
        detected_isbn = isbn or extract_isbn_from_filename(original_filename)
        if not detected_isbn and saved.suffix.lower() == '.pdf':
            detected_isbn = extract_isbn_from_pdf(str(saved))
        if not detected_isbn and saved.suffix.lower() == '.epub':
            detected_isbn = extract_isbn_from_epub(str(saved))

        # 3) If we have a DOI but no ISBN, try Crossref to discover one.
        # (Crossref metadata can include ISBNs for some book-like works.)
        if not detected_isbn and doi:
            try:
                crossref_meta = fetch_crossref_metadata(doi)
                if crossref_meta.isbn:
                    detected_isbn = crossref_meta.isbn
                # Best-effort: use Crossref fields only if they add value.
                if crossref_meta.title and not (title or '').strip():
                    title = crossref_meta.title
                if crossref_meta.authors and not (authors or '').strip():
                    authors = crossref_meta.authors
                if crossref_meta.year and not (year or '').strip():
                    year = crossref_meta.year
                if crossref_meta.publisher and not (publisher or '').strip():
                    publisher = crossref_meta.publisher
                if any(
                    [
                        crossref_meta.title,
                        crossref_meta.authors,
                        crossref_meta.year,
                        crossref_meta.publisher,
                        crossref_meta.isbn,
                    ]
                ):
                    metadata_ok = True
            except Exception:
                logger.debug('Failed to fetch Crossref metadata for DOI %s', doi, exc_info=True)

        # 4) If no ISBN, attempt OpenLibrary title/author search.
        if not detected_isbn and title:
            for prov in isbn_discovery_providers:
                if detected_isbn:
                    break
                try:
                    disc_fn = _ISBN_DISCOVERY_PROVIDERS.get(str(prov))
                    if disc_fn is not None:
                        detected_isbn = disc_fn(title=title, author=authors)
                except Exception:
                    detected_isbn = None

        # 6) If we have an ISBN, fetch metadata using provider priority.
        if detected_isbn:
            fetched_any = False
            for prov in metadata_fetch_providers:
                try:
                    meta_fn = _ISBN_METADATA_PROVIDERS.get(str(prov))
                    if meta_fn is None:
                        continue

                    meta = meta_fn(detected_isbn)

                    fetched_any = True
                    isbn = meta.isbn or detected_isbn
                    title = meta.title or title
                    authors = meta.authors or authors
                    year = meta.year or year
                    publisher = meta.publisher or publisher

                    # Rich book fields (best-effort; only fill if we got something)
                    description = (meta.description or '').strip() or description
                    language = (meta.language or '').strip() or language
                    genres = (meta.genres or '').strip() or genres
                    publication_date = (meta.publication_date or '').strip() or publication_date
                    page_count = meta.page_count if meta.page_count is not None else page_count

                    metadata_ok = True
                    break
                except Exception:
                    continue

            if not fetched_any:
                isbn = detected_isbn

    return ImportMetadata(
        title=title,
        doi=doi,
        authors=authors,
        year=year,
        journal=journal,
        publisher=publisher,
        isbn=isbn,
        description=description,
        language=language,
        genres=genres,
        publication_date=publication_date,
        series=series,
        series_index=series_index,
        page_count=page_count,
        abstract=abstract,
        url=url,
        volume=volume,
        issue=issue,
        pages=pages,
        keywords=keywords,
        metadata_ok=metadata_ok,
    )
