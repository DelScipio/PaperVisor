from __future__ import annotations

import json
from datetime import timezone

from nicegui import ui

from papervisor.services.audit_logs import list_events
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_header


def _badge_color(level: str) -> str:
    low = str(level or '').strip().lower()
    if low in {'error', 'critical'}:
        return 'negative'
    if low in {'warning', 'warn'}:
        return 'warning'
    return 'primary'


def _fmt_ts(dt) -> str:
    try:
        return dt.astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        try:
            return dt.replace(tzinfo=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return str(dt)


def render_logs_panel() -> None:
    with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
        dialog_header(
            title='Logs',
            icon='receipt_long',
            subtitle='Audit trail for useful system and security events (including failed logins).',
            extra_classes='!px-3 !py-2',
            icon_classes='text-base',
            title_classes='text-sm',
            subtitle_classes='text-xs',
        )

    state: dict[str, object] = {
        'level': '',
        'category': '',
        'limit': 200,
    }

    with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
        ui.label('Filters').classes('text-sm font-semibold pv-text-dim')

        with ui.row().classes('w-full items-center gap-2 pt-2'):
            ui.label('Quick:').classes('text-xs pv-text-dimmer')

            def _quick_category(value: str) -> None:
                state['category'] = value
                try:
                    category_sel.value = value
                    category_sel.update()
                except Exception:
                    pass
                render_rows.refresh()

            ui.button('All', on_click=lambda: _quick_category('')).props('flat dense').classes('pv-meta-action-btn')
            ui.button('Auth', on_click=lambda: _quick_category('auth')).props('flat dense').classes('pv-meta-action-btn')
            ui.button('Admin', on_click=lambda: _quick_category('admin')).props('flat dense').classes('pv-meta-action-btn')
            ui.button('API', on_click=lambda: _quick_category('api')).props('flat dense').classes('pv-meta-action-btn')
            ui.button('System', on_click=lambda: _quick_category('system')).props('flat dense').classes('pv-meta-action-btn')

        with ui.row().classes('w-full items-center gap-3 pt-2'):
            level_sel = ui.select(
                {
                    '': 'All levels',
                    'info': 'Info',
                    'warning': 'Warning',
                    'error': 'Error',
                },
                value='',
                label='Level',
            ).props('outlined dense').classes('w-44')

            category_sel = ui.select(
                {
                    '': 'All categories',
                    'auth': 'Auth',
                    'admin': 'Admin',
                    'api': 'API',
                    'system': 'System',
                },
                value='',
                label='Category',
            ).props('outlined dense').classes('w-52')

            limit_sel = ui.select(
                {
                    50: '50 rows',
                    100: '100 rows',
                    200: '200 rows',
                    500: '500 rows',
                },
                value=200,
                label='Rows',
            ).props('outlined dense').classes('w-36')

            def _set_level(e) -> None:
                args = getattr(e, 'args', None)
                state['level'] = str(args.get('value', '') if isinstance(args, dict) else args or '').strip().lower()
                render_rows.refresh()

            def _set_category(e) -> None:
                args = getattr(e, 'args', None)
                state['category'] = str(args.get('value', '') if isinstance(args, dict) else args or '').strip().lower()
                render_rows.refresh()

            def _set_limit(e) -> None:
                args = getattr(e, 'args', None)
                value = args.get('value', 200) if isinstance(args, dict) else args
                try:
                    state['limit'] = int(value or 200)
                except Exception:
                    state['limit'] = 200
                render_rows.refresh()

            level_sel.on('update:model-value', _set_level)
            category_sel.on('update:model-value', _set_category)
            limit_sel.on('update:model-value', _set_limit)

            ui.space()
            ui.button('Refresh', on_click=lambda: render_rows.refresh()).props('outline').classes('pv-meta-action-btn')

    @ui.refreshable
    def render_rows() -> None:
        level = str(state.get('level') or '').strip().lower() or None
        category = str(state.get('category') or '').strip().lower() or None
        try:
            limit = int(state.get('limit') or 200)
        except Exception:
            limit = 200

        rows = list_events(limit=limit, level=level, category=category)
        if not rows:
            with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
                ui.label('No log events found for the current filters.').classes('pv-inline-empty')
            return

        with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
            ui.label(f'Recent events ({len(rows)})').classes('text-sm font-semibold pv-text-dim')
            with ui.column().classes('w-full gap-2 pt-2'):
                for item in rows:
                    with ui.card().props('flat bordered').classes('pv-dialog-card pv-log-row w-full'):
                        with ui.row().classes('w-full items-center gap-2'):
                            ui.badge(str(item.level).upper()).props(f'color={_badge_color(item.level)}').classes('pv-chip')
                            ui.badge(str(item.category)).props('outline').classes('pv-chip')
                            ui.label(str(item.action)).classes('text-xs pv-text-dim')
                            ui.space()
                            ui.label(_fmt_ts(item.created_at)).classes('text-xs pv-text-dimmer')

                        ui.label(item.message).classes('text-sm')

                        meta_parts: list[str] = []
                        if item.username:
                            meta_parts.append(f'user={item.username}')
                        if item.user_id is not None:
                            meta_parts.append(f'user_id={item.user_id}')
                        if item.ip_address:
                            meta_parts.append(f'ip={item.ip_address}')
                        if item.request_id:
                            meta_parts.append(f'rid={item.request_id}')
                        if meta_parts:
                            ui.label(' · '.join(meta_parts)).classes('text-xs pv-text-dimmer')

                        if item.details_json:
                            try:
                                parsed = json.loads(item.details_json)
                                pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
                            except Exception:
                                pretty = str(item.details_json)
                            ui.code(pretty).classes('w-full text-xs pv-log-code')

    render_rows()
