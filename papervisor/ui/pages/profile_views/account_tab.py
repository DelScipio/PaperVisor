from __future__ import annotations

from nicegui import ui

from papervisor.services.settings import (
    get_ui_remember_location_user_override_allowed,
    settings_available,
    get_global_sharing_enabled,
)
from papervisor.services.users import set_password
from papervisor.services.user_settings import get_user_setting, set_user_setting
from papervisor.services.libraries import list_libraries, get_user_hidden_global_libraries, set_user_hidden_global_libraries
from papervisor.ui.pages.shared_state import resolve_remember_location_mode
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_header


def render_account_tab(
    *,
    user_id: int,
) -> None:
    with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
        dialog_header(
            title='Account',
            icon='person',
            subtitle='Manage your preferences, visibility, and security settings.',
            extra_classes='!px-3 !py-2',
            icon_classes='text-base',
            title_classes='text-sm',
            subtitle_classes='!px-3 !pt-1 !pb-2 !text-xs',
        )

    def _save_user_pref(*, key: str, value: str, success_message: str, failure_prefix: str) -> None:
        try:
            set_user_setting(user_id=user_id, key=key, value=value)
            ui.notify(success_message, color='positive')
        except Exception as e:
            ui.notify(f'{failure_prefix}: {e}', color='negative')

    def _render_action_row(*, label: str, on_click) -> None:
        with ui.row().classes('w-full justify-end gap-2 pt-2'):
            ui.button(label, on_click=on_click).props('color=primary')

    def _account_card(*, extra_classes: str = ''):
        return dialog_card(max_width_class='', extra_classes=extra_classes)

    def _account_select(*, options: dict[str, str], value: str | list[str], label: str):
        return ui.select(options, value=value, label=label).props(
            'outlined dense emit-value map-options'
        ).classes('w-full')

    def _account_section_header(*, title: str, subtitle: str) -> None:
        ui.label(title).classes('text-sm font-semibold pv-text-dim')
        ui.label(subtitle).classes('text-xs pv-text-dimmer')

    def _render_navigation_preferences_section() -> None:
        if not settings_available():
            return

        try:
            show_nav = bool(get_ui_remember_location_user_override_allowed())
        except Exception:
            show_nav = False

        if not show_nav:
            return

        with _account_card(extra_classes='mt-2'):
            _account_section_header(
                title='Navigation',
                subtitle='Control which view is remembered when you return',
            )

            current_mode = resolve_remember_location_mode(user_id=user_id, logger_context='profile page')

            remember_location = _account_select(
                options={'dashboard': 'Dashboard', 'library': 'Library', 'marker': 'Marker'},
                value=current_mode,
                label='Remember last opened',
            )

            def save_nav() -> None:
                _save_user_pref(
                    key='ui.remember_location.mode',
                    value=str(remember_location.value or 'library'),
                    success_message='Navigation preference saved',
                    failure_prefix='Failed to save',
                )

            _render_action_row(label='Save', on_click=save_nav)

    # --- Appearance ---
    with _account_card():
        _account_section_header(title='Appearance', subtitle='Customize the look and feel')

        current_theme = str(
            get_user_setting(user_id=user_id, key='ui.theme', default='dark') or 'dark'
        ).strip().lower()
        if current_theme not in {'dark', 'light'}:
            current_theme = 'dark'

        theme_select = _account_select(
            options={'dark': 'Dark', 'light': 'Light'},
            value=current_theme,
            label='Theme',
        )

        def save_theme() -> None:
            new_theme = str(theme_select.value or 'dark').strip().lower()
            _save_user_pref(
                key='ui.theme',
                value=new_theme,
                success_message='Theme saved',
                failure_prefix='Failed to save theme',
            )
            safe_theme = 'light' if new_theme == 'light' else 'dark'
            ui.run_javascript(
                (
                    "(function(){"
                    f"const theme='{safe_theme}';"
                    "window.dispatchEvent(new CustomEvent('pv-theme-change', { detail: { theme } }));"
                    "if(window.__pvApplyTheme){window.__pvApplyTheme(theme);}"
                    "})();"
                )
            )

        _render_action_row(label='Save', on_click=save_theme)

    # --- Global Libraries ---
    if get_global_sharing_enabled():
        with _account_card(extra_classes='mt-2'):
            _account_section_header(title='Global Libraries', subtitle='Hide global libraries from your views')
            
            # Fetch all global libraries to present as options
            all_libraries = list_libraries()
            global_libs = {str(lib.id): lib.name for lib in all_libraries if lib.scope == 'global'}
            
            if not global_libs:
                ui.label('No global libraries available.').classes('text-xs pv-text-dimmer mt-2')
            else:
                current_hidden_list = get_user_hidden_global_libraries(user_id=user_id)
                hidden_ids: set[str] = {lid for lid in current_hidden_list if lid in global_libs}

                ui.label('Select libraries to hide from your views.').classes('text-xs pv-text-dimmer')
                with ui.column().classes('w-full gap-2 pv-subtle-panel p-3'):
                    for library_id, library_name in sorted(global_libs.items(), key=lambda item: item[1].lower()):
                        checkbox = ui.checkbox(library_name, value=library_id in hidden_ids).props('dense')
                        checkbox.classes('w-full')

                        def _on_toggle(event, lid=library_id) -> None:
                            if bool(event.value):
                                hidden_ids.add(lid)
                            else:
                                hidden_ids.discard(lid)

                        checkbox.on('update:model-value', _on_toggle)

                def save_hidden_libs() -> None:
                    try:
                        set_user_hidden_global_libraries(user_id=user_id, library_ids=sorted(hidden_ids))
                        ui.notify('Hidden libraries updated. Refresh to see changes.', color='positive')
                    except Exception as e:
                        ui.notify(f'Failed to update hidden libraries: {e}', color='negative')

                _render_action_row(label='Save', on_click=save_hidden_libs)

    _render_navigation_preferences_section()

    # --- Security ---
    with _account_card(extra_classes='mt-2'):
        _account_section_header(title='Change Password', subtitle='Update your account password')

        pwd1 = ui.input('New Password', password=True, password_toggle_button=True).props(
            'outlined dense'
        ).classes('w-full')
        pwd2 = ui.input('Confirm Password', password=True).props('outlined dense').classes('w-full')

        ui.label('Leave empty to keep current password.').classes('text-xs pv-text-dimmer')

        def _validate_password_change(password: str, confirmation: str) -> str | None:
            if not password and not confirmation:
                return 'No password entered'
            if not password:
                return 'Password cannot be empty'
            if password != confirmation:
                return 'Passwords do not match'
            return None

        def _notify_warning(message: str) -> None:
            ui.notify(message, color='warning')

        def _notify_error(message: str) -> None:
            ui.notify(message, color='negative')

        def save_password() -> None:
            p1 = str(pwd1.value or '')
            p2 = str(pwd2.value or '')

            validation_error = _validate_password_change(password=p1, confirmation=p2)
            if validation_error:
                _notify_warning(validation_error)
                return

            try:
                set_password(user_id=user_id, new_password=p1)
                pwd1.value = ''
                pwd2.value = ''
                ui.notify('Password updated', color='positive')
            except Exception as e:
                _notify_error(str(e))

        _render_action_row(label='Update Password', on_click=save_password)
