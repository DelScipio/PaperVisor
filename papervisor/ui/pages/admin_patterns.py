from __future__ import annotations

from nicegui import ui
from nicegui import app

from papervisor.ui.theme import setup_theme


@ui.page('/admin/patterns')
def admin_patterns() -> None:
    setup_theme()
    ui.query('body').classes('bg-transparent')

    if not app.storage.user.get('user_id'):
        ui.timer(0.01, lambda: ui.navigate.to('/login'), once=True)
        ui.label('Redirecting…').classes('pv-text-dim')
        return

    # Keep the old URL working, but move admin UI to /admin.
    ui.timer(0.01, lambda: ui.navigate.to('/admin'), once=True)
    ui.label('Redirecting…').classes('pv-text-dim')
