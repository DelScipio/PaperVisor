from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from papervisor.db.base import Base
from papervisor.db.models import Marker, Paper, PaperMarker, PaperTag, Tag
from papervisor.services import markers


def _setup_in_memory_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, SessionLocal


def test_smart_marker_markers_empty_matches_unmarked_papers(monkeypatch) -> None:
    engine, SessionLocal = _setup_in_memory_db()
    monkeypatch.setattr(markers, 'get_session', SessionLocal)

    with SessionLocal.begin() as session:
        session.add_all(
            [
                Paper(
                    id='paper-no-marker',
                    title='No Marker',
                    subtitle='',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
                Paper(
                    id='paper-with-marker',
                    title='With Marker',
                    subtitle='',
                    file_type='paper',
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                ),
            ]
        )
        session.add(Marker(id='manual-1', name='Manual', icon='category', is_smart=False, scope='all', rules_json=''))
        session.add(PaperMarker(paper_id='paper-with-marker', marker_id='manual-1'))
        session.add(
            Marker(
                id='smart-no-marker',
                name='No Marker Rule',
                icon='auto_awesome',
                is_smart=True,
                scope='all',
                rules_json=json.dumps(
                    {
                        'version': 2,
                        'root': {
                            'type': 'group',
                            'op': 'and',
                            'children': [
                                {
                                    'type': 'rule',
                                    'field': 'markers',
                                    'operator': 'empty',
                                    'value': [],
                                }
                            ],
                        },
                    }
                ),
            )
        )

    rows = markers.list_marker_papers(user_id=None, marker_id='smart-no-marker', limit=50)

    assert [row.id for row in rows] == ['paper-no-marker']
    engine.dispose()


def test_smart_marker_tags_empty_matches_untagged_papers(monkeypatch) -> None:
    engine, SessionLocal = _setup_in_memory_db()
    monkeypatch.setattr(markers, 'get_session', SessionLocal)

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
        session.add(Tag(id=2101, name='ML'))
        session.add(PaperTag(paper_id='paper-with-tags', tag_id=2101))
        session.add(
            Marker(
                id='smart-no-tags',
                name='No Tags Rule',
                icon='auto_awesome',
                is_smart=True,
                scope='all',
                rules_json=json.dumps(
                    {
                        'version': 2,
                        'root': {
                            'type': 'group',
                            'op': 'and',
                            'children': [
                                {
                                    'type': 'rule',
                                    'field': 'tags',
                                    'operator': 'empty',
                                    'value': [],
                                }
                            ],
                        },
                    }
                ),
            )
        )

    rows = markers.list_marker_papers(user_id=None, marker_id='smart-no-tags', limit=50)

    assert [row.id for row in rows] == ['paper-no-tags']
    engine.dispose()
