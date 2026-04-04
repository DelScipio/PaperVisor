from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from papervisor.core.exceptions import NotFoundException, ValidationException
from papervisor.db.models import Paper, PaperFavorite, PaperToRead
from papervisor.db.session import use_session
from papervisor.services.media import cover_path_for_ext, thumbnail_path_for
from papervisor.services.sharing import require_library_manage

from papervisor.services.papers_files import move_file, pattern_target_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Soft-delete / trash helpers
# ---------------------------------------------------------------------------


def list_deleted_papers(*, session: Session | None = None) -> list[Paper]:
    """Return all soft-deleted papers (the trash view)."""
    with use_session(session) as session:
        stmt = (
            select(Paper)
            .where(Paper.deleted_at.is_not(None))
            .order_by(Paper.deleted_at.desc())
        )
        return list(session.execute(stmt).scalars().all())


def purge_all_deleted(*, session: Session | None = None) -> int:
    """Permanently delete **all** trashed papers and their files.

    Returns the number of papers purged.
    """
    papers = list_deleted_papers(session=session)
    for p in papers:
        _purge_paper(paper_id=str(p.id))
    return len(papers)


def record_opened(*, paper_id: str, session: Session | None = None) -> None:
    if not paper_id:
        return
    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            return
        row.open_count_total = int(row.open_count_total or 0) + 1
        row.open_count_since_reset = int(row.open_count_since_reset or 0) + 1
        row.last_opened_at = datetime.now(timezone.utc)
        session.commit()


def reset_open_counts(*, paper_id: str, session: Session | None = None) -> None:
    if not paper_id:
        return
    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            return
        row.open_count_since_reset = 0
        row.open_count_reset_at = datetime.now(timezone.utc)
        session.commit()


def set_reading_state(*, paper_id: str, progress: float | None = None, location: str | None = None, session: Session | None = None) -> Paper | None:
    if not paper_id:
        return None
    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            return None

        if progress is not None:
            try:
                p = float(progress)
            except Exception:
                p = 0.0
            p = max(0.0, min(1.0, p))

            # Snap-to-complete thresholds:
            # - PDFs: consider "done" when within last ~15% of pages (client sends page/total).
            # - EPUB/CBZ: consider "done" only when very close to the end.
            ext = ''
            try:
                ext = Path(str(row.file_path or '')).suffix.lower()
            except Exception:
                ext = ''

            threshold = 0.97
            if ext == '.pdf':
                threshold = 0.85

            if p >= threshold:
                row.reading_progress = 1.0
                row.is_completed = True
            else:
                # Don't auto-clear completion; only update progress.
                row.reading_progress = p

        if location is not None:
            row.reading_location = (str(location or '')[:2048]).strip()

        # Track last time we received reading progress.
        if progress is not None or location is not None:
            row.last_read_at = datetime.now(timezone.utc)

        session.commit()
        session.refresh(row)
        return row


def toggle_completed(*, paper_id: str, session: Session | None = None) -> bool:
    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            raise NotFoundException('Item not found')
        row.is_completed = not bool(row.is_completed)
        if row.is_completed:
            row.reading_progress = 1.0
        session.commit()
        return bool(row.is_completed)


def toggle_favorite(*, paper_id: str, user_id: int | None = None, session: Session | None = None) -> bool:
    if user_id is None:
        raise ValidationException('user_id is required')

    pid = str(paper_id or '').strip()
    if not pid:
        raise ValidationException('paper_id is required')

    with use_session(session) as session:
        # Ensure paper exists (and that the caller can perform their own authorization checks).
        row = session.get(Paper, pid)
        if row is None:
            raise NotFoundException('Item not found')

        existing = session.get(PaperFavorite, {'user_id': int(user_id), 'paper_id': pid})
        if existing is not None:
            session.execute(
                delete(PaperFavorite)
                .where(PaperFavorite.user_id == int(user_id))
                .where(PaperFavorite.paper_id == pid)
            )
            session.commit()
            return False

        session.add(PaperFavorite(user_id=int(user_id), paper_id=pid))
        session.commit()
        return True


def toggle_to_read(*, paper_id: str, user_id: int | None = None, session: Session | None = None) -> bool:
    if user_id is None:
        raise ValidationException('user_id is required')

    pid = str(paper_id or '').strip()
    if not pid:
        raise ValidationException('paper_id is required')

    with use_session(session) as session:
        row = session.get(Paper, pid)
        if row is None:
            raise NotFoundException('Item not found')

        existing = session.get(PaperToRead, {'user_id': int(user_id), 'paper_id': pid})
        if existing is not None:
            session.execute(
                delete(PaperToRead)
                .where(PaperToRead.user_id == int(user_id))
                .where(PaperToRead.paper_id == pid)
            )
            session.commit()
            return False

        session.add(PaperToRead(user_id=int(user_id), paper_id=pid))
        session.commit()
        return True


def get_paper(*, paper_id: str, session: Session | None = None) -> Paper | None:
    if not paper_id:
        return None
    with use_session(session) as session:
        return session.get(Paper, paper_id)


def update_paper_updated_at(*, paper_id: str, session: Session | None = None) -> None:
    if not paper_id:
        return
    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            return
        row.updated_at = datetime.now(timezone.utc)
        session.commit()


def delete_paper(*, paper_id: str, session: Session | None = None, permanent: bool = False) -> None:
    """Soft-delete a paper (move to trash).

    When *permanent* is ``True``, the row and its file are removed
    immediately (same as the old behaviour).
    """
    if not paper_id:
        raise ValidationException('Paper id is required')

    if permanent:
        _purge_paper(paper_id=paper_id, session=session)
        return

    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            return
        row.deleted_at = datetime.now(timezone.utc)
        session.commit()


def restore_paper(*, paper_id: str, session: Session | None = None) -> None:
    """Restore a soft-deleted paper from the trash."""
    if not paper_id:
        raise ValidationException('Paper id is required')

    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            raise NotFoundException('Paper not found')
        row.deleted_at = None
        session.commit()


def purge_paper(*, paper_id: str, session: Session | None = None) -> None:
    """Permanently delete a paper and its file from disk."""
    if not paper_id:
        raise ValidationException('Paper id is required')
    _purge_paper(paper_id=paper_id, session=session)


def _purge_paper(*, paper_id: str, session: Session | None = None) -> None:
    """Internal: hard-delete a paper row and clean up files."""
    file_path: str | None = None
    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            return
        file_path = row.file_path
        session.delete(row)
        session.commit()

    if file_path:
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            logger.warning('Failed to delete paper file %s', file_path, exc_info=True)

    # Best-effort cleanup of derived media.
    try:
        thumbnail_path_for(paper_id=str(paper_id)).unlink(missing_ok=True)
    except Exception:
        logger.debug('Failed to delete thumbnail for paper %s', paper_id, exc_info=True)
    for ext in ['.jpg', '.png', '.webp']:
        try:
            cover_path_for_ext(paper_id=str(paper_id), ext=ext).unlink(missing_ok=True)
        except Exception:
            logger.debug('Failed to delete cover (%s) for paper %s', ext, paper_id, exc_info=True)


def update_paper_metadata(
    *,
    paper_id: str,
    file_type: str | None = None,
    title: str,
    doi: str | None,
    isbn: str | None,
    authors: str | None,
    published_year: str | None,
    journal: str | None,
    publisher: str | None,
    description: str | None = None,
    language: str | None = None,
    genres: str | None = None,
    publication_date: str | None = None,
    series: str | None = None,
    series_index: str | None = None,
    page_count: int | None = None,
    abstract: str | None = None,
    url: str | None = None,
    volume: str | None = None,
    issue: str | None = None,
    pages: str | None = None,
    keywords: str | None = None,
    rename_using_pattern: bool = True,
    session: Session | None = None,
) -> Paper:
    cleaned_title = (title or '').strip()
    if not paper_id:
        raise ValidationException('Paper id is required')
    if not cleaned_title:
        raise ValidationException('Title is required')

    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            raise NotFoundException('Paper not found')

        if file_type is not None:
            ft = str(file_type or '').strip().lower()
            if ft not in {'paper', 'book'}:
                raise ValidationException('Invalid type')
            row.file_type = ft

        row.title = cleaned_title
        row.doi = (doi or '').strip() or None
        row.isbn = (isbn or '').strip() or None
        row.authors = (authors or '').strip() or None
        row.published_year = (published_year or '').strip() or None
        row.journal = (journal or '').strip() or None
        row.publisher = (publisher or '').strip() or None

        row.description = (description or '').strip() or None
        row.language = (language or '').strip() or None
        row.genres = (genres or '').strip() or None
        row.publication_date = (publication_date or '').strip() or None
        row.series = (series or '').strip() or None
        row.series_index = (series_index or '').strip() or None
        row.page_count = int(page_count) if page_count is not None else None

        row.abstract = (abstract or '').strip() or None
        row.url = (url or '').strip() or None
        row.volume = (volume or '').strip() or None
        row.issue = (issue or '').strip() or None
        row.pages = (pages or '').strip() or None
        row.keywords = (keywords or '').strip() or None

        # Rename/move file according to the library pattern when requested.
        if rename_using_pattern and row.library_id and row.file_path:
            current = Path(row.file_path)
            if current.exists():
                target = pattern_target_path(
                    library_id=row.library_id,
                    file_type=getattr(row, 'file_type', None),
                    current_path=current,
                    original_filename=current.name,
                    title=row.title,
                    authors=row.authors,
                    year=row.published_year,
                    journal=row.journal,
                    publisher=row.publisher,
                    isbn=row.isbn,
                    series=row.series,
                    series_index=row.series_index,
                    language=row.language,
                )
                if target != current:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    move_file(current, target)
                    row.file_path = str(target)

        session.commit()
        session.refresh(row)
        return row


def move_paper_to_library(
    *,
    paper_id: str,
    library_id: str | None,
    rename_using_pattern: bool = True,
    user_id: int | None = None,
    renaming_overrides: dict[str, str | None] | None = None,
    session: Session | None = None,
) -> Paper:
    if not paper_id:
        raise ValidationException('Paper id is required')

    new_library_id = str(library_id or '').strip() or None

    with use_session(session) as session:
        row = session.get(Paper, paper_id)
        if row is None:
            raise NotFoundException('Paper not found')

        old_library_id = str(row.library_id or '').strip() or None
        if old_library_id == new_library_id:
            session.refresh(row)
            return row

        if user_id is not None:
            if old_library_id:
                require_library_manage(user_id=int(user_id), library_id=str(old_library_id))
            if new_library_id:
                require_library_manage(user_id=int(user_id), library_id=str(new_library_id))

        row.library_id = new_library_id

        if rename_using_pattern and new_library_id and row.file_path:
            current = Path(row.file_path)
            if current.exists():
                src_meta = renaming_overrides or {}
                # Helper to prefer override if present, else row value
                def _get(key: str, default):
                    return src_meta[key] if key in src_meta else default

                target = pattern_target_path(
                    library_id=new_library_id,
                    file_type=_get('file_type', getattr(row, 'file_type', None)),
                    current_path=current,
                    original_filename=current.name,
                    title=_get('title', row.title),
                    authors=_get('authors', row.authors),
                    year=_get('published_year', row.published_year),
                    journal=_get('journal', row.journal),
                    publisher=_get('publisher', row.publisher),
                    isbn=_get('isbn', row.isbn),
                    series=_get('series', row.series),
                    series_index=_get('series_index', row.series_index),
                    language=_get('language', row.language),
                )
                if target != current:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    move_file(current, target)
                    row.file_path = str(target)

        session.commit()
        session.refresh(row)
        return row


def create_paper_record(
    *,
    library_id: str | None,
    file_type: str,
    file_path: str,
    title: str,
    subtitle: str = '',
    doi: str | None = None,
    authors: str | None = None,
    published_year: str | None = None,
    journal: str | None = None,
    publisher: str | None = None,
    isbn: str | None = None,
    # Book-specific
    description: str | None = None,
    language: str | None = None,
    genres: str | None = None,
    publication_date: str | None = None,
    series: str | None = None,
    series_index: str | None = None,
    page_count: int | None = None,
    # Paper-specific
    abstract: str | None = None,
    url: str | None = None,
    volume: str | None = None,
    issue: str | None = None,
    pages: str | None = None,
    keywords: str | None = None,
    session: Session | None = None,
) -> Paper:
    cleaned_title = (title or '').strip()
    if not cleaned_title:
        raise ValidationException('Title is required')

    with use_session(session) as session:
        row = Paper(
            id=str(uuid.uuid4()),
            library_id=library_id,
            file_type=(file_type or 'paper').strip() or 'paper',
            title=cleaned_title,
            subtitle=(subtitle or '').strip(),
            doi=(doi or None),
            authors=(authors or None),
            published_year=(published_year or None),
            journal=(journal or None),
            publisher=(publisher or None),
            isbn=(isbn or None),
            description=(description or None),
            language=(language or None),
            genres=(genres or None),
            publication_date=(publication_date or None),
            series=(series or None),
            series_index=(series_index or None),
            page_count=(int(page_count) if page_count is not None else None),
            abstract=(abstract or None),
            url=(url or None),
            volume=(volume or None),
            issue=(issue or None),
            pages=(pages or None),
            keywords=(keywords or None),
            file_path=file_path,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
