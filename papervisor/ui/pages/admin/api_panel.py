from __future__ import annotations

from datetime import datetime, timezone
import re

from nicegui import ui

from papervisor.services.doi import fetch_crossref_metadata
from papervisor.services.google_books import fetch_googlebooks_metadata
from papervisor.services.isbn import fetch_openlibrary_metadata
from papervisor.services.settings import (
    get_book_isbn_discovery_providers,
    get_book_metadata_fetch_providers,
    get_google_books_api_key,
    get_metadata_provider_timeout_seconds,
    set_book_isbn_discovery_providers,
    set_book_metadata_fetch_providers,
    set_google_books_api_key,
    set_metadata_provider_timeout_seconds,
    settings_available,
)
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_header


_PROVIDER_VALUES_TO_LABELS: dict[str, str] = {
    'openlibrary': 'OpenLibrary',
    'google': 'Google Books',
}

def _provider_options() -> dict[str, str]:
    # NiceGUI expects dict options as value -> label (keys are valid values).
    return dict(_PROVIDER_VALUES_TO_LABELS)


def _now_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')


def _friendly_provider_error(raw_error: str) -> str:
    msg = str(raw_error or '').strip()
    lower = msg.lower()
    if 'timed out' in lower or 'timeout' in lower:
        return 'Timeout while contacting provider. Increase timeout and retry.'
    if 'network error' in lower or 'name or service not known' in lower or 'temporary failure in name resolution' in lower:
        return 'Network/DNS issue while contacting provider.'
    code_match = re.search(r'\((\d{3})\)', msg)
    if code_match:
        code = code_match.group(1)
        if code == '401' or code == '403':
            return f'Authentication/authorization rejected by provider (HTTP {code}).'
        if code == '404':
            return 'Provider endpoint or test item not found (HTTP 404).'
        if code.startswith('5'):
            return f'Provider server error (HTTP {code}). Try again later.'
        return f'Provider returned HTTP {code}.'
    if 'invalid json' in lower:
        return 'Provider returned malformed JSON response.'
    if 'no results' in lower:
        return 'Provider responded but returned no results for probe identifier.'
    return msg or 'Unknown provider error.'


def render_api_panel() -> None:
    with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
        dialog_header(
            title='API',
            icon='key',
            subtitle='Configure external providers and priority.',
            extra_classes='!px-3 !py-2',
            icon_classes='text-base',
            title_classes='text-sm',
            subtitle_classes='text-xs',
        )

    can_persist = settings_available()
    if not can_persist:
        ui.label('Saving requires database migrations.').classes('text-xs pv-text-dim')
        ui.label('Run: alembic upgrade heads').classes('text-xs pv-text-dimmer pt-1')

    with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
        ui.label('Google Books').classes('text-sm font-semibold pv-text-dim')
        ui.label('Used for ISBN discovery and (optionally) book metadata.').classes('text-xs pv-text-dimmer')

        with ui.row().classes('w-full items-center gap-3 pt-2'):
            key_in = ui.input(
                'Google Books API key',
                value=get_google_books_api_key() if can_persist else '',
                password=True,
                password_toggle_button=True,
            ).props('outlined dense').classes('flex-1')

            def _save_key() -> None:
                try:
                    set_google_books_api_key(str(key_in.value or ''))
                    ui.notify('Google Books API key saved', color='positive')
                except Exception as ex:
                    ui.notify(str(ex), color='negative')

            def _clear_key() -> None:
                try:
                    set_google_books_api_key('')
                    key_in.value = ''
                    key_in.update()
                    ui.notify('Google Books API key cleared', color='warning')
                except Exception as ex:
                    ui.notify(str(ex), color='negative')

            save_key_btn = ui.button('Save', on_click=_save_key).props('color=primary').classes('pv-meta-save-btn')
            clear_key_btn = ui.button('Clear', on_click=_clear_key).props('outline').classes('pv-meta-action-btn')
            if not can_persist:
                save_key_btn.disable()
                clear_key_btn.disable()

    def _priority_card(*, title: str, subtitle: str, initial: list[str], on_save) -> None:
        with ui.card().props('flat bordered').classes('pv-dialog-card w-full mt-2'):
            ui.label(title).classes('text-sm font-semibold pv-text-dim')
            ui.label(subtitle).classes('text-xs pv-text-dimmer')

            primary_value = (initial[0] if initial else 'openlibrary')
            fallback_value = (initial[1] if len(initial) > 1 else 'google')

            options = _provider_options()

            with ui.row().classes('w-full items-center gap-3 pt-2'):
                # Create with safe values first, then set (avoids constructor-time "Invalid value" issues).
                primary_sel = ui.select(options, value=None, label='Primary').props('outlined dense').classes('flex-1')
                fallback_sel = ui.select(options, value=None, label='Fallback').props('outlined dense').classes('flex-1')

                if primary_value in options:
                    primary_sel.value = primary_value
                if fallback_value in options:
                    fallback_sel.value = fallback_value

            def _save() -> None:
                try:
                    on_save(primary=str(primary_sel.value or ''), fallback=str(fallback_sel.value or ''))
                    ui.notify('Provider priority saved', color='positive')
                except Exception as ex:
                    ui.notify(str(ex), color='negative')

            with ui.row().classes('w-full justify-end gap-2 pt-2'):
                save_btn = ui.button('Save', on_click=_save).props('color=primary').classes('pv-meta-save-btn')
                if not can_persist:
                    save_btn.disable()

    # ISBN discovery priority
    initial_discovery = get_book_isbn_discovery_providers() if can_persist else ['openlibrary', 'google']
    _priority_card(
        title='Book ISBN discovery priority',
        subtitle='Used when a book has no ISBN (search by title/author).',
        initial=initial_discovery,
        on_save=lambda primary, fallback: set_book_isbn_discovery_providers(primary=primary, fallback=fallback),
    )

    # Metadata fetch priority
    initial_fetch = get_book_metadata_fetch_providers() if can_persist else ['openlibrary', 'google']
    _priority_card(
        title='Book metadata fetch priority',
        subtitle='Used when a book has an ISBN (fetch title/authors/year/publisher).',
        initial=initial_fetch,
        on_save=lambda primary, fallback: set_book_metadata_fetch_providers(primary=primary, fallback=fallback),
    )

    # Provider diagnostics
    with ui.card().props('flat bordered').classes('pv-dialog-card w-full mt-2'):
        ui.label('Provider diagnostics').classes('text-sm font-semibold pv-text-dim')
        with ui.row().classes('w-full items-end gap-2 pt-2'):
            timeout_in = ui.input(
                'Timeout (seconds)',
                value=str(int(get_metadata_provider_timeout_seconds() if can_persist else 6)),
            ).props('outlined dense inputmode=numeric').classes('w-40')

            save_timeout_btn = ui.button('Save timeout', on_click=lambda: _save_timeout()).props('outline dense').classes('pv-meta-action-btn')

        def _save_timeout() -> None:
            try:
                raw = str(timeout_in.value or '').strip()
                timeout_value = int(raw or '6')
                timeout_value = max(2, min(30, timeout_value))
                timeout_in.value = str(timeout_value)
                timeout_in.update()
                set_metadata_provider_timeout_seconds(float(timeout_value))
                ui.notify('Provider timeout saved', color='positive')
            except Exception as ex:
                ui.notify(str(ex), color='negative')

        timeout_in.on('keydown.enter', lambda _e: _save_timeout())
        if not can_persist:
            timeout_in.disable()
            save_timeout_btn.disable()

        diag_state: dict[str, dict[str, str]] = {
            'crossref': {'status': 'Not tested', 'detail': '', 'at': ''},
            'openlibrary': {'status': 'Not tested', 'detail': '', 'at': ''},
            'google': {'status': 'Not tested', 'detail': '', 'at': ''},
        }

        @ui.refreshable
        def _render_diag_status() -> None:
            with ui.column().classes('w-full gap-1 pt-1'):
                for key, label in (
                    ('crossref', 'Crossref (DOI)'),
                    ('openlibrary', 'OpenLibrary (ISBN)'),
                    ('google', 'Google Books (ISBN)'),
                ):
                    item = diag_state[key]
                    ts = f" · {item['at']}" if item['at'] else ''
                    base = f"{label}: {item['status']}{ts}"
                    ui.label(base).classes('text-xs pv-text-dimmer')
                    if item['detail']:
                        ui.label(f"↳ {item['detail']}").classes('text-xs pv-text-dim')

        def _run_crossref() -> None:
            timeout_s = float(timeout_in.value or 6)
            try:
                meta = fetch_crossref_metadata('10.1038/nphys1170', timeout_s=timeout_s)
                diag_state['crossref'] = {
                    'status': 'OK',
                    'detail': f"Title: {(meta.title or '').strip()[:90]}",
                    'at': _now_stamp(),
                }
                ui.notify('Crossref test passed', color='positive')
            except Exception as ex:
                diag_state['crossref'] = {
                    'status': 'FAIL',
                    'detail': _friendly_provider_error(str(ex)),
                    'at': _now_stamp(),
                }
                ui.notify('Crossref test failed', color='negative')
            _render_diag_status.refresh()

        def _run_openlibrary() -> None:
            timeout_s = float(timeout_in.value or 6)
            try:
                meta = fetch_openlibrary_metadata('9780140328721', timeout_s=timeout_s)
                diag_state['openlibrary'] = {
                    'status': 'OK',
                    'detail': f"Title: {(meta.title or '').strip()[:90]}",
                    'at': _now_stamp(),
                }
                ui.notify('OpenLibrary test passed', color='positive')
            except Exception as ex:
                diag_state['openlibrary'] = {
                    'status': 'FAIL',
                    'detail': _friendly_provider_error(str(ex)),
                    'at': _now_stamp(),
                }
                ui.notify('OpenLibrary test failed', color='negative')
            _render_diag_status.refresh()

        def _run_google() -> None:
            timeout_s = float(timeout_in.value or 6)
            try:
                meta = fetch_googlebooks_metadata('9780140328721', timeout_s=timeout_s)
                diag_state['google'] = {
                    'status': 'OK',
                    'detail': f"Title: {(meta.title or '').strip()[:90]}",
                    'at': _now_stamp(),
                }
                ui.notify('Google Books test passed', color='positive')
            except Exception as ex:
                diag_state['google'] = {
                    'status': 'FAIL',
                    'detail': _friendly_provider_error(str(ex)),
                    'at': _now_stamp(),
                }
                ui.notify('Google Books test failed', color='negative')
            _render_diag_status.refresh()

        with ui.row().classes('w-full items-center gap-2 pt-1 flex-wrap'):
            ui.button('Test Crossref', on_click=_run_crossref).props('outline dense').classes('pv-meta-action-btn')
            ui.button('Test OpenLibrary', on_click=_run_openlibrary).props('outline dense').classes('pv-meta-action-btn')
            ui.button('Test Google Books', on_click=_run_google).props('outline dense').classes('pv-meta-action-btn')

        _render_diag_status()
