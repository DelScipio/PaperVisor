"""REST API endpoints for PaperVisor.

Provides versioned REST API (``/api/v1/...``) for document reading, listing,
reading-state management, PDF annotations, and health checking.

Legacy un-versioned routes (``/api/papers/...``) redirect to the ``v1``
equivalents so existing clients and static viewers keep working.

API Documentation is available at ``/docs`` (Swagger UI) and ``/redoc`` (ReDoc).
"""
from __future__ import annotations

import logging
import math
import os
import shutil
import uuid
from dataclasses import dataclass
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from threading import Lock
from time import monotonic
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from nicegui import app
from sqlalchemy.exc import SQLAlchemyError

from papervisor import __version__ as _APP_VERSION

from papervisor.api.schemas import (
    HealthResponse,
    OkBytesResponse,
    OkResponse,
    PaginationMeta,
    PaperListResponse,
    PaperSummary,
    ReadingStateIn,
    ReadingStateOut,
    ReadingStateUpdated,
)
from papervisor.auth import current_user_id, is_admin, require_api_admin, require_api_login
from papervisor.core.config import get_paths
from papervisor.core.exceptions import PermissionDeniedException
from papervisor.services.db_importer import get_import_report, run_import_queue
from papervisor.services.media import generate_pdf_first_page_thumbnail
from papervisor.services.papers import (
    PaperFilters,
    count_papers_filtered,
    get_paper,
    is_favorite,
    list_papers_filtered,
    record_opened,
    reset_open_counts,
    set_reading_state,
)
from papervisor.services.sharing import require_library_manage, require_library_read
from papervisor.services.users import authenticate_by_api_key

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# APIRouter – all new endpoints live under /api/v1
# ---------------------------------------------------------------------------

router = APIRouter(prefix='/api/v1', tags=['papers'])

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PAPER_FILE_CACHE_TTL_S = 2.0
_PAPER_FILE_CACHE_MAX = 2048
_MAX_PDF_UPLOAD_BYTES = 500 * 1024 * 1024
_MAX_STREAMED_FILE_BYTES = 1024 * 1024 * 1024


def _parse_positive_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, '') or '').strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        _log.warning('Invalid %s value %r; using default %s', name, raw, default)
        return default
    if value <= 0:
        _log.warning('Non-positive %s value %r; using default %s', name, raw, default)
        return default
    return value


def _parse_positive_float_env(name: str, default: float) -> float:
    raw = str(os.getenv(name, '') or '').strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        _log.warning('Invalid %s value %r; using default %s', name, raw, default)
        return default
    if value <= 0:
        _log.warning('Non-positive %s value %r; using default %s', name, raw, default)
        return default
    return value


def _resolve_library_file_path(file_path: str) -> Path | None:
    """Resolve a DB path to an on-disk path under the library root only."""
    raw = str(file_path or '').strip()
    if not raw:
        return None
    try:
        library_root = get_paths().library_files_dir.resolve()
        source = Path(raw)
        resolved = source.resolve() if source.is_absolute() else (library_root / source).resolve()
        resolved.relative_to(library_root)
        return resolved
    except (ValueError, OSError):
        return None


def _is_path_inside_library(file_path: str) -> bool:
    """Return True if *file_path* resolves to a location under the library root."""
    return _resolve_library_file_path(file_path) is not None


@dataclass(frozen=True)
class _PaperFileCacheEntry:
    expires_at: float
    file_path: str | None


_paper_file_cache: dict[tuple[int, str], _PaperFileCacheEntry] = {}
_paper_file_cache_lock = Lock()


def clear_paper_file_access_cache() -> None:
    """Clear cached paper-file authorization decisions."""
    with _paper_file_cache_lock:
        _paper_file_cache.clear()


def _paper_file_path_for_user_cached(*, user_id: int, paper_id: str) -> str | None:
    """Return a paper's file path if the user can read it (TTL-cached)."""

    pid = str(paper_id or '').strip()
    if not pid:
        return None

    key = (int(user_id), pid)
    now = monotonic()
    ttl_seconds = _parse_positive_float_env('PAPERVISOR_FILE_ACCESS_CACHE_TTL_S', _PAPER_FILE_CACHE_TTL_S)

    with _paper_file_cache_lock:
        entry = _paper_file_cache.get(key)
        if entry is not None and entry.expires_at > now:
            return entry.file_path

    row = get_paper(paper_id=pid)
    file_path = str(getattr(row, 'file_path', '') or '').strip() if row is not None else ''

    allowed_path: str | None = None
    if row is not None and file_path:
        try:
            require_library_read(user_id=int(user_id), library_id=str(getattr(row, 'library_id', '') or ''))
            # Path containment: ensure the file is inside the library root.
            resolved = _resolve_library_file_path(file_path)
            if resolved is not None:
                allowed_path = str(resolved)
        except PermissionDeniedException:
            allowed_path = None

    with _paper_file_cache_lock:
        if len(_paper_file_cache) > _PAPER_FILE_CACHE_MAX:
            _paper_file_cache.clear()
        _paper_file_cache[key] = _PaperFileCacheEntry(expires_at=now + ttl_seconds, file_path=allowed_path)

    return allowed_path


def _require_user_id_int(request: Request) -> int:
    if hasattr(request.state, 'api_user_id'):
        uid = request.state.api_user_id
    else:
        uid = current_user_id()
        
    if uid is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    try:
        return int(uid)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail='Not authenticated')


def _get_paper_row_or_404(paper_id: str):
    row = get_paper(paper_id=paper_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Item not found')
    return row


def _require_paper_read_access(*, user_id: int, row) -> None:
    try:
        require_library_read(user_id=user_id, library_id=str(row.library_id or ''))
    except PermissionDeniedException:
        raise HTTPException(status_code=403, detail='Not allowed')


def _require_paper_manage_access(*, user_id: int, row) -> None:
    try:
        require_library_manage(user_id=user_id, library_id=str(row.library_id or ''))
    except PermissionDeniedException:
        raise HTTPException(status_code=403, detail='Not allowed')


def _media_type_for_suffix(suffix: str) -> str:
    s = (suffix or '').lower()
    if s == '.pdf':
        return 'application/pdf'
    if s == '.epub':
        return 'application/epub+zip'
    if s == '.cbz':
        return 'application/vnd.comicbook+zip'
    return 'application/octet-stream'


def _allow_health_details(request: Request) -> bool:
    api_key = str(request.headers.get('X-API-Key', '') or '').strip()
    if api_key:
        api_user = authenticate_by_api_key(api_key)
        if api_user is not None and bool(getattr(api_user, 'is_admin', False)):
            return True

    return current_user_id() is not None and is_admin()


# ============================================================================
# Health check (public, no auth)
# ============================================================================

@router.get(
    '/health',
    response_model=HealthResponse,
    response_model_exclude_none=True,
    tags=['system'],
    summary='Health check',
    description='Returns public liveness status. Detailed diagnostics are shown only to authenticated admins.',
)
def health_check(request: Request) -> HealthResponse:
    if not _allow_health_details(request):
        return HealthResponse(status='ok')

    paths = get_paths()

    db_status = 'connected'
    papers_count = 0
    try:
        from papervisor.services.papers import get_dashboard_counts
        counts = get_dashboard_counts()
        papers_count = counts.get('total', 0)
    except Exception:
        db_status = 'error'

    try:
        usage = shutil.disk_usage(str(paths.library_files_dir))
        disk_free_mb = int(usage.free / (1024 * 1024))
    except Exception:
        disk_free_mb = -1

    status = 'ok' if db_status == 'connected' and disk_free_mb > 0 else 'degraded'

    return HealthResponse(
        status=status,
        version=_APP_VERSION,
        database=db_status,
        disk_free_mb=disk_free_mb,
        papers_count=papers_count,
    )


@router.get(
    '/admin/imports/report',
    tags=['admin'],
    summary='Get startup import report',
    description='Returns import queue configuration plus last run and recent history.',
    dependencies=[Depends(require_api_admin)],
)
def admin_import_report_endpoint(
    limit: int = Query(20, ge=1, le=100, description='Number of history entries to return.'),
) -> dict[str, object]:
    return get_import_report(limit=limit)


@router.post(
    '/admin/imports/run',
    tags=['admin'],
    summary='Run import queue now',
    description='Triggers import queue processing immediately. Use dry_run=true for preview mode.',
    dependencies=[Depends(require_api_admin)],
)
def admin_import_run_endpoint(
    dry_run: bool = Query(False, description='When true, performs a preview without DB writes.'),
    limit: int = Query(20, ge=1, le=100, description='Number of history entries to include in response.'),
) -> dict[str, object]:
    run_import_queue(force=True, dry_run=dry_run)
    return get_import_report(limit=limit)


# ============================================================================
# Paper list with pagination
# ============================================================================

@router.get(
    '/papers',
    response_model=PaperListResponse,
    summary='List papers',
    description=(
        'Paginated paper listing with optional search and filters. '
        'Supports file_type, favorites, to_read, completed filters '
        'and multiple sort orders.'
    ),
    dependencies=[Depends(require_api_login)],
)
def list_papers_endpoint(
    request: Request,
    page: int = Query(1, ge=1, description='Page number (1-based).'),
    per_page: int = Query(50, ge=1, le=200, description='Items per page (max 200).'),
    q: str | None = Query(None, description='Search query.'),
    mode: str = Query('all', description='Search mode: all, title, authors, doi, isbn, journal, publisher, tags.'),
    sort: str = Query('default', description='Sort: default, recent, title_asc, title_desc, author_asc, year_desc, year_asc, last_opened, last_read.'),
    file_type: str | None = Query(None, description="Filter by type: 'paper' or 'book'."),
    library_id: str | None = Query(None, description='Restrict to a single library.'),
    favorites: bool = Query(False, description='Only favorites.'),
    to_read: bool = Query(False, description='Only to-read.'),
    completed: bool = Query(False, description='Only completed.'),
) -> PaperListResponse:
    user_id = _require_user_id_int(request)
    filters = PaperFilters(
        file_type=file_type,
        favorites_only=favorites,
        to_read_only=to_read,
        completed_only=completed,
    )

    total = count_papers_filtered(
        user_id=user_id,
        library_id=library_id,
        query=q,
        mode=mode,
        filters=filters,
    )

    offset = (page - 1) * per_page
    pages = max(1, math.ceil(total / per_page))

    rows = list_papers_filtered(
        user_id=user_id,
        library_id=library_id,
        query=q,
        mode=mode,
        filters=filters,
        sort=sort,
        limit=per_page,
        offset=offset,
    )

    items = [
        PaperSummary(
            id=r.id,
            title=r.title,
            subtitle=r.subtitle,
            file_type=getattr(r, 'file_type', 'paper') or 'paper',
            authors=getattr(r, 'authors', None),
            published_year=getattr(r, 'published_year', None),
            journal=getattr(r, 'journal', None),
            doi=getattr(r, 'doi', None),
            isbn=getattr(r, 'isbn', None),
            series=getattr(r, 'series', None),
            language=getattr(r, 'language', None),
            reading_progress=r.reading_progress,
            is_completed=r.is_completed,
            is_favorite=r.is_favorite,
            is_to_read=r.is_to_read,
            open_count_total=r.open_count_total,
            file_suffix=r.file_suffix,
        )
        for r in rows
    ]

    return PaperListResponse(
        items=items,
        pagination=PaginationMeta(total=total, page=page, per_page=per_page, pages=pages),
    )


# ============================================================================
# File serving
# ============================================================================

@router.api_route(
    '/papers/{paper_id}/file',
    methods=['GET', 'HEAD'],
    dependencies=[Depends(require_api_login)],
    summary='Get paper PDF for inline viewing',
    description='Returns the PDF file with inline Content-Disposition for the built-in reader.',
    responses={
        200: {'content': {'application/pdf': {}}, 'description': 'PDF file.'},
        304: {'description': 'Not modified (conditional request).'},
        400: {'description': 'File type not supported.'},
        401: {'description': 'Not authenticated.'},
        403: {'description': 'No library access.'},
        404: {'description': 'Paper or file not found.'},
    },
)
def get_paper_file(paper_id: str, request: Request) -> Response:
    user_id = _require_user_id_int(request)
    file_path = _paper_file_path_for_user_cached(user_id=user_id, paper_id=paper_id)
    if not file_path:
        # Intentionally ambiguous: avoid leaking existence.
        raise HTTPException(status_code=404, detail='File not found')

    path = Path(str(file_path))
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail='File not found')

    # Only PDFs are supported by the built-in reader.
    if path.suffix.lower() != '.pdf':
        raise HTTPException(status_code=400, detail='Only PDF files are supported')

    stat = path.stat()
    max_served_bytes = _parse_positive_int_env('PAPERVISOR_MAX_STREAMED_FILE_BYTES', _MAX_STREAMED_FILE_BYTES)
    if stat.st_size > max_served_bytes:
        raise HTTPException(status_code=413, detail='File too large to serve')

    etag = f'W/"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    last_modified = formatdate(stat.st_mtime, usegmt=True)

    if_none_match = request.headers.get('if-none-match')
    if_modified_since = request.headers.get('if-modified-since')

    not_modified = False
    if if_none_match and if_none_match.strip() == etag:
        not_modified = True
    elif if_modified_since:
        try:
            ims_dt = parsedate_to_datetime(if_modified_since)
            if ims_dt is not None:
                ims_ts = ims_dt.timestamp()
                if stat.st_mtime <= ims_ts:
                    not_modified = True
        except (TypeError, ValueError, OverflowError, OSError):
            pass

    cache_headers = {
        'Accept-Ranges': 'bytes',
        'Content-Disposition': 'inline',
        'Cache-Control': 'private, max-age=0, must-revalidate',
        'ETag': etag,
        'Last-Modified': last_modified,
        'X-Content-Type-Options': 'nosniff',
    }

    if not_modified:
        return Response(status_code=304, headers=cache_headers)

    return FileResponse(path=str(path), media_type='application/pdf', headers=cache_headers)


@router.api_route(
    '/papers/{paper_id}/raw',
    methods=['GET', 'HEAD'],
    dependencies=[Depends(require_api_login)],
    summary='Get raw document file',
    description='Returns the stored file (PDF/EPUB/CBZ) as-is for web readers.',
    responses={
        200: {'description': 'Document file.'},
        400: {'description': 'Unsupported file type.'},
        401: {'description': 'Not authenticated.'},
        404: {'description': 'Paper or file not found.'},
    },
)
def get_paper_raw(paper_id: str, request: Request) -> FileResponse:
    user_id = _require_user_id_int(request)
    file_path = _paper_file_path_for_user_cached(user_id=user_id, paper_id=paper_id)
    if not file_path:
        raise HTTPException(status_code=404, detail='File not found')

    path = Path(str(file_path))
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail='File not found')

    suffix = path.suffix.lower()
    if suffix not in {'.pdf', '.epub', '.cbz'}:
        raise HTTPException(status_code=400, detail='Unsupported file type')
    stat = path.stat()
    max_served_bytes = _parse_positive_int_env('PAPERVISOR_MAX_STREAMED_FILE_BYTES', _MAX_STREAMED_FILE_BYTES)
    if stat.st_size > max_served_bytes:
        raise HTTPException(status_code=413, detail='File too large to serve')

    return FileResponse(
        path=str(path),
        media_type=_media_type_for_suffix(suffix),
        headers={
            'Accept-Ranges': 'bytes',
            'Content-Disposition': 'inline',
            'Cache-Control': 'no-store, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
            'X-Content-Type-Options': 'nosniff',
        },
    )


# ============================================================================
# PDF upload (save annotated PDF back)
# ============================================================================

@router.post(
    '/papers/{paper_id}/save_pdf',
    response_model=OkBytesResponse,
    summary='Upload annotated PDF',
    description='Overwrites the paper file with an annotated version from the reader.',
    dependencies=[Depends(require_api_login)],
)
async def save_paper_pdf(paper_id: str, request: Request, file: UploadFile = File(...)) -> OkBytesResponse:
    row = get_paper(paper_id=paper_id)
    if row is None or not str(row.file_path or '').strip():
        raise HTTPException(status_code=404, detail='File not found')

    user_id = _require_user_id_int(request)
    _require_paper_manage_access(user_id=user_id, row=row)

    dest = _resolve_library_file_path(str(row.file_path))
    if dest is None:
        raise HTTPException(status_code=404, detail='File not found')
    if dest.suffix.lower() != '.pdf':
        raise HTTPException(status_code=400, detail='Only PDF files are supported')

    if file.content_type not in {None, '', 'application/pdf', 'application/octet-stream'}:
        raise HTTPException(status_code=400, detail='Unsupported upload content type')

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + f'.{uuid.uuid4().hex}.tmp')

    size = 0
    chunk_size = 1024 * 1024
    max_upload_bytes = _parse_positive_int_env('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', _MAX_PDF_UPLOAD_BYTES)
    try:
        with open(tmp_path, 'wb') as out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                size += len(chunk)
                if size > max_upload_bytes:
                    raise HTTPException(status_code=413, detail='Upload exceeds maximum allowed size')
        if size <= 0:
            raise HTTPException(status_code=400, detail='Empty upload')

        os.replace(str(tmp_path), str(dest))

        try:
            generate_pdf_first_page_thumbnail(file_path=str(dest), paper_id=str(row.id))
        except (OSError, ValueError, RuntimeError):
            _log.debug('Thumbnail refresh failed for %s', row.id, exc_info=True)

        return OkBytesResponse(ok=True, bytes=size)
    finally:
        try:
            await file.close()
        except (AttributeError, RuntimeError, ValueError):
            pass
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


# ============================================================================
# Reading state
# ============================================================================

@router.get(
    '/papers/{paper_id}/reading_state',
    response_model=ReadingStateOut,
    summary='Get reading state',
    description='Returns the current reading progress, location, and flags for a paper.',
    dependencies=[Depends(require_api_login)],
)
def get_reading_state(paper_id: str, request: Request) -> ReadingStateOut:
    row = _get_paper_row_or_404(paper_id)
    user_id = _require_user_id_int(request)
    _require_paper_read_access(user_id=user_id, row=row)

    return ReadingStateOut(
        paper_id=str(row.id),
        progress=float(row.reading_progress or 0.0),
        location=str(row.reading_location or ''),
        is_completed=bool(row.is_completed),
        is_favorite=is_favorite(user_id=user_id, paper_id=str(row.id)),
    )


@router.post(
    '/papers/{paper_id}/reading_state',
    response_model=ReadingStateUpdated,
    summary='Update reading state',
    description='Set reading progress and/or location for a paper.',
    dependencies=[Depends(require_api_login)],
)
def post_reading_state(paper_id: str, request: Request, payload: ReadingStateIn = Body(...)) -> ReadingStateUpdated:
    user_id = _require_user_id_int(request)
    row0 = _get_paper_row_or_404(paper_id)
    _require_paper_read_access(user_id=user_id, row=row0)

    row = set_reading_state(paper_id=paper_id, progress=payload.progress, location=payload.location)
    if row is None:
        raise HTTPException(status_code=404, detail='Item not found')

    return ReadingStateUpdated(
        ok=True,
        paper_id=str(row.id),
        progress=float(row.reading_progress or 0.0),
        location=str(row.reading_location or ''),
        is_completed=bool(row.is_completed),
        is_favorite=is_favorite(user_id=user_id, paper_id=str(row.id)),
    )


# ============================================================================
# Open tracking
# ============================================================================

@router.post(
    '/papers/{paper_id}/opened',
    response_model=OkResponse,
    summary='Record paper opened',
    description='Increment the open counter for a paper.',
    dependencies=[Depends(require_api_login)],
)
def post_opened(paper_id: str, request: Request) -> OkResponse:
    row = _get_paper_row_or_404(paper_id)
    user_id = _require_user_id_int(request)
    _require_paper_read_access(user_id=user_id, row=row)
    try:
        record_opened(paper_id=paper_id)
    except (SQLAlchemyError, RuntimeError, ValueError):
        _log.debug('record_opened failed for %s', paper_id, exc_info=True)
    return OkResponse(ok=True)


@router.post(
    '/papers/{paper_id}/reset_open_counts',
    response_model=OkResponse,
    summary='Reset open counts',
    description='Reset the "opens since reset" counter for a paper.',
    dependencies=[Depends(require_api_login)],
)
def post_reset_open_counts(paper_id: str, request: Request) -> OkResponse:
    row = _get_paper_row_or_404(paper_id)
    user_id = _require_user_id_int(request)
    _require_paper_manage_access(user_id=user_id, row=row)
    reset_open_counts(paper_id=paper_id)
    return OkResponse(ok=True)


# ============================================================================
# Backward-compatible redirects  (old /api/papers/... → /api/v1/papers/...)
# ============================================================================

def _legacy_redirect(request: Request) -> RedirectResponse:
    """Redirect ``/api/papers/...`` → ``/api/v1/papers/...``."""
    new_path = request.url.path.replace('/api/papers/', '/api/v1/papers/', 1)
    if request.url.query:
        new_path = f'{new_path}?{request.url.query}'
    return RedirectResponse(url=new_path, status_code=308)


def register_legacy_redirects() -> None:
    """Register permanent redirects from old un-versioned routes."""
    legacy_patterns = [
        '/api/papers/{paper_id}/file',
        '/api/papers/{paper_id}/raw',
        '/api/papers/{paper_id}/save_pdf',
        '/api/papers/{paper_id}/reading_state',
        '/api/papers/{paper_id}/opened',
        '/api/papers/{paper_id}/reset_open_counts',
    ]
    for pattern in legacy_patterns:
        app.api_route(pattern, methods=['GET', 'HEAD', 'POST'], include_in_schema=False)(_legacy_redirect)

