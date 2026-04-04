from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from papervisor.core.sanitizers import normalize_list
from papervisor.db.models import Paper, PaperTag, Tag
from sqlalchemy.orm import Session

from papervisor.db.session import use_session
from papervisor.services.sharing import require_library_manage


_MAX_TAG_LEN = 64


def _normalize_tags(tags: list[str] | None) -> list[str]:
    return normalize_list(tags, max_item_len=_MAX_TAG_LEN, strip_nul=True)


def list_tags(*, session: Session | None = None) -> list[str]:
    with use_session(session) as session:
        rows = session.execute(select(Tag.name).order_by(func.lower(Tag.name).asc())).scalars().all()
    return [str(r) for r in rows]


def list_paper_tags(*, paper_id: str, session: Session | None = None) -> list[str]:
    paper_id = str(paper_id or '').strip()
    if not paper_id:
        return []

    with use_session(session) as session:
        rows = (
            session.execute(
                select(Tag.name)
                .join(PaperTag, PaperTag.tag_id == Tag.id)
                .where(PaperTag.paper_id == paper_id)
                .order_by(func.lower(Tag.name).asc())
            )
            .scalars()
            .all()
        )
    return [str(r) for r in rows]


def set_paper_tags(*, paper_id: str, tags: list[str], user_id: int | None = None, session: Session | None = None) -> None:
    paper_id = str(paper_id or '').strip()
    if not paper_id:
        raise ValueError('paper_id is required')

    tags = _normalize_tags(tags)

    with use_session(session) as session:
        paper = session.get(Paper, paper_id)
        if paper is None:
            raise ValueError('Paper not found')

        if user_id is not None:
            lib_id = str(paper.library_id or '').strip()
            if not lib_id:
                raise ValueError('Library is required')
            require_library_manage(user_id=int(user_id), library_id=lib_id)

        # Ensure tag rows exist (case-insensitive reuse to avoid duplicates like "AI" vs "ai").
        id_by_name: dict[str, int] = {}
        if tags:
            # Map lower(name) -> (id, canonical_name)
            wanted_lc = [t.lower() for t in tags]
            existing_rows = session.execute(
                select(Tag.id, Tag.name)
                .where(func.lower(Tag.name).in_(wanted_lc))
            ).all()
            existing_by_lc: dict[str, tuple[int, str]] = {
                str(name or '').lower(): (int(tid), str(name or ''))
                for (tid, name) in existing_rows
                if str(name or '').strip()
            }

            # Create missing ones.
            for name in tags:
                key = name.lower()
                if key in existing_by_lc:
                    tid, canonical = existing_by_lc[key]
                    id_by_name[canonical] = tid
                    continue

                try:
                    with session.begin_nested():
                        row = Tag(name=name)
                        session.add(row)
                        session.flush()  # get PK
                    existing_by_lc[key] = (int(row.id), name)
                    id_by_name[name] = int(row.id)
                except IntegrityError:
                    # Another request created it concurrently (or different case already exists).
                    tid_name = session.execute(
                        select(Tag.id, Tag.name).where(func.lower(Tag.name) == key)
                    ).first()
                    if tid_name is not None:
                        tid, canonical = tid_name
                        id_by_name[str(canonical or name)] = int(tid)
                    else:
                        raise

        # Replace associations
        session.execute(delete(PaperTag).where(PaperTag.paper_id == paper_id))
        for name in tags:
            # Prefer canonical match, else fall back to case-insensitive match.
            tid = id_by_name.get(name)
            if tid is None:
                for k, v in id_by_name.items():
                    if k.lower() == name.lower():
                        tid = v
                        break
            if tid is not None:
                session.add(PaperTag(paper_id=paper_id, tag_id=int(tid)))

        session.commit()
