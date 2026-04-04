from __future__ import annotations

import mimetypes
from pathlib import Path
import logging

from fastapi.staticfiles import StaticFiles
from nicegui import app


logger = logging.getLogger(__name__)


def mount_static() -> None:
    # The built pdf.js viewer uses ES modules (.mjs) and WebAssembly (.wasm).
    # Some Python installations don't register these extensions, causing the
    # browser to refuse to execute module scripts and resulting in a blank viewer.
    mimetypes.add_type('text/javascript', '.mjs')
    mimetypes.add_type('application/wasm', '.wasm')

    static_dir = Path(__file__).parent / 'static'
    static_dir.mkdir(parents=True, exist_ok=True)

    # Avoid double-mounting in reload.
    for route in list(getattr(app, 'routes', [])):
        if getattr(route, 'path', None) == '/static':
            return

    app.mount('/static', StaticFiles(directory=str(static_dir)), name='static')
    
    # Mount library_files for covers, thumbnails, and PDF/EPUB files
    # Use the configured library_files_dir from config instead of hardcoded path
    # follow_symlink=False prevents symlink-based path traversal attacks.
    from papervisor.core.config import get_paths
    library_files_dir = get_paths().library_files_dir
    if library_files_dir.exists():
        app.mount(
            '/library_files',
            StaticFiles(directory=str(library_files_dir), follow_symlink=False),
            name='library_files',
        )
    else:
        logger.warning('library_files directory does not exist yet: %s', library_files_dir)
