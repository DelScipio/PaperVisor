from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import app as nicegui_app

if TYPE_CHECKING:
    from fastapi import FastAPI


def register_api(fastapi_app: 'FastAPI | None' = None) -> None:
    """Register API routes.

    This keeps route registration explicit and localized, rather than relying on
    importing modules at app startup for side effects.
    """

    app = fastapi_app or nicegui_app

    # Avoid duplicate route registration under reload.
    try:
        if getattr(app.state, 'pv_api_registered', False):
            return
    except AttributeError:
        # If app.state isn't available for some reason, proceed best-effort.
        pass

    # OPDS endpoints (still uses decorators on the NiceGUI/FastAPI app).
    from papervisor.api import opds_api as _opds_api  # noqa: F401

    # REST API v1 – uses an APIRouter; must be included explicitly.
    from papervisor.api.reader_api import register_legacy_redirects, router as reader_router

    app.include_router(reader_router)
    register_legacy_redirects()

    try:
        app.state.pv_api_registered = True
    except AttributeError:
        pass
