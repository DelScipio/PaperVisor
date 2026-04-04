from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from nicegui import ui
from nicegui import app

from papervisor.services.papers import get_paper
from papervisor.ui.theme import setup_theme


@ui.page('/reader/{paper_id}')
def reader_page(paper_id: str) -> None:
    """Redirect into the standalone pdf.js viewer for true fullscreen viewing.

    We use `location.replace` so that the browser Back button returns to the
    PaperVisor library page rather than bouncing back through this redirect.
    """

    setup_theme()
    ui.query('body').classes('bg-transparent')

    if not app.storage.user.get('user_id'):
        ui.timer(0.01, lambda: ui.navigate.to('/login'), once=True)
        ui.label('Redirecting…').classes('pv-text-dim')
        return

    row = get_paper(paper_id=paper_id)
    if row is None or not str(row.file_path or '').strip():
        ui.label('File not found').classes('pv-text-dim')
        return

    if not str(row.file_path).lower().endswith('.pdf'):
        ui.label('Only PDF files are supported in the reader.').classes('pv-text-dim')
        return

    # IMPORTANT: pdf.js v5+ no longer double-decodes the `file=` parameter.
    # If we percent-encode slashes, pdf.js will request a literal `/%2Fapi...`
    # which doesn't exist. Keep slashes unescaped.
    file_url = f'/api/v1/papers/{paper_id}/file'
    title = (str(row.title or '').strip() or Path(str(row.file_path)).name or 'Document')

    # If we have a known resume page, include it in the initial hash so pdf.js
    # starts rendering/fetching that area immediately (especially helpful with Range requests).
    initial_hash = ''
    try:
        loc = str(getattr(row, 'reading_location', '') or '').strip().lower()
        if loc.startswith('page:'):
            n = int(loc.split(':', 1)[1].strip() or '0')
            if n > 0:
                initial_hash = f'#page={n}'
    except Exception:
        initial_hash = ''

    viewer_url = (
        '/static/pdfjs/web/viewer.html'
        + f'?file={quote(file_url, safe="/")}'
        + f'&pv_paper_id={quote(paper_id, safe="")}'
        + f'&pv_title={quote(title, safe="")}'
        + initial_hash
    )

    ui.navigate.to(viewer_url)
    ui.label('Redirecting…').classes('pv-text-dim')
