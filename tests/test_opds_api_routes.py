from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from nicegui import app as nicegui_app

# Add the project root to the sys path
sys.path.insert(0, '/home/pmmsoares/Documents/Python/PaperVisor')

from papervisor.api.register import register_api
from papervisor.api import opds_api
from papervisor.api.opds_common import OPDSContext, OPDSUrlBuilder, get_authenticated_user, opds_context
from papervisor.db.models import Paper
from papervisor.services.users import UserItem


def test_opds_all_http_response_contains_summary_and_content(monkeypatch) -> None:
    register_api(nicegui_app)

    user = UserItem(
        id=1,
        username='tester',
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    ctx = OPDSContext(
        user=user,
        base_url='http://testserver',
        api_key=None,
        key_param='',
        url=OPDSUrlBuilder('http://testserver', None),
        sort_by=None,
    )

    paper = Paper(
        id='api-route-1',
        title='Route Summary Test',
        subtitle=None,
        abstract='Route-level abstract text for summary fallback.',
        description='Route-level description text for content body.',
        updated_at=datetime.now(UTC),
        file_path='route-summary-test.pdf',
    )

    monkeypatch.setattr(
        'papervisor.services.opds.get_complete_acquisition_papers',
        lambda user_id, sort_by='newest': [paper],
    )
    monkeypatch.setattr(
        'papervisor.api.opds_api.get_markers_for_papers',
        lambda user_id, paper_ids: {},
    )

    nicegui_app.dependency_overrides[opds_context] = lambda: ctx
    try:
        client = TestClient(nicegui_app)
        response = client.get('/opds/all')
    finally:
        nicegui_app.dependency_overrides.pop(opds_context, None)

    assert response.status_code == 200
    assert 'application/atom+xml' in response.headers.get('content-type', '')

    root = ET.fromstring(response.text)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}

    summary = root.find('atom:entry/atom:summary', ns)
    content = root.find('atom:entry/atom:content', ns)
    facet_links = root.findall("atom:link[@rel='http://opds-spec.org/facet']", ns)

    assert summary is not None
    assert (summary.text or '').strip() == 'Route-level abstract text for summary fallback.'
    assert content is not None
    content_text = (content.text or '').strip()
    assert 'Route-level description text for content body.' in content_text
    assert 'Route-level abstract text for summary fallback.' in content_text
    assert any(link.get('title') == 'A–Z' for link in facet_links)
    assert any(link.get('title') == 'Z–A' for link in facet_links)
    assert any(link.get('title') == 'All Files' for link in facet_links)
    assert any(link.get('title') == 'Academic Papers' for link in facet_links)
    assert any(link.get('title') == 'Books' for link in facet_links)
    assert all(link.get('title') != 'Title' for link in facet_links)


def test_opds_markers_navigation_includes_smart_marker_item_count(monkeypatch) -> None:
    register_api(nicegui_app)

    user = UserItem(
        id=1,
        username='tester',
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    ctx = OPDSContext(
        user=user,
        base_url='http://testserver',
        api_key=None,
        key_param='',
        url=OPDSUrlBuilder('http://testserver', None),
        sort_by=None,
    )

    smart_marker = SimpleNamespace(
        id='smart-marker-1',
        name='Auto Unread',
        is_smart=True,
    )

    monkeypatch.setattr(
        'papervisor.services.opds.get_markers',
        lambda user_id: [(smart_marker, 7)],
    )

    nicegui_app.dependency_overrides[opds_context] = lambda: ctx
    try:
        client = TestClient(nicegui_app)
        response = client.get('/opds/markers')
    finally:
        nicegui_app.dependency_overrides.pop(opds_context, None)

    assert response.status_code == 200
    assert 'application/atom+xml' in response.headers.get('content-type', '')

    root = ET.fromstring(response.text)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}

    content_nodes = root.findall('atom:entry/atom:content', ns)
    assert content_nodes
    content_texts = [(node.text or '').strip() for node in content_nodes]
    assert any('Auto Unread' in text for text in content_texts)
    assert any('(7 items)' in text for text in content_texts)


def test_opds_download_rejects_absolute_db_path(monkeypatch, tmp_path) -> None:
    user = UserItem(
        id=1,
        username='tester',
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    ctx = OPDSContext(
        user=user,
        base_url='http://testserver',
        api_key=None,
        key_param='',
        url=OPDSUrlBuilder('http://testserver', None),
        sort_by=None,
    )

    monkeypatch.setattr(
        'papervisor.services.opds.get_paper_by_id',
        lambda user_id, paper_id: SimpleNamespace(id=paper_id, file_path='/etc/passwd'),
    )
    monkeypatch.setattr('papervisor.api.opds_api.record_opened', lambda paper_id: None)
    monkeypatch.setattr(
        'papervisor.core.config.get_paths',
        lambda: SimpleNamespace(library_files_dir=tmp_path / 'library'),
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        opds_api.download_paper(request=SimpleNamespace(), paper_id='p-abs', ctx=ctx)
    assert exc.value.status_code == 404


def test_opds_download_rejects_traversal_db_path(monkeypatch, tmp_path) -> None:
    user = UserItem(
        id=1,
        username='tester',
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    ctx = OPDSContext(
        user=user,
        base_url='http://testserver',
        api_key=None,
        key_param='',
        url=OPDSUrlBuilder('http://testserver', None),
        sort_by=None,
    )

    monkeypatch.setattr(
        'papervisor.services.opds.get_paper_by_id',
        lambda user_id, paper_id: SimpleNamespace(id=paper_id, file_path='../escape.pdf'),
    )
    monkeypatch.setattr('papervisor.api.opds_api.record_opened', lambda paper_id: None)
    monkeypatch.setattr(
        'papervisor.core.config.get_paths',
        lambda: SimpleNamespace(library_files_dir=tmp_path / 'library'),
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        opds_api.download_paper(request=SimpleNamespace(), paper_id='p-traversal', ctx=ctx)
    assert exc.value.status_code == 404


def test_opds_recent_rejects_non_positive_page(monkeypatch) -> None:
    register_api(nicegui_app)

    user = UserItem(
        id=1,
        username='tester',
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    ctx = OPDSContext(
        user=user,
        base_url='http://testserver',
        api_key=None,
        key_param='',
        url=OPDSUrlBuilder('http://testserver', None),
        sort_by=None,
    )

    nicegui_app.dependency_overrides[opds_context] = lambda: ctx
    try:
        client = TestClient(nicegui_app)
        response = client.get('/opds/recent?page=0')
    finally:
        nicegui_app.dependency_overrides.pop(opds_context, None)

    assert response.status_code == 422
    assert response.json()['detail'] == 'Page must be >= 1'


def test_opds_library_rejects_non_positive_page(monkeypatch) -> None:
    register_api(nicegui_app)

    user = UserItem(
        id=1,
        username='tester',
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    ctx = OPDSContext(
        user=user,
        base_url='http://testserver',
        api_key=None,
        key_param='',
        url=OPDSUrlBuilder('http://testserver', None),
        sort_by=None,
    )

    monkeypatch.setattr('papervisor.services.opds.get_library_name', lambda user_id, library_id: 'Library')

    nicegui_app.dependency_overrides[opds_context] = lambda: ctx
    try:
        client = TestClient(nicegui_app)
        response = client.get('/opds/libraries/lib-1?page=-1')
    finally:
        nicegui_app.dependency_overrides.pop(opds_context, None)

    assert response.status_code == 422
    assert response.json()['detail'] == 'Page must be >= 1'


def test_opds_disabled_returns_404_before_auth(monkeypatch) -> None:
    monkeypatch.setattr(
        'papervisor.api.opds_common.get_setting',
        lambda key, default='': '0' if key == 'protocols_enabled' else default,
    )
    monkeypatch.setattr(
        'papervisor.api.opds_common.authenticate',
        lambda username, password: (_ for _ in ()).throw(AssertionError('authenticate should not be called')),
    )
    monkeypatch.setattr(
        'papervisor.api.opds_common.authenticate_by_api_key',
        lambda key: (_ for _ in ()).throw(AssertionError('authenticate_by_api_key should not be called')),
    )

    request = SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'), headers={})
    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(request=request, credentials=None, key=None)

    assert exc.value.status_code == 404
    assert exc.value.detail == 'OPDS is disabled'


def test_opds_book_author_rejects_non_positive_page(monkeypatch) -> None:
    register_api(nicegui_app)

    user = UserItem(
        id=1,
        username='tester',
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    ctx = OPDSContext(
        user=user,
        base_url='http://testserver',
        api_key=None,
        key_param='',
        url=OPDSUrlBuilder('http://testserver', None),
        sort_by=None,
    )

    nicegui_app.dependency_overrides[opds_context] = lambda: ctx
    try:
        client = TestClient(nicegui_app)
        response = client.get('/opds/browse/book-authors/Alice?page=0')
    finally:
        nicegui_app.dependency_overrides.pop(opds_context, None)

    assert response.status_code == 422
    assert response.json()['detail'] == 'Page must be >= 1'


def test_opds_paper_author_rejects_non_positive_page(monkeypatch) -> None:
    register_api(nicegui_app)

    user = UserItem(
        id=1,
        username='tester',
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    ctx = OPDSContext(
        user=user,
        base_url='http://testserver',
        api_key=None,
        key_param='',
        url=OPDSUrlBuilder('http://testserver', None),
        sort_by=None,
    )

    nicegui_app.dependency_overrides[opds_context] = lambda: ctx
    try:
        client = TestClient(nicegui_app)
        response = client.get('/opds/browse/paper-authors/Alice?page=-1')
    finally:
        nicegui_app.dependency_overrides.pop(opds_context, None)

    assert response.status_code == 422
    assert response.json()['detail'] == 'Page must be >= 1'
