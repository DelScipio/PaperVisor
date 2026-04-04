from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from nicegui import ui
from nicegui import app

from papervisor.domain import PaperItem
from papervisor.services.papers import get_paper
from papervisor.services.papers import list_papers_filtered
from papervisor.services.papers import list_paper_filter_facets
from papervisor.services.libraries import list_libraries_for_user
from papervisor.services.markers import list_markers
from papervisor.services.tags import list_tags
from papervisor.ui.components.left_nav import left_nav
from papervisor.ui.components.filters_panel import filters_panel
from papervisor.ui.components.page_scaffold import page_scaffold
from papervisor.ui.dialogs.library_dialogs import LibraryDialogs
from papervisor.ui.dialogs.share_dialogs import ShareDialogs
from papervisor.ui.dialogs.marker_dialogs import MarkerDialogs
from papervisor.ui.dialogs.import_dialog import UploadDialog
from papervisor.ui.dialogs.metadata_dialog import MetadataDialog
from papervisor.services.user_settings import get_user_setting, set_user_setting
from papervisor.services.papers import (
    get_dashboard_counts,
    toggle_favorite,
)
from papervisor.ui.pages.shared_state import (
    apply_nav_collapsed_flags_attr,
    close_filters_drawer_and_persist,
    get_filters_drawer_open,
    load_nav_collapsed_flags,
    make_nav_toggle_handlers_attr,
    pop_nav_intent,
    persist_last_navigation_state,
    resolve_remember_location_mode,
    require_authenticated_user,
    toggle_filters_drawer_and_persist,
)
from papervisor.ui.state import PageState
from papervisor.ui.events import Event, emit, on, clear as clear_events

# Import extracted views
from papervisor.ui.pages.index_views.dashboard import render_dashboard_view
from papervisor.ui.pages.index_views.wall import (
    render_wall_section,
    render_query_views,
    render_category_views,
    render_marker_view,
    _paged_filtered,
)

logger = logging.getLogger(__name__)


def _format_meta_line(label: str, value: str | None) -> str:
    v = (value or '').strip()
    return f'{label}: {v}' if v else f'{label}: —'


@ui.page('/')
def index() -> None:
    if not require_authenticated_user():
        return

    def _refresh_left_nav() -> None:
        if 'render_left_nav' in refreshables:
            refreshables['render_left_nav'].refresh()

    def _refresh_all() -> None:
        _refresh_left_nav()
        if 'render_content' in refreshables:
            refreshables['render_content'].refresh()

    user_id = int(app.storage.user.get('user_id') or 0)
    
    # Clean up event subscriptions
    clear_events()

    def _subscribe_refresh(events: tuple[Event, ...], refresh_fn) -> None:
        def _handler(**_kw):
            refresh_fn()

        for event in events:
            on(event, _handler)

    _subscribe_refresh(
        (
            Event.LIBRARY_CREATED,
            Event.LIBRARY_UPDATED,
            Event.LIBRARY_DELETED,
            Event.SHARE_CREATED,
            Event.SHARE_REMOVED,
            Event.PAPER_UPDATED,
            Event.PAPER_DELETED,
            Event.PAPER_RESTORED,
            Event.PAPER_MOVED,
            Event.TAG_CHANGED,
        ),
        _refresh_all,
    )
    _subscribe_refresh(
        (Event.PAPER_IMPORTED, Event.MARKER_CREATED, Event.MARKER_UPDATED, Event.MARKER_DELETED),
        _refresh_left_nav,
    )

    def _on_library_changed() -> None:
        emit(Event.LIBRARY_UPDATED)

    def _on_share_changed() -> None:
        emit(Event.SHARE_CREATED)

    def _on_marker_changed() -> None:
        emit(Event.MARKER_UPDATED)

    def _on_upload_changed() -> None:
        emit(Event.PAPER_IMPORTED)

    def _on_meta_changed() -> None:
        emit(Event.PAPER_UPDATED)

    dialogs = LibraryDialogs(user_id=user_id, on_changed=_on_library_changed)
    share_dialogs = ShareDialogs(user_id=user_id, on_changed=_on_share_changed)
    marker_dialogs = MarkerDialogs(on_changed=_on_marker_changed, user_id=user_id)
    upload_dialog = UploadDialog(user_id=user_id, on_changed=_on_upload_changed)

    def _open_profile() -> None:
        ui.navigate.to('/profile')

    metadata_dialog = MetadataDialog(on_changed=_on_meta_changed, user_id=user_id)

    state = PageState()

    def _get_list_limit() -> int:
        return state.get_limit()

    def _bool(key: str) -> bool:
        return bool(getattr(state, key, False))

    def _effective_library_ids(*, view: str) -> list[str] | None:
        return state.effective_library_ids()

    def _effective_filters() -> PaperFilters:
        return state.effective_filters()

    def _normalize_search_mode(mode: object) -> str:
        raw = str(mode or '').strip().lower()
        aliases = {
            'all': 'all',
            'any': 'all',
            'title': 'title',
            'titles': 'title',
            'author': 'authors',
            'authors': 'authors',
            'publisher': 'publisher',
            'publishers': 'publisher',
            'journal': 'journal',
            'journals': 'journal',
            'tag': 'tags',
            'tags': 'tags',
            'doi': 'doi',
            'isbn': 'isbn',
        }
        return aliases.get(raw, 'all')

    def _apply_handoff_intent(intent_payload: dict[str, object]) -> None:
        view = str(intent_payload.get('view') or '').strip()
        library_id = intent_payload.get('library_id')
        marker_id = intent_payload.get('marker_id')
        query = str(intent_payload.get('query') or '')
        mode = str(intent_payload.get('mode') or 'all')

        if view == 'search':
            state.search_query = query
            state.search_mode = _normalize_search_mode(mode)
            state.view = 'search' if query.strip() else 'all'
            return

        if view in {'dashboard', 'all', 'favorites', 'to_read'}:
            state.view = view
            state.library_id = None
            state.marker_id = None
            return

        if view == 'library':
            state.view = 'library'
            state.library_id = library_id
            state.marker_id = None
            return

        if view == 'marker':
            state.view = 'marker'
            state.library_id = None
            state.marker_id = marker_id

    intent = pop_nav_intent()
    has_handoff_intent = intent is not None
    if has_handoff_intent:
        _apply_handoff_intent(intent)

    def _restore_last_opened_location() -> None:
        remember_mode = resolve_remember_location_mode(user_id=user_id, logger_context='index page')
        if remember_mode == 'dashboard':
            state.view = 'dashboard'
            state.library_id = None
            return

        last_view = str(get_user_setting(user_id=user_id, key='nav.last.view', default='') or '').strip()
        last_library_id = str(get_user_setting(user_id=user_id, key='nav.last.library_id', default='') or '').strip() or None
        last_marker_id = str(get_user_setting(user_id=user_id, key='nav.last.marker_id', default='') or '').strip() or None

        if last_view == 'library' and last_library_id:
            libs = list_libraries_for_user(user_id=user_id)
            allowed = {str(getattr(l, 'id', '') or '') for l in libs}
            if last_library_id in allowed:
                state.view = 'library'
                state.library_id = last_library_id
            return

        if last_view == 'marker' and last_marker_id:
            markers = list_markers(user_id=user_id)
            allowed = {str(getattr(s, 'id', '') or '') for s in markers}
            if last_marker_id in allowed:
                state.view = 'marker'
                state.library_id = None
                state.marker_id = last_marker_id
            return

        if last_view in {'to_read', 'favorites', 'all', 'recent'}:
            state.view = last_view
            state.library_id = None
            state.marker_id = None

    if user_id and not has_handoff_intent:
        try:
            _restore_last_opened_location()
        except Exception:
            logger.debug('Failed restoring last opened location for user_id=%s', user_id, exc_info=True)

    # Initialize display_mode from user settings
    state.display_mode = str(get_user_setting(user_id=user_id, key='ui.display_mode', default='grid') or 'grid').strip()
    if state.display_mode not in {'grid', 'list'}:
        state.display_mode = 'grid'

    collapsed = load_nav_collapsed_flags(user_id=user_id)
    apply_nav_collapsed_flags_attr(state=state, flags=collapsed)

    def open_metadata(paper: PaperItem) -> None:
        row = get_paper(paper_id=paper.id)
        if row is None:
            ui.notify('Item not found', color='warning')
            return
        metadata_dialog.open(row)

    def open_reader(paper: PaperItem) -> None:
        def _open_in_viewer(*, viewer_path: str, file_path: str, fallback_title: str) -> None:
            file_url = f'/api/v1/papers/{paper.id}/{file_path}'
            viewer_url = (
                viewer_path
                + f'?file={quote(file_url, safe="/")}'
                + f'&pv_paper_id={quote(paper.id, safe="")}'
                + f'&pv_title={quote(title or fallback_title, safe="")}'
            )
            ui.navigate.to(viewer_url, new_tab=True)

        title = (paper.title or '').strip()
        paper_row = None
        try:
            paper_row = get_paper(paper_id=paper.id)
            if paper_row is not None and not title:
                fp = str(paper_row.file_path or '').strip()
                if fp:
                    title = Path(fp).name
            if paper_row is not None and str(getattr(paper_row, 'title', '') or '').strip():
                title = str(paper_row.title).strip()
        except Exception:
            logger.debug('Failed resolving reader title for paper_id=%s', paper.id, exc_info=True)

        ext = ''
        try:
            if paper_row is not None and str(paper_row.file_path or '').strip():
                ext = Path(str(paper_row.file_path)).suffix.lower()
        except Exception:
            logger.debug('Failed resolving reader file extension for paper_id=%s', paper.id, exc_info=True)
            ext = ''

        if ext == '.epub':
            _open_in_viewer(viewer_path='/static/epub_viewer.html', file_path='raw', fallback_title='Book')
            return

        if ext == '.cbz':
            _open_in_viewer(viewer_path='/static/cbz_viewer.html', file_path='raw', fallback_title='Comic')
            return

        _open_in_viewer(viewer_path='/static/pdfjs/web/viewer.html', file_path='file', fallback_title='Document')

    refreshables: dict[str, object] = {}

    @ui.refreshable
    def render_left_nav() -> None:
        counts = get_dashboard_counts(user_id=user_id, library_id=None)

        def _open_marker(sh) -> None:
            try:
                if bool(getattr(sh, 'is_smart', False)):
                    state.filters_marker_ids = []
                else:
                    state.filters_marker_ids = [str(getattr(sh, 'id', '') or '')]
            except Exception:
                logger.debug('Failed applying marker filter selection', exc_info=True)
            _set_view('marker', None, str(getattr(sh, 'id', '') or ''))

        _toggle_navigation, _toggle_libraries, _toggle_markers, _toggle_auto_markers = make_nav_toggle_handlers_attr(
            state=state,
            user_id=user_id,
            on_refresh=render_left_nav.refresh,
        )

        left_nav(
            libraries=list_libraries_for_user(user_id=user_id),
            markers=list_markers(user_id=user_id),
            active_view=state.view,
            active_library_id=state.library_id,
            active_marker_id=state.marker_id,
            on_add_library=dialogs.open_create,
            on_edit_library=dialogs.open_edit,
            on_delete_library=dialogs.open_delete,
            on_share_library=share_dialogs.open_share_library,
            on_remove_shared_library=share_dialogs.remove_shared_library,
            on_open_dashboard=lambda: _set_view('dashboard', None),
            on_open_show_all=lambda: _set_view('all', None),
            on_open_recent=lambda: _set_view('recent', None),
            on_select_library=lambda lib: _set_view('library', lib.id),
            favorite_count=int(counts.get('favorites', 0) or 0),
            on_open_favorites_shelf=lambda: _set_view('favorites', None),
            to_read_count=int(counts.get('to_read', 0) or 0),
            on_open_to_read_shelf=lambda: _set_view('to_read', None),
            on_add_marker=marker_dialogs.open_create,
            on_add_auto_marker=marker_dialogs.open_create_auto,
            on_select_marker=_open_marker,
            on_edit_marker=marker_dialogs.open_edit,
            on_delete_marker=marker_dialogs.open_delete,
            navigation_collapsed=state.nav_navigation_collapsed,
            libraries_collapsed=state.nav_libraries_collapsed,
            markers_collapsed=state.nav_markers_collapsed,
            auto_markers_collapsed=state.nav_auto_markers_collapsed,
            on_toggle_navigation=_toggle_navigation,
            on_toggle_libraries=_toggle_libraries,
            on_toggle_markers=_toggle_markers,
            on_toggle_auto_markers=_toggle_auto_markers,
        )
    
    refreshables['render_left_nav'] = render_left_nav

    filters_header_menu = None
    right_drawer = None

    @ui.refreshable
    def render_filters() -> None:
        try:
            tags = list_tags()
        except Exception:
            logger.debug('Failed loading tags for filters panel', exc_info=True)
            tags = []
        try:
            markers = list_markers(user_id=user_id)
        except Exception:
            logger.debug('Failed loading markers for filters panel (user_id=%s)', user_id, exc_info=True)
            markers = []

        view = state.view
        eff_library_ids = state.effective_library_ids()
        ft = (state.filters_file_type or 'all').strip().lower()
        ft_val = None if ft == 'all' else ft
        try:
            facets = list_paper_filter_facets(user_id=user_id, library_ids=eff_library_ids, file_type=ft_val, limit=50)
        except Exception:
            logger.debug('Failed loading filter facets for user_id=%s view=%s', user_id, view, exc_info=True)
            facets = {}

        def _changed() -> None:
            if 'render_content' in refreshables:
                refreshables['render_content'].refresh()

        def _rebuild() -> None:
            render_filters.refresh()

        if filters_header_menu is not None:
            try:
                filters_header_menu.clear()
            except Exception:
                logger.debug('Failed clearing filters header menu container', exc_info=True)

        filters_panel(
            state=state,
            user_id=user_id,
            libraries=list_libraries_for_user(user_id=user_id),
            tags=tags,
            markers=markers,
            facets=facets,
            view=view,
            on_change=_changed,
            on_rebuild=_rebuild,
            header_container=filters_header_menu,
        )

    def _close_right_drawer(drawer) -> None:
        close_filters_drawer_and_persist(drawer=drawer, user_id=user_id, context='index')

    def render_right_drawer() -> None:
        nonlocal right_drawer, filters_header_menu
        drawer_open = get_filters_drawer_open(user_id=user_id, default=False)
        with ui.right_drawer(value=drawer_open).props('width=320 bordered breakpoint=900').classes('pv-surface') as right_drawer:
            with ui.row().classes('pv-drawer-header pv-filters-drawer-header w-full'):
                ui.label('Filters').classes('text-sm font-semibold pv-text-dimmer')
                with ui.row().classes('items-center gap-1 ml-auto') as filters_header_menu:
                    pass
                ui.button(icon='close', on_click=lambda _e, d=right_drawer: _close_right_drawer(d)).props('flat dense round').classes(
                    'pv-drawer-close'
                )
            render_filters()

    def _set_view(view: str, library_id: str | None, marker_id: str | None = None) -> None:
        state.set_view(view, library_id, marker_id)

        persist_last_navigation_state(
            user_id=user_id,
            view=state.view,
            library_id=(str(state.library_id) if state.library_id else None),
            marker_id=(str(state.marker_id) if state.marker_id else None),
            logger_context='index page',
        )
        if 'render_content' in refreshables:
            refreshables['render_content'].refresh()
        render_filters.refresh()

    def _set_search(query: str) -> None:
        state.search_query = str(query or '')
        state.reset_paging()
        _apply_search_transition()

    def _apply_search_transition() -> None:
        if state.search_query.strip():
            _set_view('search', None, None)
            return
        _set_view('all', None, None)

    def _set_search_mode(mode: str) -> None:
        state.search_mode = _normalize_search_mode(mode)
        state.reset_paging()
        if state.search_query.strip():
            _apply_search_transition()
            return
        if 'render_content' in refreshables:
            refreshables['render_content'].refresh()

    def toggle_right() -> None:
        if right_drawer:
            toggle_filters_drawer_and_persist(drawer=right_drawer, user_id=user_id, default_open=False)

    with page_scaffold(
        context='index page',
        render_left_nav=render_left_nav,
        render_right_drawer=render_right_drawer,
        on_import=upload_dialog.open,
        on_open_inbox=share_dialogs.open_inbox,
        on_open_profile=_open_profile,
        search_value=state.search_query,
        search_mode=state.search_mode,
        on_search_change=_set_search,
        on_search_mode_change=_set_search_mode,
        on_toggle_filters=toggle_right,
    ):
        # ── Keyboard navigation ─────────────────────────────────────────────
        # ... (Same as before)
        kb_info_btn = ui.button('', on_click=lambda _e=None: None).props('id=pv_kb_info').style('display:none')
        kb_reader_btn = ui.button('', on_click=lambda _e=None: None).props('id=pv_kb_reader').style('display:none')
        kb_fav_btn = ui.button('', on_click=lambda _e=None: None).props('id=pv_kb_fav').style('display:none')
        kb_search_btn = ui.button('', on_click=lambda _e=None: None).props('id=pv_kb_search').style('display:none')

        def _kb_action_on_selected(action: str) -> None:
            async def _do() -> None:
                pid = await ui.run_javascript(
                    "document.getElementById('pv_kb_info')?.dataset?.paperId || ''"
                )
                pid = str(pid or '').strip()
                if not pid:
                    return
                try:
                    paper_row = get_paper(paper_id=pid)
                except Exception:
                    paper_row = None
                if paper_row is None:
                    return

                paper_item = PaperItem(
                    id=str(paper_row.id),
                    title=str(getattr(paper_row, 'title', '') or ''),
                    subtitle=str(getattr(paper_row, 'subtitle', '') or ''),
                    reading_progress=float(getattr(paper_row, 'reading_progress', 0) or 0),
                    is_completed=bool(getattr(paper_row, 'is_completed', False)),
                    is_favorite=bool(getattr(paper_row, 'is_favorite', False)),
                    is_to_read=bool(getattr(paper_row, 'is_to_read', False)),
                    open_count_total=int(getattr(paper_row, 'open_count_total', 0) or 0),
                    open_count_since_reset=int(getattr(paper_row, 'open_count_since_reset', 0) or 0),
                    file_suffix=str(getattr(paper_row, 'file_suffix', '') or ''),
                )
                if action == 'info':
                    open_metadata(paper_item)
                elif action == 'reader':
                    open_reader(paper_item)
                elif action == 'fav':
                    try:
                        toggle_favorite(paper_id=pid, user_id=user_id)
                        if 'render_content' in refreshables:
                            refreshables['render_content'].refresh()
                    except Exception:
                        pass
            import asyncio
            asyncio.ensure_future(_do())

        kb_info_btn.on('click', lambda _e: _kb_action_on_selected('info'))
        kb_reader_btn.on('click', lambda _e: _kb_action_on_selected('reader'))
        kb_fav_btn.on('click', lambda _e: _kb_action_on_selected('fav'))
        kb_search_btn.on('click', lambda _e: ui.run_javascript(
            "document.querySelector('.pv-search-input input')?.focus()"
        ))

        ui.run_javascript("""
    (function(){
        if (window._pvKbInit) return;
        window._pvKbInit = true;
        window._pvKbInit = -1;

        function posters() { return Array.from(document.querySelectorAll('.pv-poster')); }

        function highlight(idx) {
            const ps = posters();
            ps.forEach(p => p.classList.remove('pv-poster--selected'));
            if (idx >= 0 && idx < ps.length) {
                ps[idx].classList.add('pv-poster--selected');
                ps[idx].scrollIntoView({block:'nearest',behavior:'smooth'});
                const pid = (ps[idx].id || '').replace('pv_poster_','');
                const el = document.getElementById('pv_kb_info');
                if (el) el.dataset.paperId = pid;
            }
            window._pvKbIdx = idx;
        }

        document.addEventListener('keydown', function(e) {
            const tag = (e.target.tagName||'').toLowerCase();
            if (tag==='input'||tag==='textarea'||tag==='select'||e.target.isContentEditable) {
                if (e.key==='Escape') { e.target.blur(); e.preventDefault(); }
                return;
            }
            if (document.querySelector('.q-dialog')) return;

            const ps = posters();
            const len = ps.length;
            if (!len && e.key!=='/') return;

            switch(e.key) {
                case 'j': case 'ArrowDown':
                    e.preventDefault();
                    highlight(Math.min(window._pvKbIdx+1, len-1));
                    break;
                case 'k': case 'ArrowUp':
                    e.preventDefault();
                    highlight(Math.max(window._pvKbIdx-1, 0));
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    highlight(Math.min(window._pvKbIdx+1, len-1));
                    break;
                case 'ArrowLeft':
                    e.preventDefault();
                    highlight(Math.max(window._pvKbIdx-1, 0));
                    break;
                case 'Enter':
                    e.preventDefault();
                    document.getElementById('pv_kb_reader')?.click();
                    break;
                case 'e':
                    e.preventDefault();
                    document.getElementById('pv_kb_info')?.click();
                    break;
                case 'f':
                    e.preventDefault();
                    document.getElementById('pv_kb_fav')?.click();
                    break;
                case '/':
                    e.preventDefault();
                    document.getElementById('pv_kb_search')?.click();
                    break;
                case 'Escape':
                    highlight(-1);
                    break;
            }
        });
    })();
        """)

        @ui.refreshable
        def render_content() -> None:
            # ... (Content rendering logic from before)
            # Copied from original file, need to make sure I don't miss anything.
            # I will assume the previous content logic is preserved and just pasted here.
            # I need to duplicate the render_content logic here in the tool call.
            
            libs = list_libraries_for_user(user_id=user_id)
            markers = list_markers(user_id=user_id)
            lib_name_by_id = {l.id: l.name for l in libs}
            marker_name_by_id = {s.id: s.name for s in markers}

            view = state.view
            library_id = state.library_id
            marker_id = state.marker_id

            eff_filters = state.effective_filters()
            eff_library_ids = state.effective_library_ids()

            sort_key = state.active_sort_key()

            # ── Breadcrumbs ────────────────────────────────────────────
            def _breadcrumb_nav(target_view: str, **extra: object) -> None:
                state.view = target_view
                for k, v in extra.items():
                    setattr(state, k, v)
                if 'render_content' in refreshables:
                    refreshables['render_content'].refresh()

            def _breadcrumb_sep() -> None:
                ui.label('/').classes('pv-bc-sep')

            def _breadcrumb_current(label: str) -> None:
                _breadcrumb_sep()
                ui.label(label).classes('pv-bc-current')

            def _render_library_breadcrumb() -> None:
                _breadcrumb_sep()
                with ui.button('Libraries').props('flat dense no-caps') as _lib_btn:
                    _lib_btn.classes('pv-bc-link pv-bc-trigger')
                    with ui.menu().classes('min-w-[170px]'):
                        if not libs:
                            ui.menu_item('No libraries yet').props('disable dense').classes('text-xs py-1')
                        else:
                            for lib in libs:
                                lid = getattr(lib, 'id', None)
                                lname = str(getattr(lib, 'name', '') or '').strip() or 'Library'

                                def make_library_handler(lib_id: object):
                                    def handler() -> None:
                                        _breadcrumb_nav('library', library_id=lib_id, marker_id=None)
                                    return handler

                                item = ui.menu_item(lname, on_click=make_library_handler(lid)).props('dense').classes('text-xs py-1')
                                if lid == library_id:
                                    item.props('disable')

                _breadcrumb_sep()
                ui.label(lib_name_by_id.get(library_id, 'Library')).classes('pv-bc-current')

            def _render_marker_breadcrumb() -> None:
                _breadcrumb_sep()
                with ui.button('Markers').props('flat dense no-caps') as _marker_btn:
                    _marker_btn.classes('pv-bc-link pv-bc-trigger')
                    with ui.menu().classes('min-w-[170px]'):
                        if not markers:
                            ui.menu_item('No markers yet').props('disable dense').classes('text-xs py-1')
                        else:
                            for m in markers:
                                mid = getattr(m, 'id', None)
                                mname = str(getattr(m, 'name', '') or '').strip() or 'Marker'

                                def make_marker_handler(marker_key: object):
                                    def handler() -> None:
                                        _breadcrumb_nav('marker', marker_id=marker_key, library_id=None)
                                    return handler

                                item = ui.menu_item(mname, on_click=make_marker_handler(mid)).props('dense').classes('text-xs py-1')
                                if mid == marker_id:
                                    item.props('disable')

                _breadcrumb_sep()
                ui.label(marker_name_by_id.get(marker_id, 'Marker')).classes('pv-bc-current')

            breadcrumb_label_by_view = {
                'favorites': 'Favorites',
                'to_read': 'To Read',
                'recent': 'Recently added',
                'all': 'All Files',
            }

            def _render_breadcrumbs() -> None:
                if view == 'dashboard':
                    return

                with ui.row().classes('w-full items-center justify-between mb-2'):
                    with ui.element('div').classes('pv-breadcrumbs'):
                        ui.link('Dashboard', '#').classes('pv-bc-link').on(
                            'click.prevent', lambda _e=None: _breadcrumb_nav('dashboard'),
                        )

                        if view == 'library' and library_id:
                            _render_library_breadcrumb()
                        elif view == 'marker' and marker_id:
                            _render_marker_breadcrumb()
                        elif view == 'search':
                            _breadcrumb_current(f'Search: {state.search_query}')
                        elif view in breadcrumb_label_by_view:
                            _breadcrumb_current(breadcrumb_label_by_view[view])

                    # Layout toggle
                    def _set_display_mode(mode: str) -> None:
                        state.display_mode = mode
                        set_user_setting(user_id=user_id, key='ui.display_mode', value=mode)
                        if 'render_content' in refreshables:
                            refreshables['render_content'].refresh()

                    with ui.row().classes('items-center gap-1 shrink-0'):
                        ui.button(icon='grid_view', on_click=lambda _e=None: _set_display_mode('grid')).props(
                            f'flat dense round {"color=primary" if state.display_mode == "grid" else "color=grey-5"}'
                        ).tooltip('Grid view')
                        ui.button(icon='view_list', on_click=lambda _e=None: _set_display_mode('list')).props(
                            f'flat dense round {"color=primary" if state.display_mode == "list" else "color=grey-5"}'
                        ).tooltip('List view')

            _render_breadcrumbs()

            def _load_more() -> None:
                state.load_more()
                if 'render_content' in refreshables:
                    refreshables['render_content'].refresh()

            # Render views using extracted modules
            if render_query_views(
                user_id=user_id,
                view=view,
                state=state,
                eff_library_ids=eff_library_ids,
                eff_filters=eff_filters,
                sort_key=sort_key,
                open_metadata=open_metadata,
                open_reader=open_reader,
                open_share_paper=share_dialogs.open_share_paper,
                on_refresh_left_nav=render_left_nav.refresh,
                open_upload_dialog=upload_dialog.open,
                display_mode=state.display_mode,
                get_list_limit=_get_list_limit,
                load_more_fn=_load_more,
            ):
                return

            if view == 'dashboard':
                render_dashboard_view(
                    user_id=user_id,
                    open_reader=open_reader,
                    open_metadata=open_metadata,
                    open_share_paper=share_dialogs.open_share_paper,
                    on_refresh_all=_refresh_all,
                    on_refresh_left_nav=render_left_nav.refresh,
                )
                return

            if render_category_views(
                user_id=user_id,
                view=view,
                eff_library_ids=eff_library_ids,
                eff_filters=eff_filters,
                sort_key=sort_key,
                open_metadata=open_metadata,
                open_reader=open_reader,
                open_share_paper=share_dialogs.open_share_paper,
                on_refresh_left_nav=render_left_nav.refresh,
                display_mode=state.display_mode,
                get_list_limit=_get_list_limit,
                load_more_fn=_load_more,
            ):
                return

            if render_marker_view(
                user_id=user_id,
                view=view,
                marker_id=marker_id,
                marker_name_by_id=marker_name_by_id,
                eff_library_ids=eff_library_ids,
                eff_filters=eff_filters,
                sort_key=sort_key,
                open_metadata=open_metadata,
                open_reader=open_reader,
                open_share_paper=share_dialogs.open_share_paper,
                on_refresh_left_nav=render_left_nav.refresh,
                display_mode=state.display_mode,
                get_list_limit=_get_list_limit,
                load_more_fn=_load_more,
            ):
                return

            # Fallback handling for library/all views
            def _final_section_payload() -> tuple[str, list[PaperItem], bool, str]:
                if view == 'library' and library_id:
                    title = lib_name_by_id.get(library_id, 'Library')
                    papers, has_more = _paged_filtered(
                        get_list_limit=_get_list_limit,
                        user_id=user_id,
                        library_id=str(library_id),
                        query=None,
                        mode='all',
                        filters=eff_filters,
                        sort=sort_key,
                    )
                    return title, papers, has_more, 'library'

                if view == 'all':
                    title = 'All Files'
                    papers, has_more = _paged_filtered(
                        get_list_limit=_get_list_limit,
                        user_id=user_id,
                        library_ids=eff_library_ids,
                        query=None,
                        mode='all',
                        filters=eff_filters,
                        sort=sort_key,
                    )
                    return title, papers, has_more, 'all'

                return 'Dashboard', [], False, view

            # Only render if we fall through (library or all view)
            if view in {'library', 'all'}:
                title, papers, has_more, effective_view = _final_section_payload()
                render_wall_section(
                    user_id=user_id,
                    title=title,
                    papers=papers,
                    view_name=effective_view,
                    has_more=has_more,
                    open_metadata=open_metadata,
                    open_reader=open_reader,
                    open_share_paper=share_dialogs.open_share_paper,
                    on_refresh_left_nav=render_left_nav.refresh,
                    on_empty_action=upload_dialog.open,
                    display_mode=state.display_mode,
                    get_list_limit=_get_list_limit,
                    load_more_fn=_load_more,
                )

        render_content()
        refreshables['render_content'] = render_content
