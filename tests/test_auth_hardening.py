from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, '/home/pmmsoares/Documents/Python/PaperVisor')

from papervisor import auth


class _DummyStorageUser(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def clear(self) -> None:
        super().clear()


class _DummyRequest:
    def __init__(self, ip: str = '127.0.0.1') -> None:
        self.state = SimpleNamespace()
        self.client = SimpleNamespace(host=ip)


def _patch_storage(monkeypatch, values: dict | None = None) -> None:
    storage_user = _DummyStorageUser(values or {})
    monkeypatch.setattr(auth, 'app', SimpleNamespace(storage=SimpleNamespace(user=storage_user)))


def test_require_api_login_prefers_api_key(monkeypatch) -> None:
    _patch_storage(monkeypatch, {'user_id': 99, 'is_admin': False})

    fake_user = auth.UserItem(id=7, username='kuser', is_admin=True, created_at=None)
    monkeypatch.setattr(auth, '_authenticate_api_key_user', lambda key: fake_user if key == 'k' else None)

    request = _DummyRequest()
    user_id = auth.require_api_login(request, api_key_header_value='k', api_key_query_value=None)

    assert user_id == 7
    assert request.state.api_user_id == 7
    assert request.state.api_is_admin is True


def test_require_api_login_falls_back_to_session(monkeypatch) -> None:
    _patch_storage(monkeypatch, {'user_id': 42, 'is_admin': True})
    monkeypatch.setattr(auth, '_authenticate_api_key_user', lambda key: None)

    request = _DummyRequest()
    user_id = auth.require_api_login(request, api_key_header_value=None, api_key_query_value=None)

    assert user_id == 42
    assert request.state.api_user_id == 42
    assert request.state.api_is_admin is True


def test_require_api_login_rejects_query_key_by_default(monkeypatch) -> None:
    _patch_storage(monkeypatch, {})
    monkeypatch.delenv('PAPERVISOR_API_ALLOW_QUERY_KEY', raising=False)
    monkeypatch.setattr(auth, 'log_event', lambda **kwargs: None)

    fake_user = auth.UserItem(id=8, username='query-user', is_admin=False, created_at=None)
    monkeypatch.setattr(auth, '_authenticate_api_key_user', lambda key: fake_user if key == 'qk' else None)

    request = _DummyRequest()
    with pytest.raises(HTTPException) as exc:
        auth.require_api_login(request, api_key_header_value=None, api_key_query_value='qk')

    assert exc.value.status_code == 401


def test_require_api_login_accepts_query_key_when_enabled(monkeypatch) -> None:
    _patch_storage(monkeypatch, {})
    monkeypatch.setenv('PAPERVISOR_API_ALLOW_QUERY_KEY', '1')

    fake_user = auth.UserItem(id=9, username='query-user', is_admin=False, created_at=None)
    monkeypatch.setattr(auth, '_authenticate_api_key_user', lambda key: fake_user if key == 'qk' else None)

    request = _DummyRequest()
    user_id = auth.require_api_login(request, api_key_header_value=None, api_key_query_value='qk')

    assert user_id == 9
    assert request.state.api_user_id == 9
    assert request.state.api_is_admin is False


def test_require_api_login_logs_and_raises_when_unauthenticated(monkeypatch) -> None:
    _patch_storage(monkeypatch, {})
    monkeypatch.setattr(auth, '_authenticate_api_key_user', lambda key: None)

    events: list[dict] = []

    def _capture(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(auth, 'log_event', _capture)

    request = _DummyRequest(ip='10.0.0.5')
    with pytest.raises(HTTPException) as exc:
        auth.require_api_login(request, api_key_header_value=None, api_key_query_value=None)

    assert exc.value.status_code == 401
    assert events
    assert events[-1]['action'] == 'api_access_denied_unauthenticated'
    assert events[-1]['ip_address'] == '10.0.0.5'


def test_require_api_admin_denies_non_admin(monkeypatch) -> None:
    _patch_storage(monkeypatch, {'user_id': 11, 'username': 'u1', 'is_admin': False})
    monkeypatch.setattr(auth, '_authenticate_api_key_user', lambda key: None)

    events: list[dict] = []
    monkeypatch.setattr(auth, 'log_event', lambda **kwargs: events.append(kwargs))

    request = _DummyRequest(ip='10.10.10.10')
    with pytest.raises(HTTPException) as exc:
        auth.require_api_admin(request, api_key_header_value=None, api_key_query_value=None)

    assert exc.value.status_code == 403
    assert events
    assert events[-1]['action'] == 'api_admin_denied_non_admin'
    assert events[-1]['username'] == 'u1'


def test_require_api_admin_returns_user_id_for_admin(monkeypatch) -> None:
    _patch_storage(monkeypatch, {'user_id': 12, 'username': 'admin', 'is_admin': True})
    monkeypatch.setattr(auth, '_authenticate_api_key_user', lambda key: None)

    request = _DummyRequest(ip='10.10.10.11')
    user_id = auth.require_api_admin(request, api_key_header_value=None, api_key_query_value=None)

    assert user_id == 12


def test_logout_user_logs_event_and_clears_storage(monkeypatch) -> None:
    storage_values = {'user_id': 5, 'username': 'alice', 'is_admin': True}
    _patch_storage(monkeypatch, storage_values)

    events: list[dict] = []
    monkeypatch.setattr(auth, 'log_event', lambda **kwargs: events.append(kwargs))

    auth.logout_user(ip_address='1.2.3.4', request_id='rid-1')

    assert events
    assert events[-1]['action'] == 'logout'
    assert events[-1]['user_id'] == 5
    assert auth.app.storage.user.get('user_id') is None
