from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import inspect
import logging
import os
from pathlib import Path
from typing import Literal

from nicegui import ui

from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_body, dialog_footer, dialog_header
from papervisor.services.libraries import list_libraries
from papervisor.services.papers import commit_staged_import, save_upload_to_temp
from papervisor.services.markers import list_markers, set_paper_markers
from papervisor.services.tags import list_tags, set_paper_tags
from papervisor.ui.dialogs.metadata_dialog import MetadataDialog
from papervisor.ui.dialogs.marker_dialogs import MarkerDialogs
from papervisor.services.user_settings import get_user_setting, set_user_setting


logger = logging.getLogger(__name__)


UploadStatus = Literal['queued', 'importing', 'metadata', 'done', 'failed', 'skipped', 'invalid']


@dataclass
class _QueuedUpload:
    staged_path: str
    original_filename: str
    status: UploadStatus = 'queued'
    error: str | None = None

    def status_label(self) -> str:
        if self.error:
            return f'{self.status} ({self.error})'
        return self.status


_ALLOWED_STATUS_TRANSITIONS: dict[UploadStatus, set[UploadStatus]] = {
    'queued': {'importing', 'skipped', 'invalid', 'failed'},
    'importing': {'metadata', 'done', 'failed'},
    'metadata': {'done', 'failed'},
    'done': set(),
    'failed': set(),
    'skipped': set(),
    'invalid': set(),
}


def _transition_status(item: _QueuedUpload, new_status: UploadStatus, *, error: str | None = None) -> None:
    allowed = _ALLOWED_STATUS_TRANSITIONS.get(item.status, set())
    if new_status not in allowed and new_status != item.status:
        logger.warning('Invalid upload status transition: %s -> %s (%s)', item.status, new_status, item.original_filename)
    item.status = new_status
    item.error = (str(error or '').strip() or None)


@dataclass(frozen=True)
class _UploadPayload:
    filename: str
    content: bytes


async def _get_upload_payload(e) -> _UploadPayload:
    # NiceGUI UploadEventArguments changed across versions.
    filename = (
        getattr(e, 'name', None)
        or getattr(e, 'filename', None)
        or getattr(e, 'file_name', None)
        or getattr(getattr(e, 'file', None), 'filename', None)
        or getattr(getattr(e, 'file', None), 'name', None)
        or getattr(getattr(e, 'content', None), 'filename', None)
        or getattr(getattr(e, 'content', None), 'name', None)
        or 'upload'
    )
    filename = os.path.basename(str(filename)) or 'upload'

    content_obj = getattr(e, 'content', None)
    file_obj = getattr(e, 'file', None)

    async def _read_bytes(obj) -> bytes:
        if obj is None:
            return b''
        if isinstance(obj, (bytes, bytearray, memoryview)):
            return bytes(obj)
        if hasattr(obj, 'getvalue'):
            try:
                return bytes(obj.getvalue())
            except Exception:
                logger.debug('Upload payload getvalue() failed', exc_info=True)
        if hasattr(obj, 'seek'):
            try:
                obj.seek(0)
            except Exception:
                logger.debug('Upload payload seek(0) failed', exc_info=True)
        if hasattr(obj, 'read'):
            try:
                data = obj.read()
                if inspect.isawaitable(data):
                    data = await data
                return bytes(data) if isinstance(data, (bytes, bytearray, memoryview)) else b''
            except Exception:
                return b''
        return b''

    data = await _read_bytes(content_obj)
    if not data:
        data = await _read_bytes(file_obj)

    if not data:
        raise ValueError('Upload contained no data (0 bytes)')

    return _UploadPayload(filename=str(filename), content=data)


class UploadDialog:
    def __init__(self, *, user_id: int | None = None, on_changed: Callable[[], None] | None = None) -> None:
        self._user_id = int(user_id) if user_id is not None else None
        self._on_changed = on_changed
        self._dialog = ui.dialog()

    def open(self) -> None:
        self._dialog.clear()

        libs = list_libraries()
        lib_options = {l.id: l.name for l in libs}
        default_lib = libs[0].id if libs else None

        # Restore last upload defaults (per-user).
        if self._user_id and libs:
            try:
                last_lib = str(get_user_setting(user_id=self._user_id, key='upload.last.library_id', default='') or '').strip()
                if last_lib and last_lib in lib_options:
                    default_lib = last_lib
            except Exception:
                logger.debug('Failed to restore last upload library selection', exc_info=True)

        default_type = 'paper'
        if self._user_id:
            try:
                last_type = str(get_user_setting(user_id=self._user_id, key='upload.last.type', default='paper') or '').strip().lower()
                if last_type in {'paper', 'book'}:
                    default_type = last_type
            except Exception:
                logger.debug('Failed to restore last upload type selection', exc_info=True)

        queue: list[_QueuedUpload] = []
        processing = False
        start_btn: ui.button | None = None
        cancel_btn: ui.button | None = None
        uploader: ui.upload | None = None

        with self._dialog, dialog_card(max_width_class='max-w-3xl', extra_classes='pv-flat-dialog-card overflow-hidden'):
            dialog_header(title='Upload', icon='cloud_upload')

            with ui.element('div').classes('w-full max-h-[68vh] overflow-auto scroll'):
                with dialog_body(extra_classes='pt-2'):

                    if not libs:
                        with ui.row().classes('w-full items-center justify-center p-6 pv-share-empty'):
                            ui.label('Create a library first.').classes('text-sm pv-text-dimmer')
                        with dialog_footer():
                            ui.button('Close', on_click=self._dialog.close).props('flat no-caps')
                        self._dialog.open()
                        return

                    library_select = ui.select(lib_options, value=default_lib, label='Library').props('outlined dense').classes(
                        'w-full pv-meta-field'
                    )

                    type_select = ui.select({'paper': 'Paper', 'book': 'Book'}, value=default_type, label='Type').props(
                        'outlined dense'
                    ).classes('w-full pv-meta-field')

                    # Markers (manual markers)
                    markers_in: ui.select | None = None

                    marker_dialogs = MarkerDialogs(on_changed=lambda: _refresh_marker_options(), user_id=self._user_id)

                    def _refresh_marker_options(*, select_new_id: str | None = None) -> None:
                        nonlocal markers_in
                        if markers_in is None:
                            return
                        try:
                            all_markers = [
                                s for s in list_markers(user_id=self._user_id) if not bool(getattr(s, 'is_smart', False))
                            ]
                            marker_options = {str(s.id): str(s.name) for s in all_markers}
                        except Exception:
                            marker_options = {}

                        cur = list(getattr(markers_in, 'value', None) or [])
                        cur_ids = [str(x).strip() for x in cur if str(x).strip()]
                        if select_new_id:
                            cur_ids = [*cur_ids, str(select_new_id).strip()]
                        cur_ids = [sid for sid in cur_ids if sid in marker_options]
                        try:
                            markers_in.set_options(marker_options, value=cur_ids)
                        except Exception:
                            markers_in.options = marker_options
                            markers_in.value = cur_ids

                    with ui.row().classes('w-full items-center gap-2'):
                        markers_in = (
                            ui.select(
                                {},
                                label='Markers',
                                value=[],
                                multiple=True,
                                with_input=True,
                            )
                            .props('outlined dense use-chips input-debounce=0')
                            .classes('flex-1 pv-meta-field')
                        )
                        with ui.button(icon='add').props('outline dense') as new_marker_btn:
                            new_marker_btn.tooltip('New marker')
                            with ui.menu():
                                ui.menu_item('New Marker', on_click=lambda: marker_dialogs.open_create())
                                ui.menu_item('New Auto Marker', on_click=lambda: marker_dialogs.open_create_auto())
                        if self._user_id is None:
                            new_marker_btn.disable()

                    _refresh_marker_options()

                    try:
                        tag_options = list_tags()
                    except Exception:
                        tag_options = []

                    tags_in = (
                        ui.select(
                            tag_options,
                            label='Tags',
                            value=[],
                            multiple=True,
                            with_input=True,
                            new_value_mode='add-unique',
                        )
                        .props('outlined dense use-chips input-debounce=0')
                        .classes('w-full pv-meta-field')
                    )

                    with ui.column().classes('w-full gap-1 pt-1'):
                        ui.label('Upload files').classes('text-sm font-semibold')

                        status = ui.label('').classes('text-xs pv-text-dimmer')
                        status.set_visibility(False)

                        with ui.element('div').classes('w-full'):
                            uploader = (
                                ui.upload(
                                    label='Select files or drop them here',
                                    auto_upload=True,
                                    on_upload=lambda e: _handle_upload(e),
                                )
                                .props('accept=.pdf,.epub,.cbz multiple outlined')
                                .classes('w-full pv-upload-uploader pv-upload-dropzone')
                            )

                    with ui.element('div').classes('w-full'):
                        queue_mount = ui.column().classes('w-full gap-2 pv-upload-queue')

            def _refresh_status_label() -> None:
                total = len(queue)
                queued = sum(1 for item in queue if item.status == 'queued')
                done = sum(1 for item in queue if item.status == 'done')
                failed = sum(1 for item in queue if item.status in {'failed', 'invalid'})
                if total == 0:
                    status.text = ''
                    status.set_visibility(False)
                    return
                status.text = f'{total} total · {queued} queued · {done} done · {failed} failed'
                status.set_visibility(True)

            def _has_pending_queue() -> bool:
                return any(item.status == 'queued' for item in queue)

            def _set_enabled(btn: ui.button | None, enabled: bool) -> None:
                if btn is None:
                    return
                try:
                    if enabled:
                        btn.enable()
                    else:
                        btn.disable()
                except Exception:
                    pass

            def _sync_action_buttons() -> None:
                _set_enabled(start_btn, (not processing) and _has_pending_queue())
                _set_enabled(cancel_btn, not processing)

            def _shorten(value: str, *, max_len: int = 72) -> str:
                text = str(value or '').strip()
                if len(text) <= max_len:
                    return text
                return f'{text[: max_len - 1]}…'

            @ui.refreshable
            def _render_queue() -> None:
                if not queue:
                    with ui.row().classes('w-full items-center justify-center p-6 pv-share-empty'):
                        ui.label('No files queued').classes('text-sm pv-text-dimmer')
                    return
                with ui.column().classes('w-full gap-2 pv-upload-queue-list'):
                    for item in queue:
                        with ui.column().classes('pv-upload-queue-item w-full p-3 gap-1'):
                            with ui.row().classes('w-full items-center justify-between gap-2'):
                                ui.label(_shorten(item.original_filename, max_len=78)).classes('text-sm')
                                color = {
                                    'done': 'positive',
                                    'failed': 'negative',
                                    'invalid': 'negative',
                                    'skipped': 'warning',
                                    'metadata': 'info',
                                    'importing': 'primary',
                                    'queued': 'grey-7',
                                }.get(item.status, 'grey-7')
                                ui.badge(item.status).props(f'color={color} outline').classes('text-[10px]')
                            if item.error:
                                ui.label(f"Reason: {_shorten(item.error, max_len=110)}").classes('text-[11px] text-negative')

            with queue_mount:
                _render_queue()

            async def _handle_upload(e) -> None:
                try:
                    payload = await _get_upload_payload(e)
                    staged = save_upload_to_temp(filename=payload.filename, content=payload.content)
                    queue.append(
                        _QueuedUpload(
                            staged_path=str(staged),
                            original_filename=payload.filename,
                        )
                    )
                    _refresh_status_label()
                    _sync_action_buttons()
                    _render_queue.refresh()
                except Exception as ex:
                    logger.exception('Failed to stage uploaded file')
                    ui.notify(str(ex), color='negative')

            def _cleanup_staged() -> None:
                for item in queue:
                    if item.status == 'done':
                        continue
                    p = item.staged_path
                    if not p:
                        continue
                    try:
                        Path(p).unlink(missing_ok=True)
                    except Exception:
                        logger.debug('Failed to cleanup staged file: %s', p, exc_info=True)
                queue.clear()
                nonlocal processing
                processing = False
                _sync_action_buttons()
                _refresh_status_label()
                try:
                    uploader.enable()
                except Exception:
                    logger.debug('Failed to re-enable uploader', exc_info=True)
                _render_queue.refresh()

            async def _process_queue() -> None:
                nonlocal processing
                if processing:
                    return

                if not queue:
                    ui.notify('Upload files first', color='warning')
                    return

                processing = True
                _sync_action_buttons()
                try:
                    uploader.disable()
                except Exception:
                    logger.debug('Failed to disable uploader', exc_info=True)

                library_id = str(library_select.value or '')
                file_type = str(type_select.value or 'paper')
                selected_markers = [str(s) for s in (markers_in.value or [])]
                selected_tags = [str(t) for t in (tags_in.value or [])]

                # Persist last-used selections.
                if self._user_id:
                    try:
                        set_user_setting(user_id=self._user_id, key='upload.last.library_id', value=str(library_id))
                        set_user_setting(user_id=self._user_id, key='upload.last.type', value=str(file_type))
                    except Exception:
                        logger.debug('Failed to persist upload defaults', exc_info=True)

                md = MetadataDialog(on_changed=self._on_changed, user_id=self._user_id)

                for item in queue:
                    if item.status != 'queued':
                        continue

                    staged_path = item.staged_path
                    original_filename = item.original_filename
                    if not staged_path:
                        _transition_status(item, 'skipped', error='missing staged file path')
                        _refresh_status_label()
                        _render_queue.refresh()
                        continue

                    # Basic sanity check: avoid non-PDF "paper" uploads.
                    if file_type == 'paper' and not original_filename.lower().endswith('.pdf'):
                        _transition_status(item, 'invalid', error='paper must be PDF')
                        _refresh_status_label()
                        _render_queue.refresh()
                        continue

                    _transition_status(item, 'importing')
                    _refresh_status_label()
                    _render_queue.refresh()

                    try:
                        imported = commit_staged_import(
                            library_id=library_id,
                            file_type=file_type,
                            staged_path=staged_path,
                            original_filename=original_filename,
                        )

                        original_name = Path(str(original_filename or '')).name
                        final_name = Path(str(imported.saved_path or '')).name
                        if original_name and final_name and final_name != original_name:
                            ui.notify(f'Name existed, saved as {final_name}', color='info')

                        # Apply shared (optional) tags/markers to every imported paper.
                        try:
                            if selected_markers:
                                set_paper_markers(
                                    paper_id=str(imported.paper.id),
                                    marker_ids=selected_markers,
                                    user_id=self._user_id,
                                )
                        except Exception:
                            logger.warning('Failed setting markers on imported paper %s', imported.paper.id, exc_info=True)

                        try:
                            if selected_tags:
                                set_paper_tags(
                                    paper_id=str(imported.paper.id),
                                    tags=selected_tags,
                                    user_id=self._user_id,
                                )
                        except Exception:
                            logger.warning('Failed setting tags on imported paper %s', imported.paper.id, exc_info=True)

                        _transition_status(item, 'metadata')
                        _refresh_status_label()
                        _render_queue.refresh()

                        # Review metadata one-by-one (use ISBN detection/fetch inside the dialog).
                        await md.open_and_wait(imported.paper)
                        _transition_status(item, 'done')
                        _refresh_status_label()
                        _render_queue.refresh()
                    except Exception as ex:
                        logger.exception('Failed importing queued upload: %s', original_filename)
                        _transition_status(item, 'failed', error=str(ex))
                        _refresh_status_label()
                        _render_queue.refresh()

                processing = False
                _sync_action_buttons()
                _refresh_status_label()
                try:
                    uploader.enable()
                except Exception:
                    logger.debug('Failed to re-enable uploader after batch', exc_info=True)

                failed = sum(1 for item in queue if item.status in {'failed', 'invalid'})
                if failed:
                    ui.notify(f'Upload batch finished with {failed} failure(s)', color='warning')
                else:
                    ui.notify('Upload batch finished', color='positive')

                self._dialog.close()
                if self._on_changed is not None:
                    self._on_changed()



            with dialog_footer():
                cancel_btn = ui.button('Cancel', on_click=lambda: (_cleanup_staged(), self._dialog.close())).props('flat no-caps color=negative')

                async def _start_import(_e=None) -> None:
                    await _process_queue()

                start_btn = ui.button('Start', on_click=_start_import).props('color=positive unelevated no-caps')
                _sync_action_buttons()

        self._dialog.open()


# Backwards-compat alias (older pages import ImportDialog)
ImportDialog = UploadDialog
