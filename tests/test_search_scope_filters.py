from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from papervisor.db.base import Base
from papervisor.db.models import Marker, Paper, PaperMarker, PaperTag, Tag
from papervisor.services import papers_search


def _setup_in_memory_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, SessionLocal


def test_search_scope_all_includes_tag_matches(monkeypatch) -> None:
    engine, SessionLocal = _setup_in_memory_db()
    monkeypatch.setattr(papers_search, 'get_session', SessionLocal)

    with SessionLocal.begin() as session:
        session.add(
            Paper(
                id='paper-tag-all',
                title='Unrelated title',
                subtitle='',
                file_type='paper',
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.add(Tag(id=1001, name='Neural Search'))
        session.add(PaperTag(paper_id='paper-tag-all', tag_id=1001))

    rows = papers_search.list_papers_filtered(query='neural', mode='All', user_id=None, limit=50)

    assert [row.id for row in rows] == ['paper-tag-all']
    engine.dispose()


def test_search_scope_title_only_and_label_mode(monkeypatch) -> None:
    engine, SessionLocal = _setup_in_memory_db()
    monkeypatch.setattr(papers_search, 'get_session', SessionLocal)

    with SessionLocal.begin() as session:
        session.add_all(
            [
                Paper(
                    id='paper-title-match',
                    title='Large Language Models',
                    subtitle='',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
                Paper(
                    id='paper-author-only',
                    title='Different topic',
                    subtitle='',
                    authors='Large Language Models Group',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
            ]
        )

    rows = papers_search.list_papers_filtered(query='large language', mode='Title', user_id=None, limit=50)

    assert [row.id for row in rows] == ['paper-title-match']
    engine.dispose()


def test_filter_no_tags_only_returns_untagged_papers(monkeypatch) -> None:
    engine, SessionLocal = _setup_in_memory_db()
    monkeypatch.setattr(papers_search, 'get_session', SessionLocal)

    with SessionLocal.begin() as session:
        session.add_all(
            [
                Paper(
                    id='paper-no-tags',
                    title='No Tags',
                    subtitle='',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
                Paper(
                    id='paper-with-tags',
                    title='With Tags',
                    subtitle='',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
            ]
        )
        session.add(Tag(id=2001, name='AI'))
        session.add(PaperTag(paper_id='paper-with-tags', tag_id=2001))

    rows = papers_search.list_papers_filtered(
        query=None,
        mode='all',
        user_id=None,
        filters=papers_search.PaperFilters(no_tags=True),
        limit=50,
    )

    assert [row.id for row in rows] == ['paper-no-tags']
    engine.dispose()


def test_filter_no_markers_only_returns_unmarked_papers(monkeypatch) -> None:
    engine, SessionLocal = _setup_in_memory_db()
    monkeypatch.setattr(papers_search, 'get_session', SessionLocal)

    with SessionLocal.begin() as session:
        session.add_all(
            [
                Paper(
                    id='paper-no-markers',
                    title='No Markers',
                    subtitle='',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
                Paper(
                    id='paper-with-markers',
                    title='With Markers',
                    subtitle='',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
            ]
        )
        session.add(Marker(id='m-1', name='Research', icon='category', is_smart=False, scope='all', rules_json=''))
        session.add(PaperMarker(paper_id='paper-with-markers', marker_id='m-1'))

    rows = papers_search.list_papers_filtered(
        query=None,
        mode='all',
        user_id=None,
        filters=papers_search.PaperFilters(no_markers=True),
        limit=50,
    )

    assert [row.id for row in rows] == ['paper-no-markers']
    engine.dispose()


def test_filter_no_markers_excludes_auto_marker_matches(monkeypatch) -> None:
    engine, SessionLocal = _setup_in_memory_db()
    monkeypatch.setattr(papers_search, 'get_session', SessionLocal)

    with SessionLocal.begin() as session:
        session.add_all(
            [
                Paper(
                    id='paper-smart-match',
                    title='Auto Match Document',
                    subtitle='',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
                Paper(
                    id='paper-no-marker-at-all',
                    title='Plain Document',
                    subtitle='',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
            ]
        )

        session.add(
            Marker(
                id='smart-1',
                name='Auto by title',
                icon='auto_awesome',
                is_smart=True,
                scope='all',
                rules_json='{"version":2,"root":{"type":"group","op":"and","children":[{"type":"rule","field":"title","operator":"contains","value":"auto match"}]}}',
            )
        )

    rows = papers_search.list_papers_filtered(
        query=None,
        mode='all',
        user_id=None,
        filters=papers_search.PaperFilters(no_markers=True),
        limit=50,
    )

    assert [row.id for row in rows] == ['paper-no-marker-at-all']
    engine.dispose()
