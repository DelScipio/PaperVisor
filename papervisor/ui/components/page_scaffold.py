from __future__ import annotations

import logging
from typing import Callable
from contextlib import contextmanager

from nicegui import app, ui

from papervisor.ui.theme import current_theme, setup_theme
from papervisor.ui.pages.shared_state import (
    load_nav_collapsed_flags,
    apply_nav_collapsed_flags_dict,
    apply_nav_collapsed_flags_attr,
    get_nav_drawer_open,
    persist_nav_drawer_open,
    render_navigation_left_drawer,
    render_page_top_bar,
    require_authenticated_user,
    require_admin_user,
    toggle_drawer,
)

logger = logging.getLogger(__name__)


@contextmanager
def page_scaffold(
    *,
    context: str,
    require_admin: bool = False,
    page_path: str | None = None,
    render_left_nav: Callable[[], None] | None = None,
    render_right_drawer: Callable[[], object] | None = None,
    # Navbar / Search args
    search_value: str = '',
    search_mode: str = 'all',
    on_search_change: Callable[[str], None] | None = None,
    on_search_mode_change: Callable[[str], None] | None = None,
    on_import: Callable[[], None] | None = None,
    on_open_inbox: Callable[[], None] | None = None,
    on_open_profile: Callable[[], None] | None = None,
    # Right drawer toggle handler (if external control needed)
    on_toggle_filters: Callable[[], None] | None = None,
) -> None:
    """
    Common page layout scaffold.
    Handles:
    - Theme setup
    - Auth checks
    - Base container styling
    - Left Navigation Drawer (collapsible, persistent)
    - Top Bar
    - Optional Right Drawer
    """
    setup_theme()
    ui.query('body').classes('bg-transparent pv-page-shell')
    selected_theme = current_theme()
    ui.run_javascript(
        (
            "(function(){"
            f"const theme='{selected_theme}';"
            "if(window.__pvApplyTheme){window.__pvApplyTheme(theme);}"
            "else {document.documentElement.setAttribute('data-theme', theme);}"
            "})();"
        )
    )

    if not require_authenticated_user():
        return
    
    if require_admin:
        if not require_admin_user():
            return

    user_id = int(app.storage.user.get('user_id') or 0)
    is_user_admin = bool(app.storage.user.get('is_admin'))

    # -- Left Drawer Setup --
    nav_drawer_open = get_nav_drawer_open(user_id=user_id, default=True)
    
    # We need a reference to modify it later
    left_drawer = None
    
    def _close_left() -> None:
        if left_drawer:
            left_drawer.value = False
            persist_nav_drawer_open(user_id=user_id, is_open=False)

    if render_left_nav:
        left_drawer = render_navigation_left_drawer(
            value=nav_drawer_open,
            props='width=280 bordered breakpoint=900',
            classes='pv-surface',
            on_close=_close_left,
            render_left_nav=render_left_nav,
            header_label='',
        )

    def _toggle_left() -> None:
        if left_drawer:
            is_open = toggle_drawer(left_drawer, default_open=True)
            persist_nav_drawer_open(user_id=user_id, is_open=is_open)

    # -- Top Bar --
    with ui.header().classes('w-full max-w-none p-0 pv-header pv-topbar'):
        render_page_top_bar(
            user_id=user_id,
            context=context,
            on_toggle_left=_toggle_left,
            on_toggle_filters=on_toggle_filters,
            on_import=on_import,
            on_open_inbox=on_open_inbox,
            is_admin=is_user_admin,
            on_open_profile=on_open_profile,
            search_value=search_value,
            search_mode=search_mode,
            on_search_change=on_search_change,
            on_search_mode_change=on_search_mode_change,
        )

    # -- Optional Right Drawer --
    if render_right_drawer:
        render_right_drawer()

    # -- Yield to body content --
    yield
