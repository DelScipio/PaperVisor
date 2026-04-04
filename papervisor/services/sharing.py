from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from papervisor.core.config import get_paths
from papervisor.core.exceptions import NotFoundException, PermissionDeniedException, ValidationException
from papervisor.db.models import Library, LibraryShare, Paper, PaperShare, User
from sqlalchemy.orm import Session

from papervisor.db.session import get_session, use_session


@dataclass(frozen=True)
class LibraryAccess:
    can_read: bool
    can_manage: bool
    is_owner: bool
    role: str | None


def _norm_scope(scope: str | None) -> str:
    s = str(scope or 'private').strip().lower()
    if s not in {'private', 'shared', 'global'}:
        return 'private'
    return s


def _norm_role(role: str | None) -> str:
    r = str(role or 'reader').strip().lower()
    if r not in {'reader', 'editor'}:
        return 'reader'
    return r


def get_library_access(*, user_id: int, library_id: str) -> LibraryAccess:
    uid = int(user_id)
    if not library_id:
        return LibraryAccess(can_read=False, can_manage=False, is_owner=False, role=None)

    with get_session() as session:
        lib = session.get(Library, str(library_id))
        if lib is None:
            return LibraryAccess(can_read=False, can_manage=False, is_owner=False, role=None)

        owner_id = int(lib.owner_user_id or 0)
        scope = _norm_scope(lib.scope)

        if owner_id and owner_id == uid:
            return LibraryAccess(can_read=True, can_manage=True, is_owner=True, role='owner')

        if scope == 'global':
            return LibraryAccess(can_read=True, can_manage=False, is_owner=False, role='reader')

        share = session.execute(
            select(LibraryShare)
            .where(LibraryShare.library_id == str(library_id))
            .where(LibraryShare.shared_with_user_id == uid)
            .where(LibraryShare.status == 'accepted')
        ).scalar_one_or_none()

        if share is None:
            return LibraryAccess(can_read=False, can_manage=False, is_owner=False, role=None)

        role = _norm_role(share.role)
        return LibraryAccess(can_read=True, can_manage=(role == 'editor'), is_owner=False, role=role)


def require_library_read(*, user_id: int, library_id: str) -> None:
    acc = get_library_access(user_id=user_id, library_id=library_id)
    if not acc.can_read:
        raise PermissionDeniedException('Not allowed')


def require_library_manage(*, user_id: int, library_id: str) -> None:
    acc = get_library_access(user_id=user_id, library_id=library_id)
    if not (acc.is_owner or acc.can_manage):
        raise PermissionDeniedException('Not allowed')


def _get_user_by_username(session, username: str) -> User | None:
    u = str(username or '').strip()
    if not u:
        return None
    return session.execute(select(User).where(User.username == u)).scalar_one_or_none()


def _clear_reader_file_access_cache_best_effort() -> None:
    try:
        from papervisor.api.reader_api import clear_paper_file_access_cache

        clear_paper_file_access_cache()
    except (ImportError, AttributeError, RuntimeError):
        return


def set_library_scope(*, user_id: int, library_id: str, scope: str) -> None:
    uid = int(user_id)
    s = _norm_scope(scope)

    with get_session() as session:
        lib = session.get(Library, str(library_id))
        if lib is None:
            raise NotFoundException('Library not found')
        if int(lib.owner_user_id or 0) != uid:
            raise PermissionDeniedException('Not allowed')

        lib.scope = s

        # When going private, remove all shares so access is immediately revoked.
        if s == 'private':
            session.query(LibraryShare).where(LibraryShare.library_id == str(lib.id)).delete(synchronize_session=False)

        session.commit()
        _clear_reader_file_access_cache_best_effort()


def invite_library_user(*, user_id: int, library_id: str, target_username: str, role: str = 'reader') -> None:
    uid = int(user_id)
    r = _norm_role(role)

    with get_session() as session:
        lib = session.get(Library, str(library_id))
        if lib is None:
            raise NotFoundException('Library not found')

        owner_id = int(lib.owner_user_id or 0)
        if owner_id != uid:
            # Only owner or editor can invite; owner required to change scope.
            acc = get_library_access(user_id=uid, library_id=str(lib.id))
            if not acc.can_manage:
                raise PermissionDeniedException('Not allowed')

        target = _get_user_by_username(session, target_username)
        if target is None:
            raise NotFoundException('User not found')
        if int(target.id) == owner_id:
            raise ValidationException('Owner already has access')

        existing = session.execute(
            select(LibraryShare)
            .where(LibraryShare.library_id == str(lib.id))
            .where(LibraryShare.shared_with_user_id == int(target.id))
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if existing is None:
            session.add(
                LibraryShare(
                    library_id=str(lib.id),
                    shared_with_user_id=int(target.id),
                    shared_by_user_id=uid,
                    status='pending',
                    role=r,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            existing.role = r
            existing.status = 'pending'
            existing.shared_by_user_id = uid
            existing.updated_at = now

        # If the owner is inviting users, make the library shared (unless global).
        if owner_id == uid and _norm_scope(lib.scope) != 'global':
            lib.scope = 'shared'

        session.commit()
        _clear_reader_file_access_cache_best_effort()


def update_library_share_role(*, user_id: int, library_id: str, shared_with_user_id: int, role: str) -> None:
    require_library_manage(user_id=int(user_id), library_id=str(library_id))
    r = _norm_role(role)

    with get_session() as session:
        row = session.execute(
            select(LibraryShare)
            .where(LibraryShare.library_id == str(library_id))
            .where(LibraryShare.shared_with_user_id == int(shared_with_user_id))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundException('Share not found')
        row.role = r
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        _clear_reader_file_access_cache_best_effort()


def remove_library_share(*, user_id: int, library_id: str, shared_with_user_id: int) -> None:
    require_library_manage(user_id=int(user_id), library_id=str(library_id))
    with get_session() as session:
        session.query(LibraryShare).where(
            LibraryShare.library_id == str(library_id),
            LibraryShare.shared_with_user_id == int(shared_with_user_id),
        ).delete(synchronize_session=False)
        session.commit()
        _clear_reader_file_access_cache_best_effort()


def remove_shared_library_for_me(*, user_id: int, library_id: str) -> None:
    uid = int(user_id)
    with get_session() as session:
        session.query(LibraryShare).where(
            LibraryShare.library_id == str(library_id),
            LibraryShare.shared_with_user_id == uid,
        ).delete(synchronize_session=False)
        session.commit()
        _clear_reader_file_access_cache_best_effort()


def accept_library_share(*, user_id: int, library_id: str) -> None:
    uid = int(user_id)
    with get_session() as session:
        row = session.execute(
            select(LibraryShare)
            .where(LibraryShare.library_id == str(library_id))
            .where(LibraryShare.shared_with_user_id == uid)
            .where(LibraryShare.status == 'pending')
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundException('Invite not found')
        row.status = 'accepted'
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        _clear_reader_file_access_cache_best_effort()


def decline_library_share(*, user_id: int, library_id: str) -> None:
    uid = int(user_id)
    with get_session() as session:
        session.query(LibraryShare).where(
            LibraryShare.library_id == str(library_id),
            LibraryShare.shared_with_user_id == uid,
            LibraryShare.status == 'pending',
        ).delete(synchronize_session=False)
        session.commit()
        _clear_reader_file_access_cache_best_effort()


@dataclass(frozen=True)
class PendingLibraryInvite:
    library_id: str
    library_name: str
    from_username: str | None
    role: str


@dataclass(frozen=True)
class PendingPaperInvite:
    share_id: int
    paper_id: str
    title: str
    from_username: str | None


def list_inbox(*, user_id: int) -> tuple[list[PendingLibraryInvite], list[PendingPaperInvite]]:
    uid = int(user_id)
    with get_session() as session:
        lib_invites = session.execute(
            select(LibraryShare, Library, User.username)
            .join(Library, Library.id == LibraryShare.library_id)
            .outerjoin(User, User.id == LibraryShare.shared_by_user_id)
            .where(LibraryShare.shared_with_user_id == uid)
            .where(LibraryShare.status == 'pending')
            .order_by(LibraryShare.created_at.desc())
        ).all()

        paper_invites = session.execute(
            select(PaperShare, Paper, User.username)
            .join(Paper, Paper.id == PaperShare.paper_id)
            .outerjoin(User, User.id == PaperShare.shared_by_user_id)
            .where(PaperShare.shared_with_user_id == uid)
            .where(PaperShare.status == 'pending')
            .order_by(PaperShare.created_at.desc())
        ).all()

        libs_out = [
            PendingLibraryInvite(
                library_id=str(ls.library_id),
                library_name=str(l.name),
                from_username=str(from_u) if from_u else None,
                role=_norm_role(ls.role),
            )
            for (ls, l, from_u) in lib_invites
        ]

        papers_out = [
            PendingPaperInvite(
                share_id=int(ps.id),
                paper_id=str(ps.paper_id),
                title=str(p.title),
                from_username=str(from_u) if from_u else None,
            )
            for (ps, p, from_u) in paper_invites
        ]

        return libs_out, papers_out


@dataclass(frozen=True)
class LibraryShareItem:
    user_id: int
    username: str
    status: str
    role: str


def list_library_shares(*, user_id: int, library_id: str) -> list[LibraryShareItem]:
    """List share entries for a library.

    Visible to owner and editors.
    """

    require_library_manage(user_id=int(user_id), library_id=str(library_id))

    with get_session() as session:
        rows = session.execute(
            select(LibraryShare, User.username)
            .join(User, User.id == LibraryShare.shared_with_user_id)
            .where(LibraryShare.library_id == str(library_id))
            .order_by(User.username.asc())
        ).all()

        out: list[LibraryShareItem] = []
        for (ls, uname) in rows:
            out.append(
                LibraryShareItem(
                    user_id=int(ls.shared_with_user_id),
                    username=str(uname or ''),
                    status=str(ls.status or 'pending'),
                    role=_norm_role(ls.role),
                )
            )
        return out


def share_paper_with_user(*, user_id: int, paper_id: str, target_username: str) -> None:
    uid = int(user_id)
    with get_session() as session:
        paper = session.get(Paper, str(paper_id))
        if paper is None:
            raise NotFoundException('Item not found')

        lib_id = str(paper.library_id or '')
        if not lib_id:
            raise ValidationException('Item has no library')

        # Must have read access to share.
        require_library_read(user_id=uid, library_id=lib_id)

        target = _get_user_by_username(session, target_username)
        if target is None:
            raise NotFoundException('User not found')
        if int(target.id) == uid:
            raise ValidationException('Cannot share with yourself')

        existing = session.execute(
            select(PaperShare)
            .where(PaperShare.paper_id == str(paper_id))
            .where(PaperShare.shared_with_user_id == int(target.id))
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if existing is None:
            session.add(
                PaperShare(
                    paper_id=str(paper_id),
                    shared_with_user_id=int(target.id),
                    shared_by_user_id=uid,
                    status='pending',
                    created_at=now,
                )
            )
        else:
            existing.status = 'pending'
            existing.shared_by_user_id = uid
            # created_at stays as-is

        session.commit()
        _clear_reader_file_access_cache_best_effort()


def _paper_storage_path(row: Paper) -> Path:
    fp = str(row.file_path or '').strip()
    if not fp:
        raise NotFoundException('File not found')
    p = Path(fp)
    try:
        root = get_paths().library_files_dir.resolve()
        resolved = p.resolve()
        if resolved != root and root not in resolved.parents:
            # Defensive: never allow sharing/copying files outside our managed storage.
            raise NotFoundException('File not found')
        p = resolved
    except (OSError, RuntimeError, ValueError):
        raise NotFoundException('File not found')

    if not p.exists() or not p.is_file():
        raise NotFoundException('File not found')
    return p


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or '').strip() or 'shared'
    base = base.replace('\x00', '')
    return base


def _library_owner_username(*, session, library_id: str) -> str | None:
    lib = session.get(Library, str(library_id))
    if lib is None:
        return None
    owner_id = lib.owner_user_id
    if owner_id is None:
        return None
    u = session.get(User, int(owner_id))
    if u is None:
        return None
    return str(u.username or '').strip() or None


def copy_shared_paper_to_library(*, user_id: int, share_id: int, target_library_id: str) -> str:
    """Accept a file share by copying the underlying file into one of the receiver's libraries.

    Returns new paper_id.
    """

    uid = int(user_id)
    with get_session() as session:
        share = session.get(PaperShare, int(share_id))
        if share is None or str(share.status or '') != 'pending':
            raise NotFoundException('Share not found')
        if int(share.shared_with_user_id or 0) != uid:
            raise PermissionDeniedException('Not allowed')

        paper = session.get(Paper, str(share.paper_id))
        if paper is None:
            raise NotFoundException('Item not found')

        # Receiver must own the target library.
        target_lib = session.get(Library, str(target_library_id))
        if target_lib is None:
            raise NotFoundException('Library not found')
        if int(target_lib.owner_user_id or 0) != uid:
            raise PermissionDeniedException('Not allowed')

        src_path = _paper_storage_path(paper)
        original_name = src_path.name

        # Destination folder uses the target library's current storage root.
        # (Actual path logic is in papers._library_root_for; here we mirror it to avoid imports.)
        paths = get_paths()
        dest_root: Path

        # Prefer per-user root when owner username is known.
        owner_username = _library_owner_username(session=session, library_id=str(target_lib.id))
        if owner_username:
            dest_root = paths.library_files_dir / owner_username / str(target_lib.slug)
        else:
            dest_root = paths.library_files_dir / str(target_lib.slug)

        dest_root.mkdir(parents=True, exist_ok=True)

        from papervisor.services.papers_files import unique_path

        safe = _safe_filename(original_name)
        dest = unique_path(dest_root, safe)

        shutil.copy2(str(src_path), str(dest))

        from papervisor.services.papers_files import move_file, pattern_target_path

        target = pattern_target_path(
            library_id=str(target_lib.id),
            file_type=str(paper.file_type or 'paper'),
            current_path=dest,
            original_filename=original_name,
            title=str(paper.title or dest.stem),
            authors=paper.authors,
            year=paper.published_year,
            journal=paper.journal,
            publisher=paper.publisher,
            isbn=paper.isbn,
            series=paper.series,
            series_index=paper.series_index,
            language=paper.language,
        )
        if target != dest:
            target.parent.mkdir(parents=True, exist_ok=True)
            move_file(dest, target)
            dest = target

        # Create new paper record (copy metadata).
        new_id = uuid.uuid4().hex
        new_row = Paper(
            id=str(new_id),
            library_id=str(target_lib.id),
            file_type=str(paper.file_type or 'paper'),
            title=str(paper.title or dest.stem),
            subtitle=str(paper.subtitle or ''),
            doi=paper.doi,
            authors=paper.authors,
            published_year=paper.published_year,
            journal=paper.journal,
            publisher=paper.publisher,
            isbn=paper.isbn,
            description=paper.description,
            language=paper.language,
            genres=paper.genres,
            publication_date=paper.publication_date,
            series=paper.series,
            series_index=paper.series_index,
            page_count=paper.page_count,
            abstract=paper.abstract,
            url=paper.url,
            volume=paper.volume,
            issue=paper.issue,
            pages=paper.pages,
            keywords=paper.keywords,
            file_path=str(dest),
        )
        session.add(new_row)

        share.status = 'accepted'
        session.commit()
        _clear_reader_file_access_cache_best_effort()
        return str(new_row.id)


def decline_paper_share(*, user_id: int, share_id: int) -> None:
    uid = int(user_id)
    with get_session() as session:
        share = session.get(PaperShare, int(share_id))
        if share is None:
            return
        if int(share.shared_with_user_id or 0) != uid:
            raise PermissionDeniedException('Not allowed')
        share.status = 'declined'
        session.commit()
        _clear_reader_file_access_cache_best_effort()


def transfer_library_ownership(*, user_id: int, library_id: str, new_owner_user_id: int) -> None:
    """Transfer a shared library to a new owner (must already have accepted share).

    This moves the library folder from old owner's username root to new owner's.
    """

    uid = int(user_id)
    new_uid = int(new_owner_user_id)

    with get_session() as session:
        lib = session.get(Library, str(library_id))
        if lib is None:
            raise NotFoundException('Library not found')

        old_owner = int(lib.owner_user_id or 0)
        if old_owner != uid:
            raise PermissionDeniedException('Not allowed')

        # Ensure new owner exists.
        new_owner = session.get(User, new_uid)
        if new_owner is None:
            raise NotFoundException('User not found')

        # Must be an accepted share.
        ok = session.execute(
            select(LibraryShare)
            .where(LibraryShare.library_id == str(lib.id))
            .where(LibraryShare.shared_with_user_id == new_uid)
            .where(LibraryShare.status == 'accepted')
        ).scalar_one_or_none()
        if ok is None:
            raise ValidationException('New owner must accept the library first')

        # Compute old/new paths.
        paths = get_paths()
        old_user = session.get(User, old_owner)
        old_name = (str(old_user.username or '').strip() or None) if old_user is not None else None
        new_name = str(new_owner.username or '').strip() or None

        if not new_name:
            raise ValidationException('New owner has no username')

        def _infer_src_root() -> Path:
            # Preferred layout: <library_files_dir>/<username>/<library_slug>
            if old_name:
                return paths.library_files_dir / old_name / str(lib.slug)

            # If ownership was missing or user record is unavailable, infer from existing paper file paths.
            # This avoids hard-coding old/legacy layouts while still supporting real data on disk.
            rows = session.execute(
                select(Paper.file_path)
                .where(Paper.library_id == str(lib.id))
                .where(Paper.file_path.is_not(None))
            ).all()
            slug = str(lib.slug)
            for (fp,) in rows:
                fp_s = str(fp or '').strip()
                if not fp_s:
                    continue
                try:
                    rel = Path(fp_s).relative_to(paths.library_files_dir)
                except ValueError:
                    continue
                parts = list(rel.parts)
                if slug not in parts:
                    continue
                idx = parts.index(slug)
                return paths.library_files_dir.joinpath(*parts[: idx + 1])

            return paths.library_files_dir / slug

        src_root = _infer_src_root()

        dest_root = paths.library_files_dir / new_name / str(lib.slug)
        dest_root.parent.mkdir(parents=True, exist_ok=True)

        # Move folder if it exists; if not, just switch ownership.
        if src_root.exists() and src_root.is_dir():
            if dest_root.exists():
                raise ValidationException('Destination already exists')
            shutil.move(str(src_root), str(dest_root))

            # Update file paths for papers in this library.
            rows = session.execute(select(Paper).where(Paper.library_id == str(lib.id))).scalars().all()
            for p in rows:
                fp = str(p.file_path or '').strip()
                if not fp:
                    continue
                try:
                    rel = Path(fp).relative_to(src_root)
                    p.file_path = str(dest_root / rel)
                except ValueError:
                    continue

        lib.owner_user_id = new_uid
        session.commit()
        _clear_reader_file_access_cache_best_effort()
