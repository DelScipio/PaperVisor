from __future__ import annotations

from nicegui import app
from nicegui import ui

from papervisor.auth import login_user
from papervisor.core.rate_limit import login_limiter
from papervisor.services.audit_logs import log_event
from papervisor.services.settings import get_registration_enabled, settings_available
from papervisor.services.users import bootstrap_registration_open, create_user
from papervisor.ui.theme import setup_theme


@ui.page('/register')
def register_page() -> None:
    setup_theme()
    ui.query('body').classes('bg-transparent')

    # If already logged in, go home.
    if app.storage.user.get('user_id'):
        ui.timer(0.01, lambda: ui.navigate.to('/'), once=True)
        ui.label('Redirecting…').classes('pv-text-dim')
        return

    can_persist = settings_available()
    bootstrap_open = bootstrap_registration_open()
    enabled = bootstrap_open or (bool(get_registration_enabled()) if can_persist else False)

    with ui.column().classes('w-full max-w-md mx-auto px-6 py-10 gap-4'):
        ui.label('Create account').classes('text-2xl font-bold')
        ui.label('Create a new PaperVisor user account.').classes('text-xs pv-text-dimmer')
        if bootstrap_open:
            ui.label('No users exist yet. The first account will be created as admin.').classes('text-xs pv-text-dimmer')

        if not enabled:
            with ui.card().props('flat bordered').classes('pv-surface w-full'):
                ui.label('Registration is disabled.').classes('text-sm')
                if not can_persist:
                    ui.label('Database migrations are required before registration can be enabled.').classes(
                        'text-xs pv-text-dimmer pt-1'
                    )
                    ui.label('Run: alembic upgrade heads').classes('text-xs pv-text-dimmer')
                ui.button('Back to login', on_click=lambda: ui.navigate.to('/login')).props('flat').classes('mt-2')
            return

        with ui.card().props('flat bordered').classes('pv-surface w-full'):
            with ui.column().classes('w-full gap-3'):
                user_in = ui.input('Username').props('outlined dense').classes('w-full')
                pass_in = ui.input('Password', password=True, password_toggle_button=True).props('outlined dense').classes(
                    'w-full'
                )
                pass2_in = ui.input(
                    'Confirm password', password=True, password_toggle_button=True
                ).props('outlined dense').classes('w-full')

                status = ui.label('').classes('text-xs pv-text-dimmer')

                def _submit() -> None:
                    status.text = ''
                    u = str(user_in.value or '').strip()
                    p1 = str(pass_in.value or '')
                    p2 = str(pass2_in.value or '')

                    if not u or not p1 or not p2:
                        status.text = 'Fill in all fields.'
                        log_event(
                            category='auth',
                            action='registration_validation_failed',
                            level='warning',
                            username=u or None,
                            message='Registration failed: missing required fields',
                        )
                        return
                    if p1 != p2:
                        status.text = 'Passwords do not match.'
                        log_event(
                            category='auth',
                            action='registration_validation_failed',
                            level='warning',
                            username=u or None,
                            message='Registration failed: passwords do not match',
                        )
                        return

                    # Per-IP rate limiting.
                    client_ip = str(getattr(app, '_client_ip', None) or 'unknown')
                    try:
                        client_ip = app.storage.user.get('__client_ip__') or client_ip
                    except Exception:
                        pass
                    if not login_limiter.check(client_ip):
                        status.text = 'Too many attempts. Please try again later.'
                        log_event(
                            category='auth',
                            action='registration_blocked_rate_limit',
                            level='warning',
                            username=u or None,
                            ip_address=str(client_ip),
                            message='Registration blocked due to rate limiting',
                        )
                        return

                    try:
                        item = create_user(username=u, password=p1, is_admin=False)
                        log_event(
                            category='auth',
                            action='registration_success',
                            level='info',
                            user_id=int(item.id),
                            username=item.username,
                            ip_address=str(client_ip),
                            message='User self-registration succeeded',
                        )
                        login_limiter.reset(client_ip)
                        login_user(user_id=item.id, username=item.username, is_admin=item.is_admin, ip_address=str(client_ip))
                        ui.navigate.to('/')
                    except Exception as ex:
                        status.text = str(ex)
                        log_event(
                            category='auth',
                            action='registration_failed',
                            level='warning',
                            username=u or None,
                            ip_address=str(client_ip),
                            message='Registration failed during account creation',
                            details={'error': str(ex)},
                        )

                user_in.on('keydown.enter', lambda _e: _submit())
                pass_in.on('keydown.enter', lambda _e: _submit())
                pass2_in.on('keydown.enter', lambda _e: _submit())

                ui.button('Create account', on_click=_submit).props('color=primary').classes('w-full')
                ui.button('Back to login', on_click=lambda: ui.navigate.to('/login')).props('flat').classes('w-full')
