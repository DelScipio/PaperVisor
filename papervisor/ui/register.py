from __future__ import annotations

from nicegui import app as nicegui_app


def register_pages() -> None:
    """Register NiceGUI pages.

    NiceGUI registers routes when page modules (with @ui.page decorators) are
    imported. This function centralizes that import side effect.
    """

    app = nicegui_app

    # Avoid duplicate registration under reload.
    try:
        if getattr(app.state, 'pv_pages_registered', False):
            return
    except Exception:
        pass

    from papervisor.ui.pages import admin_page as _admin_page  # noqa: F401
    from papervisor.ui.pages import admin_patterns as _admin_patterns  # noqa: F401
    from papervisor.ui.pages import index as _index  # noqa: F401
    from papervisor.ui.pages import login as _login  # noqa: F401
    from papervisor.ui.pages import profile_page as _profile_page  # noqa: F401
    from papervisor.ui.pages import reader_page as _reader_page  # noqa: F401
    from papervisor.ui.pages import register as _register  # noqa: F401

    try:
        app.state.pv_pages_registered = True
    except Exception:
        pass
