from nicegui import ui

from papervisor.services.settings import (
    get_global_sharing_enabled,
    set_global_sharing_enabled,
    get_global_sharing_requires_approval,
    set_global_sharing_requires_approval,
)
from papervisor.db.session import get_session
from papervisor.db.models import Library, LibraryShare, User
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_header
from sqlalchemy import select


def render_global_libraries_panel() -> None:
    """Render the admin panel for managing global libraries and sharing settings."""

    # UI state
    enabled = get_global_sharing_enabled()
    requires_approval = get_global_sharing_requires_approval()

    with ui.column().classes('w-full gap-4'):
        with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
            dialog_header(
                title='Global Libraries',
                icon='language',
                subtitle='Manage global sharing configuration and visibility for system-wide libraries.',
                extra_classes='!px-3 !py-2',
                icon_classes='text-base',
                title_classes='text-sm',
                subtitle_classes='text-xs',
            )

        with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
            ui.label('Global Sharing Configuration').classes('text-sm font-semibold pv-text-dim')
            
            with ui.row().classes('w-full gap-8'):
                with ui.column().classes('gap-1'):
                    def _toggle_enabled(e: ui.switch) -> None:
                        set_global_sharing_enabled(enabled=bool(e.value))
                        ui.notify('Global sharing config updated', color='positive')

                    ui.switch('Allow Global Sharing', value=enabled, on_change=_toggle_enabled).classes('font-medium')
                    ui.label('If checked, users can request to make their libraries visible to everyone in the instance.').classes('text-xs pv-text-dimmer ml-2')

                with ui.column().classes('gap-1'):
                    def _toggle_approval(e: ui.switch) -> None:
                        set_global_sharing_requires_approval(requires_approval=bool(e.value))
                        ui.notify('Admin approval config updated', color='positive')

                    ui.switch('Require Admin Approval', value=requires_approval, on_change=_toggle_approval).classes('font-medium')
                    ui.label('If checked, global sharing requests must be approved by an administrator before taking effect.').classes('text-xs pv-text-dimmer ml-2')

        with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
            ui.label('Global Libraries Management').classes('text-sm font-semibold pv-text-dim')

            list_container = ui.column().classes('w-full gap-4')

            def refresh_list() -> None:
                list_container.clear()
                with get_session() as session:
                    # Fetch libraries pending approval and active global libraries
                    stmt = select(Library, User).outerjoin(User, Library.owner_user_id == User.id).where(
                        Library.scope.in_(['global', 'pending_global'])
                    ).order_by(Library.name)
                    
                    results = session.execute(stmt).all()
                    
                    if not results:
                        with list_container:
                            ui.label('No global libraries found.').classes('pv-inline-empty')
                        return
                    
                    with list_container:
                        for lib, owner in results:
                            is_pending = lib.scope == 'pending_global'
                            
                            with ui.card().props('flat bordered').classes(f"pv-dialog-card w-full {'pv-warning-border' if is_pending else ''}"):
                                with ui.row().classes('w-full items-start justify-between gap-4'):
                                    with ui.column().classes('gap-1 flex-grow'):
                                        with ui.row().classes('items-center gap-2'):
                                            ui.label(lib.name).classes('text-base font-medium')
                                            if is_pending:
                                                ui.badge('Pending Approval', color='warning', text_color='black').props('outline')
                                            else:
                                                ui.badge('Active Global', color='positive').props('outline')
                                                
                                        owner_name = owner.username if owner else 'Unknown'
                                        ui.label(f'Owner: {owner_name}').classes('text-xs pv-text-dimmer')
                                        ui.label(f'Library ID: {lib.id}').classes('text-xs pv-text-dimmer font-mono mt-1')
                                    
                                    with ui.column().classes('items-end gap-2'):
                                        def approve_lib(lib_id=lib.id):
                                            with get_session() as s:
                                                l = s.get(Library, lib_id)
                                                if l:
                                                    l.scope = 'global'
                                                    s.commit()
                                                    ui.notify('Library approved for global sharing', color='positive')
                                                    refresh_list()
                                        
                                        def revert_to_shared(lib_id=lib.id, action_str="Reverted to shared"):
                                            with get_session() as s:
                                                l = s.get(Library, lib_id)
                                                if l:
                                                    l.scope = 'shared'
                                                    s.commit()
                                                    ui.notify(action_str, color='warning')
                                                    refresh_list()

                                        if is_pending:
                                            with ui.row().classes('gap-2'):
                                                ui.button('Decline', on_click=lambda l=lib.id: revert_to_shared(l, "Declined global request")).props('flat text-color=negative no-caps size=sm').classes('pv-meta-action-btn')
                                                ui.button('Approve', on_click=lambda l=lib.id: approve_lib(l)).props('color=positive unelevated no-caps size=sm').classes('pv-meta-save-btn')
                                        else:
                                            ui.button('Revoke Global Status', on_click=lambda l=lib.id: revert_to_shared(l, "Revoked global status. Library is now 'shared'")).props('flat text-color=negative no-caps size=sm').classes('pv-meta-action-btn')

                                # Show Members/Users who have accepted
                                if not is_pending:
                                    with ui.expansion('Active Members').classes('w-full text-sm mt-3'):
                                        with get_session() as share_session:
                                            shares = share_session.execute(
                                                select(LibraryShare, User)
                                                .join(User, LibraryShare.shared_with_user_id == User.id)
                                                .where(LibraryShare.library_id == str(lib.id))
                                                .where(LibraryShare.status == 'accepted')
                                            ).all()

                                            if not shares:
                                                ui.label('No users have explicitly accepted this library.').classes('text-xs pv-text-dim py-2')
                                            else:
                                                with ui.column().classes('w-full mt-2 gap-1 p-2 pv-subtle-panel'):
                                                    for share, share_user in shares:
                                                        with ui.row().classes('w-full justify-between items-center py-1'):
                                                            with ui.row().classes('gap-2 items-center'):
                                                                ui.icon('person', size='xs').classes('pv-text-dimmer')
                                                                ui.label(share_user.username).classes('text-sm font-medium')
                                                                if share.status == 'pending':
                                                                    ui.label('(pending invite)').classes('text-xs text-orange-400 italic')
                                                            
                                                            def revoke_access(s_id=share.id, u_name=share_user.username):
                                                                with get_session() as rs:
                                                                    rs_obj = rs.get(LibraryShare, s_id)
                                                                    if rs_obj:
                                                                        rs.delete(rs_obj)
                                                                        rs.commit()
                                                                        ui.notify(f'Revoked access for {u_name}', color='positive')
                                                                        refresh_list()
                                                                        
                                                            ui.button('Revoke Access', on_click=lambda s=share.id, u=share_user.username: revoke_access(s, u)).props('flat dense text-color=negative no-caps size=xs').classes('pv-meta-action-btn')

            refresh_list()
