from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import Request
from nicegui import ui, app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse

from papervisor.core.exceptions import (
    DatabaseException,
    ExternalServiceException,
    FileSystemException,
    MetadataException,
    NotFoundException,
    PaperVisorException,
    PermissionDeniedException,
    ValidationException,
)
from papervisor.core.logging import new_request_id, reset_request_id, set_request_id, setup_logging
from papervisor.core.config import get_settings
from papervisor.db.init_db import init_db
from papervisor.static_mount import mount_static
from papervisor.api.register import register_api
from papervisor.ui.register import register_pages
from papervisor.services.migrations import run_migrations
from papervisor.services.users import ensure_default_admin


class _RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get('X-Request-ID')
        rid = str(rid or '').strip() or new_request_id()

        token = set_request_id(rid)

        try:
            response = await call_next(request)
        finally:
            # Ensure this request_id doesn't leak into other tasks.
            try:
                reset_request_id(token)
            except (LookupError, RuntimeError, ValueError):
                logging.getLogger(__name__).exception('Failed to reset request id context')

        try:
            response.headers['X-Request-ID'] = rid
        except (AttributeError, TypeError, KeyError):
            logging.getLogger(__name__).warning('Unable to set X-Request-ID response header')
        return response


def _status_for_exception(exc: PaperVisorException) -> int:
    if isinstance(exc, ValidationException):
        return 400
    if isinstance(exc, NotFoundException):
        return 404
    if isinstance(exc, PermissionDeniedException):
        return 403
    if isinstance(exc, (ExternalServiceException, MetadataException)):
        return 502
    if isinstance(exc, (DatabaseException, FileSystemException)):
        return 500
    return 500


def _register_exception_handlers() -> None:
    @app.exception_handler(PaperVisorException)
    async def _handle_pv_exc(_request: Request, exc: PaperVisorException):
        import logging

        logging.getLogger(__name__).exception('PaperVisor error: %s', exc)
        status = _status_for_exception(exc)
        return JSONResponse(status_code=status, content={'detail': str(exc)})

    @app.exception_handler(ValueError)
    async def _handle_value_error(_request: Request, exc: ValueError):
        # Many services currently raise ValueError for validation.
        import logging

        logging.getLogger(__name__).warning('Validation error: %s', exc)
        return JSONResponse(status_code=400, content={'detail': str(exc)})


class _CspMiddleware(BaseHTTPMiddleware):
    """Add Content-Security-Policy headers to all responses.

    Uses sensible defaults that allow NiceGUI's Quasar/Vue UI, the PDF.js
    viewer and EPUB reader to work while restricting inline scripts and
    object embeds.

    - ``unsafe-inline`` + ``unsafe-eval`` are required by NiceGUI (Vue/Quasar
      use runtime-compiled templates and inline styles).
    - ``blob:`` is needed by PDF.js for its Web Worker.
    - ``data:`` is used by Quasar for inline SVG icons.
    """

    _CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com blob:; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' ws: wss:; "
        "worker-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'self'"
    )

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        try:
            response.headers.setdefault('Content-Security-Policy', self._CSP)
            response.headers.setdefault('X-Content-Type-Options', 'nosniff')
            response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        except (AttributeError, TypeError, KeyError):
            logging.getLogger(__name__).exception('Failed to apply security headers')
        return response


class _CsrfOriginMiddleware(BaseHTTPMiddleware):
    """Block cross-origin state-changing requests (CSRF protection).

    Compares the ``Origin`` / ``Referer`` header against the ``Host`` header.
    Only applies to POST/PUT/PATCH/DELETE requests on ``/api/`` paths.
    WebSocket upgrades and NiceGUI's internal ``/_nicegui/`` paths are excluded
    because NiceGUI manages its own WebSocket auth.
    """

    _MUTATING_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

    async def dispatch(self, request: Request, call_next):
        if (
            request.method in self._MUTATING_METHODS
            and request.url.path.startswith('/api/')
        ):
            host = (request.headers.get('host') or '').split(':')[0].lower()
            origin = request.headers.get('origin') or ''
            referer = request.headers.get('referer') or ''

            origin_host = ''
            if origin:
                # "https://example.com" → "example.com"
                try:
                    origin_host = origin.split('://')[1].split('/')[0].split(':')[0].lower()
                except (IndexError, ValueError):
                    pass
            elif referer:
                try:
                    origin_host = referer.split('://')[1].split('/')[0].split(':')[0].lower()
                except (IndexError, ValueError):
                    pass

            if origin_host and host and origin_host != host:
                return JSONResponse(
                    status_code=403,
                    content={'detail': 'Cross-origin request blocked (CSRF protection)'},
                )

        return await call_next(request)


def run() -> None:
    setup_logging()

    # Add middleware/handlers once (avoid duplicates under reload).
    try:
        if not getattr(app.state, 'pv_request_id_middleware', False):
            app.add_middleware(GZipMiddleware, minimum_size=1024)
            app.add_middleware(_RequestIdMiddleware)
            app.add_middleware(_CsrfOriginMiddleware)
            app.add_middleware(_CspMiddleware)
            app.state.pv_request_id_middleware = True
    except (AttributeError, RuntimeError):
        logging.getLogger(__name__).exception('Failed to register middleware stack')

    try:
        if not getattr(app.state, 'pv_exception_handlers', False):
            _register_exception_handlers()
            app.state.pv_exception_handlers = True
    except (AttributeError, RuntimeError):
        logging.getLogger(__name__).exception('Failed to register exception handlers')

    init_db()
    ensure_default_admin()
    run_migrations()
    mount_static()

    # Explicit route/page registration (localized import side effects).
    register_api(app)
    register_pages()

    settings = get_settings()

    storage_secret = settings.storage_secret
    if not storage_secret:
        if settings.require_storage_secret:
            raise RuntimeError(
                'PAPERVISOR_REQUIRE_STORAGE_SECRET is enabled but no storage secret was set. '
                'Set PAPERVISOR_STORAGE_SECRET (or NICEGUI_STORAGE_SECRET).'
            )
        storage_secret = secrets.token_urlsafe(32)
        _log = logging.getLogger(__name__)
        _log.warning(
            '⚠️  PAPERVISOR_STORAGE_SECRET is not set! '
            'A random ephemeral secret has been generated. '
            'Sessions will NOT survive restarts. '
            'Set PAPERVISOR_STORAGE_SECRET in your environment for production use.'
        )

    host = settings.host
    port = settings.port
    reload = settings.reload

    kwargs: dict = {
        'title': 'PaperVisor',
        'host': host,
        'port': port,
        'reload': reload,
        'storage_secret': storage_secret,
        'reconnect_timeout': 30.0,  # Increased timeout to handle mobile network stability
    }

    # Dev reload can get stuck in a loop if we watch runtime-mutating folders
    # (logs, uploads, caches, DB files). NiceGUI exposes Uvicorn reload settings
    # via the `uvicorn_reload_*` parameters.
    if reload:
        # Watch only source by default.
        kwargs.setdefault('uvicorn_reload_dirs', 'papervisor')
        kwargs.setdefault('uvicorn_reload_includes', '*.py')
        kwargs.setdefault(
            'uvicorn_reload_excludes',
            '.*, .py[cod], .sw.*, ~*, __pycache__/*, logs/*, library_files/*, *.log, *.db, *.sqlite, *.sqlite3',
        )

    # NiceGUI expects a filesystem path here (it serves /favicon.ico itself).
    # Passing a URL like '/static/...' makes it look for '/static' on disk.
    favicon_path = Path(__file__).parent / 'static' / 'favicon.ico'
    if favicon_path.exists():
        kwargs['favicon'] = str(favicon_path)

    ui.run(**kwargs)
