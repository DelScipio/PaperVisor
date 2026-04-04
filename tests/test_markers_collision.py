from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from papervisor.db.models import Base
from papervisor.services import markers as markers_service


def _configure_in_memory_db(monkeypatch) -> None:
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    @contextmanager
    def _fake_get_session():
        with SessionLocal() as session:
            yield session

    monkeypatch.setattr(markers_service, 'get_session', _fake_get_session)


def test_create_marker_blocks_case_insensitive_duplicate_for_same_owner(monkeypatch) -> None:
    _configure_in_memory_db(monkeypatch)

    markers_service.create_marker(name='Science', owner_user_id=1)

    try:
        markers_service.create_marker(name='science', owner_user_id=1)
    except ValueError as ex:
        assert str(ex) == 'A marker with this name already exists'
    else:
        raise AssertionError('Expected duplicate marker name to be blocked')


def test_create_marker_allows_same_name_for_different_owners(monkeypatch) -> None:
    _configure_in_memory_db(monkeypatch)

    first = markers_service.create_marker(name='Science', owner_user_id=1)
    second = markers_service.create_marker(name='science', owner_user_id=2)

    assert first.id != second.id


def test_update_marker_blocks_case_insensitive_duplicate_for_same_owner(monkeypatch) -> None:
    _configure_in_memory_db(monkeypatch)

    first = markers_service.create_marker(name='Alpha', owner_user_id=1)
    second = markers_service.create_marker(name='Beta', owner_user_id=1)

    try:
        markers_service.update_marker(
            marker_id=second.id,
            name='alpha',
            icon='category',
            is_smart=False,
            user_id=1,
        )
    except ValueError as ex:
        assert str(ex) == 'A marker with this name already exists'
    else:
        raise AssertionError('Expected duplicate marker name to be blocked on update')


def test_create_auto_marker_blocks_case_insensitive_duplicate_for_same_owner(monkeypatch) -> None:
    _configure_in_memory_db(monkeypatch)

    markers_service.create_marker(
        name='To Read',
        owner_user_id=1,
        is_smart=True,
        rules_json='{"version":2,"root":{"type":"group","op":"and","children":[]}}',
    )

    try:
        markers_service.create_marker(
            name='to read',
            owner_user_id=1,
            is_smart=True,
            rules_json='{"version":2,"root":{"type":"group","op":"and","children":[]}}',
        )
    except ValueError as ex:
        assert str(ex) == 'A marker with this name already exists'
    else:
        raise AssertionError('Expected duplicate auto marker name to be blocked')
