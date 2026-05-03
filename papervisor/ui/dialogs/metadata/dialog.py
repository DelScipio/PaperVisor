from __future__ import annotations

import asyncio
from typing import Callable

from nicegui import ui

from papervisor.db.models import Paper
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_actions_row, dialog_header
from papervisor.ui.dialogs.metadata.state import DialogState
from papervisor.ui.dialogs.metadata.actions import MetadataActions
from papervisor.ui.dialogs.metadata.ui_org import render_org_box
from papervisor.ui.dialogs.metadata.ui_details import render_details_view
from papervisor.ui.dialogs.metadata.ui_edit import render_edit_fields
from papervisor.ui.dialogs.metadata.ui_media import render_media_box

class MetadataDialog:
    def __init__(self, *, on_changed: Callable[[], None] | None = None, user_id: int | None = None) -> None:
        self._on_changed = on_changed
        self._user_id = user_id
        self._dialog = ui.dialog()
        self._close_waiters: list[asyncio.Event] = []
        self.state = DialogState()
        self.actions = MetadataActions(self)
        
        # UI references
        self.dirty_badge = None
        self.busy_row = None
        self.busy_text = None
        self.tabs = None
        self.image_box = None
        self.save_btn = None
        self.save_row = None
        self.root_card = None
        
        self.org_box = None
        self.library_in = None
        self.shelves_in = None
        self.tags_in = None
        self.class_save_btn = None
        self.class_save_row = None
        self.can_manage_paper_library = False

        self.actions_box = None
        self.book_source_in = None
        self.paper_source_in = None
        self.book_actions_col = None
        self.paper_actions_col = None
        self.doi_extract_btn = None
        self.isbn_detect_btn = None
        self.delete_top_btn = None
        self.close_top_btn = None
        self._delete_in_progress = False
        
        # Form refs
        self.inputs = {}
        self.edit_rows = {}
        self.view_rows = {}
        self.lock_buttons = {}

        def _signal_closed(_e=None) -> None:
            try:
                waiters = list(self._close_waiters)
                self._close_waiters.clear()
                for ev in waiters:
                    try:
                        ev.set()
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            self._dialog.on('hide', _signal_closed)
        except Exception:
            pass

    async def open_and_wait(self, paper: Paper) -> None:
        ev = asyncio.Event()
        self._close_waiters.append(ev)
        self.open(paper)
        await ev.wait()

    def _set_visible(self, el, visible: bool) -> None:
        if el is None:
            return
        try:
            el.set_visibility(bool(visible))
        except Exception:
            try:
                el.visible = bool(visible)
            except Exception:
                pass

    def _set_busy(self, message: str | None) -> None:
        msg = str(message or '').strip()
        if self.busy_text:
            try:
                self.busy_text.text = msg
            except Exception:
                pass
        visible = bool(msg)
        self._set_visible(self.busy_row, visible)

    def _set_actions_enabled(self, enabled: bool) -> None:
        controls = [
            getattr(self, 'tabs', None),
            getattr(self, 'save_btn', None),
            getattr(self, 'book_source_in', None),
            getattr(self, 'paper_source_in', None),
            getattr(self, 'doi_extract_btn', None),
            getattr(self, 'isbn_detect_btn', None),
            getattr(self, 'class_save_btn', None),
            getattr(self, 'library_in', None),
            getattr(self, 'shelves_in', None),
            getattr(self, 'tags_in', None),
            getattr(self, 'delete_top_btn', None),
            getattr(self, 'close_top_btn', None),
        ]
        controls.extend(self.inputs.values())
        controls.extend(self.lock_buttons.values())

        for control in controls:
            if control is None:
                continue
            try:
                if enabled:
                    control.enable()
                else:
                    control.disable()
            except Exception:
                pass

    def _get_input_value(self, key: str):
        inp = self.inputs.get(key)
        if inp is None:
            return None
        return getattr(inp, 'value', None)

    def _set_input_value(self, key: str, value):
        inp = self.inputs.get(key)
        if inp is not None:
            try:
                inp.value = value
            except Exception:
                pass

    def _update_field(self, key: str, value):
        self._mark_dirty()

    def _toggle_lock(self, key: str):
        self.state.locks[key] = not bool(self.state.locks.get(key))
        btn = self.lock_buttons.get(key)
        if btn:
            try:
                # Need to explicitly call props() again to tell Vue/Quasar to update the icon
                icon = 'lock' if self.state.locks[key] else 'lock_open'
                btn.props(f'icon={icon}')
            except Exception:
                pass

    def _mark_dirty(self, _e=None):
        if self.state.is_dirty_suspended:
            return
        if not self.state.editing_state:
            return
        self.state.dirty_state = True
        self._set_visible(self.dirty_badge, True)
        if self.save_btn:
            self.save_btn.enable()
            self._set_visible(self.save_row, True)

    def _refresh_media(self):
        if self.image_box:
            self.image_box.clear()
            with self.image_box:
                render_media_box(
                    paper=self.state.paper,
                    file_type=self.state.file_type(),
                    try_regen_fn=self.actions.regen_snapshot,
                    try_fetch_fn=self.actions.fetch_cover,
                )

    def _refresh_details(self):
        if getattr(self, 'details_container', None):
            self.details_container.clear()
            with self.details_container:
                self.view_rows = render_details_view(
                    paper=self.state.paper, 
                    open_replace_dlg_fn=getattr(self, '_open_replace_dialog_fn', None),
                    download_paper_fn=self.actions.download_paper_file,
                    copy_path_fn=self.actions.copy_paper_file_path,
                )

    def _apply_paper(self, updated):
        if not updated: return

        def _split_multi_text(value: object) -> list[str]:
            if value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                return [str(v).strip() for v in value if str(v).strip()]
            raw = str(value).strip()
            if not raw:
                return []
            normalized = raw.replace(';', ',')
            return [part.strip() for part in normalized.split(',') if part.strip()]

        self.state.is_dirty_suspended = True
        try:
            for k in [
                'title', 'doi', 'isbn', 'authors', 'year', 'journal', 'publisher',
                'publication_date', 'language', 'series', 'series_index', 'page_count', 'genres',
                'description', 'url', 'volume', 'issue', 'pages', 'keywords', 'abstract'
            ]:
                if not self.state.locks.get(k):
                    v = getattr(updated, k, None)
                    if not v and k == 'year':
                        v = getattr(updated, 'published_year', None)
                        
                    if v is not None and str(v).strip(): # Only update if fetched data has a value
                        if k == 'genres':
                            self._set_input_value(k, _split_multi_text(v))
                        else:
                            self._set_input_value(k, str(v))
        finally:
            self.state.is_dirty_suspended = False
            
        self._mark_dirty()

    def _apply_paper_obj(self, updated: Paper):
        self.state.paper = updated
        self._refresh_media()
        self._refresh_details()
        self._apply_type_visibility(editing=self.state.editing_state)

    def _type_changed(self, e=None):
        if self.inputs.get('type'):
            t = str(self.inputs['type'].value or '').strip().lower()
            if self.state.paper:
                self.state.paper.file_type = t
            self._apply_type_visibility(editing=self.state.editing_state)
            self._mark_dirty()

    def _tab_changed(self, e=None):
        try:
            self.state.editing_state = (self.tabs.value == 'Edit')
            self._apply_type_visibility(editing=self.state.editing_state)
        except Exception:
            pass

    def _apply_type_visibility(self, *, editing: bool):
        has = lambda v: bool((str(v) if v else '').strip())
        ft = self.state.file_type()
        is_paper = ft == 'paper'
        is_book = ft == 'book'
        
        # Toggle metadata search actions based on edit vs read mode
        self._set_visible(self.actions_box, editing)
        self._set_visible(self.org_box, not editing)
        self._set_visible(self.book_source_in, editing and is_book)
        self._set_visible(self.book_actions_col, editing and is_book)
        self._set_visible(self.paper_source_in, editing and is_paper)
        self._set_visible(self.paper_actions_col, editing and is_paper)
        
        # Edit tab rows
        self._set_visible(self.edit_rows.get('doi'), is_paper)
        self._set_visible(self.edit_rows.get('isbn'), is_book)
        self._set_visible(self.edit_rows.get('journal'), is_paper)
        self._set_visible(self.edit_rows.get('publisher'), has(self.state.paper.publisher) or editing)
        
        self._set_visible(self.edit_rows.get('book_row1'), is_book)
        self._set_visible(self.edit_rows.get('book_row2'), is_book)
        self._set_visible(self.edit_rows.get('genres'), is_book)
        self._set_visible(self.edit_rows.get('description'), is_book)
        
        self._set_visible(self.edit_rows.get('url'), is_paper)
        self._set_visible(self.edit_rows.get('paper_row1'), is_paper)
        self._set_visible(self.edit_rows.get('keywords'), is_paper)
        self._set_visible(self.edit_rows.get('abstract'), is_paper)
        
        # Details view rows
        self._set_visible(self.view_rows.get('publisher'), has(self.state.paper.publisher))
        self._set_visible(self.view_rows.get('journal'), is_paper and has(self.state.paper.journal))
        self._set_visible(self.view_rows.get('doi'), is_paper and has(self.state.paper.doi))
        self._set_visible(self.view_rows.get('isbn'), is_book and has(self.state.paper.isbn))
        self._set_visible(self.view_rows.get('pubdate'), is_book and has(self.state.paper.publication_date))
        self._set_visible(self.view_rows.get('lang'), is_book and has(self.state.paper.language))
        self._set_visible(self.view_rows.get('series'), is_book and has(self.state.paper.series))
        self._set_visible(self.view_rows.get('series_idx'), is_book and has(self.state.paper.series_index))
        self._set_visible(self.view_rows.get('pages'), is_book and has(self.state.paper.page_count))
        self._set_visible(self.view_rows.get('genres'), is_book and has(self.state.paper.genres))
        
        show_url = is_paper and has(self.state.paper.url)
        if show_url:
            from papervisor.ui.dialogs.metadata.ui_details import is_doi_url
            if is_doi_url(self.state.paper.url, self.state.paper.doi):
                show_url = False
        self._set_visible(self.view_rows.get('url'), show_url)
        self._set_visible(self.view_rows.get('volume'), is_paper and has(self.state.paper.volume))
        self._set_visible(self.view_rows.get('issue'), is_paper and has(self.state.paper.issue))
        self._set_visible(self.view_rows.get('pages2'), is_paper and has(self.state.paper.pages))
        self._set_visible(self.view_rows.get('keywords'), is_paper and has(self.state.paper.keywords))

    async def _confirm_delete(self):
        if not self.state.paper:
            return
        if self._delete_in_progress:
            return

        with ui.dialog() as dlg, dialog_card(max_width_class='max-w-xl', extra_classes='pv-meta-dialog-card'):
            ui.label('Delete this item?').classes('text-base font-semibold')
            ui.separator().classes('opacity-20 my-2')
            ui.label('This will move this item to Trash. You can restore it later from Trash.').classes('text-sm pv-text-dimmer')

            async def _confirm(_e=None):
                if self._delete_in_progress:
                    return
                try:
                    dlg.close()
                except Exception:
                    pass
                await self._do_delete()

            with dialog_actions_row():
                ui.button('Cancel', on_click=dlg.close).props('flat color=negative')
                ui.button('Delete', on_click=_confirm).props('color=negative')
        dlg.open()

    async def _do_delete(self):
        if not self.state.paper:
            return
        if self._delete_in_progress:
            return

        self._delete_in_progress = True
        paper_id = str(self.state.paper.id)
        self._set_busy('Deleting…')
        self._set_actions_enabled(False)
        try:
            from papervisor.services.papers import delete_paper
            await asyncio.to_thread(delete_paper, paper_id=paper_id)

            from papervisor.ui.events import Event, emit
            emit(Event.PAPER_DELETED, paper_id=paper_id)
            ui.notify('Item moved to trash', color='info')
            if self._dialog:
                self._dialog.close()
        except Exception as ex:
            ui.notify(f'Failed to delete: {ex}', color='negative')
        finally:
            self._set_busy(None)
            self._set_actions_enabled(True)
            self._delete_in_progress = False

    def open(self, paper: Paper) -> None:
        self.state = DialogState(paper=paper)
        self._dialog.clear()

        with self._dialog:
            root_card = dialog_card(
                max_width_class='max-w-[calc(100vw-2rem)] md:max-w-[96vw]',
                extra_classes='pv-meta-dialog-card md:w-[1120px] relative overflow-hidden',
            )
        self.root_card = root_card
        self.replace_dlg = ui.dialog()
        with self.replace_dlg, dialog_card(max_width_class='max-w-xl', extra_classes='pv-meta-dialog-card'):
            ui.label('Replace file').classes('text-base font-semibold')
            ui.label('Uploads a new file for this item. Metadata stays as-is.').classes('text-xs pv-text-dimmer')
            ui.upload(on_upload=self.actions.process_replace_upload, auto_upload=True, max_file_size=524288000).props('outlined').classes('w-full pv-meta-field')
            ui.button('Close', on_click=lambda _e=None: self.replace_dlg.close()).props('flat').classes('w-full pv-meta-action-btn')

        def _open_replace_dialog(_e=None) -> None:
            try:
                self.replace_dlg.open()
            except Exception:
                pass
        self._open_replace_dialog_fn = _open_replace_dialog

        with root_card:
            def _meta_actions() -> None:
                self.dirty_badge = ui.badge('Unsaved changes').props('color="warning"').classes('pv-chip')
                self._set_visible(self.dirty_badge, False)
                self.tabs = ui.tabs().props('dense')
                self.tabs.on('update:model-value', self._tab_changed)
                self.tabs.on('change', self._tab_changed)
                with self.tabs:
                    ui.tab('Details')
                    ui.tab('Edit')
                self.delete_top_btn = ui.button(icon='delete_outline', on_click=self._confirm_delete).props('flat round color=negative size=sm').classes('pv-meta-action-btn')
                self.delete_top_btn.style('min-width:34px;min-height:34px')
                self.delete_top_btn.tooltip('Delete')
                self.close_top_btn = ui.button(icon='close', on_click=lambda e: self._dialog.close()).props('flat round size=sm').classes('pv-meta-action-btn')
                self.close_top_btn.style('min-width:34px;min-height:34px')
                self.close_top_btn.tooltip('Close')

            dialog_header(title='Metadata', icon='info', actions_builder=_meta_actions)

            self.busy_row = ui.row().classes('absolute bottom-0 left-0 right-0 z-50 flex justify-center items-center pb-2 pointer-events-none')
            with self.busy_row:
                with ui.element('div').classes('pv-busy-pill'):
                    ui.spinner('dots', size='sm', color='primary')
                    self.busy_text = ui.label('').classes('text-xs font-medium')
            self._set_visible(self.busy_row, False)

            with ui.row().classes('pv-meta-body w-full gap-5 flex flex-col md:flex-row max-h-[calc(100vh-8rem)] overflow-y-auto pb-4 items-start'):
                media_col = ui.column().classes('pv-meta-media-col w-full md:w-[240px] gap-3 shrink-0')
                fields_col = ui.column().classes('pv-meta-fields-col w-full md:flex-1 min-w-0 gap-3')

            with media_col:
                self.image_box = ui.column().classes('w-full gap-2')
                self.actions_box = ui.column().classes('w-full gap-2')
                self.org_box = ui.column().classes('pv-meta-org-box w-full gap-3')
            
            self._refresh_media()
            render_org_box(dialog=self, parent_col=self.org_box)

            with self.actions_box:
                ui.label('Metadata actions').classes('text-xs pv-text-dimmer')
                ui.button('Replace file', icon='upload', on_click=_open_replace_dialog).props('outline dense').classes('w-full pv-meta-action-btn')
                self.book_source_in = ui.select(
                    {'auto': 'Auto', 'openlibrary': 'OpenLibrary', 'google': 'Google'},
                    value='auto',
                    label='Source',
                ).props('outlined dense').classes('w-full pv-meta-field')
                self.paper_source_in = ui.select({'crossref': 'Crossref'}, value='crossref', label='Source').props('outlined dense').classes('w-full pv-meta-field')

                self.paper_actions_col = ui.column().classes('w-full gap-2')
                with self.paper_actions_col:
                    ui.button('Fetch metadata', on_click=self.actions.fetch_doi).props('outline dense').classes('w-full pv-meta-action-btn')
                    self.doi_extract_btn = ui.button('Extract DOI', on_click=self.actions.extract_doi).props('outline dense').classes('w-full pv-meta-action-btn')

                self.book_actions_col = ui.column().classes('w-full gap-2')
                with self.book_actions_col:
                    ui.button('Fetch metadata', on_click=self.actions.fetch_isbn).props('outline dense').classes('w-full pv-meta-action-btn')
                    self.isbn_detect_btn = ui.button('Detect ISBN', on_click=self.actions.detect_isbn).props('outline dense').classes('w-full pv-meta-action-btn')

                self.save_row = ui.row().classes('w-full pt-2')
                with self.save_row:
                    self.save_btn = ui.button('Save changes', icon='save', on_click=self.actions.save_metadata).props('color=primary').classes('w-full pv-meta-save-btn')
                    self.save_btn.disable()
                self._set_visible(self.save_row, False)

            with fields_col:
                with ui.tab_panels(self.tabs, value='Details').classes('w-full q-pa-none'):
                    with ui.tab_panel('Details').classes('q-pa-none'):
                        self.details_container = ui.column().classes('w-full gap-1')
                        with self.details_container:
                            self.view_rows = render_details_view(
                                paper=self.state.paper, 
                                open_replace_dlg_fn=self._open_replace_dialog_fn,
                                download_paper_fn=self.actions.download_paper_file,
                                copy_path_fn=self.actions.copy_paper_file_path,
                            )
                    with ui.tab_panel('Edit').classes('q-pa-none'):
                        with ui.column().classes('w-full gap-2'):
                            self.inputs, self.edit_rows, self.lock_buttons = render_edit_fields(
                                locks=self.state.locks, 
                                toggle_lock_fn=self._toggle_lock, 
                                paper=self.state.paper,
                                update_field_fn=self._update_field
                            )
                            # Register event listener for type select from within the return value
                            if 'type' in self.inputs:
                                self.inputs['type'].on('update:model-value', self._type_changed)
                                self.inputs['type'].on('change', self._type_changed)
                                
            # Apply initial view
            self._apply_type_visibility(editing=False)
        self._dialog.open()
