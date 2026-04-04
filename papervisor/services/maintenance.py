from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy import delete, update

from papervisor.core.config import get_paths
from papervisor.db.models import (
    Library,
    LibraryNamingPattern,
    LibraryShare,
    Marker,
    Paper,
    PaperFavorite,
    PaperMarker,
    PaperShare,
    PaperTag,
    PaperToRead,
    Tag,
    User,
    UserSetting,
)
from sqlalchemy.orm import Session

from papervisor.db.session import get_session, use_session
from papervisor.services.doi import extract_doi_from_pdf, fetch_crossref_metadata
from papervisor.services.isbn import extract_isbn_from_epub, extract_isbn_from_filename, extract_isbn_from_pdf, fetch_openlibrary_metadata
from papervisor.services.google_books import fetch_googlebooks_metadata
from papervisor.services.settings import get_book_metadata_fetch_providers, get_metadata_provider_timeout_seconds
from papervisor.services.media import (
    cover_path_for,
    cover_path_for_ext,
    fetch_and_save_cover,
    generate_pdf_first_page_thumbnail,
    thumbnail_path_for,
)
from papervisor.services.papers import create_paper_record
from papervisor.services.epub import extract_epub_cover

from typing import Callable

# Progress callback: (current_index, total_count, item_label)
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class BulkResult:
    processed: int
    succeeded: int
    skipped: int
    failed: int


def _library_roots_for(library_ids: list[str] | None) -> dict[str, Path]:
    paths = get_paths()
    with get_session() as session:
        stmt = select(Library, User.username).outerjoin(User, User.id == Library.owner_user_id)
        if library_ids:
            stmt = stmt.where(Library.id.in_(library_ids))
        libs = session.execute(stmt).all()

    roots: dict[str, Path] = {}
    for (lib, owner_username) in libs:
        ou = str(owner_username or '').strip()
        if ou:
            root = paths.library_files_dir / ou / str(lib.slug)
        else:
            root = paths.library_files_dir / str(lib.slug)
        root.mkdir(parents=True, exist_ok=True)
        roots[str(lib.id)] = root
    return roots


def regenerate_thumbnails(
    *,
    library_ids: list[str] | None = None,
    overwrite: bool = False,
    on_progress: ProgressCallback | None = None,
) -> BulkResult:
    with get_session() as session:
        stmt = select(Paper)
        if library_ids:
            stmt = stmt.where(Paper.library_id.in_(library_ids))
        rows = session.execute(stmt).scalars().all()

    total = len(rows)
    processed = succeeded = skipped = failed = 0
    for row in rows:
        processed += 1
        file_path = str(row.file_path or '')
        label = Path(file_path).name if file_path else '(unknown)'
        if on_progress:
            on_progress(processed, total, label)
        if not file_path.lower().endswith('.pdf'):
            skipped += 1
            continue
        p = Path(file_path)
        if not p.exists():
            skipped += 1
            continue
        if not overwrite:
            thumb = thumbnail_path_for(paper_id=str(row.id))
            if thumb.exists() and thumb.is_file():
                skipped += 1
                continue
        try:
            generate_pdf_first_page_thumbnail(file_path=str(p), paper_id=str(row.id))
            succeeded += 1
        except Exception:
            failed += 1

    return BulkResult(processed=processed, succeeded=succeeded, skipped=skipped, failed=failed)


def fetch_book_covers(
    *,
    library_ids: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> BulkResult:
    with get_session() as session:
        stmt = select(Paper).where(Paper.file_type == 'book')
        if library_ids:
            stmt = stmt.where(Paper.library_id.in_(library_ids))
        rows = session.execute(stmt).scalars().all()

    total = len(rows)
    processed = succeeded = skipped = failed = 0
    for row in rows:
        processed += 1
        label = str(row.title or Path(str(row.file_path or '')).stem or '(unknown)')
        if on_progress:
            on_progress(processed, total, label)
        isbn = str(row.isbn or '').strip()
        if not isbn:
            skipped += 1
            continue
        try:
            fetch_and_save_cover(isbn=isbn, paper_id=str(row.id))
            succeeded += 1
        except Exception:
            failed += 1

    return BulkResult(processed=processed, succeeded=succeeded, skipped=skipped, failed=failed)


def extract_epub_covers(
    *,
    library_ids: list[str] | None = None,
    overwrite: bool = False,
    on_progress: ProgressCallback | None = None,
) -> BulkResult:
    """Extract embedded cover (or first image fallback) from EPUB files.

    This is useful for already-imported books where we didn't have a cover yet.
    """

    def _has_cover(paper_id: str) -> bool:
        try:
            # cover_path_for prefers existing cover; verify it actually exists.
            p = cover_path_for(paper_id=paper_id)
            if p.exists():
                return True
            for ext in ['.jpg', '.png', '.webp']:
                if p.with_suffix(ext).exists():
                    return True
        except Exception:
            return False
        return False

    with get_session() as session:
        stmt = select(Paper).where(Paper.file_type == 'book')
        if library_ids:
            stmt = stmt.where(Paper.library_id.in_(library_ids))
        rows = session.execute(stmt).scalars().all()

    total = len(rows)
    processed = succeeded = skipped = failed = 0
    for row in rows:
        processed += 1
        file_path = str(row.file_path or '')
        label = Path(file_path).name if file_path else '(unknown)'
        if on_progress:
            on_progress(processed, total, label)
        if not file_path.lower().endswith('.epub'):
            skipped += 1
            continue
        if not Path(file_path).exists():
            skipped += 1
            continue
        paper_id = str(row.id)
        if not overwrite and _has_cover(paper_id):
            skipped += 1
            continue

        try:
            extracted = extract_epub_cover(file_path)
            if not extracted:
                skipped += 1
                continue
            data, ext = extracted

            if overwrite:
                try:
                    for e in ['.jpg', '.png', '.webp']:
                        cover_path_for_ext(paper_id=paper_id, ext=e).unlink(missing_ok=True)
                except Exception:
                    pass

            out = cover_path_for_ext(paper_id=paper_id, ext=ext)
            out.write_bytes(data)
            succeeded += 1
        except Exception:
            failed += 1

    return BulkResult(processed=processed, succeeded=succeeded, skipped=skipped, failed=failed)


def trove_doi_metadata(
    *,
    library_ids: list[str] | None = None,
    overwrite: bool = False,
    on_progress: ProgressCallback | None = None,
) -> BulkResult:
    timeout_s = get_metadata_provider_timeout_seconds()
    with get_session() as session:
        stmt = select(Paper).where(Paper.file_type == 'paper')
        if library_ids:
            stmt = stmt.where(Paper.library_id.in_(library_ids))
        rows = session.execute(stmt).scalars().all()

    total = len(rows)
    processed = succeeded = skipped = failed = 0

    with get_session() as session:
        for row in rows:
            processed += 1
            label = str(row.title or Path(str(row.file_path or '')).stem or '(unknown)')
            if on_progress:
                on_progress(processed, total, label)

            # Refresh row in this session
            live = session.get(Paper, row.id)
            if live is None:
                skipped += 1
                continue

            doi = (live.doi or '').strip()
            file_path = str(live.file_path or '')
            if not doi:
                if file_path.lower().endswith('.pdf') and Path(file_path).exists():
                    doi = extract_doi_from_pdf(file_path) or ''
                    doi = doi.strip()

            if not doi:
                skipped += 1
                continue

            try:
                meta = fetch_crossref_metadata(doi, timeout_s=timeout_s)
            except Exception:
                failed += 1
                continue

            def _should_set(existing: str | None) -> bool:
                if overwrite:
                    return True
                return not str(existing or '').strip()

            if _should_set(live.doi):
                live.doi = meta.doi or doi
            if _should_set(live.title):
                live.title = (meta.title or live.title or '').strip() or live.title
            if _should_set(live.authors):
                live.authors = (meta.authors or '').strip() or live.authors
            if _should_set(live.published_year):
                live.published_year = (meta.year or '').strip() or live.published_year
            if _should_set(live.journal):
                live.journal = (meta.journal or '').strip() or live.journal
            if _should_set(live.publisher):
                live.publisher = (meta.publisher or '').strip() or live.publisher
            if _should_set(live.isbn):
                live.isbn = (meta.isbn or '').strip() or live.isbn

            try:
                session.commit()
                succeeded += 1
            except Exception:
                session.rollback()
                failed += 1

    return BulkResult(processed=processed, succeeded=succeeded, skipped=skipped, failed=failed)


def trove_isbn_metadata(
    *,
    library_ids: list[str] | None = None,
    overwrite: bool = False,
    fetch_covers: bool = False,
    on_progress: ProgressCallback | None = None,
) -> BulkResult:
    """Bulk-enrich book metadata using ISBN providers.

    Behavior:
    - Operates on rows where `Paper.file_type == 'book'`.
    - If ISBN is missing, tries to detect it from EPUB/PDF contents or filename.
    - Fetches metadata using providers configured in Admin (OpenLibrary/Google).
    - Fills missing fields by default; set `overwrite=True` to replace existing values.
    - If `fetch_covers=True`, also downloads cover images for books with ISBNs.
    """

    with get_session() as session:
        stmt = select(Paper).where(Paper.file_type == 'book')
        if library_ids:
            stmt = stmt.where(Paper.library_id.in_(library_ids))
        rows = session.execute(stmt).scalars().all()

    total = len(rows)
    processed = succeeded = skipped = failed = 0
    providers = get_book_metadata_fetch_providers()
    timeout_s = get_metadata_provider_timeout_seconds()

    def _should_set(existing: str | None) -> bool:
        if overwrite:
            return True
        return not str(existing or '').strip()

    def _to_abs_path(fp: str) -> Path:
        p = Path(fp)
        if p.is_absolute():
            return p
        return get_paths().library_files_dir / p

    with get_session() as session:
        for row in rows:
            processed += 1
            label = str(row.title or Path(str(row.file_path or '')).stem or '(unknown)')
            if on_progress:
                on_progress(processed, total, label)

            live = session.get(Paper, row.id)
            if live is None:
                skipped += 1
                continue

            isbn = str(live.isbn or '').strip()
            file_path = str(live.file_path or '').strip()

            if not isbn:
                # Attempt ISBN detection from file contents.
                if file_path:
                    p = _to_abs_path(file_path)
                    if p.exists() and p.is_file():
                        fp_lower = p.name.lower()
                        if fp_lower.endswith('.epub'):
                            isbn = (extract_isbn_from_epub(str(p)) or '').strip()
                        elif fp_lower.endswith('.pdf'):
                            isbn = (extract_isbn_from_pdf(str(p)) or '').strip()

                        if not isbn:
                            isbn = (extract_isbn_from_filename(p.name) or '').strip()

            if not isbn:
                skipped += 1
                continue

            meta = None
            for prov in providers:
                try:
                    if prov == 'openlibrary':
                        meta = fetch_openlibrary_metadata(isbn, timeout_s=timeout_s)
                    elif prov == 'google':
                        meta = fetch_googlebooks_metadata(isbn, timeout_s=timeout_s)
                    if meta is not None:
                        break
                except Exception:
                    meta = None
                    continue

            if meta is None:
                failed += 1
                continue

            if _should_set(live.isbn):
                live.isbn = (meta.isbn or isbn).strip() or live.isbn
            if _should_set(live.title):
                live.title = (meta.title or live.title or '').strip() or live.title
            if _should_set(live.authors):
                live.authors = (meta.authors or '').strip() or live.authors
            if _should_set(live.published_year):
                live.published_year = (meta.year or '').strip() or live.published_year
            if _should_set(live.publisher):
                live.publisher = (meta.publisher or '').strip() or live.publisher

            # Optional richer fields
            if _should_set(live.description):
                live.description = (meta.description or '').strip() or live.description
            if _should_set(live.language):
                live.language = (meta.language or '').strip() or live.language
            if _should_set(live.genres):
                live.genres = (meta.genres or '').strip() or live.genres
            if _should_set(live.publication_date):
                live.publication_date = (meta.publication_date or '').strip() or live.publication_date
            if overwrite or live.page_count is None:
                if meta.page_count is not None:
                    live.page_count = int(meta.page_count)

            try:
                session.commit()
                succeeded += 1
            except Exception:
                session.rollback()
                failed += 1

            # Optionally fetch cover using discovered/existing ISBN.
            if fetch_covers:
                final_isbn = str(live.isbn or isbn or '').strip()
                if final_isbn:
                    try:
                        fetch_and_save_cover(isbn=final_isbn, paper_id=str(live.id))
                    except Exception:
                        pass  # Cover fetch failure doesn't affect metadata result

    return BulkResult(processed=processed, succeeded=succeeded, skipped=skipped, failed=failed)


@dataclass(frozen=True)
class CleanResult:
    imported: int
    deleted_missing: int
    media_deleted: int
    empty_dirs_deleted: int


def _remove_empty_dirs(*, root: Path) -> int:
    """Remove empty directories under root (but never root itself)."""
    if not root.exists() or not root.is_dir():
        return 0

    removed = 0
    # Walk bottom-up by sorting deepest paths first.
    dirs = [p for p in root.rglob('*') if p.is_dir()]
    dirs.sort(key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        if d == root:
            continue
        try:
            if any(d.iterdir()):
                continue
            d.rmdir()
            removed += 1
        except Exception:
            continue
    return removed


def clean_libraries(
    *,
    library_ids: list[str] | None = None,
    dry_run: bool = False,
    on_progress: ProgressCallback | None = None,
) -> CleanResult:
    # 1) Delete DB entries for missing files
    deleted_missing_ids: list[str] = []
    with get_session() as session:
        stmt = select(Paper)
        if library_ids:
            stmt = stmt.where(Paper.library_id.in_(library_ids))
        rows = session.execute(stmt).scalars().all()

        total = len(rows)
        for idx, row in enumerate(rows, 1):
            if on_progress:
                on_progress(idx, total, Path(str(row.file_path or '')).name or '(scan)')
            file_path = str(row.file_path or '')
            if not file_path:
                continue
            if not Path(file_path).exists():
                deleted_missing_ids.append(str(row.id))
                if not dry_run:
                    session.delete(row)
        if not dry_run:
            session.commit()

    # delete associated media for deleted papers
    media_deleted = 0
    if not dry_run:
        for pid in deleted_missing_ids:
            cover_paths = [
                cover_path_for_ext(paper_id=pid, ext='.jpg'),
                cover_path_for_ext(paper_id=pid, ext='.png'),
                cover_path_for_ext(paper_id=pid, ext='.webp'),
            ]
            for path in [thumbnail_path_for(paper_id=pid), *cover_paths]:
                try:
                    path.unlink(missing_ok=True)
                    media_deleted += 1
                except Exception:
                    pass

    # 2) Import files on disk missing DB entries
    roots = _library_roots_for(library_ids)

    disk_files: list[tuple[str, str]] = []  # (library_id, file_path)
    for library_id, root in roots.items():
        if not root.exists():
            continue
        for p in root.rglob('*'):
            if not p.is_file():
                continue
            if any(part.startswith('.') for part in p.parts):
                continue
            ext = p.suffix.lower()
            if ext not in {'.pdf', '.epub'}:
                continue
            disk_files.append((library_id, str(p)))

    with get_session() as session:
        stmt = select(Paper.file_path)
        if library_ids:
            stmt = stmt.where(Paper.library_id.in_(library_ids))
        known_paths = {str(p or '') for (p,) in session.execute(stmt).all() if p}

    imported = 0
    for library_id, fp in disk_files:
        if fp in known_paths:
            continue

        if dry_run:
            imported += 1
            continue

        title = Path(fp).stem
        file_type = 'book' if fp.lower().endswith('.epub') else 'paper'
        try:
            create_paper_record(library_id=library_id, file_type=file_type, file_path=fp, title=title)
            imported += 1
        except Exception:
            continue

    # 3) Remove orphan thumbs/covers (safe across all libraries)
    with get_session() as session:
        all_ids = {str(pid) for (pid,) in session.execute(select(Paper.id)).all()}

    media_root = get_paths().library_files_dir / '_media'
    for folder_name in ['thumbs', 'covers']:
        folder = media_root / folder_name
        if not folder.exists():
            continue
        for f in folder.iterdir():
            if not f.is_file():
                continue
            stem = f.stem
            if stem not in all_ids:
                if not dry_run:
                    try:
                        f.unlink(missing_ok=True)
                    except Exception:
                        pass
                media_deleted += 1

    # 4) Remove empty folders inside library roots (common after migrations/renames)
    empty_dirs_deleted = 0
    if not dry_run:
        for _library_id, root in roots.items():
            empty_dirs_deleted += _remove_empty_dirs(root=root)
    else:
        # In dry-run mode, just count empty dirs without removing.
        for _library_id, root in roots.items():
            if root.exists() and root.is_dir():
                dirs = [p for p in root.rglob('*') if p.is_dir()]
                for d in dirs:
                    if d == root:
                        continue
                    try:
                        if not any(d.iterdir()):
                            empty_dirs_deleted += 1
                    except Exception:
                        pass

    return CleanResult(
        imported=imported,
        deleted_missing=len(deleted_missing_ids),
        media_deleted=media_deleted,
        empty_dirs_deleted=empty_dirs_deleted,
    )


@dataclass(frozen=True)
class UserCleanupResult:
    dry_run: bool
    db_deleted: int
    db_updated: int
    fs_deleted: int
    orphan_user_dirs: list[str]


def _safe_rc(rc: int | None) -> int:
    try:
        if rc is None or int(rc) < 0:
            return 0
        return int(rc)
    except Exception:
        return 0


def _dml_rowcount(result) -> int:
    return _safe_rc(getattr(result, 'rowcount', 0))


def clean_deleted_users(*, dry_run: bool = True, delete_orphan_user_dirs: bool = False) -> UserCleanupResult:
    """Clean up data left behind after users were deleted.

    Useful when SQLite foreign keys weren't enforced in the past.

    - Removes DB rows referencing missing users.
    - Optionally removes orphan top-level user directories under library_files.
    """

    db_deleted = 0
    db_updated = 0

    with get_session() as session:
        user_ids = {int(x) for x in session.execute(select(User.id)).scalars().all()}
        usernames = {str(x or '').strip() for x in session.execute(select(User.username)).scalars().all()}
        usernames = {u for u in usernames if u}

        library_ids = {str(x) for x in session.execute(select(Library.id)).scalars().all()}
        paper_ids = {str(x) for x in session.execute(select(Paper.id)).scalars().all()}
        marker_ids = {str(x) for x in session.execute(select(Marker.id)).scalars().all()}
        tag_ids = {int(x) for x in session.execute(select(Tag.id)).scalars().all()}

        def _not_in_users(col):
            if not user_ids:
                # No users at all — every non-null reference is orphaned,
                # but this is an extreme edge case (empty system).
                # Return a condition that matches nothing to prevent
                # accidental mass-deletion.
                from sqlalchemy import literal
                return literal(False)
            return col.not_in(user_ids)

        if not dry_run:
            # Null out invalid "by" columns (nullable).
            db_updated += _dml_rowcount(
                session.execute(update(LibraryShare).where(_not_in_users(LibraryShare.shared_by_user_id)).values(shared_by_user_id=None))
            )
            db_updated += _dml_rowcount(
                session.execute(update(PaperShare).where(_not_in_users(PaperShare.shared_by_user_id)).values(shared_by_user_id=None))
            )

            # Remove rows owned by missing users.
            db_deleted += _dml_rowcount(session.execute(delete(UserSetting).where(_not_in_users(UserSetting.user_id))))
            db_deleted += _dml_rowcount(session.execute(delete(PaperFavorite).where(_not_in_users(PaperFavorite.user_id))))
            db_deleted += _dml_rowcount(session.execute(delete(PaperToRead).where(_not_in_users(PaperToRead.user_id))))

            db_deleted += _dml_rowcount(session.execute(delete(LibraryShare).where(_not_in_users(LibraryShare.shared_with_user_id))))
            db_deleted += _dml_rowcount(session.execute(delete(PaperShare).where(_not_in_users(PaperShare.shared_with_user_id))))

            # Libraries referencing missing owners should become ownerless.
            db_updated += _dml_rowcount(session.execute(update(Library).where(_not_in_users(Library.owner_user_id)).values(owner_user_id=None)))

            # Markers should be removed if the owner no longer exists.
            db_deleted += _dml_rowcount(session.execute(delete(Marker).where(_not_in_users(Marker.owner_user_id))))

            # Orphan rows not tied to a user but commonly left behind.
            if library_ids:
                db_deleted += _dml_rowcount(
                    session.execute(delete(LibraryNamingPattern).where(LibraryNamingPattern.library_id.not_in(library_ids)))
                )
            if paper_ids:
                db_deleted += _dml_rowcount(session.execute(delete(PaperMarker).where(PaperMarker.paper_id.not_in(paper_ids))))
                db_deleted += _dml_rowcount(session.execute(delete(PaperTag).where(PaperTag.paper_id.not_in(paper_ids))))
            if marker_ids:
                db_deleted += _dml_rowcount(session.execute(delete(PaperMarker).where(PaperMarker.marker_id.not_in(marker_ids))))
            if tag_ids:
                db_deleted += _dml_rowcount(session.execute(delete(PaperTag).where(PaperTag.tag_id.not_in(tag_ids))))

            if library_ids:
                db_updated += _dml_rowcount(
                    session.execute(
                        update(Paper)
                        .where(Paper.library_id.is_not(None))
                        .where(Paper.library_id.not_in(library_ids))
                        .values(library_id=None)
                    )
                )

            session.commit()

    paths = get_paths()
    root = paths.library_files_dir

    orphan_user_dirs: list[str] = []
    fs_deleted = 0

    # Filesystem cleanup is best-effort and conservative.
    # We only delete a top-level directory if:
    # - it is not reserved (starts with '_')
    # - it is NOT a current username
    # - and it doesn't contain any subfolder matching an existing library slug
    with get_session() as session:
        usernames = {str(x or '').strip() for x in session.execute(select(User.username)).scalars().all()}
        usernames = {u for u in usernames if u}
        lib_slugs = {str(x or '').strip() for x in session.execute(select(Library.slug)).scalars().all()}
        lib_slugs = {s for s in lib_slugs if s}

    if root.exists() and root.is_dir():
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if name.startswith('_'):
                continue
            if name in usernames:
                continue

            # Heuristic safety: if it looks like it contains a library slug, don't delete.
            try:
                child_dirs = [p.name for p in entry.iterdir() if p.is_dir()]
            except Exception:
                child_dirs = []
            if any(c in lib_slugs for c in child_dirs):
                continue

            orphan_user_dirs.append(str(entry))
            if delete_orphan_user_dirs and not dry_run:
                try:
                    shutil.rmtree(entry)
                    fs_deleted += 1
                except Exception:
                    pass

    return UserCleanupResult(
        dry_run=bool(dry_run),
        db_deleted=int(db_deleted),
        db_updated=int(db_updated),
        fs_deleted=int(fs_deleted),
        orphan_user_dirs=orphan_user_dirs,
    )
