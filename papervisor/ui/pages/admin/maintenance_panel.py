from __future__ import annotations

import asyncio
import time
from typing import Callable, TypeVar

from nicegui import ui

from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_actions_row, dialog_header
from papervisor.services.libraries import list_libraries
from papervisor.services.users import list_users
from papervisor.services.maintenance import (
    clean_deleted_users,
    clean_libraries,
    extract_epub_covers,
    fetch_book_covers,
    regenerate_thumbnails,
    trove_doi_metadata,
    trove_isbn_metadata,
)
from papervisor.services.metadata_queue import get_metadata_task_queue


T = TypeVar('T')


def render_maintenance_panel(
    *,
    on_changed: Callable[[], None],
    library_owner_user_id: int | None = None,
    owner_user_id_value: str = '',
    on_owner_user_id_change: Callable[[str], None] | None = None,
) -> None:
    with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
        dialog_header(
            title='Maintenance',
            icon='build',
            subtitle='System maintenance and optimization tasks.',
            extra_classes='!px-3 !py-2',
            icon_classes='text-base',
            title_classes='text-sm',
            subtitle_classes='text-xs',
        )

    # User filter selector (if provided)
    if on_owner_user_id_change is not None:
        with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
            ui.label('Filter by User').classes('text-sm font-semibold')
            ui.label('Select a user to limit operations to their libraries only').classes('text-xs pv-text-dimmer')

            with ui.row().classes('w-full items-center gap-3 pt-2'):
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

                sel = ui.select(user_opts, value=initial_value, label='User', with_input=True).props('outlined dense').classes('flex-1')

                def _on_change(e) -> None:
                    args = getattr(e, 'args', None)
                    v = args.get('value', '') if isinstance(args, dict) else args
                    vv = str(v or '').strip()
                    if vv and vv not in user_opts:
                        vv = ''
                    on_owner_user_id_change(vv)

                sel.on('update:model-value', _on_change)

    # ---------------------------------------------------------------
    # Shared progress state — updated from background threads.
    # ---------------------------------------------------------------
    progress_state: dict[str, object] = {
        'current': 0,
        'total': 0,
        'label': '',
    }

    # ---------------------------------------------------------------
    # Shared helpers
    # ---------------------------------------------------------------

    def _choose_libraries_with_options(
        *,
        title: str,
        subtitle: str,
        on_confirm,
        show_overwrite: bool = False,
        show_dry_run: bool = False,
        show_fetch_covers: bool = False,
        extra_options: list[tuple[str, bool]] | None = None,
    ):
        """Unified dialog for choosing libraries + optional checkboxes.

        ``on_confirm`` receives ``(library_ids, options_dict)`` where
        ``options_dict`` has keys like ``'overwrite'``, ``'dry_run'``, ``'fetch_covers'``.
        """
        dlg = ui.dialog()
        libs2 = list_libraries(owner_user_id=library_owner_user_id)
        lib_checks: dict[str, ui.checkbox] = {}
        option_widgets: dict[str, ui.checkbox] = {}

        with dlg, dialog_card(max_width_class='max-w-2xl'):
            ui.label(title).classes('text-base font-semibold')
            if subtitle:
                ui.label(subtitle).classes('text-xs pv-text-dimmer')
            ui.separator().classes('opacity-20 my-2')

            if not libs2:
                ui.label('No libraries found.').classes('pv-inline-empty')
                ui.button('Close', on_click=dlg.close).props('flat').classes('pv-meta-action-btn')
                return dlg

            # Option checkboxes
            if show_overwrite:
                option_widgets['overwrite'] = ui.checkbox('Overwrite existing data', value=False).classes('text-sm')

            if show_dry_run:
                option_widgets['dry_run'] = ui.checkbox('Dry run (preview only, no changes)', value=True).classes('text-sm')
                with ui.row().classes('w-full items-center gap-2'):
                    ui.icon('info', color='blue').classes('text-sm')
                    ui.label('Preview what will be changed before committing').classes('text-xs pv-text-dimmer')

            if show_fetch_covers:
                option_widgets['fetch_covers'] = ui.checkbox('Also fetch cover images', value=True).classes('text-sm')

            if extra_options:
                for opt_label, opt_default in extra_options:
                    key = opt_label.lower().replace(' ', '_')
                    option_widgets[key] = ui.checkbox(opt_label, value=opt_default).classes('text-sm')

            ui.separator().classes('opacity-20 my-2')

            # Library selection
            all_toggle = ui.checkbox('All libraries', value=True).classes('text-sm')

            with ui.column().classes('w-full gap-1 pt-2'):
                for lib in libs2:
                    c = ui.checkbox(lib.name, value=True)
                    lib_checks[lib.id] = c

            def _apply_all_state() -> None:
                enabled = not bool(all_toggle.value)
                for c in lib_checks.values():
                    if enabled:
                        c.enable()
                    else:
                        c.disable()

            all_toggle.on('update:model-value', lambda _e: _apply_all_state())
            _apply_all_state()

            async def _confirm(_e=None) -> None:
                try:
                    opts = {k: bool(w.value) for k, w in option_widgets.items()}
                    if bool(all_toggle.value):
                        await on_confirm(None, opts)
                    else:
                        selected = [lid for (lid, c) in lib_checks.items() if bool(c.value)]
                        if not selected:
                            ui.notify('No libraries selected', color='warning')
                            return
                        await on_confirm(selected, opts)
                finally:
                    dlg.close()

            with dialog_actions_row():
                ui.button('Cancel', on_click=dlg.close).props('flat color=negative').classes('pv-meta-action-btn')
                ui.button('Run', on_click=_confirm).props('color=primary').classes('pv-meta-save-btn')

        return dlg

    async def _run_with_progress(
        *,
        label: str,
        runner: Callable[[], T],
        progress_bar: ui.linear_progress,
        progress_label: ui.label,
    ) -> T | None:
        """Run a long operation in a thread, updating a progress bar via polling.

        Uses ``asyncio.sleep`` polling instead of ``ui.timer`` to avoid
        slot-context errors when called from inside dialog callbacks.
        """
        progress_state['current'] = 0
        progress_state['total'] = 0
        progress_state['label'] = ''
        progress_bar.set_visibility(True)
        progress_label.set_visibility(True)
        progress_bar.value = 0

        def _update_progress() -> None:
            total = int(progress_state.get('total') or 0)
            current = int(progress_state.get('current') or 0)
            item = str(progress_state.get('label') or '')
            if total > 0:
                progress_bar.value = current / total
                truncated = (item[:40] + '…') if len(item) > 40 else item
                progress_label.text = f'{label}: {current}/{total} — {truncated}'
            else:
                progress_label.text = f'{label}: starting…'

        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, runner)
        try:
            while not future.done():
                _update_progress()
                await asyncio.sleep(0.25)
            result = future.result()
            on_changed()
            return result
        except Exception as ex:
            ui.notify(f'Error: {str(ex)}', color='negative')
            return None
        finally:
            progress_bar.set_visibility(False)
            progress_label.text = ''
            progress_label.set_visibility(False)

    async def _run_metadata_queue_job(
        *,
        label: str,
        runner_with_progress: Callable[[Callable[[int, int, str], None]], T],
        progress_bar: ui.linear_progress,
        progress_label: ui.label,
    ) -> T | None:
        """Queue DOI/ISBN metadata work on a dedicated background worker and poll progress."""
        progress_state['current'] = 0
        progress_state['total'] = 0
        progress_state['label'] = ''
        progress_bar.set_visibility(True)
        progress_label.set_visibility(True)
        progress_bar.value = 0

        queue = get_metadata_task_queue()
        job_id = queue.submit(label=label, runner=runner_with_progress)

        def _format_eta(seconds_left: float) -> str:
            seconds = max(0, int(seconds_left))
            minutes, secs = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            if hours > 0:
                return f'{hours:d}:{minutes:02d}:{secs:02d}'
            return f'{minutes:02d}:{secs:02d}'

        try:
            while True:
                snap = queue.get(job_id)
                if snap is None:
                    await asyncio.sleep(0.25)
                    continue

                total = int(getattr(snap, 'total', 0) or 0)
                current = int(getattr(snap, 'current', 0) or 0)
                item = str(getattr(snap, 'item_label', '') or '')
                status = str(getattr(snap, 'status', '') or '')
                started_at = getattr(snap, 'started_at', None)
                queued_ahead = int(getattr(snap, 'queued_ahead', 0) or 0)
                queued_total = int(getattr(snap, 'queued_total', 0) or 0)

                if total > 0:
                    progress_bar.value = current / total
                    truncated = (item[:40] + '…') if len(item) > 40 else item
                    eta_part = ''
                    if status == 'running' and started_at is not None and current > 0:
                        elapsed = max(0.001, time.monotonic() - float(started_at))
                        rate = current / elapsed
                        if rate > 0:
                            remaining = max(0.0, (total - current) / rate)
                            eta_part = f' • ETA {_format_eta(remaining)}'
                    progress_label.text = f'{label}: {current}/{total}{eta_part} — {truncated}'
                elif status == 'queued':
                    if queued_total > 0:
                        progress_label.text = f'{label}: queued ({queued_ahead + 1}/{queued_total})…'
                    else:
                        progress_label.text = f'{label}: queued…'
                else:
                    progress_label.text = f'{label}: running…'

                if status == 'done':
                    on_changed()
                    return snap.result
                if status == 'failed':
                    ui.notify(f'Error: {snap.error or "Metadata job failed"}', color='negative')
                    return None

                await asyncio.sleep(0.25)
        finally:
            progress_bar.set_visibility(False)
            progress_label.text = ''
            progress_label.set_visibility(False)

    def _make_progress_callback():
        """Return a callback that updates ``progress_state`` (thread-safe enough for counters)."""
        def _on_progress(current: int, total: int, item_label: str) -> None:
            progress_state['current'] = current
            progress_state['total'] = total
            progress_state['label'] = item_label
        return _on_progress

    # ---------------------------------------------------------------
    # Global progress bar (shared across all operations)
    # ---------------------------------------------------------------
    progress_bar = ui.linear_progress(value=0, show_value=False).props('rounded').classes('w-full mt-2')
    progress_bar.set_visibility(False)
    progress_label = ui.label('').classes('text-xs pv-text-dimmer')
    progress_label.set_visibility(False)

    # ========================
    # LIBRARY MAINTENANCE
    # ========================
    with ui.card().props('flat bordered').classes('pv-dialog-card w-full mt-2'):
        ui.label('Library Maintenance').classes('text-sm font-semibold pv-text-dim')
        ui.label('Sync, clean, and optimize your libraries').classes('text-xs pv-text-dimmer')

        with ui.expansion('Clean Libraries', icon='cleaning_services').classes('w-full mt-2'):
            ui.markdown('''
            **Purpose:** Synchronize database with filesystem and remove orphaned data
            
            **Actions performed:**
            - Imports files from disk that are missing in database
            - Removes database entries for files that no longer exist
            - Deletes orphaned thumbnails and cover images
            - Removes empty directories
            
            **When to use:**
            - After manually adding/removing files from library folders
            - After file system reorganization
            - To recover from sync issues
            - Regular maintenance (monthly recommended)
            
            **Safety:** Use dry-run first to preview what will change
            ''')

            def _clean_click() -> None:
                async def _go(library_ids: list[str] | None, opts: dict) -> None:
                    dry_run = opts.get('dry_run', False)
                    cb = _make_progress_callback()
                    r = await _run_with_progress(
                        label='Clean libraries',
                        runner=lambda: clean_libraries(library_ids=library_ids, dry_run=dry_run, on_progress=cb),
                        progress_bar=progress_bar,
                        progress_label=progress_label,
                    )
                    if r is not None:
                        mode = 'Preview' if dry_run else 'Completed'
                        msg = (
                            f"{mode}: "
                            f"Files to import={r.imported}, "
                            f"Missing entries to remove={r.deleted_missing}, "
                            f"Orphan media={r.media_deleted}, "
                            f"Empty dirs={r.empty_dirs_deleted}"
                        )
                        ui.notify(msg, color='info' if dry_run else 'positive', timeout=8000)

                _choose_libraries_with_options(
                    title='Clean Libraries',
                    subtitle='Sync database with filesystem and remove orphaned data',
                    show_dry_run=True,
                    on_confirm=_go,
                ).open()

            with ui.row().classes('w-full justify-end pt-2'):
                ui.button('Run Clean', on_click=_clean_click, icon='cleaning_services').props('color=primary').classes('pv-meta-save-btn')

        with ui.expansion('Regenerate PDF Thumbnails', icon='image').classes('w-full'):
            ui.markdown('''
            **Purpose:** Regenerate thumbnail images for PDF files
            
            **When to use:**
            - Missing or corrupted thumbnails
            - After upgrading thumbnail generation system
            - To improve thumbnail quality
            
            **Note:** Only processes PDF files. EPUB covers use embedded images.
            ''')

            def _regen_thumbs_click() -> None:
                async def _go(library_ids: list[str] | None, opts: dict) -> None:
                    overwrite = opts.get('overwrite', False)
                    cb = _make_progress_callback()
                    r = await _run_with_progress(
                        label='Regenerate thumbnails',
                        runner=lambda: regenerate_thumbnails(
                            library_ids=library_ids,
                            overwrite=overwrite,
                            on_progress=cb,
                        ),
                        progress_bar=progress_bar,
                        progress_label=progress_label,
                    )
                    if r is not None:
                        mode = 'Overwrite all' if overwrite else 'Missing only'
                        msg = (
                            f'Thumbnails ({mode}): '
                            f'Processed={r.processed}, Success={r.succeeded}, '
                            f'Skipped={r.skipped}, Failed={r.failed}'
                        )
                        ui.notify(msg, color='positive', timeout=6000)

                _choose_libraries_with_options(
                    title='Regenerate PDF Thumbnails',
                    subtitle='Generate new thumbnail images from PDF first pages',
                    show_overwrite=True,
                    on_confirm=_go,
                ).open()

            with ui.row().classes('w-full justify-end pt-2'):
                ui.button('Run', on_click=_regen_thumbs_click, icon='refresh').props('outline').classes('pv-meta-action-btn')

    # ========================
    # METADATA ENRICHMENT
    # ========================
    with ui.card().props('flat bordered').classes('pv-dialog-card w-full mt-2'):
        ui.label('Metadata Enrichment').classes('text-sm font-semibold pv-text-dim')
        ui.label('Fetch and enrich metadata from external sources').classes('text-xs pv-text-dimmer')

        with ui.expansion('Extract EPUB Covers', icon='auto_stories').classes('w-full mt-2'):
            ui.markdown('''
            **Purpose:** Extract embedded cover images from EPUB files
            
            **When to use:**
            - EPUB books missing cover display
            - After importing new EPUB files
            - Alternative to online cover fetching
            
            **Process:** Extracts cover from EPUB metadata or first image in book
            ''')

            def _epub_covers_click() -> None:
                async def _go(library_ids: list[str] | None, opts: dict) -> None:
                    overwrite = opts.get('overwrite', False)
                    cb = _make_progress_callback()
                    r = await _run_with_progress(
                        label='Extract EPUB covers',
                        runner=lambda: extract_epub_covers(library_ids=library_ids, overwrite=overwrite, on_progress=cb),
                        progress_bar=progress_bar,
                        progress_label=progress_label,
                    )
                    if r is not None:
                        msg = f'EPUB covers: Processed={r.processed}, Success={r.succeeded}, Skipped={r.skipped}, Failed={r.failed}'
                        ui.notify(msg, color='positive', timeout=6000)

                _choose_libraries_with_options(
                    title='Extract EPUB Covers',
                    subtitle='Extract cover images embedded in EPUB files',
                    show_overwrite=True,
                    on_confirm=_go,
                ).open()

            with ui.row().classes('w-full justify-end pt-2'):
                ui.button('Run', on_click=_epub_covers_click, icon='collections').props('outline').classes('pv-meta-action-btn')

        with ui.expansion('Fetch DOI Metadata (Papers)', icon='article').classes('w-full'):
            ui.markdown('''
            **Purpose:** Enrich paper metadata using DOI identifiers
            
            **Sources:** CrossRef, Semantic Scholar, arXiv
            
            **Metadata fetched:**
            - Title, authors, publication year
            - Journal, publisher, volume/issue
            - Abstract and citations
            
            **When to use:**
            - Papers with DOI but missing metadata
            - To improve paper organization
            - Research paper collections
            
            **Note:** DOI is auto-extracted from PDF files if not already set
            ''')

            def _doi_click() -> None:
                async def _go(library_ids: list[str] | None, opts: dict) -> None:
                    overwrite = opts.get('overwrite', False)
                    r = await _run_metadata_queue_job(
                        label='Fetch DOI metadata',
                        runner_with_progress=lambda cb: trove_doi_metadata(
                            library_ids=library_ids,
                            overwrite=overwrite,
                            on_progress=cb,
                        ),
                        progress_bar=progress_bar,
                        progress_label=progress_label,
                    )
                    if r is not None:
                        msg = f'DOI metadata: Processed={r.processed}, Success={r.succeeded}, Skipped={r.skipped}, Failed={r.failed}'
                        ui.notify(msg, color='positive', timeout=6000)

                _choose_libraries_with_options(
                    title='Fetch DOI Metadata',
                    subtitle='Bulk-fetch metadata for papers using DOI identifiers',
                    show_overwrite=True,
                    on_confirm=_go,
                ).open()

            with ui.row().classes('w-full justify-end pt-2'):
                ui.button('Run', on_click=_doi_click, icon='science').props('outline').classes('pv-meta-action-btn')

        with ui.expansion('Fetch ISBN Metadata & Covers (Books)', icon='library_books').classes('w-full'):
            ui.markdown('''
            **Purpose:** Enrich book metadata using ISBN identifiers and optionally fetch covers
            
            **Sources:** OpenLibrary, Google Books (if configured)
            
            **Metadata fetched:**
            - Title, authors, publication year
            - Publisher, series information
            - Descriptions, subjects, page count
            
            **Cover images:** Enable "Also fetch cover images" to download covers for books with ISBNs
            
            **When to use:**
            - Books with ISBN but missing metadata
            - After importing new books
            - To improve book organization and visual appeal
            
            **Note:** ISBN is auto-detected from EPUB/PDF contents or filename if not already set
            ''')

            def _isbn_click() -> None:
                async def _go(library_ids: list[str] | None, opts: dict) -> None:
                    overwrite = opts.get('overwrite', False)
                    do_covers = opts.get('fetch_covers', False)
                    r = await _run_metadata_queue_job(
                        label='Fetch ISBN metadata',
                        runner_with_progress=lambda cb: trove_isbn_metadata(
                            library_ids=library_ids,
                            overwrite=overwrite,
                            fetch_covers=do_covers,
                            on_progress=cb,
                        ),
                        progress_bar=progress_bar,
                        progress_label=progress_label,
                    )
                    if r is not None:
                        extra = ' (with covers)' if do_covers else ''
                        msg = f'ISBN metadata{extra}: Processed={r.processed}, Success={r.succeeded}, Skipped={r.skipped}, Failed={r.failed}'
                        ui.notify(msg, color='positive', timeout=6000)

                _choose_libraries_with_options(
                    title='Fetch ISBN Metadata & Covers',
                    subtitle='Bulk-fetch metadata and covers for books using ISBN identifiers',
                    show_overwrite=True,
                    show_fetch_covers=True,
                    on_confirm=_go,
                ).open()

            with ui.row().classes('w-full justify-end pt-2'):
                ui.button('Run', on_click=_isbn_click, icon='barcode_scanner').props('outline').classes('pv-meta-action-btn')

    # ========================
    # ADVANCED / DANGER ZONE
    # ========================
    with ui.card().props('flat bordered').classes('pv-dialog-card w-full mt-2'):
        with ui.expansion('Advanced Operations', icon='warning').classes('w-full'):
            ui.label('These operations are rarely needed. Use with caution.').classes('text-xs text-orange pt-1')

            ui.separator().classes('opacity-20 my-2')

            # --- Fetch Book Covers (standalone) ---
            with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
                ui.label('Fetch Book Covers (standalone)').classes('text-sm font-semibold pv-text-dim')
                ui.label('Download covers for books that already have ISBNs set. For most use cases, use "Fetch ISBN Metadata & Covers" instead.').classes('text-xs pv-text-dimmer')

                def _covers_click() -> None:
                    async def _go(library_ids: list[str] | None, opts: dict) -> None:
                        cb = _make_progress_callback()
                        r = await _run_with_progress(
                            label='Fetch book covers',
                            runner=lambda: fetch_book_covers(library_ids=library_ids, on_progress=cb),
                            progress_bar=progress_bar,
                            progress_label=progress_label,
                        )
                        if r is not None:
                            msg = f'Covers: Processed={r.processed}, Success={r.succeeded}, Skipped={r.skipped}, Failed={r.failed}'
                            ui.notify(msg, color='positive', timeout=6000)

                    _choose_libraries_with_options(
                        title='Fetch Book Covers',
                        subtitle='Download cover images for books with existing ISBNs',
                        on_confirm=_go,
                    ).open()

                with ui.row().classes('w-full justify-end pt-2'):
                    ui.button('Run', on_click=_covers_click, icon='download').props('outline').classes('pv-meta-action-btn')

            ui.separator().classes('opacity-20 my-2')

            # --- User Data Cleanup ---
            with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
                ui.label('User Data Cleanup').classes('text-sm font-semibold pv-text-dim')
                ui.label('Remove orphaned database records and files from deleted users').classes('text-xs pv-text-dimmer')

                with ui.expansion('What does this do?', icon='help_outline').classes('w-full mt-2'):
                    ui.markdown('''
                    **Purpose:** Clean up data left behind after deleting users
                    
                    **Actions performed:**
                    - Removes database records referencing deleted users
                    - Deletes orphaned user libraries, shares, and settings
                    - Optionally removes orphaned user directories from disk
                    
                    **When to use:**
                    - After deleting user accounts
                    - To free up disk space from old user files
                    - To maintain database integrity
                    
                    **Safety:** Always test with "Dry run" first to preview changes
                    ''')

                dry_run_cb = ui.checkbox('Dry run (preview only, no actual deletions)', value=True).classes('text-sm pt-2')
                delete_dirs_cb = ui.checkbox('Also delete orphaned user folders from disk', value=False).classes('text-sm')

                with ui.row().classes('w-full items-center gap-2 pt-2'):
                    ui.icon('warning', color='orange').classes('text-base')
                    ui.label('Recommended: Run with dry run enabled first to review what will be deleted').classes('text-xs text-orange')

                async def _run_user_cleanup(_e=None) -> None:
                    progress_bar.set_visibility(True)
                    progress_label.set_visibility(True)
                    progress_label.text = 'Running user cleanup…'
                    progress_bar.value = None  # indeterminate
                    try:
                        r = await asyncio.to_thread(
                            lambda: clean_deleted_users(
                                dry_run=bool(dry_run_cb.value),
                                delete_orphan_user_dirs=bool(delete_dirs_cb.value),
                            )
                        )
                        mode = 'Preview' if r.dry_run else 'Completed'
                        msg = (
                            f"{mode}: "
                            f"DB records deleted={r.db_deleted}, updated={r.db_updated} | "
                            f"Files deleted={r.fs_deleted} | "
                            f"Orphan directories found={len(r.orphan_user_dirs)}"
                        )
                        ui.notify(msg, color='positive' if not r.dry_run else 'info', timeout=8000)
                        on_changed()
                    except Exception as ex:
                        ui.notify(f'Error: {str(ex)}', color='negative')
                    finally:
                        progress_bar.set_visibility(False)
                        progress_label.text = ''
                        progress_label.set_visibility(False)

                with ui.row().classes('w-full justify-end pt-2'):
                    ui.button('Run Cleanup', on_click=_run_user_cleanup, icon='cleaning_services').props('color=primary').classes('pv-meta-save-btn')
