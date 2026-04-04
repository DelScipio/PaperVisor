from __future__ import annotations

from pathlib import Path

from nicegui import app, ui

from papervisor.services.user_settings import get_user_setting


def _user_theme() -> str:
    """Return 'dark' or 'light' based on current user preference."""
    try:
        uid = int(app.storage.user.get('user_id') or 0)
        if uid:
            return str(
                get_user_setting(user_id=uid, key='ui.theme', default='dark') or 'dark'
            ).strip().lower()
    except Exception:
        pass
    return 'dark'


def current_theme() -> str:
    theme = _user_theme()
    return 'light' if theme == 'light' else 'dark'


def _theme_css_cache_token() -> str:
    try:
        css_path = Path(__file__).resolve().parent.parent / 'static' / 'theme.css'
        return str(int(css_path.stat().st_mtime))
    except Exception:
        return '1'


def setup_theme() -> None:
    theme = current_theme()
    is_light = theme == 'light'
    theme_css_token = _theme_css_cache_token()

    if is_light:
        ui.dark_mode().disable()
    else:
        ui.dark_mode().enable()

    ui.colors(
        primary='#22c55e',
        secondary='#64748b',
        accent='#22c55e',
        dark='#0b1220',
        positive='#22c55e',
        negative='#ef4444',
        info='#60a5fa',
        warning='#f59e0b',
    )

    ui.add_head_html(
        f"""
        <!-- Google Material Symbols -->
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" />
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" />
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Sharp:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" />

        <!-- App icon / favicon -->
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link rel="apple-touch-icon" href="/static/apple-touch-icon.png" />

        <script>
          (() => {{
            const applyTheme = (value) => {{
              const theme = value === 'light' ? 'light' : 'dark';
              document.documentElement.setAttribute('data-theme', theme);
              if (document.body) document.body.setAttribute('data-theme', theme);
            }};

            applyTheme('{theme}');
            window.__pvApplyTheme = applyTheme;
            window.addEventListener('pv-theme-change', (event) => {{
              const selected = event && event.detail ? event.detail.theme : null;
              applyTheme(selected);
            }});
          }})();
        </script>

        <!-- App styles — single source of truth -->
        <link rel="stylesheet" href="/static/theme.css?v={theme_css_token}" />
        """
    )
