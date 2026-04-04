from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy import or_

from papervisor.core.config import get_paths
from papervisor.db.models import Library, LibraryShare, Paper, User, HiddenGlobalLibrary
from sqlalchemy.orm import Session

from papervisor.db.session import use_session
from papervisor.domain import LibraryItem


_slug_cleanup_re = re.compile(r'[^a-z0-9]')


def _slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r'\s+', '-', s)
    s = _slug_cleanup_re.sub('-', s)
    s = re.sub(r'-{2,}', '-', s).strip('-')
    return s or 'library'


@dataclass(frozen=True)
class CreateLibraryResult:
    library: LibraryItem
    folder: Path


def list_libraries(*, owner_user_id: int | None = None, session: Session | None = None) -> list[LibraryItem]:
    with use_session(session) as session:
        raw_counts = session.execute(
            select(Paper.library_id, func.count(Paper.id))
            .where(Paper.library_id.is_not(None))
            .group_by(Paper.library_id)
        ).all()
        counts: dict[str, int] = {str(lid): int(cnt) for (lid, cnt) in raw_counts if lid is not None}
        stmt = select(Library)
        if owner_user_id is not None:
            stmt = stmt.where(Library.owner_user_id == int(owner_user_id))
        rows = session.execute(stmt.order_by(Library.created_at.asc())).scalars().all()
        return [
            LibraryItem(
                id=r.id,
                name=r.name,
                slug=r.slug,
                description=r.description,
                icon=r.icon,
                paper_count=int(counts.get(r.id, 0)),
                owner_user_id=r.owner_user_id,
                scope=str(r.scope or 'private'),
            )
            for r in rows
        ]


def list_libraries_for_user(*, user_id: int, session: Session | None = None) -> list[LibraryItem]:
    uid = int(user_id)
    with use_session(session) as session:
        shared_subq = (
            select(LibraryShare.library_id)
            .where(LibraryShare.shared_with_user_id == uid)
            .where(LibraryShare.status == 'accepted')
        )

        # Get hidden global libraries
        hidden_libs_result = session.execute(
            select(HiddenGlobalLibrary.library_id).where(HiddenGlobalLibrary.user_id == uid)
        ).scalars().all()
        hidden_ids = [str(lid) for lid in hidden_libs_result]

        lib_rows = session.execute(
            select(Library, User.username)
            .outerjoin(User, User.id == Library.owner_user_id)
            .where(
                or_(
                    Library.owner_user_id == uid,
                    Library.scope == 'global',
                    Library.id.in_(shared_subq),
                )
            )
            .order_by(Library.created_at.asc())
        ).all()
        
        # Filter out hidden global libraries
        filtered_rows = []
        for row in lib_rows:
            lib = row[0]
            if lib.scope == 'global' and str(lib.id) in hidden_ids:
                continue
            filtered_rows.append(row)
        lib_rows = filtered_rows

        lib_ids = [str(row[0].id) for row in lib_rows]
        counts: dict[str, int] = {}
        if lib_ids:
            raw_counts = session.execute(
                select(Paper.library_id, func.count(Paper.id))
                .where(Paper.library_id.in_(lib_ids))
                .group_by(Paper.library_id)
            ).all()
            counts = {str(lid): int(cnt) for (lid, cnt) in raw_counts if lid is not None}

        share_rows = session.execute(
            select(LibraryShare.library_id, LibraryShare.role)
            .where(LibraryShare.shared_with_user_id == uid)
            .where(LibraryShare.status == 'accepted')
        ).all()
        role_by_lib: dict[str, str] = {str(lid): str(role or 'reader') for (lid, role) in share_rows}

        out: list[LibraryItem] = []
        for row in lib_rows:
            r = row[0]
            owner_name = row[1]
            lib_id = str(r.id)
            owner_id = r.owner_user_id
            role = role_by_lib.get(lib_id)
            owned_by_me = bool(int(owner_id or 0) == uid and int(owner_id or 0) > 0)
            out.append(
                LibraryItem(
                    id=lib_id,
                    name=r.name,
                    slug=r.slug,
                    description=r.description,
                    icon=r.icon,
                    paper_count=int(counts.get(lib_id, 0)),
                    owner_user_id=int(owner_id) if owner_id is not None else None,
                    owner_username=str(owner_name) if owner_name else None,
                    scope=str(r.scope or 'private'),
                    shared_role=role,
                    is_shared_with_me=bool(role) and int(owner_id or 0) != uid,
                    is_owned_by_me=owned_by_me,
                )
            )
        return out


def create_library(*, owner_user_id: int, name: str, description: str = '', icon: str = 'menu_book', session: Session | None = None) -> CreateLibraryResult:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError('Library name is required')
    normalized_name = cleaned_name.lower()

    cleaned_description = description.strip()
    cleaned_icon = (icon or 'menu_book').strip() or 'menu_book'

    paths = get_paths()

    library_item: LibraryItem | None = None
    username: str | None = None

    with use_session(session) as session:
        owner = session.get(User, int(owner_user_id))
        if owner is None:
            raise ValueError('Owner user not found')

        existing = session.execute(select(Library).where(func.lower(Library.name) == normalized_name)).scalar_one_or_none()
        if existing is not None:
            raise ValueError('A library with that name already exists')

        slug_base = _slugify(cleaned_name)
        slug = slug_base
        i = 2
        while session.execute(select(Library).where(Library.slug == slug)).scalar_one_or_none() is not None:
            slug = f'{slug_base}-{i}'
            i += 1

        row = Library(
            id=str(uuid.uuid4()),
            name=cleaned_name,
            slug=slug,
            description=cleaned_description,
            icon=cleaned_icon,
            owner_user_id=int(owner.id),
            scope='private',
        )
        session.add(row)
        session.commit()

        # Build return values while session is active to avoid detached/expired attribute access.
        username = str(owner.username or '').strip() or 'user'
        library_item = LibraryItem(
            id=str(row.id),
            name=str(row.name),
            slug=str(row.slug),
            description=str(row.description or ''),
            icon=str(row.icon or ''),
            paper_count=0,
            owner_user_id=int(owner.id),
            scope=str(row.scope or 'private'),
        )

    if library_item is None or username is None:
        raise RuntimeError('Failed to create library')

    folder = paths.library_files_dir / username / library_item.slug
    folder.mkdir(parents=True, exist_ok=True)

    return CreateLibraryResult(
        library=library_item,
        folder=folder,
    )


def update_library(*, user_id: int, library_id: str, name: str, description: str, icon: str, session: Session | None = None) -> LibraryItem:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError('Library name is required')
    normalized_name = cleaned_name.lower()

    cleaned_description = description.strip()
    cleaned_icon = (icon or 'menu_book').strip() or 'menu_book'

    with use_session(session) as session:
        row = session.get(Library, library_id)
        if row is None:
            raise ValueError('Library not found')

        if int(row.owner_user_id or 0) != int(user_id):
            raise ValueError('Not allowed')

        if cleaned_name != row.name:
            existing = session.execute(
                select(Library)
                .where(func.lower(Library.name) == normalized_name)
                .where(Library.id != str(row.id))
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError('A library with that name already exists')
            row.name = cleaned_name

        row.description = cleaned_description
        row.icon = cleaned_icon
        session.commit()

        paper_count = session.scalar(select(func.count()).select_from(Paper).where(Paper.library_id == str(row.id)))

        return LibraryItem(
            id=row.id,
            name=row.name,
            slug=row.slug,
            description=row.description,
            icon=row.icon,
            paper_count=int(paper_count or 0),
            owner_user_id=row.owner_user_id,
            scope=str(row.scope or 'private'),
        )


def delete_library(*, user_id: int, library_id: str, session: Session | None = None) -> None:
    with use_session(session) as session:
        row = session.get(Library, library_id)
        if row is None:
            raise ValueError('Library not found')

        if int(row.owner_user_id or 0) != int(user_id):
            raise ValueError('Not allowed')

        # If this library is shared, deletion must be handled via ownership transfer.
        shared_cnt = session.scalar(
            select(func.count()).select_from(LibraryShare).where(LibraryShare.library_id == str(row.id)).where(LibraryShare.status == 'accepted')
        )
        if int(shared_cnt or 0) > 0:
            raise ValueError('Library is shared; transfer ownership before deleting')

        session.delete(row)
        session.commit()

def get_user_hidden_global_libraries(*, user_id: int, session: Session | None = None) -> list[str]:
    with use_session(session) as session:
        rows = session.execute(
            select(HiddenGlobalLibrary.library_id).where(HiddenGlobalLibrary.user_id == int(user_id))
        ).scalars().all()
        return [str(r) for r in rows]

def set_user_hidden_global_libraries(*, user_id: int, library_ids: list[str], session: Session | None = None) -> None:
    uid = int(user_id)
    with use_session(session) as session:
        session.execute(
            HiddenGlobalLibrary.__table__.delete().where(HiddenGlobalLibrary.user_id == uid)
        )
        for lid in library_ids:
            if str(lid).strip():
                session.add(HiddenGlobalLibrary(user_id=uid, library_id=str(lid).strip()))
        session.commit()
