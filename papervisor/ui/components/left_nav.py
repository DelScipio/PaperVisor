from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from papervisor.domain import LibraryItem
from papervisor.domain import MarkerItem


def left_nav(
    *,
    libraries: list[LibraryItem],
    markers: list[MarkerItem] | None = None,
    active_view: str | None = None,
    active_library_id: str | None = None,
    active_marker_id: str | None = None,
    on_add_library: Callable[[], None],
    on_edit_library: Callable[[LibraryItem], None],
    on_delete_library: Callable[[LibraryItem], None],
    on_share_library: Callable[[LibraryItem], None] | None = None,
    on_remove_shared_library: Callable[[LibraryItem], None] | None = None,
    on_open_dashboard: Callable[[], None] | None = None,
    on_open_show_all: Callable[[], None] | None = None,
    on_open_recent: Callable[[], None] | None = None,
    on_select_library: Callable[[LibraryItem], None] | None = None,
    favorite_count: int | None = None,
    on_open_favorites_shelf: Callable[[], None] | None = None,
    to_read_count: int | None = None,
    on_open_to_read_shelf: Callable[[], None] | None = None,
    on_add_marker: Callable[[], None] | None = None,
    on_add_auto_marker: Callable[[], None] | None = None,
    on_select_marker: Callable[[MarkerItem], None] | None = None,
    on_edit_marker: Callable[[MarkerItem], None] | None = None,
    on_delete_marker: Callable[[MarkerItem], None] | None = None,
    navigation_collapsed: bool = False,
    libraries_collapsed: bool = False,
    markers_collapsed: bool = False,
    auto_markers_collapsed: bool = False,
    on_toggle_navigation: Callable[[], None] | None = None,
    on_toggle_libraries: Callable[[], None] | None = None,
    on_toggle_markers: Callable[[], None] | None = None,
    on_toggle_auto_markers: Callable[[], None] | None = None,
) -> None:
    av = str(active_view or '').strip().lower()
    alib = str(active_library_id or '').strip()
    amarker = str(active_marker_id or '').strip()

    marker_list = markers or []

    def nav_button(
        *,
        icon: str,
        label: str,
        on_click: Callable[[], None] | None = None,
        badge: str | None = None,
        on_badge_menu: Callable[[], None] | None = None,
        active: bool = False,
    ) -> None:
        props = 'flat no-caps dense'
        btn_classes = 'pv-nav-btn w-full block justify-start'
        if active:
            btn_classes += ' pv-nav-btn--active'
        handler = on_click or (lambda: None)
        with ui.button(on_click=handler).props(props).classes(btn_classes):
            with ui.row().classes('w-full items-center gap-2 no-wrap'):
                ui.icon(icon).classes('pv-nav-icon')
                ui.label(label).style('font-size:14px;')
                ui.space()
                if badge is not None:
                    if on_badge_menu is None:
                        with ui.element('div').classes('pv-nav-badge-slot'):
                            ui.badge(badge).props('color="primary"').classes('pv-chip')
                    else:
                        with ui.element('div').classes('pv-nav-badge-slot'):
                            with ui.button(badge, on_click=on_badge_menu).props('flat dense no-caps').classes('pv-chip pv-nav-chip-btn'):
                                pass

    with ui.element('div').classes('pv-nav-section-header'):
        if on_toggle_navigation is not None:
            with ui.button(on_click=on_toggle_navigation).props('flat no-caps dense').classes('pv-nav-section-toggle'):
                ui.label('Navigation').classes('pv-nav-section-label')
                ui.icon('chevron_right' if navigation_collapsed else 'expand_more').classes('pv-text-dimmer').style('font-size:16px;')
        else:
            ui.label('Navigation').classes('pv-nav-section-label')

    if not navigation_collapsed:
        with ui.column().classes('w-full px-2 gap-0'):
            nav_button(icon='home', label='Dashboard', on_click=on_open_dashboard, active=(av == 'dashboard'))
            nav_button(icon='description', label='All Files', on_click=on_open_show_all, active=(av == 'all'))
            nav_button(icon='schedule', label='Recently added', on_click=(on_open_recent or on_open_dashboard), active=(av == 'recent'))
            nav_button(
                icon='bookmark',
                label='To Read',
                on_click=on_open_to_read_shelf,
                badge=(None if to_read_count is None else str(int(to_read_count))),
                active=(av == 'to_read'),
            )
            nav_button(
                icon='favorite',
                label='Favorites',
                on_click=on_open_favorites_shelf,
                badge=(None if favorite_count is None else str(int(favorite_count))),
                active=(av == 'favorites'),
            )

    ui.element('div').classes('pv-nav-section-divider')

    with ui.element('div').classes('pv-nav-section-header'):
        if on_toggle_libraries is not None:
            with ui.button(on_click=on_toggle_libraries).props('flat no-caps dense').classes('pv-nav-section-toggle'):
                ui.label('Libraries').classes('pv-nav-section-label')
                ui.icon('chevron_right' if libraries_collapsed else 'expand_more').classes('pv-text-dimmer').style('font-size:16px;')
        else:
            ui.label('Libraries').classes('pv-nav-section-label')
        ui.button(icon='add', on_click=on_add_library).props('dense flat round size=sm').classes('pv-nav-add-btn')
    with ui.column().classes('w-full px-2 gap-0'):
        if libraries_collapsed:
            pass
        elif libraries:
            for lib in libraries:
                lib_click = (
                    (lambda _e, l=lib: on_select_library(l))
                    if on_select_library is not None
                    else (lambda _e, l=lib: None)
                )

                badge_color = 'purple'
                if lib.scope == 'global':
                    badge_color = 'green'
                elif lib.scope == 'shared':
                    badge_color = 'blue'

                menu_items: list[tuple[str, Callable[[], None]]] = []
                if bool(getattr(lib, 'is_shared_with_me', False)):
                    if on_remove_shared_library is not None:
                        menu_items.append(('Remove shared', lambda l=lib: on_remove_shared_library(l)))
                    if str(getattr(lib, 'shared_role', '') or '') == 'editor' and on_share_library is not None:
                        menu_items.insert(0, ('Share', lambda l=lib: on_share_library(l)))
                elif bool(getattr(lib, 'is_owned_by_me', False)):
                    menu_items.append(('Edit', lambda l=lib: on_edit_library(l)))
                    if on_share_library is not None:
                        menu_items.append(('Share', lambda l=lib: on_share_library(l)))
                    menu_items.append(('Delete', lambda l=lib: on_delete_library(l)))

                row_class = 'pv-lib-row w-full'
                if not menu_items:
                    row_class += ' pv-no-menu'

                with ui.element('div').classes(row_class):
                    with ui.button(on_click=lib_click).props('flat no-caps dense').classes(
                        'pv-nav-btn w-full block justify-start'
                        + (' pv-nav-btn--active' if (av == 'library' and str(lib.id) == alib) else '')
                    ):
                        with ui.row().classes('w-full items-center gap-2 no-wrap'):
                            ui.icon(lib.icon or 'menu_book').classes('pv-nav-icon')
                            ui.label(lib.name).style('font-size:14px;')
                            ui.space()
                            with ui.element('div').classes('pv-lib-count'):
                                ui.badge(str(lib.paper_count)).props(f'color="{badge_color}"').classes('pv-chip')

                    if menu_items:
                        with ui.button(icon='more_vert').props('flat round dense size=sm').classes('pv-lib-menu pv-action-dots'):
                            with ui.menu():
                                for (label, cb) in menu_items:
                                    ui.menu_item(label, on_click=lambda _e, c=cb: c())
        else:
            ui.label('No libraries yet').classes('text-xs pv-text-dimmer px-2')

    ui.element('div').classes('pv-nav-section-divider')

    with ui.element('div').classes('pv-nav-section-header'):
        if on_toggle_markers is not None:
            with ui.button(on_click=on_toggle_markers).props('flat no-caps dense').classes('pv-nav-section-toggle'):
                ui.label('Markers').classes('pv-nav-section-label')
                ui.icon('chevron_right' if markers_collapsed else 'expand_more').classes('pv-text-dimmer').style('font-size:16px;')
        else:
            ui.label('Markers').classes('pv-nav-section-label')
        if on_add_marker is not None or on_add_auto_marker is not None:
            if on_add_marker is not None and on_add_auto_marker is not None:
                with ui.button(icon='add').props('dense flat round size=sm').classes('pv-nav-menu-btn'):
                    with ui.menu():
                        ui.menu_item('New Marker', on_click=lambda: on_add_marker())
                        ui.menu_item('New Auto Marker', on_click=lambda: on_add_auto_marker())
            elif on_add_marker is not None:
                ui.button(icon='add', on_click=on_add_marker).props('dense flat round size=sm').classes('pv-nav-add-btn')
            elif on_add_auto_marker is not None:
                ui.button(icon='add', on_click=on_add_auto_marker).props('dense flat round size=sm').classes('pv-nav-add-btn')

    def _render_marker(sh: MarkerItem) -> None:
        badge = str(int(getattr(sh, 'paper_count', 0) or 0))

        select_marker_cb = on_select_marker

        def _on_select_marker(_e=None, s=sh) -> None:
            if select_marker_cb is not None:
                select_marker_cb(s)

        has_marker_menu = on_edit_marker is not None or on_delete_marker is not None

        with ui.element('div').classes('pv-lib-row w-full' + ('' if has_marker_menu else ' pv-no-menu')):
            with ui.button(on_click=_on_select_marker).props('flat no-caps dense').classes(
                'pv-nav-btn w-full block justify-start'
                + (' pv-nav-btn--active' if (av == 'marker' and str(sh.id) == amarker) else '')
            ):
                with ui.row().classes('w-full items-center gap-2 no-wrap'):
                    ui.icon(str(sh.icon or 'category')).classes('pv-nav-icon')
                    ui.label(str(sh.name)).style('font-size:14px;')
                    ui.space()
                    with ui.element('div').classes('pv-lib-count'):
                        ui.badge(badge).props('color="primary"').classes('pv-chip')

            if has_marker_menu:
                with ui.button(icon='more_vert').props('flat round dense size=sm').classes('pv-lib-menu pv-action-dots'):
                    with ui.menu():
                        if on_edit_marker is not None:
                            edit_cb = on_edit_marker
                            ui.menu_item('Edit', on_click=lambda _e, s=sh, cb=edit_cb: cb(s) if cb is not None else None)
                        if on_delete_marker is not None:
                            delete_cb = on_delete_marker
                            ui.menu_item('Delete', on_click=lambda _e, s=sh, cb=delete_cb: cb(s) if cb is not None else None)

    if not markers_collapsed:
        with ui.column().classes('w-full px-2 gap-0'):
            for sh in marker_list:
                _render_marker(sh)
