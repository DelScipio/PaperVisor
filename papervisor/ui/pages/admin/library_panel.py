from __future__ import annotations

from typing import Callable

from nicegui import ui

from papervisor.services.libraries import list_libraries
from papervisor.services.users import list_users
from papervisor.services.settings import (
    SORT_OPTIONS,
    get_default_sort,
    get_ui_remember_location_default,
    get_ui_remember_location_user_override_allowed,
    set_default_sort,
    set_ui_remember_location_default,
    set_ui_remember_location_user_override_allowed,
    settings_available,
)
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_header
from papervisor.ui.dialogs.library_dialogs import LibraryDialogs


def render_library_panel(
    *,
    dialogs: LibraryDialogs,
    on_changed: Callable[[], None],
    library_owner_user_id: int | None = None,
    owner_user_id_value: str = '',
    on_owner_user_id_change: Callable[[str], None] | None = None,
) -> None:
    with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
        dialog_header(
            title='Library',
            icon='library_books',
            subtitle='Manage libraries and run bulk maintenance.',
            extra_classes='!px-3 !py-2',
            icon_classes='text-base',
            title_classes='text-sm',
            subtitle_classes='text-xs',
        )

    with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
        if on_owner_user_id_change is not None:
            with ui.row().classes('w-full items-center gap-3'):
                ui.label('User').classes('text-xs pv-text-dimmer w-20')
                try:
                    users = list_users()
                    user_opts = {'': 'All users'}
                    for u in users:
                        user_opts[str(int(u.id))] = str(u.username)
                except Exception:
                    user_opts = {'': 'All users'}

                initial_value = str(owner_user_id_value or '').strip()
                if initial_value not in user_opts:
                    initial_value = ''

                sel = ui.select(user_opts, value=initial_value, with_input=True).props('outlined dense').classes('w-full')

                def _on_change(e) -> None:
                    args = getattr(e, 'args', None)
                    v = args.get('value', '') if isinstance(args, dict) else args
                    vv = str(v or '').strip()
                    if vv and vv not in user_opts:
                        vv = ''
                    on_owner_user_id_change(vv)

                sel.on('update:model-value', _on_change)

        ui.label('Libraries').classes('text-sm font-semibold pv-text-dim')
        with ui.row().classes('w-full justify-end'):
            ui.button('New Library', on_click=dialogs.open_create).props('color=primary').classes('pv-meta-save-btn')

        libs = list_libraries(owner_user_id=library_owner_user_id)
        if not libs:
            ui.label('No libraries yet.').classes('pv-inline-empty')
        else:
            with ui.column().classes('w-full gap-2 pt-2'):
                for lib in libs:
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label(f'{lib.name}').classes('text-sm')
                        with ui.row().classes('gap-1'):
                            ui.button('Edit', on_click=lambda _e=None, l=lib: dialogs.open_edit(l)).props('flat').classes('pv-meta-action-btn')
                            ui.button('Delete', on_click=lambda _e=None, l=lib: dialogs.open_delete(l)).props('flat').classes('pv-meta-action-btn')

    sort_options = {o.key: o.label for o in SORT_OPTIONS}

    with ui.card().props('flat bordered').classes('pv-dialog-card w-full mt-2'):
        ui.label('Default sorting of files').classes('text-sm font-semibold pv-text-dim')
        ui.label('Controls the default order used in the main poster grid.').classes('text-xs pv-text-dimmer')

        if not settings_available():
            ui.label('Saving requires database migrations.').classes('text-xs pv-text-dim pt-2')
            ui.label('Run: alembic upgrade heads').classes('text-xs pv-text-dimmer pt-1')
        
        with ui.row().classes('w-full items-center gap-3 pt-2'):
            sort_select = ui.select(sort_options, value=get_default_sort(), label='Sort').props(
                'outlined dense emit-value map-options'
            ).classes('flex-1')

            def _save_sort() -> None:
                try:
                    set_default_sort(str(sort_select.value or 'recent'))
                    ui.notify('Default sorting saved', color='positive')
                except Exception as ex:
                    ui.notify(str(ex), color='negative')

            save_btn = ui.button('Save', on_click=_save_sort).props('color=primary').classes('pv-meta-save-btn')
            if not settings_available():
                save_btn.disable()

    with ui.card().props('flat bordered').classes('pv-dialog-card w-full mt-2'):
        ui.label('Remember last opened').classes('text-sm font-semibold pv-text-dim')
        ui.label('Controls what the app restores after a refresh.').classes('text-xs pv-text-dimmer')

        can_persist = settings_available()
        if not can_persist:
            ui.label('Saving requires database migrations.').classes('text-xs pv-text-dim pt-2')
            ui.label('Run: alembic upgrade heads').classes('text-xs pv-text-dimmer pt-1')

        default_options = {'dashboard': 'Dashboard', 'library': 'Library', 'marker': 'Marker'}
        try:
            current_default = get_ui_remember_location_default() if can_persist else 'library'
        except Exception:
            current_default = 'library'

        try:
            current_user_override = bool(get_ui_remember_location_user_override_allowed()) if can_persist else True
        except Exception:
            current_user_override = True

        with ui.row().classes('w-full items-center gap-3 pt-2'):
            default_select = ui.select(default_options, value=current_default, label='Default').props(
                'outlined dense emit-value map-options'
            ).classes('flex-1')
            override_sw = ui.switch(value=current_user_override).props('dense')
            ui.label('Users can override').classes('text-xs pv-text-dimmer')

        def _save_remember() -> None:
            try:
                set_ui_remember_location_default(str(default_select.value or 'library'))
                set_ui_remember_location_user_override_allowed(allowed=bool(override_sw.value))
                ui.notify('Remember last opened settings saved', color='positive')
            except Exception as ex:
                ui.notify(str(ex), color='negative')

        save_remember_btn = ui.button('Save', on_click=_save_remember).props('color=primary').classes('mt-2 pv-meta-save-btn')
        if not can_persist:
            save_remember_btn.disable()

