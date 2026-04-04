from __future__ import annotations

from nicegui import ui, app

from papervisor.auth import login_user, logout_user
from papervisor.core.rate_limit import login_limiter
from papervisor.services.audit_logs import log_event
from papervisor.services.settings import get_registration_enabled, settings_available
from papervisor.services.users import bootstrap_registration_open
from papervisor.services.users import authenticate
from papervisor.ui.theme import setup_theme


@ui.page('/login')
def login_page() -> None:
    setup_theme()
    ui.query('body').classes('bg-transparent pv-login-page')

    # If already logged in, go home.
    if app.storage.user.get('user_id'):
        ui.timer(0.01, lambda: ui.navigate.to('/'), once=True)
        ui.label('Redirecting…').classes('pv-text-dim')
        return

    with ui.column().classes('w-full max-w-md mx-auto px-6 py-10 gap-4'):
        with ui.column().classes('w-full gap-1'):
            ui.label('Sign in').classes('text-2xl font-bold leading-tight')
            ui.label('Use your PaperVisor account to continue.').classes('text-xs pv-text-dimmer')

        with ui.card().props('flat bordered').classes('pv-surface w-full'):
            with ui.column().classes('w-full gap-3'):
                # Keep login fields deterministic across browser autofill/credential overlays.
                auth_field_props = 'outlined dense autocorrect=off autocapitalize=off spellcheck=false'
                user_in = ui.input('Username').props(f'{auth_field_props} autocomplete=username').classes(
                    'w-full pv-login-input pv-login-auth-input'
                )
                pass_in = ui.input('Password', password=True, password_toggle_button=True).props(
                    f'{auth_field_props} autocomplete=current-password'
                ).classes('w-full pv-login-input pv-login-auth-input')
                status = ui.label('').classes('text-xs pv-text-dimmer')

                def _submit() -> None:
                    status.text = ''
                    u = str(user_in.value or '').strip()
                    p = str(pass_in.value or '')
                    if not u or not p:
                        status.text = 'Enter username and password.'
                        return

                    # Per-IP rate limiting to prevent brute-force attacks.
                    client_ip = str(getattr(app, '_client_ip', None) or 'unknown')
                    try:
                        client_ip = app.storage.user.get('__client_ip__') or client_ip
                    except Exception:
                        pass
                    if not login_limiter.check(client_ip):
                        status.text = 'Too many login attempts. Please try again later.'
                        log_event(
                            category='auth',
                            action='login_blocked_rate_limit',
                            level='warning',
                            username=u,
                            ip_address=str(client_ip),
                            message='Login blocked due to rate limiting',
                        )
                        return

                    item = authenticate(username=u, password=p)
                    if item is None:
                        status.text = 'Invalid username or password.'
                        log_event(
                            category='auth',
                            action='login_failed',
                            level='warning',
                            username=u,
                            ip_address=str(client_ip),
                            message='Login failed: invalid username or password',
                        )
                        return

                    login_limiter.reset(client_ip)
                    login_user(user_id=item.id, username=item.username, is_admin=item.is_admin, ip_address=str(client_ip))
                    ui.navigate.to('/')

                # Press Enter to submit
                user_in.on('keydown.enter', lambda _e: _submit())
                pass_in.on('keydown.enter', lambda _e: _submit())

                ui.button('Login', on_click=_submit).props('color=primary').classes('w-full')

                can_register = bootstrap_registration_open() or (settings_available() and bool(get_registration_enabled()))
                if can_register:
                    ui.button('Create account', on_click=lambda: ui.navigate.to('/register')).props('flat').classes('w-full')

        # Safety: allow clearing a broken session
        def _clear() -> None:
            logout_user(ip_address=str(getattr(app, '_client_ip', None) or 'unknown'))
            ui.notify('Session cleared', color='positive')

        ui.button('Clear session', on_click=_clear).props('flat').classes('self-start text-xs')
