from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, select

from papervisor.core.logging import get_request_id
from papervisor.db.models import AuditLogEvent
from papervisor.db.session import get_session


_MAX_MESSAGE = 1024
_MAX_DETAILS = 4096
_MAX_USERNAME = 64
_MAX_IP = 64
_MAX_REQUEST_ID = 64


@dataclass(frozen=True)
class AuditLogItem:
    id: int
    created_at: datetime
    level: str
    category: str
    action: str
    message: str
    username: str | None
    user_id: int | None
    ip_address: str | None
    request_id: str | None
    details_json: str | None


def _truncate(value: str, max_len: int) -> str:
    s = str(value or '').strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + '…'


def _to_item(row: AuditLogEvent) -> AuditLogItem:
    return AuditLogItem(
        id=int(row.id),
        created_at=row.created_at,
        level=str(row.level or 'info'),
        category=str(row.category or 'general'),
        action=str(row.action or 'event'),
        message=str(row.message or ''),
        username=(str(row.username).strip() if row.username is not None else None),
        user_id=(int(row.user_id) if row.user_id is not None else None),
        ip_address=(str(row.ip_address).strip() if row.ip_address is not None else None),
        request_id=(str(row.request_id).strip() if row.request_id is not None else None),
        details_json=(str(row.details_json) if row.details_json else None),
    )


def log_event(
    *,
    category: str,
    action: str,
    message: str,
    level: str = 'info',
    username: str | None = None,
    user_id: int | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    details_json: str | None = None
    if details:
        try:
            details_json = _truncate(json.dumps(details, ensure_ascii=False, sort_keys=True), _MAX_DETAILS)
        except Exception:
            details_json = _truncate(str(details), _MAX_DETAILS)

    rid = (request_id or get_request_id() or '').strip() or None

    try:
        with get_session() as session:
            row = AuditLogEvent(
                level=_truncate(level or 'info', 16).lower(),
                category=_truncate(category or 'general', 32).lower(),
                action=_truncate(action or 'event', 64).lower(),
                message=_truncate(message or '', _MAX_MESSAGE),
                username=(_truncate(username, _MAX_USERNAME) if username else None),
                user_id=(int(user_id) if user_id is not None else None),
                ip_address=(_truncate(ip_address, _MAX_IP) if ip_address else None),
                request_id=(_truncate(rid, _MAX_REQUEST_ID) if rid else None),
                details_json=details_json,
            )
            session.add(row)
            session.commit()
    except Exception:
        # Best-effort auditing: never block caller flow.
        return


def list_events(*, limit: int = 200, category: str | None = None, level: str | None = None) -> list[AuditLogItem]:
    capped_limit = max(1, min(int(limit or 200), 1000))
    with get_session() as session:
        query = select(AuditLogEvent)
        if category:
            query = query.where(AuditLogEvent.category == str(category).strip().lower())
        if level:
            query = query.where(AuditLogEvent.level == str(level).strip().lower())

        rows = session.execute(
            query.order_by(desc(AuditLogEvent.created_at), desc(AuditLogEvent.id)).limit(capped_limit)
        ).scalars().all()
        return [_to_item(r) for r in rows]
