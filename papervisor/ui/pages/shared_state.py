from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from nicegui import ui
from nicegui import app

from papervisor.services.audit_logs import log_event
from papervisor.services.settings import get_ui_remember_location_default, get_ui_remember_location_user_override_allowed
from papervisor.services.sharing import list_inbox
from papervisor.services.user_settings import get_user_setting, get_user_setting_bool, set_user_setting, set_user_setting_bool
from papervisor.ui.components.top_bar import top_bar


logger = logging.getLogger(__name__)

_NAV_SECTION_TO_SETTING_KEY: dict[str, str] = {
    'navigation': 'nav.navigation.collapsed',
    'libraries': 'nav.libraries.collapsed',
    'markers': 'nav.markers.collapsed',
    'auto_markers': 'nav.auto_markers.collapsed',
}


def resolve_remember_location_mode(*, user_id: int | None, logger_context: str) -> str:
    """Return effective remember-location mode: dashboard|library|marker.

    Uses admin default, then optional user override when enabled.
    """
    try:
        default_mode = str(get_ui_remember_location_default() or 'library')
    except Exception:
        logger.debug('Failed loading default remember-location mode on %s', logger_context, exc_info=True)
        default_mode = 'library'

    if default_mode not in {'dashboard', 'library', 'marker'}:
        default_mode = 'library'

    if not user_id:
        return default_mode

    try:
        if not bool(get_ui_remember_location_user_override_allowed()):
            return default_mode
    except Exception:
        logger.debug('Failed reading remember-location override setting on %s', logger_context, exc_info=True)
        return default_mode

    try:
        value = str(get_user_setting(user_id=user_id, key='ui.remember_location.mode', default='') or '').strip().lower()
    except Exception:
        logger.debug('Failed reading user remember-location mode for user_id=%s on %s', user_id, logger_context, exc_info=True)
        value = ''

    return value if value in {'dashboard', 'library', 'marker'} else default_mode


def persist_last_navigation_state(
    *,
    user_id: int | None,
    view: str,
    library_id: str | None,
    marker_id: str | None,
    logger_context: str,
) -> None:
    if not user_id:
        return
    try:
        set_user_setting(user_id=user_id, key='nav.last.view', value=str(view or ''))
        if str(view or '') == 'library' and library_id:
            set_user_setting(user_id=user_id, key='nav.last.library_id', value=str(library_id))
        elif str(view or '') == 'marker' and marker_id:
            set_user_setting(user_id=user_id, key='nav.last.marker_id', value=str(marker_id))
    except Exception:
        logger.debug('Failed persisting last navigation state for user_id=%s on %s', user_id, logger_context, exc_info=True)


def load_nav_collapsed_flags(*, user_id: int | None) -> dict[str, bool]:
    defaults = {
        'navigation': False,
        'libraries': False,
        'markers': False,
        'auto_markers': False,
    }
    if not user_id:
        return defaults

    out = dict(defaults)
    for section, setting_key in _NAV_SECTION_TO_SETTING_KEY.items():
        try:
            out[section] = bool(get_user_setting_bool(user_id=user_id, key=setting_key, default=False))
        except Exception:
            logger.debug('Failed loading %s for user_id=%s', setting_key, user_id, exc_info=True)
    return out


def apply_nav_collapsed_flags_dict(*, state: dict[str, str | None], flags: dict[str, bool]) -> None:
    state['nav_navigation_collapsed'] = '1' if bool(flags.get('navigation', False)) else '0'
    state['nav_libraries_collapsed'] = '1' if bool(flags.get('libraries', False)) else '0'
    state['nav_markers_collapsed'] = '1' if bool(flags.get('markers', False)) else '0'
    state['nav_auto_markers_collapsed'] = '1' if bool(flags.get('auto_markers', False)) else '0'


def apply_nav_collapsed_flags_attr(*, state: object, flags: dict[str, bool]) -> None:
    setattr(state, 'nav_navigation_collapsed', bool(flags.get('navigation', False)))
    setattr(state, 'nav_libraries_collapsed', bool(flags.get('libraries', False)))
    setattr(state, 'nav_markers_collapsed', bool(flags.get('markers', False)))
    setattr(state, 'nav_auto_markers_collapsed', bool(flags.get('auto_markers', False)))


def persist_nav_collapsed_flag(*, user_id: int | None, section: str, collapsed: bool) -> None:
    if not user_id:
        return
    setting_key = _NAV_SECTION_TO_SETTING_KEY.get(section)
    if not setting_key:
        logger.debug('Unknown nav section for persistence: %s', section)
        return
    try:
        set_user_setting_bool(user_id=user_id, key=setting_key, value=bool(collapsed))
    except Exception:
        logger.debug('Failed persisting %s for user_id=%s', setting_key, user_id, exc_info=True)


def toggle_nav_collapsed_attr(*, state: object, attr: str, user_id: int | None, section: str) -> bool:
    current = bool(getattr(state, attr, False))
    new_value = not current
    setattr(state, attr, new_value)
    persist_nav_collapsed_flag(user_id=user_id, section=section, collapsed=new_value)
    return new_value


def toggle_nav_collapsed_dict(*, state: dict[str, str | None], key: str, user_id: int | None, section: str) -> bool:
    collapsed = str(state.get(key) or '0') == '1'
    new_collapsed = not collapsed
    state[key] = '1' if new_collapsed else '0'
    persist_nav_collapsed_flag(user_id=user_id, section=section, collapsed=new_collapsed)
    return new_collapsed


def make_nav_toggle_handlers_dict(
    *,
    state: dict[str, str | None],
    user_id: int | None,
    on_refresh: Callable[[], None],
) -> tuple[Callable[[], None], Callable[[], None], Callable[[], None], Callable[[], None]]:
    def _toggle_navigation() -> None:
        toggle_nav_collapsed_dict(state=state, key='nav_navigation_collapsed', user_id=user_id, section='navigation')
        on_refresh()

    def _toggle_libraries() -> None:
        toggle_nav_collapsed_dict(state=state, key='nav_libraries_collapsed', user_id=user_id, section='libraries')
        on_refresh()

    def _toggle_markers() -> None:
        toggle_nav_collapsed_dict(state=state, key='nav_markers_collapsed', user_id=user_id, section='markers')
        on_refresh()

    def _toggle_auto_markers() -> None:
        toggle_nav_collapsed_dict(state=state, key='nav_auto_markers_collapsed', user_id=user_id, section='auto_markers')
        on_refresh()

    return _toggle_navigation, _toggle_libraries, _toggle_markers, _toggle_auto_markers


def make_nav_toggle_handlers_attr(
    *,
    state: object,
    user_id: int | None,
    on_refresh: Callable[[], None],
) -> tuple[Callable[[], None], Callable[[], None], Callable[[], None], Callable[[], None]]:
    def _toggle_navigation() -> None:
        toggle_nav_collapsed_attr(state=state, attr='nav_navigation_collapsed', user_id=user_id, section='navigation')
        on_refresh()

    def _toggle_libraries() -> None:
        toggle_nav_collapsed_attr(state=state, attr='nav_libraries_collapsed', user_id=user_id, section='libraries')
        on_refresh()

    def _toggle_markers() -> None:
        toggle_nav_collapsed_attr(state=state, attr='nav_markers_collapsed', user_id=user_id, section='markers')
        on_refresh()

    def _toggle_auto_markers() -> None:
        toggle_nav_collapsed_attr(state=state, attr='nav_auto_markers_collapsed', user_id=user_id, section='auto_markers')
        on_refresh()

    return _toggle_navigation, _toggle_libraries, _toggle_markers, _toggle_auto_markers


def store_nav_intent(intent: dict[str, Any]) -> None:
    try:
        app.storage.user['pv.nav.intent'] = intent
    except Exception:
        logger.debug('Failed storing nav handoff intent', exc_info=True)


def pop_nav_intent() -> dict[str, Any] | None:
    try:
        intent = app.storage.user.pop('pv.nav.intent', None)
    except Exception:
        logger.debug('Failed popping nav handoff intent', exc_info=True)
        return None
    return intent if isinstance(intent, dict) else None


def make_search_handoff_handlers(
    *,
    state: dict[str, str | None],
    handoff: Callable[[dict[str, Any]], None],
    debounce_seconds: float = 0.45,
) -> tuple[Callable[[str], None], Callable[[str], None], Callable[[], None]]:
    """Create search query/mode handlers with a debounced handoff callback."""

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

    search_pending: bool = False
    search_last_change: float = 0.0

    def on_search_change(query: str) -> None:
        nonlocal search_pending, search_last_change
        state['search_query'] = str(query or '')
        search_pending = True
        search_last_change = time.monotonic()

    def on_search_mode_change(mode: str) -> None:
        nonlocal search_pending, search_last_change
        state['search_mode'] = _normalize_search_mode(mode)
        search_pending = True
        search_last_change = time.monotonic()

    def poll() -> None:
        nonlocal search_pending, search_last_change
        if not search_pending:
            return
        if (time.monotonic() - float(search_last_change)) < float(debounce_seconds):
            return
        search_pending = False
        handoff(
            {
                'view': 'search',
                'query': str(state.get('search_query') or ''),
                'mode': _normalize_search_mode(state.get('search_mode') or 'all'),
            }
        )

    return on_search_change, on_search_mode_change, poll


def get_nav_drawer_open(*, user_id: int | None, default: bool = True) -> bool:
    if not user_id:
        return bool(default)
    try:
        return bool(get_user_setting_bool(user_id=user_id, key='ui.nav_drawer.open', default=bool(default)))
    except Exception:
        logger.debug('Failed restoring ui.nav_drawer.open for user_id=%s', user_id, exc_info=True)
        return bool(default)


def persist_nav_drawer_open(*, user_id: int | None, is_open: bool) -> None:
    if not user_id:
        return
    try:
        set_user_setting_bool(user_id=user_id, key='ui.nav_drawer.open', value=bool(is_open))
    except Exception:
        logger.debug('Failed persisting ui.nav_drawer.open for user_id=%s', user_id, exc_info=True)


def toggle_drawer(drawer, *, default_open: bool) -> bool:
    """Toggle a NiceGUI drawer-like component and return the resulting open state."""
    toggle = getattr(drawer, 'toggle', None)
    if callable(toggle):
        toggle()
    else:
        drawer.value = not bool(getattr(drawer, 'value', bool(default_open)))
    return bool(getattr(drawer, 'value', bool(default_open)))


def close_nav_drawer_and_persist(*, drawer, user_id: int, context: str) -> None:
    try:
        drawer.value = False
    except Exception:
        logger.debug('Failed closing %s left drawer', context, exc_info=True)
    persist_nav_drawer_open(user_id=user_id, is_open=False)


def toggle_nav_drawer_and_persist(*, drawer, user_id: int, default_open: bool) -> bool:
    is_open = toggle_drawer(drawer, default_open=default_open)
    persist_nav_drawer_open(user_id=user_id, is_open=is_open)
    return is_open


def get_filters_drawer_open(*, user_id: int | None, default: bool = False) -> bool:
    if not user_id:
        return bool(default)
    try:
        return bool(get_user_setting_bool(user_id=user_id, key='ui.filters_drawer.open', default=bool(default)))
    except Exception:
        logger.debug('Failed restoring ui.filters_drawer.open for user_id=%s', user_id, exc_info=True)
        return bool(default)


def persist_filters_drawer_open(*, user_id: int | None, is_open: bool) -> None:
    if not user_id:
        return
    try:
        set_user_setting_bool(user_id=user_id, key='ui.filters_drawer.open', value=bool(is_open))
    except Exception:
        logger.debug('Failed persisting ui.filters_drawer.open for user_id=%s', user_id, exc_info=True)


def close_filters_drawer_and_persist(*, drawer, user_id: int, context: str) -> None:
    try:
        drawer.value = False
    except Exception:
        logger.debug('Failed closing %s right drawer', context, exc_info=True)
    persist_filters_drawer_open(user_id=user_id, is_open=False)


def toggle_filters_drawer_and_persist(*, drawer, user_id: int, default_open: bool = False) -> bool:
    is_open = toggle_drawer(drawer, default_open=default_open)
    persist_filters_drawer_open(user_id=user_id, is_open=is_open)
    return is_open


def load_inbox_count(*, user_id: int, context: str) -> int:
    try:
        inbox_libs, inbox_papers = list_inbox(user_id=user_id)
        return int(len(inbox_libs) + len(inbox_papers))
    except Exception:
        logger.debug('Failed loading inbox counts on %s (user_id=%s)', context, user_id, exc_info=True)
        return 0


def _redirect_with_label(path: str) -> None:
    ui.timer(0.01, lambda: ui.navigate.to(path), once=True)
    ui.label('Redirecting…').classes('pv-text-dim')


def require_authenticated_user() -> bool:
    if app.storage.user.get('user_id'):
        return True
    ip_address: str | None = None
    try:
        ip_address = str(app.storage.user.get('__client_ip__') or '').strip() or None
    except Exception:
        ip_address = None
    log_event(
        category='auth',
        action='ui_access_denied_unauthenticated',
        level='warning',
        ip_address=ip_address,
        message='UI access denied: user not authenticated',
    )
    _redirect_with_label('/login')
    return False


def require_admin_user() -> bool:
    if bool(app.storage.user.get('is_admin')):
        return True
    user_id: int | None = None
    username: str | None = None
    ip_address: str | None = None
    try:
        raw_user_id = app.storage.user.get('user_id')
        user_id = int(raw_user_id) if raw_user_id is not None else None
    except Exception:
        user_id = None
    try:
        username = str(app.storage.user.get('username') or '').strip() or None
    except Exception:
        username = None
    try:
        ip_address = str(app.storage.user.get('__client_ip__') or '').strip() or None
    except Exception:
        ip_address = None
    log_event(
        category='auth',
        action='ui_admin_denied_non_admin',
        level='warning',
        user_id=user_id,
        username=username,
        ip_address=ip_address,
        message='UI admin access denied: admin role required',
    )
    _redirect_with_label('/')
    return False


def logout_and_redirect_login() -> None:
    from papervisor.auth import logout_user

    logout_user()
    ui.navigate.to('/login')


def render_page_top_bar(
    *,
    user_id: int,
    context: str,
    on_toggle_left,
    on_import,
    on_open_inbox,
    is_admin: bool,
    on_open_profile,
    search_value: str | None = None,
    search_mode: str = 'all',
    on_search_change=None,
    on_search_mode_change=None,
    on_toggle_filters=None,
) -> None:
    inbox_count = load_inbox_count(user_id=user_id, context=context)
    top_bar(
        on_toggle_left=on_toggle_left,
        on_toggle_filters=on_toggle_filters,
        on_import=on_import,
        on_logout=logout_and_redirect_login,
        search_value=search_value,
        search_mode=search_mode,
        on_search_change=on_search_change,
        on_search_mode_change=on_search_mode_change,
        inbox_count=inbox_count,
        on_open_inbox=on_open_inbox,
        is_admin=is_admin,
        on_open_profile=on_open_profile,
    )


def render_navigation_left_drawer(
    *,
    value: bool,
    props: str,
    classes: str,
    on_close: Callable[[], None],
    render_left_nav: Callable[[], None],
    header_label: str = 'Navigation',
    header_row_classes: str = 'pv-drawer-header',
    header_row_style: str | None = None,
    header_label_classes: str = 'text-sm font-semibold pv-text-dimmer',
    header_label_style: str | None = None,
    close_button_props: str = 'flat dense round',
) -> object:
    with ui.left_drawer(value=value).props(props).classes(classes) as left_drawer:
        with ui.row().classes(header_row_classes).style(str(header_row_style or '')):
            if str(header_label or '').strip():
                ui.label(header_label).classes(header_label_classes).style(str(header_label_style or ''))
            ui.button(icon='close', on_click=lambda _e: on_close()).props(close_button_props).classes('pv-drawer-close pv-topbar-btn')
        render_left_nav()
    return left_drawer
