from __future__ import annotations

import json
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from nicegui import ui


@lru_cache(maxsize=1)
def _load_all_material_symbols() -> list[str]:
    """Lazy-load the full Material Symbols list from a JSON data file."""
    json_path = Path(__file__).parent / 'material_icons.json'
    with open(json_path, encoding='utf-8') as f:
        return json.load(f)


# A curated set of Material icon names (Quasar / NiceGUI) to keep UX simple but flexible.
# Extend this list whenever we need more categories.
ICON_OPTIONS: list[str] = [
    'menu_book',
    'library_books',
    'description',
    'inbox',
    'auto_awesome',
    'folder',
    'folder_open',
    'folder_special',
    'folder_shared',
    'folder_zip',
    'science',
    'auto_stories',
    'book',
    'bookmark',
    'bookmark_border',
    'bookmark_add',
    'favorite',
    'favorite_border',
    'star',
    'star_border',
    'local_library',
    'school',
    'article',
    'feed',
    'topic',
    'newspaper',
    'collections_bookmark',
    'checklist',
    'checklist_rtl',
    'inventory_2',
    'archive',
    'category',
    'sell',
    'tag',
    'label',
    'label_outline',
    'local_offer',
    'style',
    'dashboard',
    'view_module',
    'view_list',
    'grid_view',
    'widgets',
    'lists',
    'upload_file',
    'cloud_upload',
    'download',
    'download_for_offline',
    'upload',
    'search',
    'manage_search',
    'tune',
    'filter_list',
    'sort',
    'settings',
    'settings_applications',
    'build',
    'edit',
    'edit_note',
    'delete',
    'delete_forever',
    'add',
    'add_circle',
    'remove',
    'remove_circle',
    'close',
    'check',
    'check_circle',
    'done_all',
    'info',
    'help',
    'warning',
    'schedule',
    'event',
    'collections',
    'image',
    'picture_as_pdf',
    'text_snippet',
    'format_quote',
    'movie',
    'local_movies',
    'video_library',
    'tv',
    'live_tv',
    'play_circle',
    'pause_circle',
    'headphones',
    'music_note',
    'timeline',
    'bar_chart',
    'insights',
    'analytics',
    'bolt',
    'psychology',
    'history',
    'update',
    'refresh',
    'sync',
    'cloud',
    'cloud_done',
    'cloud_off',
    'wifi',
    'wifi_off',
    'lock',
    'lock_open',
    'security',
    'admin_panel_settings',
    'person',
    'group',
    'share',
    'link',
    'open_in_new',
    'launch',
    'arrow_back',
    'arrow_forward',
    'arrow_upward',
    'arrow_downward',
    'chevron_left',
    'chevron_right',
]


_ICON_OPTION_LABELS: dict[str, str] = {name: name.replace('_', ' ').title() for name in ICON_OPTIONS}


def _normalize_icon_token(raw: str) -> str:
    return str(raw or '').strip().lower().replace(' ', '_')


def _split_quasar_icon_name(value: str) -> tuple[str | None, str]:
    """Return (mode, base_name) from a quasar icon string.

    Examples:
      - "menu_book" -> (None, "menu_book")
      - "sym_o_menu_book" -> ("sym_o", "menu_book")
    """

    v = _normalize_icon_token(value)
    for mode in ('sym_o', 'sym_r', 'sym_s'):
        prefix = f'{mode}_'
        if v.startswith(prefix):
            return mode, v[len(prefix) :]
    return None, v


def _apply_mode(*, mode: str, name: str) -> str:
    base = _normalize_icon_token(name)
    if not base:
        return ''
    if mode == 'legacy':
        return base
    return f'{mode}_{base}'


def icon_picker(
    *,
    label: str = 'Icon',
    value: str = 'menu_book',
    compact: bool = False,
    dropdown: bool = False,
) -> tuple[ui.element, ui.icon]:
    """Create a searchable icon picker.

    Returns (select, preview_icon).
    """

    # State holder for the selected icon.
    # This must accept arbitrary values (full Material Symbols catalog), so we avoid ui.select
    # which would otherwise coerce unknown values back to None.
    select = ui.input(label, value=value).classes('hidden')

    # Hidden bound preview element returned to callers for compatibility.
    preview = ui.icon(value).classes('hidden')
    preview.bind_name_from(select, 'value')

    # Always use Material Symbols Outlined (matches theme.py global icon rendering)
    icon_set_mode = 'sym_o'

    # Show current selection inline (preview + name)
    if not compact and not dropdown:
        with ui.row().classes('w-full items-center gap-3'):
            shown_preview = ui.icon(value).classes('text-xl')
            shown_preview.bind_name_from(select, 'value')
            current = ui.label('').classes('text-xs pv-text-dimmer')
            current.bind_text_from(select, 'value', lambda v: f'Selected: {str(v or "").strip() or "(none)"}')

    if dropdown:
        with ui.button(color='primary').props('outline dense').classes('pv-icon-trigger-btn'):
            with ui.row().classes('items-center gap-1 no-wrap'):
                shown_preview = ui.icon(value).classes('text-lg')
                shown_preview.bind_name_from(select, 'value')
            with ui.menu().classes('pv-menu pv-no-shadow').props('fit'):
                with ui.card().props('flat bordered').classes('pv-solid no-shadow w-[360px] max-w-[90vw] p-2'):
                    ui.label('Material Symbols').classes('text-xs pv-text-dimmer')
                    search = ui.input('Search / name').props('outlined dense clearable placeholder="Type to search or enter an icon name"').classes('w-full')

                    def _typed_icon_value() -> str:
                        token = _normalize_icon_token(str(search.value or ''))
                        if not token:
                            return ''
                        existing, base = _split_quasar_icon_name(token)
                        if existing is not None:
                            return f'{existing}_{base}'
                        return _apply_mode(mode=icon_set_mode, name=token)

                    def _apply_icon_name(raw_name: str) -> None:
                        token = _normalize_icon_token(raw_name)
                        if not token:
                            return
                        existing, base = _split_quasar_icon_name(token)
                        if existing is not None:
                            select.value = f'{existing}_{base}'
                            return
                        select.value = _apply_mode(mode=icon_set_mode, name=base)

                    @ui.refreshable
                    def grid() -> None:
                        query = str(search.value or '').strip().lower().replace(' ', '_')

                        if bool(query):
                            filtered = [name for name in _load_all_material_symbols() if query in name]
                            filtered = filtered[:100]

                            count_text = f'Matching icons ({len(filtered)}'
                            if len(filtered) == 100:
                                count_text += ', more available)'
                            else:
                                count_text += ')'
                            ui.label(count_text).classes('text-xs pv-text-dimmer')
                        else:
                            filtered = ICON_OPTIONS

                        with ui.element('div').classes('pv-icon-grid'):
                            with ui.row().classes('gap-2 flex-wrap'):
                                for name in filtered:
                                    icon_name = _apply_mode(mode=icon_set_mode, name=name)
                                    classes = 'pv-icon-btn'
                                    if str(select.value or '') == icon_name:
                                        classes += ' pv-icon-btn--active'
                                    btn = ui.button(icon=icon_name, on_click=lambda _e, n=name: _apply_icon_name(n)).props(
                                        'flat round dense'
                                    ).classes(classes)
                                    btn.tooltip(_ICON_OPTION_LABELS.get(name, name))

                    search_pending = False
                    search_last_change = 0.0

                    def _schedule_search_refresh() -> None:
                        nonlocal search_pending, search_last_change
                        search_pending = True
                        search_last_change = time.monotonic()

                    def _poll_search_refresh() -> None:
                        nonlocal search_pending, search_last_change
                        if not search_pending:
                            return
                        if (time.monotonic() - float(search_last_change)) < 0.20:
                            return
                        search_pending = False
                        grid.refresh()

                    ui.timer(0.10, _poll_search_refresh)

                    search.on('update:model-value', lambda _e: _schedule_search_refresh())
                    search.on('keydown.enter', lambda _e: _apply_icon_name(str(search.value or '')))
                    grid()

        return select, preview

    # Search input starts empty to show curated list by default
    # (the current selection is already visible in the preview above)
    search = ui.input('Search / name').props('outlined dense clearable placeholder="Type to search or enter an icon name"').classes('w-full')

    def _typed_icon_value() -> str:
        """Return the icon token for the current typed name (may be empty)."""
        token = _normalize_icon_token(str(search.value or ''))
        if not token:
            return ''
        existing, base = _split_quasar_icon_name(token)
        if existing is not None:
            return f'{existing}_{base}'
        return _apply_mode(mode=icon_set_mode, name=token)

    def _apply_icon_name(raw_name: str) -> None:
        token = _normalize_icon_token(raw_name)
        if not token:
            return
        existing, base = _split_quasar_icon_name(token)
        if existing is not None:
            select.value = f'{existing}_{base}'
            return
        select.value = _apply_mode(mode=icon_set_mode, name=base)

    @ui.refreshable
    def grid() -> None:
        query = str(search.value or '').strip().lower().replace(' ', '_')

        # When searching, use the full Material Symbols set; otherwise show curated icons
        if bool(query):
            # Filter from ALL Material Symbols (4000+ icons)
            filtered = [name for name in _load_all_material_symbols() if query in name]
            # Limit to first 100 matches to keep UI responsive
            filtered = filtered[:100]
            
            count_text = f'Matching icons ({len(filtered)}'
            if len(filtered) == 100:
                count_text += ', more available)'
            else:
                count_text += ')'
            ui.label(count_text).classes('text-xs pv-text-dimmer')
        else:
            # No search query: show curated list
            filtered = ICON_OPTIONS

        with ui.element('div').classes('pv-icon-grid'):
            with ui.row().classes('gap-2 flex-wrap'):
                for name in filtered:
                    icon_name = _apply_mode(mode=icon_set_mode, name=name)
                    classes = 'pv-icon-btn'
                    if str(select.value or '') == icon_name:
                        classes += ' pv-icon-btn--active'
                    btn = ui.button(icon=icon_name, on_click=lambda _e, n=name: _apply_icon_name(n)).props(
                        'flat round dense'
                    ).classes(classes)
                    btn.tooltip(_ICON_OPTION_LABELS.get(name, name))

    # Debounce search updates to keep typing responsive.
    search_pending = False
    search_last_change = 0.0

    def _schedule_search_refresh() -> None:
        nonlocal search_pending, search_last_change
        search_pending = True
        search_last_change = time.monotonic()

    def _poll_search_refresh() -> None:
        nonlocal search_pending, search_last_change
        if not search_pending:
            return
        if (time.monotonic() - float(search_last_change)) < 0.20:
            return
        search_pending = False
        grid.refresh()

    ui.timer(0.10, _poll_search_refresh)

    # Use update:model-value for reliable reactive behavior.
    search.on('update:model-value', lambda _e: _schedule_search_refresh())
    search.on('keydown.enter', lambda _e: _apply_icon_name(str(search.value or '')))

    grid()
    return select, preview


def compact_icon_name_row(
    *,
    icon_value: str,
    name_label: str = 'Name',
    name_value: str | None = None,
    row_classes: str = 'w-full items-stretch gap-2 flex-wrap',
    name_classes: str = 'flex-1 min-w-[220px]',
    extra_builder: Callable[[], None] | None = None,
) -> tuple[ui.element, ui.icon, ui.input]:
    """Render a compact row with icon dropdown trigger and name input.

    Returns (icon_select, icon_preview, name_input).
    """

    with ui.row().classes(row_classes):
        icon_select, icon_preview = icon_picker(value=icon_value, compact=True, dropdown=True)
        if name_value is None:
            name_input = ui.input(name_label)
        else:
            name_input = ui.input(name_label, value=name_value)
        name_input.props('outlined dense clearable').classes(name_classes)
        if extra_builder is not None:
            extra_builder()
    return icon_select, icon_preview, name_input
