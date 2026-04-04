from __future__ import annotations

import logging
from collections.abc import Callable

from nicegui import ui
from nicegui import app

from papervisor.services.libraries import list_libraries_for_user
from papervisor.services.papers import get_dashboard_counts
from papervisor.services.markers import list_markers
from papervisor.ui.components.left_nav import left_nav
from papervisor.ui.components.page_states import show_initial_panel_loading
from papervisor.ui.components.page_scaffold import page_scaffold
from papervisor.ui.dialogs.import_dialog import UploadDialog
from papervisor.ui.dialogs.library_dialogs import LibraryDialogs
from papervisor.ui.dialogs.share_dialogs import ShareDialogs
from papervisor.ui.dialogs.marker_dialogs import MarkerDialogs
from papervisor.ui.pages.admin.library_panel import render_library_panel
from papervisor.ui.pages.admin.global_libraries_panel import render_global_libraries_panel
from papervisor.ui.pages.admin.api_panel import render_api_panel
from papervisor.ui.pages.admin.maintenance_panel import render_maintenance_panel
from papervisor.ui.pages.admin.opds_panel import render_opds_panel
from papervisor.ui.pages.admin.patterns_panel import render_patterns_panel
from papervisor.ui.pages.admin.logs_panel import render_logs_panel
from papervisor.ui.pages.admin.users_panel import render_users_panel
from papervisor.ui.pages.shared_state import (
    apply_nav_collapsed_flags_dict,
    load_nav_collapsed_flags,
    make_nav_toggle_handlers_dict,
    make_search_handoff_handlers,
    store_nav_intent,
    require_authenticated_user,
    require_admin_user,
)


logger = logging.getLogger(__name__)


@ui.page('/admin')
def admin() -> None:
    if not require_authenticated_user():
        return
    if not require_admin_user():
        return

    def _refresh_all() -> None:
        if 'render_left_nav' in refreshables:
            refreshables['render_left_nav'].refresh()
        try:
            for key in panel_loading:
                panel_loading[key] = True
            # Refresh bodies if they exist
            for key in ['patterns', 'library', 'global_libs', 'maintenance', 'opds', 'api', 'users', 'logs']:
                fn_name = f'render_{key}_body'
                if fn_name in refreshables:
                    refreshables[fn_name].refresh()
        except Exception:
            logger.debug('Skipped admin body refresh', exc_info=True)

    user_id = int(app.storage.user.get('user_id') or 0)
    is_user_admin = bool(app.storage.user.get('is_admin'))

    state: dict[str, str | None] = {
        'nav_libraries_collapsed': '0',
        'nav_markers_collapsed': '0',
        'nav_auto_markers_collapsed': '0',
        'search_query': '',
        'search_mode': 'all',
        'patterns_owner_user_id': '',
        'library_owner_user_id': '',
        'maintenance_owner_user_id': '',
    }
    panel_loading: dict[str, bool] = {
        'patterns': True,
        'library': True,
        'global_libs': True,
        'maintenance': True,
        'opds': True,
        'api': True,
        'users': True,
        'logs': True,
    }
    collapsed = load_nav_collapsed_flags(user_id=user_id)
    apply_nav_collapsed_flags_dict(state=state, flags=collapsed)

    refreshables: dict[str, object] = {}

    dialogs = LibraryDialogs(user_id=user_id, on_changed=_refresh_all)
    share_dialogs = ShareDialogs(user_id=user_id, on_changed=_refresh_all)

    def _refresh_left_nav() -> None:
        if 'render_left_nav' in refreshables:
            refreshables['render_left_nav'].refresh()

    marker_dialogs = MarkerDialogs(on_changed=_refresh_left_nav, user_id=user_id)
    upload_dialog = UploadDialog(user_id=user_id, on_changed=_refresh_all)

    def _make_owner_helpers(key: str) -> tuple[Callable[[], str], Callable[[], int | None], Callable[[str], None]]:
        def _raw() -> str:
            return str(state.get(key) or '').strip()

        def _val() -> int | None:
            raw = _raw()
            return int(raw) if raw.isdigit() else None

        def _set(v: str) -> None:
            state[key] = str(v or '')
            _refresh_all()
        
        return _raw, _val, _set

    patterns_raw, patterns_val, patterns_set = _make_owner_helpers('patterns_owner_user_id')
    library_raw, library_val, library_set = _make_owner_helpers('library_owner_user_id')
    maint_raw, maint_val, maint_set = _make_owner_helpers('maintenance_owner_user_id')

    def _open_profile() -> None:
        ui.navigate.to('/profile')

    def _handoff_to_main(intent: dict[str, object]) -> None:
        store_nav_intent(intent)
        ui.navigate.to('/')

    _on_search_change, _on_search_mode_change, _poll_search_handoff = make_search_handoff_handlers(
        state=state,
        handoff=_handoff_to_main,
        debounce_seconds=0.45,
    )

    ui.timer(0.10, _poll_search_handoff)

    @ui.refreshable
    def render_left_nav() -> None:
        counts = get_dashboard_counts(user_id=user_id, library_id=None)

        _toggle_navigation, _toggle_libraries, _toggle_markers, _toggle_auto_markers = make_nav_toggle_handlers_dict(
            state=state,
            user_id=user_id,
            on_refresh=render_left_nav.refresh,
        )

        left_nav(
            libraries=list_libraries_for_user(user_id=user_id),
            markers=list_markers(user_id=user_id),
            on_add_library=dialogs.open_create,
            on_edit_library=dialogs.open_edit,
            on_delete_library=dialogs.open_delete,
            on_share_library=share_dialogs.open_share_library,
            on_remove_shared_library=share_dialogs.remove_shared_library,
            on_open_dashboard=lambda: _handoff_to_main({'view': 'dashboard'}),
            on_open_show_all=lambda: _handoff_to_main({'view': 'all'}),
            on_open_recent=lambda: _handoff_to_main({'view': 'recent'}),
            on_select_library=lambda lib: _handoff_to_main({'view': 'library', 'library_id': lib.id}),
            favorite_count=int(counts.get('favorites', 0) or 0),
            on_open_favorites_shelf=lambda: _handoff_to_main({'view': 'favorites'}),
            to_read_count=int(counts.get('to_read', 0) or 0),
            on_open_to_read_shelf=lambda: _handoff_to_main({'view': 'to_read'}),
            on_add_marker=marker_dialogs.open_create,
            on_add_auto_marker=marker_dialogs.open_create_auto,
            on_select_marker=lambda sh: _handoff_to_main({'view': 'marker', 'marker_id': sh.id}),
            on_edit_marker=marker_dialogs.open_edit,
            on_delete_marker=marker_dialogs.open_delete,
            navigation_collapsed=str(state.get('nav_navigation_collapsed') or '0') == '1',
            libraries_collapsed=str(state.get('nav_libraries_collapsed') or '0') == '1',
            markers_collapsed=str(state.get('nav_markers_collapsed') or '0') == '1',
            auto_markers_collapsed=str(state.get('nav_auto_markers_collapsed') or '0') == '1',
            on_toggle_navigation=_toggle_navigation,
            on_toggle_libraries=_toggle_libraries,
            on_toggle_markers=_toggle_markers,
            on_toggle_auto_markers=_toggle_auto_markers,
        )

    refreshables['render_left_nav'] = render_left_nav

    with page_scaffold(
        context='admin page',
        require_admin=True,
        render_left_nav=render_left_nav,
        on_import=upload_dialog.open,
        on_open_inbox=share_dialogs.open_inbox,
        on_open_profile=_open_profile,
        search_value=str(state.get('search_query') or ''),
        search_mode=str(state.get('search_mode') or 'all'),
        on_search_change=_on_search_change,
        on_search_mode_change=_on_search_mode_change,
    ):
        with ui.column().classes('w-full px-4 py-4 gap-4'):
            with ui.card().props('flat bordered').classes('pv-surface w-full !p-0'):
                with ui.row().classes('w-full items-center gap-0 min-w-0 flex-nowrap overflow-hidden'):
                    with ui.tabs().props('dense narrow-indicator outside-arrows mobile-arrows').classes('pv-admin-tabs w-full min-w-0') as tabs:
                        ui.tab('Patterns', icon='pattern').props('inline-label')
                        ui.tab('Library', icon='library_books').props('inline-label')
                        ui.tab('Global Libs', icon='language').props('inline-label')
                        ui.tab('Maintenance', icon='build').props('inline-label')
                        ui.tab('OPDS', icon='rss_feed').props('inline-label')
                        ui.tab('API', icon='key').props('inline-label')
                        ui.tab('Users', icon='group').props('inline-label')
                        ui.tab('Logs', icon='receipt_long').props('inline-label')
                    tabs.value = 'Patterns'

            with ui.tab_panels(tabs).props('animated=false transition-prev=none transition-next=none keep-alive').classes('w-full pv-profile-tab-panels'):
                with ui.tab_panel('Patterns').classes('p-0'):
                    @ui.refreshable
                    def render_patterns_body() -> None:
                        if show_initial_panel_loading(
                            panel_loading=panel_loading,
                            key='patterns',
                            message='Loading patterns…',
                            refresh=render_patterns_body.refresh,
                        ):
                            return

                        render_patterns_panel(
                            current_user_id=user_id,
                            library_owner_user_id=patterns_val(),
                            owner_user_id_value=patterns_raw(),
                            on_owner_user_id_change=patterns_set,
                        )

                    render_patterns_body()
                    refreshables['render_patterns_body'] = render_patterns_body

                with ui.tab_panel('Library').classes('p-0'):
                    @ui.refreshable
                    def render_library_body() -> None:
                        if show_initial_panel_loading(
                            panel_loading=panel_loading,
                            key='library',
                            message='Loading library settings…',
                            refresh=render_library_body.refresh,
                        ):
                            return

                        render_library_panel(
                            dialogs=dialogs,
                            on_changed=_refresh_all,
                            library_owner_user_id=library_val(),
                            owner_user_id_value=library_raw(),
                            on_owner_user_id_change=library_set,
                        )

                    render_library_body()
                    refreshables['render_library_body'] = render_library_body

                with ui.tab_panel('Global Libs').classes('p-0'):
                    @ui.refreshable
                    def render_global_libs_body() -> None:
                        if show_initial_panel_loading(
                            panel_loading=panel_loading,
                            key='global_libs',
                            message='Loading global libraries…',
                            refresh=render_global_libs_body.refresh,
                        ):
                            return

                        render_global_libraries_panel()

                    render_global_libs_body()
                    refreshables['render_global_libs_body'] = render_global_libs_body

                with ui.tab_panel('Maintenance').classes('p-0'):
                    @ui.refreshable
                    def render_maintenance_body() -> None:
                        if show_initial_panel_loading(
                            panel_loading=panel_loading,
                            key='maintenance',
                            message='Loading maintenance tools…',
                            refresh=render_maintenance_body.refresh,
                        ):
                            return

                        render_maintenance_panel(
                            on_changed=_refresh_all,
                            library_owner_user_id=maint_val(),
                            owner_user_id_value=maint_raw(),
                            on_owner_user_id_change=maint_set,
                        )

                    render_maintenance_body()
                    refreshables['render_maintenance_body'] = render_maintenance_body

                with ui.tab_panel('OPDS').classes('p-0'):
                    @ui.refreshable
                    def render_opds_body() -> None:
                        if show_initial_panel_loading(
                            panel_loading=panel_loading,
                            key='opds',
                            message='Loading OPDS settings…',
                            refresh=render_opds_body.refresh,
                        ):
                            return
                        render_opds_panel()

                    render_opds_body()
                    refreshables['render_opds_body'] = render_opds_body

                with ui.tab_panel('API').classes('p-0'):
                    @ui.refreshable
                    def render_api_body() -> None:
                        if show_initial_panel_loading(
                            panel_loading=panel_loading,
                            key='api',
                            message='Loading API settings…',
                            refresh=render_api_body.refresh,
                        ):
                            return
                        render_api_panel()

                    render_api_body()
                    refreshables['render_api_body'] = render_api_body

                with ui.tab_panel('Users').classes('p-0'):
                    @ui.refreshable
                    def render_users_body() -> None:
                        if show_initial_panel_loading(
                            panel_loading=panel_loading,
                            key='users',
                            message='Loading users…',
                            refresh=render_users_body.refresh,
                        ):
                            return
                        render_users_panel()

                    render_users_body()
                    refreshables['render_users_body'] = render_users_body

                with ui.tab_panel('Logs').classes('p-0'):
                    @ui.refreshable
                    def render_logs_body() -> None:
                        if show_initial_panel_loading(
                            panel_loading=panel_loading,
                            key='logs',
                            message='Loading logs…',
                            refresh=render_logs_body.refresh,
                        ):
                            return
                        render_logs_panel()

                    render_logs_body()
                    refreshables['render_logs_body'] = render_logs_body
