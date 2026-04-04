from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from papervisor.db.models import Base, User
from papervisor.services import libraries as libraries_service


def _configure_in_memory_db(monkeypatch, tmp_path) -> sessionmaker:
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    @contextmanager
    def _fake_use_session(session=None):
        if session is not None:
            yield session
            return
        with session_local() as new_session:
            yield new_session

    monkeypatch.setattr(libraries_service, 'use_session', _fake_use_session)
    monkeypatch.setattr(
        libraries_service,
        'get_paths',
        lambda: SimpleNamespace(library_files_dir=tmp_path / 'library_files'),
    )

    return session_local


def test_create_library_blocks_case_insensitive_duplicate(monkeypatch, tmp_path) -> None:
    session_local = _configure_in_memory_db(monkeypatch, tmp_path)

    with session_local() as session:
        session.add(User(username='alice', password_hash='x', is_admin=False))
        session.commit()
        owner_id = int(session.query(User).filter(User.username == 'alice').one().id)

    libraries_service.create_library(owner_user_id=owner_id, name='Research')

    try:
        libraries_service.create_library(owner_user_id=owner_id, name='research')
    except ValueError as ex:
        assert str(ex) == 'A library with that name already exists'
    else:
        raise AssertionError('Expected duplicate library name to be blocked')


def test_update_library_blocks_case_insensitive_duplicate(monkeypatch, tmp_path) -> None:
    session_local = _configure_in_memory_db(monkeypatch, tmp_path)

    with session_local() as session:
        session.add(User(username='alice', password_hash='x', is_admin=False))
        session.commit()
        owner_id = int(session.query(User).filter(User.username == 'alice').one().id)

    first = libraries_service.create_library(owner_user_id=owner_id, name='Inbox').library
    second = libraries_service.create_library(owner_user_id=owner_id, name='Archive').library

    try:
        libraries_service.update_library(
            user_id=owner_id,
            library_id=str(second.id),
            name='inbox',
            description='',
            icon='menu_book',
        )
    except ValueError as ex:
        assert str(ex) == 'A library with that name already exists'
    else:
        raise AssertionError('Expected duplicate library name to be blocked on update')

    # Keep lints quiet about intentionally created first library.
    assert first.id
