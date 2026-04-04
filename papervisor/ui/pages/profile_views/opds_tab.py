from __future__ import annotations

from nicegui import ui

from papervisor.services.users import get_opds_api_key, generate_opds_api_key, revoke_opds_api_key
from papervisor.services.settings import get_setting
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_header
from papervisor.ui.components.page_states import show_initial_panel_loading

def render_opds_tab(
    *,
    user_id: int,
    panel_loading: dict[str, bool],
) -> None:
    @ui.refreshable
    def render_opds_settings() -> None:
        if show_initial_panel_loading(
            panel_loading=panel_loading,
            key='opds',
            message='Loading OPDS settings…',
            refresh=render_opds_settings.refresh,
        ):
            return

        def _opds_section_header(
            *,
            title: str,
            subtitle: str | None = None,
            title_classes: str = 'text-sm font-semibold pv-text-dim',
            subtitle_classes: str = 'text-xs pv-text-dimmer',
        ) -> None:
            ui.label(title).classes(title_classes)
            if subtitle:
                ui.label(subtitle).classes(subtitle_classes)

        with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
            dialog_header(
                title='OPDS',
                icon='rss_feed',
                subtitle=None,
                extra_classes='!px-3 !py-2',
                icon_classes='text-base',
                title_classes='text-sm',
                subtitle_classes='!px-3 !pt-1 !pb-2 !text-xs',
            )

        api_directory = get_setting(key='opds_api_directory', default='').strip()

        def _render_copy_button(*, value: str, notify_message: str, tooltip: str = 'Copy') -> None:
            safe_value = value.replace("'", "\\'").replace('"', '\\"')

            async def _copy(v=safe_value, message=notify_message):
                await ui.run_javascript(f'navigator.clipboard.writeText("{v}")')
                ui.notify(message, type='positive')

            ui.button(icon='content_copy', on_click=_copy).props('flat dense').tooltip(tooltip)

        def _run_opds_key_action(action, success_message: str, success_type: str) -> None:
            def _refresh_opds_panel() -> None:
                panel_loading['opds'] = True
                render_opds_settings.refresh()

            action()
            _refresh_opds_panel()
            ui.notify(success_message, type=success_type)

        def _render_disabled_copy_button(tooltip: str) -> None:
            ui.button(icon='content_copy').props('flat dense disable').tooltip(tooltip)

        def _render_copy_or_disabled(
            *,
            copyable_key: str | None,
            value: str,
            notify_message: str,
            tooltip: str,
            disabled_tooltip: str,
        ) -> None:
            if copyable_key:
                _render_copy_button(value=value, notify_message=notify_message, tooltip=tooltip)
                return
            _render_disabled_copy_button(disabled_tooltip)

        def _readonly_opds_input(*, label: str, value: str, classes: str) -> None:
            ui.input(label, value=value).props('readonly outlined dense').classes(classes)

        def _render_opds_action_row(*, on_regenerate, on_revoke) -> None:
            with ui.row().classes('gap-2'):
                ui.button('Regenerate', on_click=on_regenerate, icon='refresh').props('outline color=orange')
                ui.button('Revoke', on_click=on_revoke, icon='delete').props('outline color=red')

        def _opds_card(*, extra_classes: str = ''):
            return dialog_card(max_width_class='', extra_classes=extra_classes)

        def _build_opds_url(*, copyable_key: str | None) -> str:
            if copyable_key and api_directory:
                return f'{api_directory}/opds/?key={copyable_key}'
            if copyable_key:
                return f'https://YOUR_DOMAIN/opds/?key={copyable_key}'
            if api_directory:
                return f'{api_directory}/opds/?key=YOUR_API_KEY'
            return 'https://YOUR_DOMAIN/opds/?key=YOUR_API_KEY'

        def _render_key_visibility_status(*, legacy_masked: bool) -> None:
            if legacy_masked:
                with ui.row().classes('w-full items-center gap-2 pt-1'):
                    ui.icon('warning', color='orange').classes('text-sm')
                    ui.label(
                        'Legacy key is masked. Regenerate once to store a persistent, visible key.'
                    ).classes('text-xs text-orange')
                return
            ui.label('Key is persisted and will stay visible after refresh.').classes(
                'text-xs text-positive pt-1'
            )

        def _render_opds_url_status(*, api_directory_value: str) -> None:
            if not api_directory_value:
                ui.label(
                    'Replace YOUR_DOMAIN with your server address (use https when available). '
                    'Ask your admin to configure the API directory in Admin → OPDS.'
                ).classes('text-xs pv-text-dimmer pt-1')
                return
            ui.label(
                'This URL is ready to use. Configured by admin in Admin → OPDS → API Directory.'
            ).classes('text-xs text-positive pt-1')

        def _key_action(*, action, message: str, status: str):
            return lambda: _run_opds_key_action(action, message, status)

        def _opds_separator() -> None:
            ui.separator().classes('my-2')
        
        # API Key Section
        with _opds_card():
            _opds_section_header(
                title='OPDS API Key',
                subtitle=None,
            )

            stored_key = str(get_opds_api_key(user_id) or '').strip()
            has_key = bool(stored_key)
            legacy_masked = stored_key == '••••••••'
            copyable_key = stored_key if (has_key and not legacy_masked) else None

            if has_key:
                with ui.row().classes('w-full items-center gap-3 pt-1'):
                    _readonly_opds_input(
                        label='Your API Key',
                        value=stored_key,
                        classes='flex-1 font-mono text-sm',
                    )
                    _render_copy_or_disabled(
                        copyable_key=copyable_key,
                        value=copyable_key or '',
                        notify_message='API key copied',
                        tooltip='Copy',
                        disabled_tooltip='Regenerate key to make it copyable',
                    )

                _render_key_visibility_status(legacy_masked=legacy_masked)

                _opds_separator()

                opds_url = _build_opds_url(copyable_key=copyable_key)
                
                with ui.row().classes('w-full items-center gap-3'):
                    _readonly_opds_input(
                        label='OPDS URL with your API Key',
                        value=opds_url,
                        classes='flex-1 font-mono text-xs',
                    )
                    _render_copy_or_disabled(
                        copyable_key=copyable_key,
                        value=opds_url,
                        notify_message='URL copied',
                        tooltip='Copy URL',
                        disabled_tooltip='Regenerate key to copy URL',
                    )

                _render_opds_url_status(api_directory_value=api_directory)

                _opds_separator()

                _render_opds_action_row(
                    on_regenerate=_key_action(
                        action=lambda: generate_opds_api_key(user_id),
                        message='New API key generated and saved',
                        status='positive',
                    ),
                    on_revoke=_key_action(
                        action=lambda: revoke_opds_api_key(user_id),
                        message='API key revoked',
                        status='warning',
                    ),
                )

            else:
                ui.label('No API key generated').classes('text-xs pv-text-dimmer pt-1')
                ui.button(
                    'Generate My API Key',
                    on_click=_key_action(
                        action=lambda: generate_opds_api_key(user_id),
                        message='API key created and saved',
                        status='positive',
                    ),
                    icon='vpn_key',
                ).props('color=primary')
        
    render_opds_settings()
    return render_opds_settings
