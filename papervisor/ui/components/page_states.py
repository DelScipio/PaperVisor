from __future__ import annotations

from collections.abc import Callable

from nicegui import ui


def inline_loading_state(message: str = 'Loading…') -> None:
    with ui.row().classes('w-full items-center gap-2 px-4 py-3'):
        ui.spinner('dots', size='sm')
        ui.label(str(message or 'Loading…')).classes('text-xs pv-text-dimmer')


def inline_empty_state(message: str = 'Nothing here yet') -> None:
    ui.label(str(message or 'Nothing here yet')).classes('text-xs pv-text-dimmer px-4 py-2')


def show_initial_panel_loading(
    *,
    panel_loading: dict[str, bool],
    key: str,
    message: str,
    refresh: Callable[[], None],
) -> bool:
    if not bool(panel_loading.get(key, False)):
        return False
    panel_loading[key] = False
    inline_loading_state(message)
    ui.timer(0.01, refresh, once=True)
    return True
