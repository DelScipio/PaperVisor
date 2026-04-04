from __future__ import annotations

from nicegui import ui, app

from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_actions_row, dialog_header
from papervisor.services.audit_logs import log_event
from papervisor.services.settings import get_registration_enabled, set_registration_enabled, settings_available
from papervisor.services.users import create_user, delete_user, list_users, set_password, set_username


def render_users_panel() -> None:
    with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
        dialog_header(
            title='Users',
            icon='group',
            subtitle='Create and manage users.',
            extra_classes='!px-3 !py-2',
            icon_classes='text-base',
            title_classes='text-sm',
            subtitle_classes='text-xs',
        )

    current_username = str(app.storage.user.get('username') or '').strip()
    current_user_id_raw = app.storage.user.get('user_id')
    try:
        current_user_id = int(current_user_id_raw) if current_user_id_raw is not None else None
    except Exception:
        current_user_id = None

    with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
        ui.label('Registration').classes('text-sm font-semibold pv-text-dim')
        ui.label('Allow new users to create their own accounts from the login page.').classes('text-xs pv-text-dimmer')

        can_persist = settings_available()
        if not can_persist:
            ui.label('Registration settings require database migrations.').classes('text-xs pv-text-dim pt-2')
            ui.label('Run: alembic upgrade heads').classes('text-xs pv-text-dimmer')
        else:
            enabled = bool(get_registration_enabled())
            with ui.row().classes('w-full items-center justify-between gap-3 pt-2'):
                ui.label('Enable self-service registration').classes('text-sm pv-text-dim')
                reg_toggle = ui.switch(value=enabled)

            def _apply_reg(_e=None) -> None:
                try:
                    set_registration_enabled(enabled=bool(reg_toggle.value))
                    log_event(
                        category='admin',
                        action='registration_setting_changed',
                        level='info',
                        user_id=current_user_id,
                        username=current_username or None,
                        message='Admin changed self-service registration setting',
                        details={'enabled': bool(reg_toggle.value)},
                    )
                    ui.notify('Registration setting saved', color='positive')
                except Exception as ex:
                    ui.notify(str(ex), color='negative')

            reg_toggle.on('update:model-value', _apply_reg)
            reg_toggle.on('change', _apply_reg)

    with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
        ui.label('Create user').classes('text-sm font-semibold pv-text-dim')
        with ui.row().classes('w-full items-center gap-3 pt-2'):
            username_in = ui.input('Username').props('outlined dense').classes('flex-1')
            password_in = ui.input('Password', password=True, password_toggle_button=True).props('outlined dense').classes(
                'flex-1'
            )
            admin_cb = ui.checkbox('Admin', value=False).classes('text-sm')

        def _create() -> None:
            new_username = str(username_in.value or '').strip()
            try:
                create_user(
                    username=new_username,
                    password=str(password_in.value or ''),
                    is_admin=bool(admin_cb.value),
                )
                log_event(
                    category='admin',
                    action='user_created',
                    level='info',
                    user_id=current_user_id,
                    username=current_username or None,
                    message='Admin created a user',
                    details={'created_username': new_username, 'is_admin': bool(admin_cb.value)},
                )
                username_in.value = ''
                password_in.value = ''
                admin_cb.value = False
                ui.notify('User created', color='positive')
                render_users_body.refresh()
            except Exception as ex:
                ui.notify(str(ex), color='negative')

        with ui.row().classes('w-full justify-end pt-2'):
            ui.button('Create', on_click=_create).props('color=primary').classes('pv-meta-save-btn')

    @ui.refreshable
    def render_users_body() -> None:
        users = list_users()
        if not users:
            ui.label('No users found.').classes('pv-inline-empty')
            return

        with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
            ui.label('Existing users').classes('text-sm font-semibold pv-text-dim')
            with ui.column().classes('w-full gap-2 pt-2'):
                for u in users:
                    with ui.row().classes('w-full items-center justify-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.label(u.username).classes('text-sm')
                            if u.is_admin:
                                ui.badge('admin').props('color="primary"').classes('pv-chip')

                        with ui.row().classes('items-center gap-2'):
                            def _edit_dialog(user_id: int, username: str) -> None:
                                dlg = ui.dialog()
                                with dlg, dialog_card(max_width_class='max-w-xl'):
                                    ui.label(f'Edit user: {username}').classes('text-base font-semibold')
                                    ui.separator().classes('opacity-20 my-2')

                                    new_username = ui.input('Username', value=username).props('outlined dense').classes('w-full')
                                    new_password = ui.input(
                                        'New password (leave empty to keep)',
                                        password=True,
                                        password_toggle_button=True,
                                    ).props('outlined dense').classes('w-full')

                                    def _save() -> None:
                                        try:
                                            nu = str(new_username.value or '').strip()
                                            changed_username = nu != username
                                            if nu != username:
                                                set_username(user_id=user_id, new_username=nu)
                                                # Keep session consistent if you renamed yourself.
                                                if username == current_username:
                                                    app.storage.user['username'] = nu

                                            npw = str(new_password.value or '')
                                            changed_password = bool(npw)
                                            if npw:
                                                set_password(user_id=user_id, new_password=npw)

                                            if changed_username or changed_password:
                                                log_event(
                                                    category='admin',
                                                    action='user_updated',
                                                    level='info',
                                                    user_id=current_user_id,
                                                    username=current_username or None,
                                                    message='Admin updated a user',
                                                    details={
                                                        'target_user_id': int(user_id),
                                                        'target_username_before': username,
                                                        'target_username_after': nu,
                                                        'password_changed': changed_password,
                                                    },
                                                )

                                            ui.notify('User updated', color='positive')
                                            dlg.close()
                                            render_users_body.refresh()
                                        except Exception as ex:
                                            ui.notify(str(ex), color='negative')

                                    with dialog_actions_row():
                                        ui.button('Cancel', on_click=dlg.close).props('flat color=negative').classes('pv-meta-action-btn')
                                        ui.button('Save', on_click=_save).props('color=primary').classes('pv-meta-save-btn')
                                dlg.open()

                            def _reset_pw_dialog(user_id: int, username: str) -> None:
                                dlg = ui.dialog()
                                with dlg, dialog_card(max_width_class='max-w-xl'):
                                    ui.label(f'Reset password: {username}').classes('text-base font-semibold')
                                    ui.separator().classes('opacity-20 my-2')
                                    pw = ui.input('New password', password=True, password_toggle_button=True).props(
                                        'outlined dense'
                                    ).classes('w-full')
                                    ui.label('Enter a new password for this user.').classes('text-xs pv-text-dimmer')

                                    def _save() -> None:
                                        try:
                                            set_password(user_id=user_id, new_password=str(pw.value or ''))
                                            log_event(
                                                category='admin',
                                                action='user_password_reset',
                                                level='warning',
                                                user_id=current_user_id,
                                                username=current_username or None,
                                                message='Admin reset user password',
                                                details={'target_user_id': int(user_id), 'target_username': username},
                                            )
                                            ui.notify('Password updated', color='positive')
                                            dlg.close()
                                        except Exception as ex:
                                            ui.notify(str(ex), color='negative')

                                    with dialog_actions_row():
                                        ui.button('Cancel', on_click=dlg.close).props('flat color=negative').classes('pv-meta-action-btn')
                                        ui.button('Save', on_click=_save).props('color=primary').classes('pv-meta-save-btn')
                                dlg.open()

                            ui.button('Edit', on_click=lambda _e=None, uid=u.id, un=u.username: _edit_dialog(uid, un)).props('flat').classes('pv-meta-action-btn')

                            admin_count = sum(1 for x in users if bool(x.is_admin))
                            can_delete_admin = (not u.is_admin) or (admin_count >= 2)
                            # Allow deleting yourself only when it's safe (not last admin).
                            can_delete_self = (u.username != current_username) or (
                                u.username == current_username and can_delete_admin
                            )
                            can_delete = can_delete_self and can_delete_admin

                            def _delete(user_id: int, username: str, is_admin: bool) -> None:
                                if bool(is_admin) and admin_count < 2:
                                    ui.notify('Cannot delete the last admin user', color='warning')
                                    return
                                try:
                                    delete_user(user_id=user_id)
                                    log_event(
                                        category='admin',
                                        action='user_deleted',
                                        level='warning',
                                        user_id=current_user_id,
                                        username=current_username or None,
                                        message='Admin deleted a user',
                                        details={
                                            'target_user_id': int(user_id),
                                            'target_username': username,
                                            'target_was_admin': bool(is_admin),
                                        },
                                    )
                                    ui.notify('User deleted', color='positive')
                                    if username == current_username:
                                        app.storage.user.clear()
                                        ui.navigate.to('/login')
                                    else:
                                        render_users_body.refresh()
                                except Exception as ex:
                                    ui.notify(str(ex), color='negative')

                            btn = ui.button(
                                'Delete',
                                on_click=lambda _e=None, uid=u.id, un=u.username, ia=u.is_admin: _delete(uid, un, ia),
                            ).props('color=negative').classes('pv-meta-action-btn')
                            if not can_delete:
                                btn.disable()

    render_users_body()
