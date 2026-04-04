from __future__ import annotations

from typing import Any, cast

from nicegui import ui

from papervisor.services.db_importer import get_import_report, run_import_queue


def render_imports_panel() -> None:
    @ui.refreshable
    def _render_content() -> None:
        report = cast(dict[str, Any], get_import_report(limit=50))
        config_raw = report.get('config')
        config = config_raw if isinstance(config_raw, dict) else {}
        import_dir = str(config.get('import_dir') or '-')

        with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
            ui.label('Database Imports').classes('text-base font-semibold')
            ui.label('Manage one-off imports from the configured import directory.').classes('text-xs pv-text-dimmer')
            ui.label(f'Import directory: {import_dir}').classes('text-sm pt-1')

            with ui.row().classes('w-full gap-2 pt-2'):
                def _run(dry_run: bool, force: bool) -> None:
                    result = cast(dict[str, Any], run_import_queue(dry_run=dry_run, force=force))
                    run_info_raw = result.get('run')
                    run_info = run_info_raw if isinstance(run_info_raw, dict) else {}
                    processed = int(run_info.get('processed_files') or 0)
                    imported = int(run_info.get('imported_databases') or 0)
                    mode = 'dry run' if dry_run else 'import run'
                    ui.notify(f'Queue {mode} completed: processed {processed}, imported {imported}.', color='positive')
                    _render_content.refresh()

                ui.button('Dry Run Queue', on_click=lambda: _run(True, False)).props('outline color=primary').classes('pv-meta-action-btn')
                ui.button('Run Queue Now', on_click=lambda: _run(False, True)).props('color=primary').classes('pv-meta-save-btn')

        last_run = report.get('last_run')
        with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
            ui.label('Last Run').classes('text-sm font-semibold')
            if isinstance(last_run, dict):
                status = str(last_run.get('status') or '-')
                message = str(last_run.get('message') or '-')
                started = str(last_run.get('started_at') or '-')
                completed = str(last_run.get('completed_at') or '-')
                processed = int(last_run.get('processed_files') or 0)
                imported = int(last_run.get('imported_databases') or 0)
                ui.label(f'Status: {status}').classes('text-sm')
                ui.label(f'Message: {message}').classes('text-sm')
                ui.label(f'Started: {started}').classes('text-sm')
                ui.label(f'Completed: {completed}').classes('text-sm')
                ui.label(f'Processed files: {processed}').classes('text-sm')
                ui.label(f'Imported databases: {imported}').classes('text-sm')
            else:
                ui.label('No imports have run yet.').classes('text-sm pv-text-dimmer')

        history_raw = report.get('history')
        history: list[dict[str, Any]] = [row for row in history_raw if isinstance(row, dict)] if isinstance(history_raw, list) else []
        with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
            ui.label('Recent History').classes('text-sm font-semibold')
            if history:
                columns = [
                    {'name': 'started_at', 'label': 'Started', 'field': 'started_at'},
                    {'name': 'status', 'label': 'Status', 'field': 'status'},
                    {'name': 'dry_run', 'label': 'Dry Run', 'field': 'dry_run'},
                    {'name': 'processed_files', 'label': 'Processed', 'field': 'processed_files'},
                    {'name': 'imported_databases', 'label': 'Imported', 'field': 'imported_databases'},
                    {'name': 'message', 'label': 'Message', 'field': 'message'},
                ]
                ui.table(columns=columns, rows=history).props('dense flat wrap-cells').classes('w-full')
            else:
                ui.label('History is empty.').classes('text-sm pv-text-dimmer')

    _render_content()
