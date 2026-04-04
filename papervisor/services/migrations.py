from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from papervisor.db.models import AppSetting, UserSetting
from papervisor.db.session import get_session


logger = logging.getLogger(__name__)


_MIGRATION_DONE_KEY = 'migrations.20260201_shelves_to_markers.done'


def _get_app_setting(*, session, key: str) -> str | None:
    try:
        row = session.get(AppSetting, key)
        return None if row is None else str(row.value or '')
    except Exception:
        return None


def _set_app_setting(*, session, key: str, value: str) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        session.add(row)
    else:
        row.value = value


def _upsert_user_setting(*, session, user_id: int, key: str, value: str) -> None:
    row = session.get(UserSetting, {'user_id': int(user_id), 'key': str(key)})
    if row is None:
        row = UserSetting(user_id=int(user_id), key=str(key), value=str(value), updated_at=datetime.now(timezone.utc))
        session.add(row)
    else:
        row.value = str(value)
        row.updated_at = datetime.now(timezone.utc)


def _rename_user_setting_key(*, session, old_key: str, new_key: str) -> None:
    rows = session.execute(
        select(UserSetting.user_id, UserSetting.value)
        .where(UserSetting.key == str(old_key))
    ).all()

    if not rows:
        return

    for (user_id, value) in rows:
        _upsert_user_setting(session=session, user_id=int(user_id), key=str(new_key), value=str(value or ''))

    session.execute(delete(UserSetting).where(UserSetting.key == str(old_key)))


def _migrate_filter_presets_payload(raw: str) -> str | None:
    """Rewrite legacy filter preset payloads.

    We rename keys inside the JSON blob:
    - filters_shelf_ids -> filters_marker_ids
    """

    try:
        data = json.loads(raw)
    except Exception:
        return None

    if not isinstance(data, list):
        return None

    changed = False
    out: list[dict[str, object]] = []

    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        payload = item.get('data')
        if not name or not isinstance(payload, dict):
            continue

        payload2 = dict(payload)

        shelf_raw = payload2.get('filters_shelf_ids')
        marker_raw = payload2.get('filters_marker_ids')
        if (marker_raw is None or str(marker_raw).strip() in {'', '[]'}) and shelf_raw is not None:
            payload2['filters_marker_ids'] = shelf_raw
            changed = True
        if 'filters_shelf_ids' in payload2:
            payload2.pop('filters_shelf_ids', None)
            changed = True

        out.append({'name': name, 'data': payload2})

    if not changed:
        return None

    try:
        encoded = json.dumps(out, ensure_ascii=False)
    except Exception:
        return None

    # user_settings value is capped at 2048 chars
    if len(encoded) > 2048:
        return None

    return encoded


def run_migrations() -> None:
    """Run one-time, idempotent data migrations.

    Safe to call on every startup; uses an AppSetting flag.
    """

    try:
        with get_session() as session:
            done = _get_app_setting(session=session, key=_MIGRATION_DONE_KEY)
            if str(done or '').strip() == '1':
                return

            # If tables are missing (fresh db without alembic applied), don't crash startup.
            try:
                session.execute(select(AppSetting.key).limit(1)).all()
                session.execute(select(UserSetting.user_id).limit(1)).all()
            except OperationalError:
                return

            logger.info('Running migration: shelves→markers (2026-02-01)')

            # App settings
            v = _get_app_setting(session=session, key='ui.remember_location.default')
            if str(v or '').strip().lower() == 'shelf':
                _set_app_setting(session=session, key='ui.remember_location.default', value='marker')

            # User settings: nav keys
            _rename_user_setting_key(session=session, old_key='nav.shelves.collapsed', new_key='nav.markers.collapsed')
            _rename_user_setting_key(session=session, old_key='nav.auto_shelves.collapsed', new_key='nav.auto_markers.collapsed')
            _rename_user_setting_key(session=session, old_key='nav.last.shelf_id', new_key='nav.last.marker_id')

            # nav.last.view value: shelf -> marker
            rows = session.execute(
                select(UserSetting.user_id, UserSetting.value)
                .where(UserSetting.key == 'nav.last.view')
            ).all()
            for (user_id, value) in rows:
                if str(value or '').strip().lower() == 'shelf':
                    _upsert_user_setting(session=session, user_id=int(user_id), key='nav.last.view', value='marker')

            # remember location per-user: shelf -> marker
            rows = session.execute(
                select(UserSetting.user_id, UserSetting.value)
                .where(UserSetting.key == 'ui.remember_location.mode')
            ).all()
            for (user_id, value) in rows:
                if str(value or '').strip().lower() == 'shelf':
                    _upsert_user_setting(session=session, user_id=int(user_id), key='ui.remember_location.mode', value='marker')

            # Filter presets blob migration
            preset_rows = session.execute(
                select(UserSetting.user_id, UserSetting.value)
                .where(UserSetting.key == 'ui.filter_presets')
            ).all()
            for (user_id, value) in preset_rows:
                raw = str(value or '').strip()
                if not raw:
                    continue
                migrated = _migrate_filter_presets_payload(raw)
                if migrated is not None:
                    _upsert_user_setting(session=session, user_id=int(user_id), key='ui.filter_presets', value=migrated)

            # Mark done
            _set_app_setting(session=session, key=_MIGRATION_DONE_KEY, value='1')
            session.commit()

            logger.info('Migration complete: shelves→markers')
    except Exception:
        logger.exception('Migration failed: shelves→markers')
