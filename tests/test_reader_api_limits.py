from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

# Add project root to import path
sys.path.insert(0, '/home/pmmsoares/Documents/Python/PaperVisor')

from papervisor.api import reader_api
from papervisor.services.users import UserItem


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(reader_api.router)

    def _fake_login(request: Request) -> int:
        request.state.api_user_id = 1
        request.state.api_is_admin = True
        return 1

    app.dependency_overrides[reader_api.require_api_login] = _fake_login
    return app


def test_get_paper_file_returns_413_when_file_too_large(tmp_path, monkeypatch) -> None:
    app = _build_test_app()
    client = TestClient(app)

    pdf_path = tmp_path / 'big.pdf'
    pdf_path.write_bytes(b'x' * 64)

    monkeypatch.setenv('PAPERVISOR_MAX_STREAMED_FILE_BYTES', '16')
    monkeypatch.setattr(
        reader_api,
        '_paper_file_path_for_user_cached',
        lambda user_id, paper_id: str(pdf_path),
    )

    response = client.get('/api/v1/papers/p1/file')
    assert response.status_code == 413
    assert response.json()['detail'] == 'File too large to serve'


def test_get_paper_raw_returns_413_when_file_too_large(tmp_path, monkeypatch) -> None:
    app = _build_test_app()
    client = TestClient(app)

    epub_path = tmp_path / 'big.epub'
    epub_path.write_bytes(b'x' * 64)

    monkeypatch.setenv('PAPERVISOR_MAX_STREAMED_FILE_BYTES', '16')
    monkeypatch.setattr(
        reader_api,
        '_paper_file_path_for_user_cached',
        lambda user_id, paper_id: str(epub_path),
    )

    response = client.get('/api/v1/papers/p2/raw')
    assert response.status_code == 413
    assert response.json()['detail'] == 'File too large to serve'


def test_health_returns_minimal_payload_for_anonymous(monkeypatch, tmp_path) -> None:
    app = _build_test_app()
    client = TestClient(app)

    monkeypatch.setattr(reader_api, 'get_paths', lambda: SimpleNamespace(library_files_dir=tmp_path))
    monkeypatch.setattr(reader_api, 'authenticate_by_api_key', lambda api_key: None)
    monkeypatch.setattr(reader_api, 'current_user_id', lambda: None)
    monkeypatch.setattr(reader_api, 'is_admin', lambda: False)

    response = client.get('/api/v1/health')

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {'status'}
    assert body['status'] == 'ok'


def test_health_anonymous_skips_expensive_diagnostics(monkeypatch, tmp_path) -> None:
    app = _build_test_app()
    client = TestClient(app)

    monkeypatch.setattr(reader_api, 'authenticate_by_api_key', lambda api_key: None)
    monkeypatch.setattr(reader_api, 'current_user_id', lambda: None)
    monkeypatch.setattr(reader_api, 'is_admin', lambda: False)
    monkeypatch.setattr(
        'papervisor.services.papers.get_dashboard_counts',
        lambda: (_ for _ in ()).throw(AssertionError('dashboard counts should not be called')),
    )
    monkeypatch.setattr(
        reader_api.shutil,
        'disk_usage',
        lambda path: (_ for _ in ()).throw(AssertionError('disk_usage should not be called')),
    )

    response = client.get('/api/v1/health')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_health_returns_detailed_payload_for_admin_api_key(monkeypatch, tmp_path) -> None:
    app = _build_test_app()
    client = TestClient(app)

    admin_user = UserItem(
        id=1,
        username='admin',
        is_admin=True,
        created_at=datetime.now(UTC),
    )

    monkeypatch.setattr(reader_api, 'get_paths', lambda: SimpleNamespace(library_files_dir=tmp_path))
    monkeypatch.setattr(reader_api, 'authenticate_by_api_key', lambda api_key: admin_user if api_key == 'adminkey' else None)
    monkeypatch.setattr('papervisor.services.papers.get_dashboard_counts', lambda: {'total': 12})

    response = client.get('/api/v1/health', headers={'X-API-Key': 'adminkey'})

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'ok'
    assert body['version'] == reader_api._APP_VERSION
    assert body['database'] == 'connected'
    assert isinstance(body['disk_free_mb'], int)
    assert body['disk_free_mb'] >= 0
    assert body['papers_count'] == 12


def test_save_pdf_returns_413_when_upload_too_large(tmp_path, monkeypatch) -> None:
    app = _build_test_app()
    client = TestClient(app)

    library_root = tmp_path / 'library'
    library_root.mkdir(parents=True, exist_ok=True)
    row = SimpleNamespace(id='p3', file_path='annotated.pdf', library_id='lib-1')

    monkeypatch.setenv('PAPERVISOR_MAX_PDF_UPLOAD_BYTES', '16')
    monkeypatch.setattr(reader_api, 'get_paths', lambda: SimpleNamespace(library_files_dir=library_root))
    monkeypatch.setattr(reader_api, 'get_paper', lambda paper_id: row)
    monkeypatch.setattr(reader_api, '_require_paper_manage_access', lambda user_id, row: None)

    response = client.post(
        '/api/v1/papers/p3/save_pdf',
        files={'file': ('annotated.pdf', b'x' * 64, 'application/pdf')},
    )

    assert response.status_code == 413
    assert response.json()['detail'] == 'Upload exceeds maximum allowed size'


def test_save_pdf_rejects_write_outside_library_root(tmp_path, monkeypatch) -> None:
    app = _build_test_app()
    client = TestClient(app)

    library_root = tmp_path / 'library'
    library_root.mkdir(parents=True, exist_ok=True)

    outside = tmp_path / 'outside.pdf'
    row = SimpleNamespace(id='p4', file_path=str(outside), library_id='lib-1')

    monkeypatch.setattr(reader_api, 'get_paths', lambda: SimpleNamespace(library_files_dir=library_root))
    monkeypatch.setattr(reader_api, 'get_paper', lambda paper_id: row)
    monkeypatch.setattr(reader_api, '_require_paper_manage_access', lambda user_id, row: None)

    response = client.post(
        '/api/v1/papers/p4/save_pdf',
        files={'file': ('annotated.pdf', b'%PDF-1.4\n', 'application/pdf')},
    )

    assert response.status_code == 404
    assert not outside.exists()


def test_save_pdf_rejects_symlink_escape(tmp_path, monkeypatch) -> None:
    app = _build_test_app()
    client = TestClient(app)

    library_root = tmp_path / 'library'
    library_root.mkdir(parents=True, exist_ok=True)
    outside_dir = tmp_path / 'outside'
    outside_dir.mkdir(parents=True, exist_ok=True)

    link_path = library_root / 'link'
    try:
        os.symlink(outside_dir, link_path)
    except OSError:
        return

    row = SimpleNamespace(id='p5', file_path='link/escaped.pdf', library_id='lib-1')

    monkeypatch.setattr(reader_api, 'get_paths', lambda: SimpleNamespace(library_files_dir=library_root))
    monkeypatch.setattr(reader_api, 'get_paper', lambda paper_id: row)
    monkeypatch.setattr(reader_api, '_require_paper_manage_access', lambda user_id, row: None)

    response = client.post(
        '/api/v1/papers/p5/save_pdf',
        files={'file': ('annotated.pdf', b'%PDF-1.4\n', 'application/pdf')},
    )

    assert response.status_code == 404
    assert not (outside_dir / 'escaped.pdf').exists()


def test_save_pdf_requires_manage_access(tmp_path, monkeypatch) -> None:
    app = _build_test_app()
    client = TestClient(app)

    library_root = tmp_path / 'library'
    library_root.mkdir(parents=True, exist_ok=True)
    row = SimpleNamespace(id='p6', file_path='annotated.pdf', library_id='lib-1')

    monkeypatch.setattr(reader_api, 'get_paths', lambda: SimpleNamespace(library_files_dir=library_root))
    monkeypatch.setattr(reader_api, 'get_paper', lambda paper_id: row)

    def _deny_manage(*, user_id: int, row) -> None:
        raise HTTPException(status_code=403, detail='Not allowed')

    monkeypatch.setattr(reader_api, '_require_paper_manage_access', _deny_manage)

    response = client.post(
        '/api/v1/papers/p6/save_pdf',
        files={'file': ('annotated.pdf', b'%PDF-1.4\n', 'application/pdf')},
    )

    assert response.status_code == 403
    assert response.json()['detail'] == 'Not allowed'


def test_reset_open_counts_requires_manage_access(monkeypatch) -> None:
    app = _build_test_app()
    client = TestClient(app)

    row = SimpleNamespace(id='p7', file_path='annotated.pdf', library_id='lib-1')
    monkeypatch.setattr(reader_api, 'get_paper', lambda paper_id: row)

    def _deny_manage(*, user_id: int, row) -> None:
        raise HTTPException(status_code=403, detail='Not allowed')

    monkeypatch.setattr(reader_api, '_require_paper_manage_access', _deny_manage)

    response = client.post('/api/v1/papers/p7/reset_open_counts')

    assert response.status_code == 403
    assert response.json()['detail'] == 'Not allowed'


def test_list_papers_populates_file_type_and_optional_metadata(monkeypatch) -> None:
    app = _build_test_app()
    client = TestClient(app)

    monkeypatch.setattr(reader_api, 'count_papers_filtered', lambda **kwargs: 1)
    monkeypatch.setattr(
        reader_api,
        'list_papers_filtered',
        lambda **kwargs: [
            SimpleNamespace(
                id='p-list',
                title='Book Item',
                subtitle='Sub',
                file_type='book',
                authors='Author One',
                published_year='2025',
                journal='Journal X',
                doi='10.1000/test',
                isbn='9781234567890',
                series='Series A',
                language='en',
                reading_progress=0.25,
                is_completed=False,
                is_favorite=True,
                is_to_read=False,
                open_count_total=3,
                file_suffix='.epub',
            )
        ],
    )

    response = client.get('/api/v1/papers')

    assert response.status_code == 200
    body = response.json()
    assert body['items'][0]['file_type'] == 'book'
    assert body['items'][0]['authors'] == 'Author One'
    assert body['items'][0]['published_year'] == '2025'
    assert body['items'][0]['journal'] == 'Journal X'
    assert body['items'][0]['doi'] == '10.1000/test'
    assert body['items'][0]['isbn'] == '9781234567890'
    assert body['items'][0]['series'] == 'Series A'
    assert body['items'][0]['language'] == 'en'
