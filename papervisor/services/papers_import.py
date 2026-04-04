from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from papervisor.core.config import get_paths
from papervisor.core.exceptions import NotFoundException, ValidationException
from papervisor.db.models import Library, Paper, User
from sqlalchemy.orm import Session

from papervisor.db.session import get_session, use_session
from papervisor.services.epub import extract_epub_cover
from papervisor.services.media import cover_path_for, cover_path_for_ext, generate_pdf_first_page_thumbnail
from papervisor.services.patterns import get_pattern_settings, render_pattern, resolve_pattern_for

from papervisor.services.papers_crud import create_paper_record
from papervisor.services.papers_files import (
    move_file,
    safe_filename,
    unique_path,
    unique_path_excluding,
)
from papervisor.services.papers_metadata import extract_import_metadata

logger = logging.getLogger(__name__)


def _refresh_preview_assets_after_upload(*, paper_id: str, file_path: str, file_type: str) -> None:
    path = str(file_path or '')
    if not path:
        return

    try:
        if path.lower().endswith('.pdf'):
            generate_pdf_first_page_thumbnail(file_path=path, paper_id=str(paper_id))
    except Exception:
        logger.debug('Failed to regenerate PDF thumbnail for paper %s', paper_id, exc_info=True)

    try:
        if (file_type or '').lower() == 'book' and path.lower().endswith('.epub'):
            existing = cover_path_for(paper_id=str(paper_id))
            if not existing.exists():
                extracted = extract_epub_cover(path)
                if extracted:
                    data, ext = extracted
                    out = cover_path_for_ext(paper_id=str(paper_id), ext=ext)
                    out.write_bytes(data)
    except Exception:
        logger.debug('Failed to extract EPUB cover for paper %s', paper_id, exc_info=True)


@dataclass(frozen=True)
class ImportedPaper:
    paper: Paper
    saved_path: Path


@dataclass(frozen=True)
class RenameResult:
    processed: int
    renamed: int
    skipped: int
    failed: int


def rename_papers_to_match_patterns(*, library_ids: list[str] | None = None) -> RenameResult:
    """Rename/move existing files to match the current pattern settings.

    This updates `Paper.file_path` to the new location/name when a file is moved.
    """

    processed = renamed = skipped = failed = 0
    paths = get_paths()
    settings = get_pattern_settings()

    with get_session() as session:
        libs_stmt = select(Library.id, Library.slug, User.username).outerjoin(User, User.id == Library.owner_user_id)
        if library_ids:
            libs_stmt = libs_stmt.where(Library.id.in_(library_ids))
        lib_rows = session.execute(libs_stmt).all()
        slug_by_id: dict[str, str] = {str(lid): str(slug) for (lid, slug, _u) in lib_rows}
        owner_username_by_id: dict[str, str | None] = {
            str(lid): (str(un or '').strip() or None) for (lid, _slug, un) in lib_rows
        }

        stmt = select(Paper).where(Paper.library_id.is_not(None)).where(Paper.file_path.is_not(None))
        if library_ids:
            stmt = stmt.where(Paper.library_id.in_(library_ids))
        rows = session.execute(stmt).scalars().all()

        for row in rows:
            processed += 1
            library_id = str(row.library_id or '')
            file_path = str(row.file_path or '')
            if not library_id or not file_path:
                skipped += 1
                continue

            slug = slug_by_id.get(library_id)
            if not slug:
                skipped += 1
                continue

            current = Path(file_path)
            if not current.exists():
                skipped += 1
                continue

            try:
                owner_un = owner_username_by_id.get(library_id)
                if owner_un:
                    root = paths.library_files_dir / owner_un / slug
                else:
                    root = paths.library_files_dir / slug
                root.mkdir(parents=True, exist_ok=True)

                pattern = resolve_pattern_for(
                    settings=settings, library_id=library_id, file_type=getattr(row, 'file_type', None)
                )
                rendered = render_pattern(
                    pattern,
                    {
                        'title': (row.title or '').strip() or current.stem,
                        'subtitle': (row.subtitle or '').strip(),
                        'authors': (row.authors or '').strip(),
                        'year': (row.published_year or '').strip(),
                        'series': (row.series or '').strip(),
                        'seriesIndex': (row.series_index or '').strip(),
                        'language': (row.language or '').strip(),
                        'publisher': (row.publisher or '').strip(),
                        'isbn': (row.isbn or '').strip(),
                        'journal': (row.journal or '').strip(),
                        'currentFilename': current.name,
                    },
                )

                if not str(rendered or '').strip():
                    rendered = current.stem

                rel = Path(str(rendered)).as_posix()
                rel = str(rel).replace('\\', '/')
                rel = str(rel).strip()

                # Use the same sanitizer as patterns service.
                from papervisor.services.patterns import sanitize_rel_path

                rel_path = sanitize_rel_path(str(rel))

                target_dir = (root / rel_path).parent
                target_dir.mkdir(parents=True, exist_ok=True)
                rendered_name = (root / rel_path).name or current.stem

                suffix = current.suffix
                if rendered_name.lower().endswith(suffix.lower()):
                    target_name = rendered_name
                else:
                    target_name = rendered_name + suffix

                target = unique_path_excluding(target_dir, target_name, exclude=current)

                if target == current:
                    skipped += 1
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                move_file(current, target)
                row.file_path = str(target)
                renamed += 1
            except Exception:
                logger.warning('Failed to rename paper %s (file: %s)', row.id, file_path, exc_info=True)
                failed += 1

        session.commit()

    return RenameResult(processed=processed, renamed=renamed, skipped=skipped, failed=failed)


def save_upload_to_temp(*, filename: str, content: bytes) -> Path:
    if not content:
        raise ValidationException('Upload contained no data (0 bytes)')
    paths = get_paths()
    folder = paths.library_files_dir / '_tmp'
    folder.mkdir(parents=True, exist_ok=True)

    safe = safe_filename(filename)
    # UUID prefix is 32 hex chars + dash = 33 bytes.  safe_filename already
    # truncates, but the combined name must still fit within NAME_MAX (255).
    # unique_path will handle any remaining overflow via _truncate_component.
    dest = unique_path(folder, f'{uuid.uuid4().hex}-{safe}')
    dest.write_bytes(content)
    return dest


def commit_staged_import(*, library_id: str, file_type: str, staged_path: str, original_filename: str) -> ImportedPaper:
    src = Path(staged_path)
    if not src.exists():
        raise ValidationException('Staged file not found')

    # Move staged file into the library first, keeping the original name.
    from papervisor.services.papers_files import library_root_for, sanitize_relative_path

    root = library_root_for(library_id)

    safe_original = safe_filename(original_filename)
    initial_dest = unique_path(root, safe_original)
    initial_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(initial_dest))
    saved = initial_dest

    ft = (file_type or 'paper').lower()
    meta = extract_import_metadata(file_type=ft, file_path=saved, original_filename=original_filename)

    final_path = saved
    if meta.metadata_ok:
        settings = get_pattern_settings()
        pattern = resolve_pattern_for(settings=settings, library_id=library_id, file_type=file_type)
        rendered = render_pattern(
            pattern,
            {
                'title': meta.title,
                'subtitle': '',
                'authors': meta.authors or '',
                'year': meta.year or '',
                'series': meta.series or '',
                'seriesIndex': meta.series_index or '',
                'language': meta.language or '',
                'publisher': meta.publisher or '',
                'isbn': meta.isbn or '',
                'journal': meta.journal or '',
                'currentFilename': original_filename,
            },
        )

        if not str(rendered or '').strip():
            rendered = Path(final_path).stem

        rel = sanitize_relative_path(rendered)
        target_dir = (root / rel).parent
        target_dir.mkdir(parents=True, exist_ok=True)
        rendered_name = (root / rel).name
        if not rendered_name:
            rendered_name = saved.stem

        if rendered_name.lower().endswith(saved.suffix.lower()):
            target_name = rendered_name
        else:
            target_name = rendered_name + saved.suffix

        target = unique_path(target_dir, target_name)
        move_file(saved, target)
        final_path = target

    row = create_paper_record(
        library_id=library_id,
        file_type=ft,
        file_path=str(final_path),
        title=meta.title,
        doi=meta.doi,
        authors=meta.authors,
        published_year=meta.year,
        journal=meta.journal,
        publisher=meta.publisher,
        isbn=meta.isbn,
        description=meta.description,
        language=meta.language,
        genres=meta.genres,
        publication_date=meta.publication_date,
        series=meta.series,
        series_index=meta.series_index,
        page_count=meta.page_count,
        abstract=meta.abstract,
        url=meta.url,
        volume=meta.volume,
        issue=meta.issue,
        pages=meta.pages,
        keywords=meta.keywords,
    )

    _refresh_preview_assets_after_upload(paper_id=str(row.id), file_path=str(final_path), file_type=ft)

    return ImportedPaper(paper=row, saved_path=final_path)


def attach_staged_file_to_paper(
    *,
    paper_id: str,
    staged_path: str,
    original_filename: str,
    library_id: str | None = None,
    file_type: str | None = None,
) -> ImportedPaper:
    """Attach/replace a file for an existing Paper row.

    This is used by the Upload dialog when the user selects an existing book.
    """

    if not paper_id:
        raise ValidationException('Paper id is required')

    src = Path(staged_path)
    if not src.exists():
        raise ValidationException('Staged file not found')

    from papervisor.services.papers_files import library_root_for, pattern_target_path

    old_path: str | None = None
    final_path_str: str = ''
    with get_session() as session:
        row = session.get(Paper, paper_id)
        if row is None:
            raise NotFoundException('Paper not found')

        # Bind to a library if needed.
        desired_library_id = str(library_id or row.library_id or '')
        if not desired_library_id:
            raise ValidationException('Library is required')
        if row.library_id and str(row.library_id) != desired_library_id:
            raise ValidationException('Selected book belongs to a different library')
        row.library_id = desired_library_id

        desired_type = (file_type or row.file_type or 'paper').strip() or 'paper'
        row.file_type = desired_type

        old_path = str(row.file_path) if row.file_path else None
        old_file = Path(str(old_path)) if old_path else None
        if old_file is not None and not old_file.is_absolute():
            old_file = get_paths().library_files_dir / old_file

        root = library_root_for(desired_library_id)
        safe_original = safe_filename(original_filename)

        # Move staged file into the library first, keeping the original name.
        initial_dest = unique_path(root, safe_original)
        initial_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(initial_dest))
        saved = initial_dest

        # Rename/move according to the current pattern using existing metadata.
        target = pattern_target_path(
            library_id=desired_library_id,
            file_type=getattr(row, 'file_type', None),
            current_path=saved,
            original_filename=original_filename,
            title=row.title,
            authors=row.authors,
            year=row.published_year,
            journal=row.journal,
            publisher=row.publisher,
            isbn=row.isbn,
            exclude_paths=[old_file] if old_file is not None else None,
        )

        final_path = saved
        if target != saved:
            target.parent.mkdir(parents=True, exist_ok=True)
            move_file(saved, target)
            final_path = target

        final_path_str = str(final_path)
        row.file_path = final_path_str
        session.commit()
        session.refresh(row)

    _refresh_preview_assets_after_upload(
        paper_id=str(row.id),
        file_path=final_path_str,
        file_type=str(getattr(row, 'file_type', '') or ''),
    )

    # Best-effort cleanup of the old file when replaced.
    if old_path and str(old_path).strip():
        try:
            old = Path(old_path)
            if final_path_str and old.exists() and old.is_file() and str(old) != final_path_str:
                old.unlink(missing_ok=True)
        except Exception:
            logger.warning('Failed to clean up old file %s', old_path, exc_info=True)

    return ImportedPaper(paper=row, saved_path=Path(final_path_str or str(row.file_path or '')))


def import_file(*, library_id: str, file_type: str, filename: str, content: bytes) -> ImportedPaper:
    staged = save_upload_to_temp(filename=filename, content=content)
    return commit_staged_import(
        library_id=library_id,
        file_type=file_type,
        staged_path=str(staged),
        original_filename=filename,
    )

def replace_paper_file(
    *,
    paper_id: str,
    original_filename: str,
    content: bytes,
    library_id: str | None = None,
    file_type: str | None = None,
) -> ImportedPaper:
    """Convenience wrapper to save an uploaded file and attach it to a paper."""
    staged = save_upload_to_temp(filename=original_filename, content=content)
    return attach_staged_file_to_paper(
        paper_id=paper_id,
        staged_path=str(staged),
        original_filename=original_filename,
        library_id=library_id,
        file_type=file_type,
    )
