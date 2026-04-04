from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from nicegui import ui
from nicegui import app

from papervisor.domain import LibraryItem, PaperItem
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_actions_row, dialog_body, dialog_footer, dialog_header
from papervisor.services.libraries import list_libraries_for_user
from papervisor.services.users import list_users
from papervisor.services.settings import get_global_sharing_enabled, get_global_sharing_requires_approval
from papervisor.services.papers import get_paper
from papervisor.services.sharing import (
    accept_library_share,
    copy_shared_paper_to_library,
    decline_library_share,
    decline_paper_share,
    invite_library_user,
    list_inbox,
    list_library_shares,
    remove_library_share,
    remove_shared_library_for_me,
    set_library_scope,
    share_paper_with_user,
    transfer_library_ownership,
    update_library_share_role,
)

def _user_avatar(username: str, size: str = 'sm', color: str = 'primary') -> None:
    initial = (username[0] if username else '?').upper()
    with ui.avatar(color=color, size=size).props('text-color=white'):
        ui.label(initial).classes('font-medium')


class ShareDialogs:
    def __init__(self, *, user_id: int, on_changed: Callable[[], None]) -> None:
        self._user_id = int(user_id)
        self._on_changed = on_changed
        self._library_dialog = ui.dialog()
        self._paper_dialog = ui.dialog()
        self._inbox_dialog = ui.dialog()
        self._transfer_dialog = ui.dialog()

    def open_share_library(self, lib: LibraryItem) -> None:
        self._library_dialog.clear()

        can_manage = bool(lib.owner_user_id == self._user_id or str(lib.shared_role or '') == 'editor')
        if not can_manage:
            ui.notify('Not allowed', color='negative')
            return

        with self._library_dialog, dialog_card(max_width_class='max-w-3xl', extra_classes='overflow-hidden'):
            dialog_header(title='Share Library', icon='folder_shared')

            with ui.row().classes('w-full items-center gap-4 mt-3 mb-3 p-3 pv-subtle-panel'):
                ui.icon('folder_shared', size='md').classes('text-primary')
                with ui.column().classes('gap-0'):
                    ui.label(lib.name).classes('text-base font-medium')
                    if lib.owner_user_id == self._user_id:
                        ui.label('You are the owner').classes('text-xs pv-text-dimmer')
                    elif getattr(lib, 'owner_username', None):
                        ui.label(f'Owned by {lib.owner_username}').classes('text-xs pv-text-dimmer')

            is_owner = bool(lib.owner_user_id == self._user_id)
            is_admin = bool(app.storage.user.get('is_admin'))
            scope_val = str(getattr(lib, 'scope', 'private') or 'private')
            global_enabled = get_global_sharing_enabled()
            requires_approval = get_global_sharing_requires_approval()

            scope_opts = {
                'private': 'Private (only me)',
                'shared': 'Shared (invites only)',
            }
            if global_enabled or scope_val == 'global' or scope_val == 'pending_global':
                if requires_approval and not is_admin:
                    scope_opts['pending_global'] = 'Global (requires approval)'
                else:
                    scope_opts['global'] = 'Global (everyone can read)'
                    
                if scope_val == 'global':
                    scope_opts['global'] = 'Global (everyone can read)'
                elif scope_val == 'pending_global':
                    scope_opts['pending_global'] = 'Global (Pending Admin Approval)'

            with ui.row().classes('w-full items-center justify-between gap-4 py-2'):
                with ui.column().classes('gap-1'):
                    ui.label('Library Access').classes('text-sm font-semibold')
                    if scope_val == 'private':
                        ui.label('Only you have access to this library.').classes('text-xs pv-text-dimmer max-w-[300px]')
                    elif scope_val == 'shared':
                        ui.label('You can invite specific users to view or edit.').classes('text-xs pv-text-dimmer max-w-[300px]')
                    elif scope_val == 'global':
                        ui.label('Everyone can read this library.').classes('text-xs pv-text-dimmer max-w-[300px]')
                    elif scope_val == 'pending_global':
                        ui.label('Waiting for admin approval to be visible globally.').classes('text-xs pv-warning-text max-w-[300px]')

                def _set_scope(s: str):
                    nonlocal scope_val
                    scope_val = s
                    scope_btn.text = scope_opts[s]

                scope_btn = ui.button(scope_opts.get(scope_val, scope_val)).props('flat no-caps icon-right=expand_more outline color=primary')
                if not is_owner:
                    scope_btn.disable()
                
                with scope_btn:
                    with ui.menu().classes('pv-menu pv-no-shadow'):
                        for k, v in scope_opts.items():
                            if k == 'pending_global' and not requires_approval and not scope_val == 'pending_global':
                                continue # only Admins should see the un-pending variant, which is handled
                            if k == 'global' and not is_admin and requires_approval and scope_val != 'global':
                                k_use = 'pending_global'
                            else:
                                k_use = k
                            ui.menu_item(scope_opts.get(k_use, v), on_click=lambda k_use=k_use: _set_scope(k_use))

            if scope_val != 'private':
                ui.separator().classes('opacity-20 my-4')
                ui.label('Invite User').classes('text-sm font-semibold mb-2')
                
                with ui.row().classes('w-full items-center gap-2 p-2 pv-subtle-panel'):
                    users = list_users()
                    user_opts = [u.username for u in users]
                    user_sel = ui.select(user_opts, label='Search by username', value=None).props('outlined dense use-input fill-input input-debounce="0" hide-selected borderless').classes('flex-grow')
                    
                    role_val = 'reader'
                    role_btn = ui.button(role_val.title()).props('flat no-caps icon-right=expand_more')
                    with role_btn:
                        with ui.menu().classes('pv-menu pv-no-shadow'):
                            def _set_role(r: str):
                                nonlocal role_val
                                role_val = r
                                role_btn.text = r.title()
                            ui.menu_item('Reader', on_click=lambda: _set_role('reader'))
                            ui.menu_item('Editor', on_click=lambda: _set_role('editor'))

                    def _invite() -> None:
                        try:
                            if not str(user_sel.value or '').strip():
                                raise ValueError('Select a user to invite')
                            invite_library_user(
                                user_id=self._user_id,
                                library_id=str(lib.id),
                                target_username=str(user_sel.value or ''),
                                role=role_val,
                            )
                            ui.notify('Invite sent', color='positive')
                            self._on_changed()
                            self.open_share_library(lib)
                        except Exception as ex:
                            ui.notify(str(ex), color='negative')

                    ui.button('Invite', on_click=_invite).props('color=primary unelevated no-caps px-4')

                ui.separator().classes('opacity-20 my-4')
                ui.label('Shared with').classes('text-sm font-semibold mb-2')

                try:
                    shares = list_library_shares(user_id=self._user_id, library_id=str(lib.id))
                except Exception as ex:
                    shares = []
                    ui.label(str(ex)).classes('text-xs pv-text-dimmer')

                if not shares and is_owner:
                    with ui.column().classes('w-full items-center justify-center p-4 py-8 pv-share-empty'):
                        ui.icon('group_add', size='md').classes('pv-text-dimmer mb-2')
                        ui.label('Not shared with anyone yet').classes('text-sm pv-text-dimmer text-center')
                else:
                    with ui.column().classes('w-full gap-2'):
                        # Display owner
                        with ui.row().classes('w-full items-center justify-between p-2 rounded pv-share-hover-row'):
                            with ui.row().classes('items-center gap-3'):
                                _user_avatar(lib.owner_username or 'Owner', color='orange-6' if is_owner else 'grey-6')
                                with ui.column().classes('gap-0'):
                                    ui.label(f"{lib.owner_username or 'Owner'} (You)" if is_owner else lib.owner_username).classes('text-sm font-medium')
                                    ui.label('Owner').classes('text-xs pv-text-dimmer')
                            
                        # Display shares
                        for s in shares:
                            with ui.row().classes('w-full items-center justify-between p-2 rounded pv-share-hover-row'):
                                with ui.row().classes('items-center gap-3'):
                                    _user_avatar(s.username, color='cyan-6' if s.status == 'pending' else 'blue-6')
                                    with ui.column().classes('gap-0'):
                                        ui.label(s.username).classes('text-sm font-medium')
                                        if s.status == 'pending':
                                            ui.badge('Pending', color='warning', text_color='black').props('outline').classes('text-[10px] mt-0.5 px-1 py-0 min-h-0')

                                with ui.row().classes('items-center gap-2'):
                                    ui.label(str(s.role).title()).classes('text-xs pv-text-dimmer mr-2')

                                    def _save_role(role_val: str, shared_user_id=int(s.user_id)):
                                        try:
                                            update_library_share_role(
                                                user_id=self._user_id,
                                                library_id=str(lib.id),
                                                shared_with_user_id=int(shared_user_id),
                                                role=role_val,
                                            )
                                            ui.notify('Role updated', color='positive')
                                            self._on_changed()
                                            self.open_share_library(lib)
                                        except Exception as ex:
                                            ui.notify(str(ex), color='negative')

                                    def _remove(_e=None, shared_user_id=int(s.user_id)):
                                        try:
                                            remove_library_share(
                                                user_id=self._user_id,
                                                library_id=str(lib.id),
                                                shared_with_user_id=int(shared_user_id),
                                            )
                                            ui.notify('Removed', color='positive')
                                            self._on_changed()
                                            self.open_share_library(lib)
                                        except Exception as ex:
                                            ui.notify(str(ex), color='negative')

                                    if is_owner or self._user_id == s.user_id:
                                        with ui.button(icon='more_vert').props('flat round dense size=sm'):
                                            with ui.menu().classes('pv-menu pv-no-shadow'):
                                                if is_owner:
                                                    ui.menu_item('Set as Reader', on_click=lambda: _save_role('reader'))
                                                    ui.menu_item('Set as Editor', on_click=lambda: _save_role('editor'))
                                                    ui.separator()
                                                
                                                if is_owner or self._user_id == s.user_id:
                                                    lbl = 'Cancel Invite' if s.status == 'pending' else ('Leave Library' if self._user_id == s.user_id else 'Remove Access')
                                                    ui.menu_item(lbl, on_click=_remove).props('text-color=negative')

            ui.separator().classes('opacity-20 my-4')
            with ui.row().classes('w-full justify-between items-center'):
                if is_owner and scope_val != 'private':
                    ui.button('Transfer Ownership', icon='swap_horiz', on_click=lambda _e=None, l=lib: self.open_transfer_owner(l)).props('flat no-caps text-color=grey-7')
                else:
                    ui.element('div')

                with ui.row().classes('gap-2'):
                    ui.button('Close', on_click=self._library_dialog.close).props('flat no-caps')

                    def _save_scope() -> None:
                        if not is_owner:
                            self._library_dialog.close()
                            return
                        try:
                            # If pending global, use that, else use scope_val normally
                            set_library_scope(user_id=self._user_id, library_id=str(lib.id), scope=scope_val)
                            ui.notify('Scope updated', color='positive')
                            self._on_changed()
                            self._library_dialog.close()
                        except Exception as ex:
                            ui.notify(str(ex), color='negative')

                    ui.button('Save Changes', on_click=_save_scope).props('color=primary unelevated no-caps')

        self._library_dialog.open()

    def open_share_paper(self, paper: PaperItem) -> None:
        self._paper_dialog.clear()
        with self._paper_dialog, dialog_card(max_width_class='max-w-2xl', extra_classes='p-0 overflow-hidden'):
            dialog_header(title='Share File', icon='description')

            with dialog_body():
                with ui.row().classes('w-full items-center gap-4 mb-1 p-3 pv-subtle-panel flex-nowrap'):
                    ui.icon('description', size='md').classes('text-primary shrink-0')
                    with ui.column().classes('gap-0 min-w-0 flex-grow'):
                        ui.label(str(paper.title or 'Unknown Title')).classes('text-base font-medium ellipsis w-full overflow-hidden whitespace-nowrap')

                users = list_users()
                user_opts = [u.username for u in users]
                ui.label('Select User').classes('text-sm font-medium mb-1')
                user_sel = ui.select(user_opts, label='Search by username', value=None).props('outlined dense use-input fill-input input-debounce="0" hide-selected w-full').classes('pv-meta-field')

                with dialog_actions_row(extra_classes='pt-6'):
                    ui.button('Cancel', on_click=self._paper_dialog.close).props('flat no-caps color=negative')

                    def _share() -> None:
                        try:
                            if not str(user_sel.value or '').strip():
                                raise ValueError('Select a user to share with')
                            share_paper_with_user(
                                user_id=self._user_id,
                                paper_id=str(paper.id),
                                target_username=str(user_sel.value or ''),
                            )
                            ui.notify('Shared successfully', color='positive')
                            self._paper_dialog.close()
                        except Exception as ex:
                            ui.notify(str(ex), color='negative')

                    ui.button('Share File', icon='send', on_click=_share).props('color=primary unelevated no-caps')

        self._paper_dialog.open()

    def open_inbox(self) -> None:
        self._inbox_dialog.clear()
        with self._inbox_dialog, dialog_card(max_width_class='max-w-3xl', extra_classes='pv-flat-dialog-card overflow-hidden'):
            dialog_header(title='Inbox & Notifications', icon='inbox')

            libs, papers = list_inbox(user_id=self._user_id)

            with ui.element('div').classes('w-full max-h-[60vh] overflow-auto scroll'):
                with dialog_body(extra_classes='gap-6 pt-2'):
                    # Library Invites Section
                    with ui.column().classes('w-full gap-2'):
                        ui.label('Library Invites').classes('text-sm font-semibold text-primary')
                        if not libs:
                            with ui.row().classes('w-full items-center justify-center p-6 pv-share-empty'):
                                ui.label('No pending library invitations.').classes('text-sm pv-text-dimmer')
                        else:
                            with ui.column().classes('w-full gap-2'):
                                for inv in libs:
                                    with ui.row().classes('pv-share-row items-center justify-between p-3'):
                                        with ui.row().classes('items-center gap-3'):
                                            _user_avatar(inv.from_username or 'System', color='indigo-5')
                                            with ui.column().classes('gap-0'):
                                                # Use row for title to keep it on one line if possible
                                                with ui.row().classes('items-center gap-1'):
                                                    ui.label(inv.library_name).classes('text-sm font-bold')
                                                    ui.label('•').classes('pv-text-dimmer text-xs')
                                                    ui.label(inv.role.title()).classes('text-xs font-medium uppercase tracking-wider text-primary')
                                                
                                                if inv.from_username:
                                                    ui.label(f"Invited by {inv.from_username}").classes('text-xs pv-text-dimmer')

                                        with ui.row().classes('items-center gap-2'):
                                            def _accept(_e=None, library_id=str(inv.library_id)):
                                                try:
                                                    accept_library_share(user_id=self._user_id, library_id=library_id)
                                                    ui.notify('Accepted library invite', color='positive')
                                                    self._on_changed()
                                                    self.open_inbox()
                                                except Exception as ex:
                                                    ui.notify(str(ex), color='negative')

                                            def _decline(_e=None, library_id=str(inv.library_id)):
                                                try:
                                                    decline_library_share(user_id=self._user_id, library_id=library_id)
                                                    ui.notify('Declined library invite', color='positive')
                                                    self._on_changed()
                                                    self.open_inbox()
                                                except Exception as ex:
                                                    ui.notify(str(ex), color='negative')

                                            ui.button('Decline', on_click=_decline).props('flat no-caps text-color=negative')
                                            ui.button('Accept', icon='check', on_click=_accept).props('unelevated color=positive no-caps')

                    # File Shares Section
                    with ui.column().classes('w-full gap-2 pt-2'):
                        ui.label('File Shares').classes('text-sm font-semibold text-primary')
                        if not papers:
                            with ui.row().classes('w-full items-center justify-center p-6 pv-share-empty'):
                                ui.label('No pending file shares.').classes('text-sm pv-text-dimmer')
                        else:
                            owned_libs = [l for l in list_libraries_for_user(user_id=self._user_id) if int(l.owner_user_id or 0) == self._user_id]
                            lib_opts = {l.id: l.name for l in owned_libs}

                            with ui.column().classes('w-full gap-2'):
                                for inv in papers:
                                    with ui.row().classes('pv-share-row items-start md:items-center justify-between p-3 flex-wrap gap-3'):
                                        with ui.row().classes('items-center gap-3 min-w-0 flex-grow w-full md:w-auto'):
                                            _user_avatar(inv.from_username or 'System', color='cyan-6')
                                            with ui.column().classes('gap-0 min-w-0 flex-grow'):
                                                # Enable ellipsis for long file names
                                                ui.label(inv.title).classes('text-sm font-bold ellipsis w-full overflow-hidden whitespace-nowrap md:max-w-[320px]')
                                                if inv.from_username:
                                                    ui.label(f"Shared by {inv.from_username}").classes('text-xs pv-text-dimmer')

                                        with ui.row().classes('pv-share-actions items-center gap-2 justify-end w-full md:w-auto mt-1 md:mt-0 flex-wrap md:flex-nowrap'):
                                            target_sel = ui.select(lib_opts, label='Save to Library', value=None).props('outlined dense use-input fill-input input-debounce="0" hide-selected borderless').classes('pv-meta-field pv-share-target')
                                            if lib_opts:
                                                target_sel.value = list(lib_opts.keys())[0]

                                            def _accept_file(_e=None, share_id=int(inv.share_id), sel=target_sel):
                                                try:
                                                    if not str(sel.value or '').strip():
                                                        raise ValueError('Choose a destination library')
                                                    new_paper_id = copy_shared_paper_to_library(
                                                        user_id=self._user_id,
                                                        share_id=int(share_id),
                                                        target_library_id=str(sel.value),
                                                    )

                                                    new_row = get_paper(paper_id=str(new_paper_id))
                                                    original_name = (str(inv.title or '').strip() or '')
                                                    final_name = ''
                                                    if new_row is not None:
                                                        final_name = Path(str(getattr(new_row, 'file_path', '') or '')).name

                                                    if original_name and final_name and original_name != final_name:
                                                        ui.notify(f'Name existed, saved as {final_name}', color='info')

                                                    ui.notify('Copied into library successfully', color='positive')
                                                    self._on_changed()
                                                    self.open_inbox()
                                                except Exception as ex:
                                                    ui.notify(str(ex), color='negative')

                                            def _decline_file(_e=None, share_id=int(inv.share_id)):
                                                try:
                                                    decline_paper_share(user_id=self._user_id, share_id=int(share_id))
                                                    ui.notify('Declined shared file', color='positive')
                                                    self._on_changed()
                                                    self.open_inbox()
                                                except Exception as ex:
                                                    ui.notify(str(ex), color='negative')

                                            ui.button('Decline', on_click=_decline_file).props('flat no-caps text-color=negative').classes('pv-share-decline-btn')
                                            ui.button('Accept', icon='download', on_click=_accept_file).props('unelevated color=positive no-caps').classes('pv-share-accept-btn')

            with dialog_footer():
                ui.button('Close', on_click=self._inbox_dialog.close).props('flat no-caps')

        self._inbox_dialog.open()

    def open_transfer_owner(self, lib: LibraryItem) -> None:
        self._transfer_dialog.clear()

        if int(lib.owner_user_id or 0) != self._user_id:
            ui.notify('Not allowed', color='negative')
            return

        with self._transfer_dialog, dialog_card(max_width_class='max-w-xl', extra_classes='p-6'):
            dialog_header(
                title='Transfer Ownership',
                icon='swap_horiz',
                subtitle=str(lib.name),
                icon_classes='pv-warning-text',
                title_classes='pv-warning-text',
            )

            ui.separator().classes('opacity-20 my-4')
            
            ui.label('Warning: Transferring ownership is permanent. The new owner must have already accepted an invitation to this library.').classes('text-xs pv-warning-text mb-4 font-medium p-3 pv-warn-panel')

            shares = list_library_shares(user_id=self._user_id, library_id=str(lib.id))
            accepted = [s for s in shares if str(s.status) == 'accepted']
            
            if not accepted:
                ui.label('No users have accepted an invitation to this library yet. You can only transfer ownership to active members.').classes('text-sm pv-text-dimmer')
            else:
                ui.label('Select New Owner').classes('text-sm font-semibold mb-2')
                
                # Use a custom UI select to show avatars if possible, or just standard select
                opts = {int(s.user_id): s.username for s in accepted}
                sel = ui.select(opts, label='New owner', value=(list(opts.keys())[0] if opts else None)).props('outlined use-input fill-input input-debounce="0" hide-selected w-full').classes('pv-meta-field')

            with dialog_actions_row(extra_classes='pt-6'):
                ui.button('Cancel', on_click=self._transfer_dialog.close).props('flat no-caps color=negative')

                def _transfer() -> None:
                    try:
                        if not accepted:
                            self._transfer_dialog.close()
                            return
                        if not sel.value:
                            raise ValueError('Choose a new owner')
                        transfer_library_ownership(
                            user_id=self._user_id,
                            library_id=str(lib.id),
                            new_owner_user_id=int(sel.value),
                        )
                        ui.notify('Ownership transferred successfully', color='positive')
                        self._transfer_dialog.close()
                        self._on_changed()
                    except Exception as ex:
                        ui.notify(str(ex), color='negative')

                if accepted:
                    ui.button('Transfer Permanent Ownership', icon='warning', on_click=_transfer).props('color=negative unelevated no-caps')
                else:
                    ui.button('Close', on_click=self._transfer_dialog.close).props('color=primary unelevated no-caps')

        self._transfer_dialog.open()

    def remove_shared_library(self, lib: LibraryItem) -> None:
        try:
            remove_shared_library_for_me(user_id=self._user_id, library_id=str(lib.id))
            ui.notify('Removed', color='positive')
            self._on_changed()
        except Exception as ex:
            ui.notify(str(ex), color='negative')
