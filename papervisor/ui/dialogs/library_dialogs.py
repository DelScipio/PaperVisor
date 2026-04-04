from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from papervisor.domain import LibraryItem
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_actions_row, dialog_header
from papervisor.services.libraries import create_library, delete_library, list_libraries_for_user, update_library
from papervisor.ui.components.icon_picker import compact_icon_name_row


class LibraryDialogs:
    def __init__(self, *, user_id: int, on_changed: Callable[[], None]) -> None:
        self._user_id = int(user_id)
        self._on_changed = on_changed
        self._create_dialog = ui.dialog()
        self._edit_dialog = ui.dialog()
        self._delete_dialog = ui.dialog()

    def open_create(self) -> None:
        self._create_dialog.clear()
        with self._create_dialog, dialog_card(max_width_class='max-w-xl'):
            dialog_header(title='Create Library', icon='library_add')

            icon_select, _icon_preview, name_input = compact_icon_name_row(icon_value='menu_book')

            description_input = ui.textarea('Description').props('outlined dense autogrow').classes('w-full')

            with dialog_actions_row():
                ui.button('Cancel', on_click=self._create_dialog.close).props('flat color=negative')

                def submit() -> None:
                    try:
                        result = create_library(
                            owner_user_id=int(self._user_id),
                            name=str(name_input.value or ''),
                            description=str(description_input.value or ''),
                            icon=str(icon_select.value or 'menu_book'),
                        )
                    except ValueError as e:
                        ui.notify(str(e), color='negative')
                        return

                    ui.notify(f'Created: {result.library.name}', color='positive')
                    self._create_dialog.close()
                    self._on_changed()

                ui.button('Create', on_click=submit).props('color=primary')

        self._create_dialog.open()

    def open_edit(self, lib: LibraryItem) -> None:
        # Pull latest data to avoid editing stale values
        libs = {l.id: l for l in list_libraries_for_user(user_id=int(self._user_id))}
        lib = libs.get(lib.id, lib)

        self._edit_dialog.clear()
        with self._edit_dialog, dialog_card(max_width_class='max-w-xl'):
            dialog_header(title='Edit Library', icon='edit')

            icon_select, _icon_preview, name_input = compact_icon_name_row(
                icon_value=lib.icon or 'menu_book',
                name_value=lib.name,
            )

            description_input = ui.textarea('Description', value=lib.description or '').props(
                'outlined dense autogrow'
            ).classes('w-full')

            with dialog_actions_row():
                ui.button('Cancel', on_click=self._edit_dialog.close).props('flat color=negative')

                def submit() -> None:
                    try:
                        updated = update_library(
                            user_id=int(self._user_id),
                            library_id=lib.id,
                            name=str(name_input.value or ''),
                            description=str(description_input.value or ''),
                            icon=str(icon_select.value or 'menu_book'),
                        )
                    except ValueError as e:
                        ui.notify(str(e), color='negative')
                        return

                    ui.notify(f'Updated: {updated.name}', color='positive')
                    self._edit_dialog.close()
                    self._on_changed()

                ui.button('Save', on_click=submit).props('color=primary')

        self._edit_dialog.open()

    def open_delete(self, lib: LibraryItem) -> None:
        self._delete_dialog.clear()
        with self._delete_dialog, dialog_card(max_width_class='max-w-xl'):
            dialog_header(title='Delete Library', icon='delete_outline')
            ui.label(f'Delete “{lib.name}”?').classes('text-sm pv-text-dimmer')
            ui.label('Note: files in library_files are not deleted.').classes('text-xs pv-text-dimmer pt-1')

            with dialog_actions_row():
                ui.button('Cancel', on_click=self._delete_dialog.close).props('flat color=negative')

                def confirm() -> None:
                    try:
                        delete_library(user_id=int(self._user_id), library_id=lib.id)
                    except ValueError as e:
                        ui.notify(str(e), color='negative')
                        return

                    ui.notify('Library deleted', color='positive')
                    self._delete_dialog.close()
                    self._on_changed()

                ui.button('Delete', on_click=confirm).props('color=negative')

        self._delete_dialog.open()
