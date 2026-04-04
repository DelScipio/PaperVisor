from __future__ import annotations

import logging

from nicegui import app
from nicegui import ui

from papervisor.services.libraries import list_libraries_for_user
from papervisor.services.papers import get_dashboard_counts
from papervisor.services.markers import list_markers
from papervisor.ui.components.left_nav import left_nav
from papervisor.ui.components.page_scaffold import page_scaffold
from papervisor.ui.dialogs.import_dialog import UploadDialog
from papervisor.ui.dialogs.library_dialogs import LibraryDialogs
from papervisor.ui.dialogs.share_dialogs import ShareDialogs
from papervisor.ui.dialogs.marker_dialogs import MarkerDialogs
from papervisor.ui.pages.shared_state import (
    apply_nav_collapsed_flags_dict,
    load_nav_collapsed_flags,
    make_nav_toggle_handlers_dict,
    make_search_handoff_handlers,
    store_nav_intent,
    require_authenticated_user,
)

# Import extracted views
from papervisor.ui.pages.profile_views.patterns_tab import render_patterns_tab
from papervisor.ui.pages.profile_views.opds_tab import render_opds_tab
from papervisor.ui.pages.profile_views.account_tab import render_account_tab

logger = logging.getLogger(__name__)


@ui.page('/profile')
def profile_page() -> None:
    # Pre-checks for early return if needed (though scaffold handles auth, we might need user_id for setup)
    # Actually scaffold handles auth return, but we need user_id for dialogs *before* scaffold yield?
    # No, we can init dialogs inside. But scaffold yields *after* auth check.
    # So we should probably do:
    if not require_authenticated_user():
        return

    user_id = int(app.storage.user.get('user_id') or 0)
    username = str(app.storage.user.get('username') or '')

    state: dict[str, str | None] = {
        'nav_libraries_collapsed': '0',
        'nav_markers_collapsed': '0',
        'nav_auto_markers_collapsed': '0',
        'search_query': '',
        'search_mode': 'all',
    }

    collapsed = load_nav_collapsed_flags(user_id=user_id)
    apply_nav_collapsed_flags_dict(state=state, flags=collapsed)

    refreshables: dict[str, object] = {}
    panel_loading: dict[str, bool] = {
        'patterns': True,
        'opds': True,
    }

    def _refresh_patterns_if_ready() -> None:
        fn = refreshables.get('render_patterns')
        refresh = getattr(fn, 'refresh', None)
        if callable(refresh):
            panel_loading['patterns'] = True
            refresh()

    def _refresh_left_nav() -> None:
        if 'render_left_nav' in refreshables:
            refreshables['render_left_nav'].refresh()

    def _refresh_all() -> None:
        _refresh_left_nav()
        _refresh_patterns_if_ready()

    dialogs = LibraryDialogs(user_id=user_id, on_changed=_refresh_all)
    share_dialogs = ShareDialogs(user_id=user_id, on_changed=_refresh_all)
    marker_dialogs = MarkerDialogs(on_changed=_refresh_left_nav, user_id=user_id)
    upload_dialog = UploadDialog(user_id=user_id, on_changed=_refresh_left_nav)

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

    def _libraries() -> list:
        try:
            return list_libraries_for_user(user_id=user_id)
        except Exception:
            logger.debug('Failed listing libraries for profile left-nav (user_id=%s)', user_id, exc_info=True)
            return []

    def _profile_metrics() -> dict[str, int]:
        libraries = _libraries()

        try:
            markers = list_markers(user_id=user_id)
        except Exception:
            logger.debug('Failed listing markers for profile metrics (user_id=%s)', user_id, exc_info=True)
            markers = []

        try:
            counts = get_dashboard_counts(user_id=user_id, library_id=None)
        except Exception:
            logger.debug('Failed loading dashboard counts for profile metrics (user_id=%s)', user_id, exc_info=True)
            counts = {}

        return {
            'libraries': len(libraries),
            'markers': len(markers),
            'total': int(counts.get('total', 0) or 0),
            'completed': int(counts.get('completed', 0) or 0),
            'favorites': int(counts.get('favorites', 0) or 0),
            'to_read': int(counts.get('to_read', 0) or 0),
        }

    def _profile_badge(*, text: str, classes: str, color: str) -> None:
        badge = ui.badge(text).props('outline').classes(classes)
        badge.style(f'color: {color} !important;')

    @ui.refreshable
    def render_left_nav() -> None:
        libs = _libraries()
        counts = get_dashboard_counts(user_id=user_id, library_id=None)

        _toggle_navigation, _toggle_libraries, _toggle_markers, _toggle_auto_markers = make_nav_toggle_handlers_dict(
            state=state,
            user_id=user_id,
            on_refresh=render_left_nav.refresh,
        )

        left_nav(
            libraries=libs,
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
        context='profile page',
        render_left_nav=render_left_nav,
        on_import=upload_dialog.open,
        on_open_inbox=share_dialogs.open_inbox,
        on_open_profile=_open_profile,
        search_value=str(state.get('search_query') or ''),
    ):
        metrics = _profile_metrics()

        with ui.column().classes('w-full px-4 py-4 gap-4'):
            with ui.card().props('flat bordered').classes('pv-surface w-full pv-profile-hero'):
                with ui.row().classes('w-full items-center justify-between gap-3 flex-wrap'):
                    with ui.row().classes('items-center gap-3 min-w-0'):
                        with ui.element('div').classes('pv-profile-hero-icon'):
                            ui.icon('person')
                        with ui.column().classes('gap-0 min-w-0'):
                            ui.label('Profile').classes('text-base font-semibold')
                            ui.label(username).classes('text-sm pv-text-dim truncate')
                    _profile_badge(
                        text=f"{metrics['total']} papers",
                        classes='pv-chip pv-profile-chip pv-profile-chip-total',
                        color='color-mix(in srgb, var(--pv-accent) 88%, var(--pv-text) 12%)',
                    )

                with ui.row().classes('w-full items-center gap-2 mt-2 flex-wrap'):
                    _profile_badge(
                        text=f"{metrics['completed']} completed",
                        classes='pv-chip pv-profile-chip pv-profile-chip-completed',
                        color='color-mix(in srgb, var(--pv-stat-green-fg) 86%, var(--pv-text) 14%)',
                    )
                    _profile_badge(
                        text=f"{metrics['favorites']} favorites",
                        classes='pv-chip pv-profile-chip pv-profile-chip-favorites',
                        color='color-mix(in srgb, var(--pv-stat-red-fg) 86%, var(--pv-text) 14%)',
                    )
                    _profile_badge(
                        text=f"{metrics['to_read']} to read",
                        classes='pv-chip pv-profile-chip pv-profile-chip-to-read',
                        color='color-mix(in srgb, var(--pv-stat-orange-fg) 86%, var(--pv-text) 14%)',
                    )
                    _profile_badge(
                        text=f"{metrics['libraries']} libraries",
                        classes='pv-chip pv-profile-chip pv-profile-chip-libraries',
                        color='color-mix(in srgb, var(--pv-stat-blue-fg) 86%, var(--pv-text) 14%)',
                    )
                    _profile_badge(
                        text=f"{metrics['markers']} markers",
                        classes='pv-chip pv-profile-chip pv-profile-chip-markers',
                        color='color-mix(in srgb, var(--q-secondary) 88%, var(--pv-text) 12%)',
                    )

            with ui.card().props('flat bordered').classes('pv-surface w-full !p-0'):
                with ui.row().classes('w-full items-center gap-0 min-w-0 flex-nowrap overflow-hidden'):
                    with ui.tabs().props('dense narrow-indicator outside-arrows mobile-arrows').classes('pv-admin-tabs w-full min-w-0') as tabs:
                        ui.tab('Patterns', icon='pattern').props('inline-label')
                        ui.tab('OPDS', icon='rss_feed').props('inline-label')
                        ui.tab('Account', icon='person').props('inline-label')
                    tabs.value = 'Patterns'

            with ui.tab_panels(tabs).props('animated=false transition-prev=none transition-next=none keep-alive').classes(
                'w-full pv-profile-tab-panels'
            ):
                with ui.tab_panel('Patterns').classes('p-0'):
                    refreshables['render_patterns'] = render_patterns_tab(
                        user_id=user_id,
                        panel_loading=panel_loading,
                        libraries_provider=_libraries,
                    )

                with ui.tab_panel('OPDS').classes('p-0'):
                    refreshables['render_opds_settings'] = render_opds_tab(
                        user_id=user_id,
                        panel_loading=panel_loading,
                    )

                with ui.tab_panel('Account').classes('p-0'):
                    render_account_tab(user_id=user_id)
