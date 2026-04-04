"""Sidebar filters panel - completely rebuilt for reliability."""
from __future__ import annotations

import json
from collections.abc import Callable
from nicegui import ui

from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_actions_row
from papervisor.services.user_settings import get_user_setting, set_user_setting


def filters_panel(
    *,
    state: dict[str, str | None],
    user_id: int | None = None,
    libraries: list,
    tags: list[str] | None = None,
    markers: list | None = None,
    facets: dict[str, list[tuple[str, int]]] | None = None,
    view: str,
    on_change: Callable[[], None],
    on_rebuild: Callable[[], None] | None = None,
    header_container: object | None = None,
) -> None:
    """Render the filters sidebar panel."""

    uid: int | None = int(user_id) if user_id is not None else None

    markers = markers or []

    # ─────────────────────────────────────────────────────────────────────────
    # Helper functions
    # ─────────────────────────────────────────────────────────────────────────

    def trigger_change() -> None:
        """Notify parent that filters changed and content should refresh."""
        on_change()

    def trigger_rebuild() -> None:
        """Notify parent that filter panel itself needs rebuild (e.g., facets changed)."""
        if callable(on_rebuild):
            on_rebuild()

    def get_json_list(key: str) -> list[str]:
        """Parse a JSON list from state."""
        raw = str(state.get(key) or '[]').strip()
        try:
            v = json.loads(raw)
            if isinstance(v, list):
                return [str(x) for x in v if str(x).strip()]
        except Exception:
            pass
        return []

    def set_json_list(key: str, value: list[str]) -> None:
        """Store a list as JSON in state."""
        state[key] = json.dumps([str(x) for x in (value or []) if str(x).strip()])

    def get_bool(key: str) -> bool:
        """Get a boolean from state."""
        return str(state.get(key) or '0') == '1'

    def set_bool(key: str, value: bool) -> None:
        """Set a boolean in state."""
        state[key] = '1' if value else '0'

    # ─────────────────────────────────────────────────────────────────────────
    # Clear all filters
    # ─────────────────────────────────────────────────────────────────────────

    def _set_selected_preset_name(name: str) -> None:
        nm = str(name or '').strip()
        state['filters_preset_name'] = nm
        if uid is None:
            return
        try:
            set_user_setting(user_id=uid, key='ui.filter_presets.selected', value=nm)
        except Exception:
            pass

    def _clear_selected_preset() -> None:
        # Deselecting a saved filter also cleans active filter fields.
        _set_selected_preset_name('')
        _apply_preset_data({})

    def clear_all() -> None:
        # Also clear the selected saved-filter indicator.
        _set_selected_preset_name('')
        state['filters_library_id'] = ''
        state['filters_library_ids'] = '[]'
        state['filters_file_type'] = 'all'
        state['filters_sort'] = 'default'
        state['filters_favorites_only'] = '0'
        state['filters_to_read_only'] = '0'
        state['filters_has_doi'] = '0'
        state['filters_has_isbn'] = '0'
        state['filters_completed_only'] = '0'
        state['filters_missing_id'] = '0'
        state['filters_no_tags'] = '0'
        state['filters_no_markers'] = '0'
        state['filters_tag_names'] = '[]'
        state['filters_marker_ids'] = '[]'
        state['filters_authors'] = '[]'
        state['filters_journals'] = '[]'
        state['filters_publishers'] = '[]'
        state['filters_series'] = '[]'
        state['filters_languages'] = '[]'
        state['filters_genres'] = '[]'
        state['filters_year_min'] = ''
        state['filters_year_max'] = ''
        trigger_change()
        trigger_rebuild()

    # Defaults for compact preset storage.
    _FILTER_DEFAULTS: dict[str, str] = {
        'filters_library_id': '',
        'filters_library_ids': '[]',
        'filters_file_type': 'all',
        'filters_sort': 'default',
        'filters_favorites_only': '0',
        'filters_to_read_only': '0',
        'filters_has_doi': '0',
        'filters_has_isbn': '0',
        'filters_completed_only': '0',
        'filters_missing_id': '0',
        'filters_no_tags': '0',
        'filters_no_markers': '0',
        'filters_tag_names': '[]',
        'filters_marker_ids': '[]',
        'filters_authors': '[]',
        'filters_journals': '[]',
        'filters_publishers': '[]',
        'filters_series': '[]',
        'filters_languages': '[]',
        'filters_genres': '[]',
        'filters_year_min': '',
        'filters_year_max': '',
    }

    def _filters_to_preset_data() -> dict[str, str]:
        """Return a compact dict of current filter state (only non-default values)."""
        data: dict[str, str] = {}
        for k, dflt in _FILTER_DEFAULTS.items():
            v = str(state.get(k) if state.get(k) is not None else dflt)
            if v != dflt:
                data[k] = v
        return data

    def _apply_preset_data(data: dict[str, object]) -> None:
        # Reset to defaults then apply preset.
        for k, dflt in _FILTER_DEFAULTS.items():
            state[k] = dflt

        for k, v in (data or {}).items():
            if k in _FILTER_DEFAULTS:
                state[k] = str(v)

        trigger_change()
        trigger_rebuild()

    def _load_presets() -> list[dict[str, object]]:
        if uid is None:
            return []
        try:
            raw = str(get_user_setting(user_id=uid, key='ui.filter_presets', default='[]') or '[]')
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                out: list[dict[str, object]] = []
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get('name') or '').strip()
                    data = item.get('data')
                    if not name or not isinstance(data, dict):
                        continue
                    out.append({'name': name, 'data': dict(data)})
                return out
        except Exception:
            return []
        return []

    def _save_presets(presets: list[dict[str, object]]) -> bool:
        if uid is None:
            return False
        try:
            encoded = json.dumps(presets, ensure_ascii=False)
        except Exception:
            return False

        # user_settings value is capped at 2048 chars; keep a little headroom.
        if len(encoded) > 2000:
            return False
        try:
            set_user_setting(user_id=uid, key='ui.filter_presets', value=encoded)
            return True
        except Exception:
            return False

    # Restore last selected preset name (does not auto-apply).
    if user_id and not str(state.get('filters_preset_name') or '').strip():
        try:
            if uid is None:
                selected = ''
            else:
                selected = str(get_user_setting(user_id=uid, key='ui.filter_presets.selected', default='') or '').strip()
            if selected:
                state['filters_preset_name'] = selected
        except Exception:
            pass

    def _open_save_dialog() -> None:
        if uid is None:
            ui.notify('Sign in to save filters', color='warning')
            return

        current_name = str(state.get('filters_preset_name') or '').strip()

        d = ui.dialog()
        with d, dialog_card(max_width_class='max-w-xl'):
            ui.label('Save filter').classes('text-base font-semibold')
            name_in = ui.input('Name', value=current_name).props('outlined dense').classes('w-full')

            def _do_save() -> None:
                name = str(name_in.value or '').strip()
                if not name:
                    ui.notify('Name is required', color='warning')
                    return
                if len(name) > 64:
                    name = name[:64]

                data = _filters_to_preset_data()
                new_item = {'name': name, 'data': data}

                existing = _load_presets()
                rewriting = any(str(p.get('name') or '').strip() == name for p in existing)
                existing = [p for p in existing if str(p.get('name') or '').strip() != name]
                existing.insert(0, new_item)
                existing = existing[:20]

                if not _save_presets(existing):
                    ui.notify('Could not save (preset too large). Try fewer selections.', color='negative')
                    return

                state['filters_preset_name'] = name
                _set_selected_preset_name(name)

                ui.notify('Filter updated' if rewriting else 'Filter saved', color='positive')
                d.close()
                trigger_rebuild()

            with dialog_actions_row():
                ui.button('Cancel', on_click=d.close).props('flat color=negative')
                ui.button('Save', on_click=_do_save).props('color=primary')

        d.open()

    def _open_delete_dialog(*, preset_name: str) -> None:
        if uid is None:
            return

        uid2: int = uid
        name = str(preset_name or '').strip()
        if not name:
            ui.notify('No saved filter selected', color='warning')
            return

        d = ui.dialog()
        with d, dialog_card(max_width_class='max-w-xl'):
            ui.label('Delete saved filter?').classes('text-base font-semibold')
            ui.separator().classes('opacity-20 my-2')
            ui.label(name).classes('text-sm pv-text-dimmer')

            def _do_delete() -> None:
                existing = _load_presets()
                remaining = [p for p in existing if str(p.get('name') or '').strip() != name]
                if not _save_presets(remaining):
                    ui.notify('Could not delete filter', color='negative')
                    return

                if str(state.get('filters_preset_name') or '').strip() == name:
                    state['filters_preset_name'] = ''
                    try:
                        set_user_setting(user_id=uid2, key='ui.filter_presets.selected', value='')
                    except Exception:
                        pass

                ui.notify('Filter deleted', color='positive')
                d.close()
                trigger_rebuild()

            with dialog_actions_row():
                ui.button('Cancel', on_click=d.close).props('flat color=negative')
                ui.button('Delete', on_click=_do_delete).props('color=negative')

        d.open()

    # ─────────────────────────────────────────────────────────────────────────
    # UI Layout
    # ─────────────────────────────────────────────────────────────────────────

    # Saved filters (per-user). Always show the controls; disable actions if not available.
    presets = _load_presets() if uid is not None else []

    def _render_presets_menu(*, compact: bool = False) -> None:
        def _apply_preset_by_name(name: str) -> None:
            nm = str(name or '').strip()
            if not nm:
                return
            for p in presets:
                if str(p.get('name') or '').strip() == nm:
                    state['filters_preset_name'] = nm
                    _set_selected_preset_name(nm)
                    data_obj = p.get('data')
                    if isinstance(data_obj, dict):
                        normalized = {str(k): v for k, v in data_obj.items()}
                    else:
                        normalized = {}
                    _apply_preset_data(normalized)
                    return

        cur_preset = str(state.get('filters_preset_name') or '').strip()
        if cur_preset and cur_preset not in {str(p.get('name') or '').strip() for p in presets}:
            cur_preset = ''

        row_classes = 'items-center gap-0.5 min-w-0'
        if not compact:
            row_classes += ' w-full'

        with ui.row().classes(row_classes):
            if compact:
                if cur_preset:
                    ui.label(cur_preset).classes('text-xs pv-text-dimmer truncate max-w-[120px]')
                else:
                    ui.label('Select filter').classes('text-xs pv-text-dimmer')
            else:
                if cur_preset:
                    ui.label(cur_preset).classes('text-xs pv-text-dimmer flex-1 truncate')
                else:
                    ui.element('div').classes('flex-1')

            with ui.button(icon='close', on_click=_clear_selected_preset).props('dense flat round size=sm color=primary') as _inline_delete_btn:
                _inline_delete_btn.tooltip('Deselect filter')
                if not cur_preset:
                    _inline_delete_btn.props('disable')

            with ui.button(icon='more_vert').props('dense flat round size=sm color=primary').classes('pv-filters-menu-btn') as _preset_menu_btn:
                _preset_menu_btn.tooltip('Saved filters')
                with ui.menu().classes('min-w-[145px]'):
                    if uid is None:
                        ui.menu_item('Sign in to use saved filters').props('disable dense').classes('text-xs py-1')
                    else:
                        ui.menu_item('Save current filter', on_click=_open_save_dialog).props('dense').classes('text-xs py-1')
                        ui.separator().classes('my-1')

                        if presets:
                            for p in presets:
                                nm = str(p.get('name') or '').strip()
                                if not nm:
                                    continue

                                def make_select_handler(preset_name: str):
                                    def handler():
                                        _apply_preset_by_name(preset_name)
                                        ui.notify(f'Applied: {preset_name}', color='positive')
                                    return handler

                                def make_delete_handler(preset_name: str):
                                    def handler():
                                        _open_delete_dialog(preset_name=preset_name)
                                    return handler

                                with ui.row().classes('pv-menu-row'):
                                    with ui.element('div').classes('flex-1 min-w-0').on('click', make_select_handler(nm)):
                                        ui.label(nm).classes('text-xs truncate')
                                    if nm == cur_preset:
                                        ui.icon('check').classes('text-primary text-xs shrink-0')
                                    ui.button(icon='delete', on_click=make_delete_handler(nm)).props('flat dense round size=xs color=negative').classes('shrink-0')
                        else:
                            ui.menu_item('No saved filters yet').props('disable dense').classes('text-xs py-1')

    # Header row: saved preset picker (drawer title is handled outside)
    if header_container is None:
        with ui.row().classes('w-full px-4 pt-4 pb-2 items-center justify-between gap-2'):
            _render_presets_menu(compact=False)
    else:
        with header_container:
            _render_presets_menu(compact=True)

    with ui.column().classes('w-full gap-3 px-4 py-3'):

        # ─────────────────────────────────────────────────────────────────────
        # SORT / ORDER
        # (Shown in most views; excluded from Dashboard/Recently added)
        # ─────────────────────────────────────────────────────────────────────

        if str(view or '') not in {'dashboard', 'recent'}:
            sort_options = {
                'default': 'Default',
                'recent': 'Recently added',
                'title_asc': 'Title (A → Z)',
                'title_desc': 'Title (Z → A)',
                'author_asc': 'Author (A → Z)',
                'year_desc': 'Year (newest)',
                'year_asc': 'Year (oldest)',
                'last_opened': 'Last opened',
                'last_read': 'Last read',
            }

            cur_sort = str(state.get('filters_sort') or 'default').strip().lower()
            if cur_sort not in set(sort_options.keys()):
                cur_sort = 'default'

            def on_sort_change(e) -> None:
                val = getattr(e, 'value', None)
                if val is None:
                    args = getattr(e, 'args', None)
                    if isinstance(args, dict):
                        val = args.get('value', None)
                v = str(val or 'default').strip().lower()
                if v not in set(sort_options.keys()):
                    v = 'default'
                state['filters_sort'] = v
                trigger_change()

            ui.select(
                sort_options,
                label='Order by',
                value=cur_sort,
                on_change=on_sort_change,
            ).props('outlined dense').classes('w-full')

        # ─────────────────────────────────────────────────────────────────────
        # TYPE FILTER (Paper / Book / All) - Using button group
        # ─────────────────────────────────────────────────────────────────────

        cur_type = str(state.get('filters_file_type') or 'all').strip().lower()
        if cur_type not in {'all', 'paper', 'book'}:
            cur_type = 'all'

        with ui.button_group().classes('w-full'):
            def make_type_handler(t: str):
                def handler():
                    state['filters_file_type'] = t

                    # Prevent hidden facet selections from staying active when switching types.
                    if t == 'paper':
                        state['filters_series'] = '[]'
                        state['filters_languages'] = '[]'
                        state['filters_genres'] = '[]'
                    elif t == 'book':
                        state['filters_journals'] = '[]'

                    trigger_change()
                    trigger_rebuild()
                return handler

            btn_all = ui.button('ALL', on_click=make_type_handler('all')).classes('flex-1')
            btn_paper = ui.button('PAPERS', on_click=make_type_handler('paper')).classes('flex-1')
            btn_book = ui.button('BOOKS', on_click=make_type_handler('book')).classes('flex-1')

            if cur_type == 'all':
                btn_all.props('color=primary')
                btn_paper.props('flat')
                btn_book.props('flat')
            elif cur_type == 'paper':
                btn_all.props('flat')
                btn_paper.props('color=primary')
                btn_book.props('flat')
            elif cur_type == 'book':
                btn_all.props('flat')
                btn_paper.props('flat')
                btn_book.props('color=primary')

        # ─────────────────────────────────────────────────────────────────────
        # STATUS FILTERS - Multi-select dropdown to save space
        # ─────────────────────────────────────────────────────────────────────

        status_options = {
            'favorites': 'Favorites',
            'to_read': 'To Read',
            'completed': 'Completed',
            'has_id': 'Contains ID',
            'missing_id': 'Missing ID',
        }

        # Build current value from state
        status_value: list[str] = []
        if get_bool('filters_favorites_only'):
            status_value.append('favorites')
        if get_bool('filters_to_read_only'):
            status_value.append('to_read')
        if get_bool('filters_completed_only'):
            status_value.append('completed')
        if get_bool('filters_has_doi') or get_bool('filters_has_isbn'):
            status_value.append('has_id')
        if get_bool('filters_missing_id'):
            status_value.append('missing_id')

        def on_status_change(e):
            val = e.value if hasattr(e, 'value') else []
            if isinstance(val, str):
                val = [val] if val else []
            selected = set(val)
            # "Contains ID" and "Missing ID" are mutually exclusive.
            if 'has_id' in selected and 'missing_id' in selected:
                # Last selection wins: keep the one that changed.
                prev_has = get_bool('filters_has_doi') or get_bool('filters_has_isbn')
                prev_missing = get_bool('filters_missing_id')
                if prev_has and not prev_missing:
                    # User just added missing_id → drop has_id.
                    selected.discard('has_id')
                else:
                    # User just added has_id → drop missing_id.
                    selected.discard('missing_id')
            set_bool('filters_favorites_only', 'favorites' in selected)
            set_bool('filters_to_read_only', 'to_read' in selected)
            set_bool('filters_completed_only', 'completed' in selected)
            # "Contains ID" means has DOI OR has ISBN
            set_bool('filters_has_doi', 'has_id' in selected)
            set_bool('filters_has_isbn', 'has_id' in selected)
            set_bool('filters_missing_id', 'missing_id' in selected)
            trigger_change()
            trigger_rebuild()

        ui.select(
            status_options,
            label='Filter by status',
            value=status_value,
            multiple=True,
            on_change=on_status_change,
        ).props('outlined dense use-chips').classes('w-full')

        # ─────────────────────────────────────────────────────────────────────
        # LIBRARY FILTER (hide in library view since already filtered)
        # ─────────────────────────────────────────────────────────────────────

        if str(view or '') not in {'library', 'dashboard'}:
            lib_options: dict[str, str] = {}
            try:
                for lib in libraries:
                    lid = str(getattr(lib, 'id', '') or '').strip()
                    name = str(getattr(lib, 'name', '') or lid).strip()
                    if lid:
                        lib_options[lid] = name
            except Exception:
                lib_options = {}

            if lib_options:
                def on_libs_change(e):
                    val = e.value if hasattr(e, 'value') else []
                    if isinstance(val, str):
                        val = [val] if val else []
                    set_json_list('filters_library_ids', val)
                    trigger_change()
                    trigger_rebuild()

                ui.select(
                    lib_options,
                    label='Select libraries',
                    value=get_json_list('filters_library_ids'),
                    multiple=True,
                    on_change=on_libs_change,
                ).props('outlined dense use-chips').classes('w-full')

        # ─────────────────────────────────────────────────────────────────────
        # MARKERS FILTER (hide only in marker view since already filtered)
        # ─────────────────────────────────────────────────────────────────────

        v = str(view or '').strip().lower()

        def on_no_markers_change(e) -> None:
            val = bool(getattr(e, 'value', False))
            set_bool('filters_no_markers', val)
            if val:
                set_json_list('filters_marker_ids', [])
            trigger_change()

        if v != 'marker':
            marker_options: dict[str, str] = {}
            try:
                for s in markers or []:
                    sid = str(getattr(s, 'id', '') or '').strip()
                    name = str(getattr(s, 'name', '') or sid).strip()
                    if sid:
                        marker_options[sid] = name
            except Exception:
                marker_options = {}

            if marker_options:
                def on_markers_change(e):
                    val = e.value if hasattr(e, 'value') else []
                    if isinstance(val, str):
                        val = [val] if val else []
                    set_json_list('filters_marker_ids', val)
                    if val:
                        set_bool('filters_no_markers', False)
                    # marker_ids is the canonical persisted filter
                    trigger_change()

                ui.select(
                    marker_options,
                    label='Select markers',
                    value=get_json_list('filters_marker_ids'),
                    multiple=True,
                    on_change=on_markers_change,
                ).props('outlined dense use-chips').classes('w-full')

        # ─────────────────────────────────────────────────────────────────────
        # TAGS FILTER
        # ─────────────────────────────────────────────────────────────────────

        tag_options = [str(t).strip() for t in (tags or []) if str(t).strip()]
        if tag_options:
            def on_tags_change(e):
                val = e.value if hasattr(e, 'value') else []
                if isinstance(val, str):
                    val = [val] if val else []
                set_json_list('filters_tag_names', val)
                if val:
                    set_bool('filters_no_tags', False)
                trigger_change()

            ui.select(
                tag_options,
                label='Select tags',
                value=get_json_list('filters_tag_names'),
                multiple=True,
                on_change=on_tags_change,
            ).props('outlined dense use-chips').classes('w-full')

        def on_no_tags_change(e) -> None:
            val = bool(getattr(e, 'value', False))
            set_bool('filters_no_tags', val)
            if val:
                set_json_list('filters_tag_names', [])
            trigger_change()

        if v != 'marker':
            with ui.row().classes('w-full gap-2 items-center no-wrap'):
                ui.checkbox(
                    'No marker',
                    value=get_bool('filters_no_markers'),
                    on_change=on_no_markers_change,
                ).props('dense').classes('flex-1 min-w-0')

                ui.checkbox(
                    'No tags',
                    value=get_bool('filters_no_tags'),
                    on_change=on_no_tags_change,
                ).props('dense').classes('flex-1 min-w-0')
        else:
            ui.checkbox(
                'No tags',
                value=get_bool('filters_no_tags'),
                on_change=on_no_tags_change,
            ).props('dense').classes('w-full')

        # ─────────────────────────────────────────────────────────────────────
        # FACET FILTERS (Author, Publisher, etc.)
        # ─────────────────────────────────────────────────────────────────────

        fx = facets or {}
        ft = str(state.get('filters_file_type') or 'all').strip().lower()

        def facet_section(title: str, key: str, items: list[tuple[str, int]] | None) -> None:
            values = [(str(v).strip(), int(c or 0)) for (v, c) in (items or []) if str(v).strip()]
            if not values:
                return

            selected = set(get_json_list(key))

            with ui.expansion(title).props('dense').classes('w-full'):
                with ui.column().classes('w-full gap-1'):
                    for value, count in values:

                        def make_facet_handler(k: str, v: str):
                            def handler(e):
                                cur = set(get_json_list(k))
                                checked = e.value if hasattr(e, 'value') else bool(e.args)
                                if checked:
                                    cur.add(v)
                                else:
                                    cur.discard(v)
                                set_json_list(k, sorted(cur, key=lambda s: s.lower()))
                                trigger_change()
                            return handler

                        with ui.row().classes('w-full items-center justify-between gap-2'):
                            ui.checkbox(
                                '',
                                value=(value in selected),
                                on_change=make_facet_handler(key, value),
                            ).props('dense').classes('shrink-0')
                            ui.label(value).classes('text-sm flex-1 overflow-hidden text-ellipsis whitespace-nowrap').tooltip(value)
                            ui.label(str(count)).classes('text-xs pv-text-dimmer shrink-0')

        # Facets are contextual by file type:
        # - Paper: Author, Journal, Publisher
        # - Book: Author, Publisher, Series, Language, Genres
        # - All: show everything available

        facet_section('Author', 'filters_authors', fx.get('authors'))
        facet_section('Publisher', 'filters_publishers', fx.get('publisher'))

        if ft in {'all', 'paper'}:
            facet_section('Journal', 'filters_journals', fx.get('journal'))

        if ft in {'all', 'book'}:
            facet_section('Series', 'filters_series', fx.get('series'))
            facet_section('Language', 'filters_languages', fx.get('language'))
            facet_section('Genres', 'filters_genres', fx.get('genres'))

        # ─────────────────────────────────────────────────────────────────────
        # YEAR RANGE - Same row, clean styling without spinners
        # ─────────────────────────────────────────────────────────────────────

        with ui.row().classes('w-full gap-2 items-center'):
            def on_year_min_change(e):
                val = str(e.value if hasattr(e, 'value') else '').strip()
                # Only accept numeric values (or empty to clear).
                if val and not val.isdigit():
                    return
                state['filters_year_min'] = val
                trigger_change()

            def on_year_max_change(e):
                val = str(e.value if hasattr(e, 'value') else '').strip()
                # Only accept numeric values (or empty to clear).
                if val and not val.isdigit():
                    return
                state['filters_year_max'] = val
                trigger_change()

            ui.input(
                'Year from',
                value=str(state.get('filters_year_min') or ''),
                on_change=on_year_min_change,
            ).props('outlined dense hide-bottom-space').classes('flex-1')

            ui.label('–').classes('pv-text-dimmer')

            ui.input(
                'Year to',
                value=str(state.get('filters_year_max') or ''),
                on_change=on_year_max_change,
            ).props('outlined dense hide-bottom-space').classes('flex-1')

        # ─────────────────────────────────────────────────────────────────────
        # ACTION BUTTONS
        # ─────────────────────────────────────────────────────────────────────

        with ui.row().classes('w-full gap-2 pt-2'):
            if uid is not None:
                ui.button('Save', on_click=_open_save_dialog).props('outline color=primary no-caps').classes('flex-1')
            ui.button('Clear', on_click=clear_all).props('outline color=negative no-caps').classes('flex-1')
