from __future__ import annotations

from papervisor.services import doi


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_fetch_crossref_metadata_normalizes_resolver_url_and_trailing_punctuation(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _fake_get(url: str, **_kwargs):
        captured['url'] = url
        return _FakeResponse(
            {
                'message': {
                    'title': ['Paper Title'],
                    'URL': 'https://doi.org/10.1038/nphys1170',
                }
            }
        )

    monkeypatch.setattr(doi.requests, 'get', _fake_get)

    meta = doi.fetch_crossref_metadata('https://doi.org/10.1038/nphys1170.')

    assert meta.doi == '10.1038/nphys1170'
    assert captured['url'].endswith('/10.1038/nphys1170')


def test_fetch_crossref_metadata_extracts_doi_from_free_text(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _fake_get(url: str, **_kwargs):
        captured['url'] = url
        return _FakeResponse({'message': {'title': ['x']}})

    monkeypatch.setattr(doi.requests, 'get', _fake_get)

    meta = doi.fetch_crossref_metadata('See DOI: 10.1000/xyz123). Thanks')

    assert meta.doi == '10.1000/xyz123'
    assert captured['url'].endswith('/10.1000/xyz123')
