from __future__ import annotations

import os

from fastapi import HTTPException, Request, Depends
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from nicegui import app

from papervisor.services.audit_logs import log_event
from papervisor.services.users import UserItem, authenticate_by_api_key

api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query_scheme = APIKeyQuery(name="api_key", auto_error=False)


def _storage_user_get(key: str):
    try:
        return app.storage.user.get(key)
    except (AttributeError, KeyError, TypeError, RuntimeError):
        return None


def _storage_user_int(key: str) -> int | None:
    raw = _storage_user_get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _storage_user_str(key: str) -> str | None:
    raw = _storage_user_get(key)
    text = str(raw or '').strip()
    return text or None


def _request_ip(request: Request | None) -> str | None:
    if request is not None and getattr(request, 'client', None) is not None:
        return request.client.host
    return _storage_user_str('__client_ip__')


def current_user_id() -> int | None:
    return _storage_user_int('user_id')


def current_username() -> str | None:
    return _storage_user_str('username')


def is_logged_in() -> bool:
    return current_user_id() is not None


def is_admin() -> bool:
    return bool(_storage_user_get('is_admin'))


def _authenticate_api_key_user(api_key: str | None) -> UserItem | None:
    if not api_key:
        return None
    return authenticate_by_api_key(api_key)


def _allow_api_query_key() -> bool:
    """Return ``True`` when REST ``?api_key=...`` auth is allowed.

    Controlled by ``PAPERVISOR_API_ALLOW_QUERY_KEY``.
    Defaults to **False** to reduce credential leakage in URLs.
    """
    val = str(os.environ.get('PAPERVISOR_API_ALLOW_QUERY_KEY', '0')).strip().lower()
    return val in {'1', 'true', 'yes', 'on'}


def require_api_login(
    request: Request,
    api_key_header_value: str | None = Depends(api_key_header_scheme),
    api_key_query_value: str | None = Depends(api_key_query_scheme),
) -> int:
    """FastAPI Dependency to enforce authentication.
    
    Returns the authenticated user's ID.
    Checks API keys first (for programmatic access),
    then falls back to NiceGUI session storage (for browser access).
    """
    
    # 1. Check API Key
    api_key = api_key_header_value
    if not api_key and _allow_api_query_key():
        api_key = api_key_query_value
    api_user = _authenticate_api_key_user(api_key)
    if api_user is not None:
        if request is not None:
            request.state.api_user_id = int(api_user.id)
            request.state.api_is_admin = bool(api_user.is_admin)
        return int(api_user.id)

    # 2. Check UI Session Cookie
    if is_logged_in():
        user_id = current_user_id()
        if user_id is None:
            raise HTTPException(status_code=401, detail='Not authenticated')
        if request is not None:
            request.state.api_user_id = user_id
            request.state.api_is_admin = is_admin()
        return user_id

    # Unauthorized
    ip_address = _request_ip(request)

    log_event(
        category='auth',
        action='api_access_denied_unauthenticated',
        level='warning',
        ip_address=ip_address,
        message='API access denied: not authenticated',
    )
    raise HTTPException(status_code=401, detail='Not authenticated')


def require_api_admin(
    request: Request,
    api_key_header_value: str | None = Depends(api_key_header_scheme),
    api_key_query_value: str | None = Depends(api_key_query_scheme),
) -> int:
    """FastAPI dependency enforcing admin access."""
    # First ensure they are logged in. This populates request.state.
    user_id = require_api_login(request, api_key_header_value, api_key_query_value)
    
    is_user_admin = False
    
    # Check if they are admin via the stored state
    if request is not None and hasattr(request.state, 'api_is_admin'):
        is_user_admin = request.state.api_is_admin
    else:
        # Fallback to UI session directly if request context is weirdly absent
        is_user_admin = is_admin()

    if not is_user_admin:
        user_id = _storage_user_int('user_id')
        username = _storage_user_str('username')
        ip_address = _request_ip(request)
        log_event(
            category='auth',
            action='api_admin_denied_non_admin',
            level='warning',
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            message='API admin access denied: admin role required',
        )
        raise HTTPException(status_code=403, detail='Admin only')

    return user_id


def login_user(
    *,
    user_id: int,
    username: str,
    is_admin: bool,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> None:
    app.storage.user['user_id'] = int(user_id)
    app.storage.user['username'] = str(username)
    app.storage.user['is_admin'] = bool(is_admin)
    log_event(
        category='auth',
        action='login_success',
        level='info',
        user_id=int(user_id),
        username=str(username),
        ip_address=ip_address,
        request_id=request_id,
        message='User login succeeded',
        details={'is_admin': bool(is_admin)},
    )


def logout_user(*, ip_address: str | None = None, request_id: str | None = None) -> None:
    user_id = _storage_user_int('user_id')
    username = _storage_user_str('username')

    try:
        app.storage.user.clear()
    except (AttributeError, KeyError, TypeError, RuntimeError):
        # fallback
        app.storage.user['user_id'] = None
        app.storage.user['username'] = None
        app.storage.user['is_admin'] = None

    if user_id is not None or username:
        log_event(
            category='auth',
            action='logout',
            level='info',
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            request_id=request_id,
            message='User logged out',
        )
