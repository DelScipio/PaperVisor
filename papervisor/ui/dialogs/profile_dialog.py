from __future__ import annotations

from nicegui import ui

from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_actions_row, dialog_header
from papervisor.services.users import set_password


class ProfileDialog:
    def __init__(self, *, user_id: int, username: str) -> None:
        self.user_id = user_id
        self.username = username
        self._dialog = ui.dialog()

    def open(self) -> None:
        self._dialog.clear()
        with self._dialog, dialog_card(max_width_class='max-w-xl'):
            dialog_header(title='Profile', icon='person')

            ui.label(f'Username: {self.username}').classes('text-sm mb-2 pv-text-dimmer')

            ui.separator().classes('opacity-20 my-2')
            ui.label('Change Password').classes('text-sm font-semibold pv-text-dimmer')

            pwd1 = ui.input('New Password', password=True, password_toggle_button=True).props(
                'outlined dense'
            ).classes('w-full')
            pwd2 = ui.input('Confirm Password', password=True).props('outlined dense').classes('w-full')

            ui.label('Leave empty to keep current password.').classes('text-xs pv-text-dimmer')

            def save() -> None:
                p1 = str(pwd1.value or '')
                p2 = str(pwd2.value or '')

                if not p1 and not p2:
                    # No changes
                    self._dialog.close()
                    ui.notify('Settings saved', color='positive')
                    return

                if not p1:
                    ui.notify('Password cannot be empty', color='warning')
                    return
                if p1 != p2:
                    ui.notify('Passwords do not match', color='warning')
                    return

                try:
                    set_password(user_id=self.user_id, new_password=p1)
                    ui.notify('Password updated', color='positive')
                    self._dialog.close()
                except Exception as e:
                    ui.notify(str(e), color='negative')

            with dialog_actions_row():
                ui.button('Cancel', on_click=self._dialog.close).props('flat color=negative')
                ui.button('Save', on_click=save).props('color=primary')

        self._dialog.open()
