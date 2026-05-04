from __future__ import annotations

from papervisor.services import google_books


class _FakeResponse:
    def __init__(self, *, payload: dict, status_code: int = 200, headers: dict[str, str] | None = None, content: bytes | None = None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {'content-type': 'application/json'}
        if content is None:
            content = b'{}'
        self.content = content

    def json(self):
        return self._payload


def test_fetch_googlebooks_metadata_prefers_item_matching_requested_isbn(monkeypatch) -> None:
    # First item is unrelated but appears first in API result order.
    payload = {
        'items': [
            {
                'volumeInfo': {
                    'title': 'Wrong Book',
                    'authors': ['Other Author'],
                    'industryIdentifiers': [
                        {'type': 'ISBN_13', 'identifier': '9780000000001'},
                    ],
                }
            },
            {
                'volumeInfo': {
                    'title': 'Expected Book',
                    'authors': ['Correct Author'],
                    'publisher': 'Expected Publisher',
                    'publishedDate': '2020-05-01',
                    'industryIdentifiers': [
                        {'type': 'ISBN_13', 'identifier': '9780140328721'},
                    ],
                }
            },
        ]
    }

    monkeypatch.setattr(google_books, '_enabled', lambda: True)
    monkeypatch.setattr(google_books, '_request_volumes', lambda **_kwargs: (_FakeResponse(payload=payload), None))

    meta = google_books.fetch_googlebooks_metadata('9780140328721')

    assert meta.title == 'Expected Book'
    assert meta.authors == 'Correct Author'
    assert meta.publisher == 'Expected Publisher'
    assert meta.year == '2020'
    assert meta.isbn == '9780140328721'


def test_fetch_googlebooks_cover_prefers_item_matching_requested_isbn(monkeypatch) -> None:
    # First item has a cover URL but for a different ISBN; second matches the query ISBN.
    payload = {
        'items': [
            {
                'volumeInfo': {
                    'industryIdentifiers': [
                        {'type': 'ISBN_13', 'identifier': '9780000000001'},
                    ],
                    'imageLinks': {
                        'thumbnail': 'https://example.org/wrong.jpg',
                    },
                }
            },
            {
                'volumeInfo': {
                    'industryIdentifiers': [
                        {'type': 'ISBN_13', 'identifier': '9780140328721'},
                    ],
                    'imageLinks': {
                        'thumbnail': 'https://example.org/right.png',
                    },
                }
            },
        ]
    }

    monkeypatch.setattr(google_books, '_enabled', lambda: True)
    monkeypatch.setattr(google_books, '_request_volumes', lambda **_kwargs: (_FakeResponse(payload=payload), None))

    def _fake_requests_get(url: str, **_kwargs):
        if url.endswith('right.png'):
            return _FakeResponse(payload={}, headers={'content-type': 'image/png'}, content=b'png-bytes')
        return _FakeResponse(payload={}, headers={'content-type': 'image/jpeg'}, content=b'wrong-bytes')

    monkeypatch.setattr(google_books.requests, 'get', _fake_requests_get)

    data, ext = google_books.fetch_googlebooks_cover(isbn='9780140328721')

    assert data == b'png-bytes'
    assert ext == '.png'
