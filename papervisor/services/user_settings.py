from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from papervisor.core.sanitizers import clean_nul
from papervisor.db.models import UserSetting
from sqlalchemy.orm import Session

from papervisor.db.session import get_session, use_session


_MAX_USER_SETTING_KEY_LEN = 64
_MAX_USER_SETTING_VALUE_LEN = 2048


# Aliases – keep call-sites unchanged.
_clean_key = clean_nul
_clean_value = clean_nul


def get_user_setting(*, user_id: int, key: str, default: str = '') -> str:
    k = _clean_key(key)
    if not k or len(k) > _MAX_USER_SETTING_KEY_LEN:
        return str(default or '')

    try:
        with get_session() as session:
            row = session.get(UserSetting, {'user_id': int(user_id), 'key': k})
            if row is None:
                return str(default or '')
            return str(row.value or '')
    except OperationalError:
        # Table might not exist if migrations haven't been applied yet.
        return str(default or '')


def set_user_setting(*, user_id: int, key: str, value: str) -> None:
    k = _clean_key(key)
    if not k or len(k) > _MAX_USER_SETTING_KEY_LEN:
        return

    v = _clean_value(value)
    if len(v) > _MAX_USER_SETTING_VALUE_LEN:
        v = v[:_MAX_USER_SETTING_VALUE_LEN]

    try:
        with get_session() as session:
            row = session.get(UserSetting, {'user_id': int(user_id), 'key': k})
            if row is None:
                row = UserSetting(user_id=int(user_id), key=k, value=v, updated_at=datetime.now(timezone.utc))
                session.add(row)
            else:
                row.value = v
                row.updated_at = datetime.now(timezone.utc)

            try:
                session.commit()
            except IntegrityError:
                # Concurrent create/update; retry once.
                session.rollback()
                row = session.get(UserSetting, {'user_id': int(user_id), 'key': k})
                if row is None:
                    row = UserSetting(user_id=int(user_id), key=k, value=v, updated_at=datetime.now(timezone.utc))
                    session.add(row)
                else:
                    row.value = v
                    row.updated_at = datetime.now(timezone.utc)
                session.commit()
    except OperationalError:
        # Keep behavior quiet if migrations aren't applied.
        return


def get_user_setting_bool(*, user_id: int, key: str, default: bool = False) -> bool:
    """Convenience wrapper for boolean-like user settings.

    Accepts common true/false string values and keeps behavior stable even when
    migrations haven't been applied (falls back to `default`).
    """

    raw = str(get_user_setting(user_id=user_id, key=key, default=('1' if default else '0')) or '').strip().lower()
    if raw in {'1', 'true', 'yes', 'y', 'on'}:
        return True
    if raw in {'0', 'false', 'no', 'n', 'off', ''}:
        return False
    # Unknown value: fallback to default.
    return bool(default)


def set_user_setting_bool(*, user_id: int, key: str, value: bool) -> None:
    set_user_setting(user_id=user_id, key=key, value=('1' if bool(value) else '0'))
