"""OPDS configuration panel for admin page."""

import json

from nicegui import ui
from papervisor.services.settings import get_setting, set_setting
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_header


def render_opds_panel() -> None:
    """Render OPDS system-wide configuration panel (admin only)."""

    with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
        dialog_header(
            title='OPDS',
            icon='rss_feed',
            subtitle='Configure global OPDS server settings.',
            extra_classes='!px-3 !py-2',
            icon_classes='text-base',
            title_classes='text-sm',
            subtitle_classes='text-xs',
        )
    
    # OPDS Status Section
    with ui.card().props('flat bordered').classes('pv-dialog-card w-full'):
        enabled = get_setting(key='protocols_enabled', default='1') == '1'

        def _resolve_opds_base_url() -> str:
            """Build a best-effort OPDS base URL from admin config."""
            configured = str(get_setting(key='opds_api_directory', default='') or '').strip().rstrip('/')
            if not configured:
                return 'https://YOUR_DOMAIN'
            # If the admin already included /opds, keep it.
            return configured

        opds_base = _resolve_opds_base_url()
        # Build a readable example root URL without requiring a user API key.
        if opds_base.endswith('/opds'):
            opds_root_url = f'{opds_base}/'
            opds_ping_url = f'{opds_base}/ping'
        else:
            opds_root_url = f'{opds_base}/opds/'
            opds_ping_url = f'{opds_base}/opds/ping'

        with ui.row().classes('w-full items-start justify-between gap-4'):
            with ui.column().classes('gap-0'):
                ui.label('OPDS Server').classes('text-sm font-semibold pv-text-dim')
                ui.label('Enable or disable the OPDS catalog server for all users.').classes('text-xs pv-text-dimmer')
                ui.label('Users authenticate using their personal API key (Profile → OPDS) or HTTP Basic Auth.').classes(
                    'text-xs pv-text-dimmer'
                )

            with ui.row().classes('items-center gap-3'):
                state = {'enabled': bool(enabled)}

                @ui.refreshable
                def _status_badge() -> None:
                    ui.badge('Enabled' if state['enabled'] else 'Disabled').props(
                        f'color="{"positive" if state["enabled"] else "negative"}"'
                    ).classes('pv-chip')

                _status_badge()

                opds_toggle = ui.switch(value=state['enabled']).props('dense')

                def _apply_toggle(_e=None) -> None:
                    try:
                        is_enabled = bool(opds_toggle.value)
                        set_setting(key='protocols_enabled', value='1' if is_enabled else '0')
                        state['enabled'] = is_enabled
                        _status_badge.refresh()
                        ui.notify(f'OPDS {"enabled" if is_enabled else "disabled"}', color='positive')
                    except Exception as ex:
                        ui.notify(str(ex), color='negative')

                opds_toggle.on('update:model-value', _apply_toggle)
                opds_toggle.on('change', _apply_toggle)

        ui.separator().classes('opacity-10 my-3')

        with ui.row().classes('w-full items-center gap-2'):
            root_in = ui.input('OPDS endpoint', value=opds_root_url).props('readonly outlined dense').classes(
                'flex-1 font-mono text-xs'
            )

            def _copy_root() -> None:
                ui.run_javascript(f'navigator.clipboard.writeText({json.dumps(opds_root_url)})')
                ui.notify('Copied OPDS endpoint', color='positive', timeout=1200)

            def _open_ping() -> None:
                ui.run_javascript(f'window.open({json.dumps(opds_ping_url)}, "_blank")')

            ui.button(icon='content_copy', on_click=_copy_root).props('flat').classes('pv-meta-action-btn')
            ui.button(icon='open_in_new', on_click=_open_ping).props('flat').classes('pv-meta-action-btn')

        ui.label('Ping endpoint: used for quick connectivity checks.').classes('text-xs pv-text-dimmer pt-1')
    
    # Catalog Settings Section
    with ui.card().props('flat bordered').classes('pv-dialog-card w-full mt-2'):
        ui.label('Catalog Settings').classes('text-sm font-semibold pv-text-dim')
        ui.label('Configure OPDS catalog metadata').classes('text-xs pv-text-dimmer')
        
        # Title setting
        title_value = get_setting(key='opds_title', default='PaperVisor Library')
        with ui.row().classes('w-full items-center gap-3 pt-2'):
            title_input = ui.input('Catalog Title', value=title_value).props('outlined dense').classes('flex-1')
            
            def save_title():
                set_setting(key='opds_title', value=title_input.value)
                ui.notify('Title saved', type='positive')
            
            ui.button('Save', on_click=save_title).props('color=primary').classes('pv-meta-save-btn')
        
        # Subtitle setting
        subtitle_value = get_setting(key='opds_subtitle', default='Browse and download papers and books')
        with ui.row().classes('w-full items-center gap-3'):
            subtitle_input = ui.input('Catalog Subtitle', value=subtitle_value).props('outlined dense').classes('flex-1')
            
            def save_subtitle():
                set_setting(key='opds_subtitle', value=subtitle_input.value)
                ui.notify('Subtitle saved', type='positive')
            
            ui.button('Save', on_click=save_subtitle).props('color=primary').classes('pv-meta-save-btn')
    
    # API Directory Section
    with ui.card().props('flat bordered').classes('pv-dialog-card w-full mt-2'):
        ui.label('API Directory').classes('text-sm font-semibold pv-text-dim')
        ui.label('Configure the site directory for building user API access URLs').classes('text-xs pv-text-dimmer')
        
        # API Directory setting
        api_dir_value = get_setting(key='opds_api_directory', default='')
        with ui.row().classes('w-full items-center gap-3 pt-2'):
            api_dir_input = ui.input('API Site Directory', value=api_dir_value, placeholder='e.g., https://example.com').props('outlined dense').classes('flex-1')
            
            def save_api_dir():
                value = api_dir_input.value.strip()
                # Validate that URL includes protocol
                if value and not (value.startswith('http://') or value.startswith('https://')):
                    ui.notify('URL must start with http:// or https://', type='negative')
                    return
                set_setting(key='opds_api_directory', value=value)
                ui.notify('API directory saved', type='positive')
            
            ui.button('Save', on_click=save_api_dir).props('color=primary').classes('pv-meta-save-btn')
        
        ui.label('Base URL for OPDS API. Can be domain only (https://example.com) or with /opds path (https://example.com/opds)').classes('text-xs pv-text-dimmer pt-1')
    
