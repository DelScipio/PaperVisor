from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

# Add the project root to the sys path
sys.path.insert(0, '/home/pmmsoares/Documents/Python/PaperVisor')

from papervisor.api.opds_common import _opds_auth_rate_limit_key, _sanitize_forwarded_host, _sanitize_forwarded_proto
from papervisor.api.opds_common import OPDSUrlBuilder, get_api_key
from papervisor.api.opds_common import get_base_url
from papervisor.api.opds_common import get_authenticated_user
from papervisor.api.reader_api import _parse_positive_float_env, _parse_positive_int_env


def test_sanitize_forwarded_proto_accepts_http_https() -> None:
    assert _sanitize_forwarded_proto('http', 'https') == 'http'
    assert _sanitize_forwarded_proto('HTTPS', 'http') == 'https'
    assert _sanitize_forwarded_proto('ftp', 'https') == 'https'
    assert _sanitize_forwarded_proto('', 'https') == 'https'


def test_sanitize_forwarded_host_rejects_invalid(monkeypatch) -> None:
    monkeypatch.delenv('PAPERVISOR_ALLOWED_FORWARDED_HOSTS', raising=False)

    assert _sanitize_forwarded_host('example.com', 'fallback.local') == 'example.com'
    assert _sanitize_forwarded_host('example.com:8443', 'fallback.local') == 'example.com:8443'

    # invalid char
    assert _sanitize_forwarded_host('bad/host', 'fallback.local') == 'fallback.local'
    # empty host
    assert _sanitize_forwarded_host('', 'fallback.local') == 'fallback.local'


def test_sanitize_forwarded_host_allowlist(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_ALLOWED_FORWARDED_HOSTS', 'allowed.example.com,another.local')

    assert (
        _sanitize_forwarded_host('allowed.example.com', 'fallback.local')
        == 'allowed.example.com'
    )
    assert _sanitize_forwarded_host('blocked.example.com', 'fallback.local') == 'fallback.local'


def test_parse_positive_int_env(monkeypatch) -> None:
    monkeypatch.delenv('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', raising=False)
    assert _parse_positive_int_env('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', 10) == 10

    monkeypatch.setenv('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', '25')
    assert _parse_positive_int_env('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', 10) == 25

    monkeypatch.setenv('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', '-1')
    assert _parse_positive_int_env('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', 10) == 10

    monkeypatch.setenv('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', 'abc')
    assert _parse_positive_int_env('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', 10) == 10


def test_parse_positive_float_env(monkeypatch) -> None:
    monkeypatch.delenv('PAPERVISOR_FILE_ACCESS_CACHE_TTL_S', raising=False)
    assert _parse_positive_float_env('PAPERVISOR_FILE_ACCESS_CACHE_TTL_S', 2.0) == 2.0

    monkeypatch.setenv('PAPERVISOR_FILE_ACCESS_CACHE_TTL_S', '1.5')
    assert _parse_positive_float_env('PAPERVISOR_FILE_ACCESS_CACHE_TTL_S', 2.0) == 1.5

    monkeypatch.setenv('PAPERVISOR_FILE_ACCESS_CACHE_TTL_S', '0')
    assert _parse_positive_float_env('PAPERVISOR_FILE_ACCESS_CACHE_TTL_S', 2.0) == 2.0

    monkeypatch.setenv('PAPERVISOR_FILE_ACCESS_CACHE_TTL_S', 'nope')
    assert _parse_positive_float_env('PAPERVISOR_FILE_ACCESS_CACHE_TTL_S', 2.0) == 2.0


def test_get_api_key_respects_query_key_gate(monkeypatch) -> None:
    class _Req:
        def __init__(self) -> None:
            self.query_params = {'key': 'abc123'}

    req = _Req()

    monkeypatch.setenv('PAPERVISOR_OPDS_ALLOW_QUERY_KEY', '0')
    assert get_api_key(req) is None

    monkeypatch.setenv('PAPERVISOR_OPDS_ALLOW_QUERY_KEY', '1')
    assert get_api_key(req) == 'abc123'


def test_get_api_key_default_is_disabled(monkeypatch) -> None:
    class _Req:
        def __init__(self) -> None:
            self.query_params = {'key': 'abc123'}

    monkeypatch.delenv('PAPERVISOR_OPDS_ALLOW_QUERY_KEY', raising=False)
    assert get_api_key(_Req()) is None


def test_opds_rate_limit_key_uses_forwarded_ip_and_username_when_trusted(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_TRUST_FORWARDED', '1')
    request = SimpleNamespace(
        client=SimpleNamespace(host='10.0.0.2'),
        headers={'X-Forwarded-For': '203.0.113.10, 10.0.0.2'},
    )
    creds = SimpleNamespace(username='Alice')

    key = _opds_auth_rate_limit_key(request=request, credentials=creds, query_key=None)

    assert key == '203.0.113.10|u:alice'


def test_opds_rate_limit_key_uses_query_key_fingerprint(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_TRUST_FORWARDED', '0')
    request = SimpleNamespace(
        client=SimpleNamespace(host='198.51.100.2'),
        headers={},
    )

    key = _opds_auth_rate_limit_key(request=request, credentials=None, query_key='secret-key')

    assert key.startswith('198.51.100.2|k:')
    assert len(key.split(':', 1)[1]) == 16


def test_get_authenticated_user_enforces_global_ip_budget_on_failed_auth(monkeypatch) -> None:
    class _DummyLimiter:
        def __init__(self, blocked_keys: set[str]) -> None:
            self.blocked_keys = blocked_keys
            self.checked: list[str] = []
            self.reset_keys: list[str] = []

        def check(self, key: str) -> bool:
            self.checked.append(key)
            return key not in self.blocked_keys

        def reset(self, key: str) -> None:
            self.reset_keys.append(key)

    request = SimpleNamespace(
        client=SimpleNamespace(host='198.51.100.20'),
        headers={},
    )
    creds = SimpleNamespace(username='Alice', password='bad')

    global_key = '198.51.100.20'
    limiter = _DummyLimiter(blocked_keys={global_key})

    monkeypatch.setenv('PAPERVISOR_OPDS_ALLOW_QUERY_KEY', '0')
    monkeypatch.setattr('papervisor.api.opds_common.authenticate', lambda username, password: None)
    monkeypatch.setattr('papervisor.api.opds_common.authenticate_by_api_key', lambda key: None)
    monkeypatch.setattr('papervisor.api.opds_common.opds_auth_limiter', limiter)

    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(request=request, credentials=creds, key=None)

    assert exc.value.status_code == 429
    assert limiter.checked == [global_key]
    assert limiter.reset_keys == []


def test_get_authenticated_user_enforces_principal_budget_on_failed_auth(monkeypatch) -> None:
    class _DummyLimiter:
        def __init__(self, blocked_keys: set[str]) -> None:
            self.blocked_keys = blocked_keys
            self.checked: list[str] = []
            self.reset_keys: list[str] = []

        def check(self, key: str) -> bool:
            self.checked.append(key)
            return key not in self.blocked_keys

        def reset(self, key: str) -> None:
            self.reset_keys.append(key)

    request = SimpleNamespace(
        client=SimpleNamespace(host='198.51.100.21'),
        headers={},
    )
    creds = SimpleNamespace(username='Alice', password='bad')

    global_key = '198.51.100.21'
    principal_key = '198.51.100.21|u:alice'
    limiter = _DummyLimiter(blocked_keys={principal_key})

    monkeypatch.setenv('PAPERVISOR_OPDS_ALLOW_QUERY_KEY', '0')
    monkeypatch.setattr('papervisor.api.opds_common.authenticate', lambda username, password: None)
    monkeypatch.setattr('papervisor.api.opds_common.authenticate_by_api_key', lambda key: None)
    monkeypatch.setattr('papervisor.api.opds_common.opds_auth_limiter', limiter)

    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(request=request, credentials=creds, key=None)

    assert exc.value.status_code == 429
    assert limiter.checked == [global_key, principal_key]
    assert limiter.reset_keys == []


def test_get_authenticated_user_success_resets_principal_only(monkeypatch) -> None:
    class _DummyLimiter:
        def __init__(self) -> None:
            self.checked: list[str] = []
            self.reset_keys: list[str] = []

        def check(self, key: str) -> bool:
            self.checked.append(key)
            return True

        def reset(self, key: str) -> None:
            self.reset_keys.append(key)

    request = SimpleNamespace(
        client=SimpleNamespace(host='198.51.100.22'),
        headers={},
    )
    creds = SimpleNamespace(username='Alice', password='good')

    user = SimpleNamespace(id=7, username='alice', is_admin=False)
    limiter = _DummyLimiter()

    monkeypatch.setenv('PAPERVISOR_OPDS_ALLOW_QUERY_KEY', '0')
    monkeypatch.setattr('papervisor.api.opds_common.authenticate', lambda username, password: user)
    monkeypatch.setattr('papervisor.api.opds_common.authenticate_by_api_key', lambda key: None)
    monkeypatch.setattr('papervisor.api.opds_common.opds_auth_limiter', limiter)

    result = get_authenticated_user(request=request, credentials=creds, key=None)

    assert result is user
    assert limiter.checked == []
    assert limiter.reset_keys == ['198.51.100.22|u:alice']


def test_opds_url_builder_drops_key_when_query_key_disabled(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_OPDS_ALLOW_QUERY_KEY', '0')
    url = OPDSUrlBuilder('https://example.test', 'secret-key').build('all', page=1)
    assert 'key=' not in url

    monkeypatch.setenv('PAPERVISOR_OPDS_ALLOW_QUERY_KEY', '1')
    url2 = OPDSUrlBuilder('https://example.test', 'secret-key').build('all', page=1)
    assert 'key=secret-key' in url2


def test_get_base_url_uses_forwarded_headers_when_trusted(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_TRUST_FORWARDED', '1')
    monkeypatch.delenv('PAPERVISOR_ALLOWED_FORWARDED_HOSTS', raising=False)

    request = SimpleNamespace(
        headers={
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': 'public.example.com',
            'X-Forwarded-Prefix': '/pv',
        },
        url=SimpleNamespace(scheme='http', netloc='internal.local:8080'),
        scope={'root_path': ''},
    )

    monkeypatch.setattr(
        'papervisor.api.opds_common.get_setting',
        lambda key, default='': '',
    )

    assert get_base_url(request) == 'https://public.example.com/pv'


def test_get_base_url_falls_back_when_forwarded_host_not_allowed(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_TRUST_FORWARDED', '1')
    monkeypatch.setenv('PAPERVISOR_ALLOWED_FORWARDED_HOSTS', 'allowed.example.com')

    request = SimpleNamespace(
        headers={
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': 'blocked.example.com',
        },
        url=SimpleNamespace(scheme='http', netloc='internal.local:8080'),
        scope={'root_path': ''},
    )

    monkeypatch.setattr(
        'papervisor.api.opds_common.get_setting',
        lambda key, default='': '',
    )

    assert get_base_url(request) == 'https://internal.local:8080'
