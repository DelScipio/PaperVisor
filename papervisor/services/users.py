from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import logging
import os
import secrets
import string

from sqlalchemy import func, select

from papervisor.core.exceptions import NotFoundException, ValidationException
from papervisor.db.models import User
from sqlalchemy.orm import Session

from papervisor.db.session import get_session, use_session
from papervisor.services.settings import validate_password_policy


_PBKDF2_ITERS = 210_000
_MIN_PBKDF2_ITERS = 50_000
_MAX_PBKDF2_ITERS = 2_000_000

_MAX_USERNAME_LEN = 64
_MIN_PASSWORD_LEN = 8
_OPDS_KEY_MASK = '••••••••'
_OPDS_KEY_PREFIX = 'sha256:'

logger = logging.getLogger(__name__)


def _is_sha256_hex(value: str) -> bool:
    s = str(value or '').strip().lower()
    return len(s) == 64 and all(ch in string.hexdigits for ch in s)


def _hash_opds_api_key(value: str) -> str:
    raw = str(value or '')
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return f'{_OPDS_KEY_PREFIX}{digest}'


def _is_hashed_opds_key(value: str) -> bool:
    s = str(value or '').strip().lower()
    if s.startswith(_OPDS_KEY_PREFIX):
        return _is_sha256_hex(s[len(_OPDS_KEY_PREFIX) :])
    return _is_sha256_hex(s)


@dataclass(frozen=True)
class UserItem:
    id: int
    username: str
    is_admin: bool
    created_at: datetime


def _to_item(u: User) -> UserItem:
    return UserItem(id=int(u.id), username=str(u.username), is_admin=bool(u.is_admin), created_at=u.created_at)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, _PBKDF2_ITERS, dklen=32)
    salt_b64 = base64.urlsafe_b64encode(salt).decode('ascii').rstrip('=')
    dk_b64 = base64.urlsafe_b64encode(dk).decode('ascii').rstrip('=')
    return f'pbkdf2_sha256${_PBKDF2_ITERS}${salt_b64}${dk_b64}'


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iter_s, salt_b64, dk_b64 = str(password_hash or '').split('$', 3)
        if algo != 'pbkdf2_sha256':
            return False
        iters = int(iter_s)
        if iters < _MIN_PBKDF2_ITERS or iters > _MAX_PBKDF2_ITERS:
            return False

        def _pad(s: str) -> str:
            return s + '=' * (-len(s) % 4)

        salt = base64.urlsafe_b64decode(_pad(salt_b64))
        expected = base64.urlsafe_b64decode(_pad(dk_b64))
        got = hashlib.pbkdf2_hmac('sha256', str(password or '').encode('utf-8'), salt, iters, dklen=len(expected))
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


def count_users() -> int:
    with get_session() as session:
        return int(session.scalar(select(func.count()).select_from(User)) or 0)


def list_users() -> list[UserItem]:
    with get_session() as session:
        rows = session.execute(select(User).order_by(User.username.asc())).scalars().all()
        return [_to_item(r) for r in rows]


def get_user_by_username(*, username: str) -> User | None:
    u = (username or '').replace('\x00', '').strip()
    if not u:
        return None
    with get_session() as session:
        return session.execute(select(User).where(func.lower(User.username) == u.lower())).scalar_one_or_none()


def authenticate(*, username: str, password: str) -> UserItem | None:
    u = (username or '').replace('\x00', '').strip()
    if not u:
        return None
    with get_session() as session:
        row = session.execute(select(User).where(func.lower(User.username) == u.lower())).scalar_one_or_none()
        if row is None:
            return None
        if not verify_password(str(password or ''), str(row.password_hash or '')):
            return None
        return _to_item(row)


def create_user(*, username: str, password: str, is_admin: bool = False) -> UserItem:
    u = (username or '').replace('\x00', '').strip()
    if not u:
        raise ValidationException('Username is required')
    if len(u) > _MAX_USERNAME_LEN:
        raise ValidationException('Username too long')
    if not str(password or ''):
        raise ValidationException('Password is required')
    policy_error = validate_password_policy(str(password))
    if policy_error:
        raise ValidationException(policy_error)

    with get_session() as session:
        existing = session.execute(select(User).where(func.lower(User.username) == u.lower())).scalar_one_or_none()
        if existing is not None:
            raise ValidationException('Username already exists')

        # Safety bootstrap: if this is the first account in the database,
        # always grant admin so the instance is manageable.
        existing_user_count = int(session.scalar(select(func.count()).select_from(User)) or 0)
        effective_is_admin = bool(is_admin) or existing_user_count == 0

        row = User(username=u, password_hash=hash_password(str(password)), is_admin=effective_is_admin)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_item(row)


def bootstrap_registration_open() -> bool:
    """Return True when no users exist yet (first-user bootstrap mode)."""

    try:
        return count_users() == 0
    except Exception:
        return False


def set_password(*, user_id: int, new_password: str) -> None:
    if not str(new_password or ''):
        raise ValidationException('Password is required')
    policy_error = validate_password_policy(str(new_password))
    if policy_error:
        raise ValidationException(policy_error)

    with get_session() as session:
        row = session.get(User, int(user_id))
        if row is None:
            raise NotFoundException('User not found')
        row.password_hash = hash_password(str(new_password))
        session.commit()


def set_username(*, user_id: int, new_username: str) -> None:
    u = (new_username or '').replace('\x00', '').strip()
    if not u:
        raise ValidationException('Username is required')
    if len(u) > _MAX_USERNAME_LEN:
        raise ValidationException('Username too long')

    with get_session() as session:
        row = session.get(User, int(user_id))
        if row is None:
            raise NotFoundException('User not found')

        existing = session.execute(
            select(User)
            .where(func.lower(User.username) == u.lower())
            .where(User.id != int(user_id))
        ).scalar_one_or_none()
        if existing is not None:
            raise ValidationException('Username already exists')

        row.username = u
        session.commit()


def delete_user(*, user_id: int) -> None:
    with get_session() as session:
        row = session.get(User, int(user_id))
        if row is None:
            return
        session.delete(row)
        session.commit()


def ensure_default_admin() -> bool:
    """Create a default admin user only when explicitly enabled.

    By default this is OFF for safety. To enable, set env var:
    - PAPERVISOR_CREATE_DEFAULT_ADMIN=1

    Required when enabled:
    - PAPERVISOR_DEFAULT_ADMIN_USERNAME
    - PAPERVISOR_DEFAULT_ADMIN_PASSWORD

    Returns True if created, False otherwise.
    """

    try:
        if str(os.getenv('PAPERVISOR_CREATE_DEFAULT_ADMIN', '')).strip() not in {'1', 'true', 'yes', 'on'}:
            return False

        if count_users() > 0:
            return False

        username = str(os.getenv('PAPERVISOR_DEFAULT_ADMIN_USERNAME', '') or '').strip()
        password = str(os.getenv('PAPERVISOR_DEFAULT_ADMIN_PASSWORD', '') or '')
        if not username or not password:
            logger.warning(
                'Default admin creation requested but credentials are missing. '
                'Set PAPERVISOR_DEFAULT_ADMIN_USERNAME and PAPERVISOR_DEFAULT_ADMIN_PASSWORD.'
            )
            return False
        create_user(username=username, password=password, is_admin=True)
        return True
    except Exception:
        # Best-effort: if DB isn't migrated yet, don't crash startup.
        return False


def generate_opds_api_key(user_id: int) -> str:
    """Generate a new OPDS API key for a user.

    Returns the raw key and stores it so users can view/copy it later.
    Legacy hashed keys remain supported during authentication.
    """
    api_key = secrets.token_urlsafe(16)  # 16 bytes = ~22 characters base64

    with get_session() as session:
        user = session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not user:
            raise NotFoundException('User not found')

        user.opds_api_key = api_key
        session.commit()

    return api_key


def get_opds_api_key(user_id: int) -> str | None:
    """Get the user's OPDS API key.

    Returns:
    - raw key when stored in recoverable format,
    - a masked placeholder for hashed legacy keys,
    - ``None`` when no key exists.
    """
    with get_session() as session:
        user = session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not user:
            return None
        stored = str(user.opds_api_key or '').strip()
        if not stored:
            return None
        if _is_hashed_opds_key(stored):
            return _OPDS_KEY_MASK
        return stored


def authenticate_by_api_key(api_key: str) -> UserItem | None:
    """Authenticate a user by their OPDS API key.

    Supports:
    - current recoverable plain text format
    - current hashed format: ``sha256:<hex>``
    - legacy hashed format: ``<hex>``
    - legacy recoverable plain text
    """
    if not api_key:
        return None

    with get_session() as session:
        user = session.execute(select(User).where(User.opds_api_key == api_key)).scalar_one_or_none()
        if user is not None:
            return _to_item(user)

        hashed = _hash_opds_api_key(api_key)
        legacy_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()

        user = session.execute(select(User).where(User.opds_api_key == hashed)).scalar_one_or_none()
        if not user:
            user = session.execute(select(User).where(User.opds_api_key == legacy_hash)).scalar_one_or_none()
        if not user:
            return None
        return _to_item(user)


def revoke_opds_api_key(user_id: int) -> None:
    """Revoke (delete) the OPDS API key for a user."""
    with get_session() as session:
        user = session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if user:
            user.opds_api_key = None
            session.commit()
