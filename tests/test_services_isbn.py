from __future__ import annotations

import pytest

from papervisor.services import isbn


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, content: bytes = b'{}'):
        self._payload = payload
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._payload


def test_fetch_openlibrary_metadata_raises_when_no_results(monkeypatch) -> None:
    monkeypatch.setattr(isbn.requests, 'get', lambda _url, **_kwargs: _FakeResponse(payload={}))

    with pytest.raises(ValueError, match='OpenLibrary: no results'):
        isbn.fetch_openlibrary_metadata('9780140328721')


def test_fetch_openlibrary_metadata_parses_basic_fields(monkeypatch) -> None:
    payload = {
        'ISBN:9780140328721': {
            'title': 'Matilda',
            'authors': [{'name': 'Roald Dahl'}],
            'publishers': [{'name': 'Puffin'}],
            'publish_date': '1988-10-01',
        }
    }
    monkeypatch.setattr(isbn.requests, 'get', lambda _url, **_kwargs: _FakeResponse(payload=payload))

    meta = isbn.fetch_openlibrary_metadata('9780140328721')

    assert meta.isbn == '9780140328721'
    assert meta.title == 'Matilda'
    assert meta.authors == 'Roald Dahl'
    assert meta.publisher == 'Puffin'
    assert meta.year == '1988'
