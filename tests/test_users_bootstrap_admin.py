from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from papervisor.db.models import Base
from papervisor.services import users as users_service


def _configure_in_memory_db(monkeypatch) -> sessionmaker:
    engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    @contextmanager
    def _fake_get_session():
        with session_local() as session:
            yield session

    monkeypatch.setattr(users_service, 'get_session', _fake_get_session)
    return session_local


def test_first_created_user_is_promoted_to_admin(monkeypatch) -> None:
    _configure_in_memory_db(monkeypatch)

    first = users_service.create_user(username='first-user', password='Password123!', is_admin=False)

    assert first.is_admin is True
    assert users_service.bootstrap_registration_open() is False


def test_second_created_user_respects_requested_role(monkeypatch) -> None:
    _configure_in_memory_db(monkeypatch)

    users_service.create_user(username='admin', password='Password123!', is_admin=False)
    second = users_service.create_user(username='reader', password='Password123!', is_admin=False)

    assert second.is_admin is False


def test_bootstrap_registration_open_when_no_users(monkeypatch) -> None:
    _configure_in_memory_db(monkeypatch)

    assert users_service.bootstrap_registration_open() is True
