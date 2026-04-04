from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from papervisor.db.base import Base
from papervisor.db.models import Paper, PaperTag, Tag
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
