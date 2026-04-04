from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from papervisor.core.config import get_paths
from papervisor.services.papers_files import safe_filename, unique_path

logger = logging.getLogger(__name__)


@dataclass
class ImportRun:
    started_at: str
    completed_at: str
    status: str
    dry_run: bool
    force: bool
    import_dir: str
    processed_files: int
    imported_databases: int
    message: str


_history: deque[ImportRun] = deque(maxlen=200)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _import_dir_path() -> Path:
    """Resolve import directory with safe local fallback.

    Precedence:
    1. PAPERVISOR_IMPORT_DIR
    2. /data/import when writable
    3. <project_root>/data/import
    """
    env_raw = os.environ.get('PAPERVISOR_IMPORT_DIR')
    if env_raw:
        candidate = Path(env_raw).expanduser()
    else:
        candidate = Path('/data/import')

    if not candidate.is_absolute():
        candidate = (get_paths().project_root / candidate).resolve()

    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except PermissionError:
        fallback = (get_paths().project_root / 'data' / 'import').resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning('Import directory %s not writable; using %s', candidate, fallback)
        return fallback


def _collect_candidates(*, import_dir: Path, target_db: Path, accept_all: bool) -> list[Path]:
    candidates: list[Path] = []
    for db_path in sorted(import_dir.glob('*.db')):
        name = db_path.name.lower()
        if not accept_all and 'papervisor' not in name:
            continue
        if db_path.resolve() == target_db:
            continue
        candidates.append(db_path)
    return candidates


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, '1' if default else '0')).strip().lower()
    return raw in {'1', 'true', 'yes', 'on'}


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f'PRAGMA table_info({_q(table)})').fetchall()
    return [str(r[1]) for r in rows]


def _select_rows(conn: sqlite3.Connection, table: str, columns: list[str]) -> list[sqlite3.Row]:
    if not columns:
        return []
    cols_sql = ', '.join(_q(c) for c in columns)
    return conn.execute(f'SELECT {cols_sql} FROM {_q(table)}').fetchall()


def _insert_row(conn: sqlite3.Connection, table: str, row: dict[str, object]) -> None:
    if not row:
        return
    cols = list(row.keys())
    cols_sql = ', '.join(_q(c) for c in cols)
    vals_sql = ', '.join(['?'] * len(cols))
    conn.execute(
        f'INSERT INTO {_q(table)} ({cols_sql}) VALUES ({vals_sql})',
        [row[c] for c in cols],
    )


def _insert_or_ignore_row(conn: sqlite3.Connection, table: str, row: dict[str, object]) -> None:
    if not row:
        return
    cols = list(row.keys())
    cols_sql = ', '.join(_q(c) for c in cols)
    vals_sql = ', '.join(['?'] * len(cols))
    conn.execute(
        f'INSERT OR IGNORE INTO {_q(table)} ({cols_sql}) VALUES ({vals_sql})',
        [row[c] for c in cols],
    )


def _next_unique_slug(base: str, existing: set[str]) -> str:
    root = str(base or 'library').strip() or 'library'
    candidate = root
    i = 2
    while candidate.lower() in existing:
        candidate = f'{root}-{i}'
        i += 1
    return candidate


def _resolve_source_file(raw_path: str, src_db_path: Path, files_root: Path) -> Path | None:
    raw = str(raw_path or '').strip()
    if not raw:
        return None

    p = Path(raw).expanduser()
    candidates: list[Path] = []
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append((src_db_path.parent / p).resolve())
        candidates.append((files_root / p).resolve())
        candidates.append((Path('/data/files') / p).resolve())

    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                return cand
        except OSError:
            continue
    return None


def _backup_document(
    *,
    raw_path: str,
    src_db_path: Path,
    files_root: Path,
    source_tag: str,
    copied_map: dict[str, str],
) -> str | None:
    src = _resolve_source_file(raw_path, src_db_path, files_root)
    if src is None:
        return None

    key = str(src.resolve())
    if key in copied_map:
        return copied_map[key]

    target_dir = files_root / '_imports' / source_tag
    target_dir.mkdir(parents=True, exist_ok=True)

    name = safe_filename(src.name)
    dest = unique_path(target_dir, name)
    shutil.copy2(src, dest)

    copied_map[key] = str(dest)
    return str(dest)


@dataclass
class ImportSummary:
    source_db: str
    users_imported: int = 0
    users_matched: int = 0
    libraries_imported: int = 0
    papers_imported: int = 0
    markers_imported: int = 0
    paper_markers_imported: int = 0
    favorites_imported: int = 0
    to_read_imported: int = 0
    documents_backed_up: int = 0
    documents_missing: int = 0


def _import_users(src: sqlite3.Connection, dst: sqlite3.Connection, summary: ImportSummary) -> dict[int, int]:
    mapping: dict[int, int] = {}
    if not _table_exists(src, 'users') or not _table_exists(dst, 'users'):
        return mapping

    src_cols = _table_columns(src, 'users')
    dst_cols = set(_table_columns(dst, 'users'))
    copy_cols = [c for c in src_cols if c in dst_cols]
    if 'username' not in copy_cols:
        return mapping

    existing_by_username = {
        str(r['username']).strip().lower(): int(r['id'])
        for r in dst.execute('SELECT id, username FROM users').fetchall()
    }
    existing_ids = {int(r['id']) for r in dst.execute('SELECT id FROM users').fetchall()}

    for row in _select_rows(src, 'users', copy_cols):
        username = str(row['username'] or '').strip()
        if not username:
            continue

        old_id_raw = row['id'] if 'id' in row.keys() else None
        old_id = int(old_id_raw) if old_id_raw is not None else None
        username_key = username.lower()

        if username_key in existing_by_username:
            target_id = existing_by_username[username_key]
            summary.users_matched += 1
            if old_id is not None:
                mapping[old_id] = int(target_id)
            continue

        payload = {c: row[c] for c in copy_cols if c != 'id'}

        assigned_id: int | None = None
        if old_id is not None and 'id' in dst_cols and old_id not in existing_ids:
            with_id = {'id': old_id}
            with_id.update(payload)
            try:
                _insert_row(dst, 'users', with_id)
                assigned_id = old_id
            except sqlite3.IntegrityError:
                assigned_id = None

        if assigned_id is None:
            _insert_row(dst, 'users', payload)
            found = dst.execute(
                'SELECT id FROM users WHERE lower(username)=lower(?) LIMIT 1',
                (username,),
            ).fetchone()
            if found is None:
                continue
            assigned_id = int(found['id'])

        existing_by_username[username_key] = assigned_id
        existing_ids.add(assigned_id)
        summary.users_imported += 1
        if old_id is not None:
            mapping[old_id] = assigned_id

    return mapping


def _import_libraries(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    user_map: dict[int, int],
    source_tag: str,
    summary: ImportSummary,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not _table_exists(src, 'libraries') or not _table_exists(dst, 'libraries'):
        return mapping

    src_cols = _table_columns(src, 'libraries')
    dst_cols = set(_table_columns(dst, 'libraries'))
    copy_cols = [c for c in src_cols if c in dst_cols]
    if 'id' not in copy_cols:
        return mapping

    existing_ids = {
        str(r['id']): str(r['id'])
        for r in dst.execute('SELECT id FROM libraries').fetchall()
    }
    existing_slug = {
        str(r['slug']).strip().lower()
        for r in dst.execute('SELECT slug FROM libraries').fetchall()
        if r['slug'] is not None
    }
    existing_name = {
        str(r['name']).strip().lower()
        for r in dst.execute('SELECT name FROM libraries').fetchall()
        if r['name'] is not None
    }

    for row in _select_rows(src, 'libraries', copy_cols):
        old_id = str(row['id'] or '').strip()
        if not old_id:
            continue

        if old_id in existing_ids:
            mapping[old_id] = old_id
            continue

        payload = {c: row[c] for c in copy_cols}
        target_id = old_id

        if 'owner_user_id' in payload and payload['owner_user_id'] is not None:
            owner_old = int(payload['owner_user_id'])
            payload['owner_user_id'] = user_map.get(owner_old)

        if 'slug' in payload:
            slug_base = str(payload.get('slug') or 'library').strip() or 'library'
            new_slug = _next_unique_slug(slug_base, existing_slug)
            payload['slug'] = new_slug
            existing_slug.add(new_slug.lower())

        if 'name' in payload:
            name = str(payload.get('name') or 'Library').strip() or 'Library'
            if name.lower() in existing_name:
                name = f'{name} ({source_tag})'
            payload['name'] = name
            existing_name.add(name.lower())

        try:
            _insert_row(dst, 'libraries', payload)
        except sqlite3.IntegrityError:
            target_id = str(uuid.uuid4())
            payload['id'] = target_id
            if 'slug' in payload:
                slug_base = str(payload.get('slug') or 'library').strip() or 'library'
                new_slug = _next_unique_slug(slug_base, existing_slug)
                payload['slug'] = new_slug
                existing_slug.add(new_slug.lower())
            _insert_row(dst, 'libraries', payload)

        mapping[old_id] = target_id
        existing_ids[target_id] = target_id
        summary.libraries_imported += 1

    return mapping


def _import_papers(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    *,
    src_db_path: Path,
    files_root: Path,
    source_tag: str,
    library_map: dict[str, str],
    summary: ImportSummary,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not _table_exists(src, 'papers') or not _table_exists(dst, 'papers'):
        return mapping

    src_cols = _table_columns(src, 'papers')
    dst_cols = set(_table_columns(dst, 'papers'))
    copy_cols = [c for c in src_cols if c in dst_cols]
    if 'id' not in copy_cols:
        return mapping

    existing_ids = {
        str(r['id']): str(r['id'])
        for r in dst.execute('SELECT id FROM papers').fetchall()
    }
    copied_map: dict[str, str] = {}

    for row in _select_rows(src, 'papers', copy_cols):
        old_id = str(row['id'] or '').strip()
        if not old_id:
            continue

        payload = {c: row[c] for c in copy_cols}
        target_id = old_id
        if old_id in existing_ids:
            target_id = uuid.uuid4().hex

        payload['id'] = target_id

        if 'library_id' in payload and payload['library_id'] is not None:
            payload['library_id'] = library_map.get(str(payload['library_id']), payload['library_id'])

        if 'file_path' in payload:
            raw_file_path = str(payload.get('file_path') or '').strip()
            if raw_file_path:
                copied = _backup_document(
                    raw_path=raw_file_path,
                    src_db_path=src_db_path,
                    files_root=files_root,
                    source_tag=source_tag,
                    copied_map=copied_map,
                )
                if copied:
                    payload['file_path'] = copied
                    summary.documents_backed_up += 1
                else:
                    summary.documents_missing += 1

        _insert_row(dst, 'papers', payload)
        mapping[old_id] = target_id
        existing_ids[target_id] = target_id
        summary.papers_imported += 1

    return mapping


def _import_markers(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    *,
    user_map: dict[int, int],
    summary: ImportSummary,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not _table_exists(src, 'markers') or not _table_exists(dst, 'markers'):
        return mapping

    src_cols = _table_columns(src, 'markers')
    dst_cols = set(_table_columns(dst, 'markers'))
    copy_cols = [c for c in src_cols if c in dst_cols]
    if 'id' not in copy_cols:
        return mapping

    existing_ids = {
        str(r['id']): str(r['id'])
        for r in dst.execute('SELECT id FROM markers').fetchall()
    }

    for row in _select_rows(src, 'markers', copy_cols):
        old_id = str(row['id'] or '').strip()
        if not old_id:
            continue

        payload = {c: row[c] for c in copy_cols}

        if 'owner_user_id' in payload and payload['owner_user_id'] is not None:
            owner_old = int(payload['owner_user_id'])
            payload['owner_user_id'] = user_map.get(owner_old)

        target_id = old_id
        if old_id in existing_ids:
            target_id = str(uuid.uuid4())
        payload['id'] = target_id

        _insert_row(dst, 'markers', payload)
        mapping[old_id] = target_id
        existing_ids[target_id] = target_id
        summary.markers_imported += 1

    return mapping


def _import_paper_markers(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    *,
    paper_map: dict[str, str],
    marker_map: dict[str, str],
    summary: ImportSummary,
) -> None:
    if not _table_exists(src, 'paper_markers') or not _table_exists(dst, 'paper_markers'):
        return

    src_cols = _table_columns(src, 'paper_markers')
    dst_cols = set(_table_columns(dst, 'paper_markers'))
    copy_cols = [c for c in src_cols if c in dst_cols]
    if 'paper_id' not in copy_cols or 'marker_id' not in copy_cols:
        return

    for row in _select_rows(src, 'paper_markers', copy_cols):
        old_paper_id = str(row['paper_id'] or '').strip()
        old_marker_id = str(row['marker_id'] or '').strip()
        if not old_paper_id or not old_marker_id:
            continue
        new_paper_id = paper_map.get(old_paper_id)
        new_marker_id = marker_map.get(old_marker_id)
        if not new_paper_id or not new_marker_id:
            continue

        payload = {c: row[c] for c in copy_cols}
        payload['paper_id'] = new_paper_id
        payload['marker_id'] = new_marker_id
        _insert_or_ignore_row(dst, 'paper_markers', payload)
        summary.paper_markers_imported += 1


def _import_user_paper_links(
    *,
    table_name: str,
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    user_map: dict[int, int],
    paper_map: dict[str, str],
) -> int:
    if not _table_exists(src, table_name) or not _table_exists(dst, table_name):
        return 0

    src_cols = _table_columns(src, table_name)
    dst_cols = set(_table_columns(dst, table_name))
    copy_cols = [c for c in src_cols if c in dst_cols]
    if 'user_id' not in copy_cols or 'paper_id' not in copy_cols:
        return 0

    imported = 0
    for row in _select_rows(src, table_name, copy_cols):
        old_user_id = int(row['user_id']) if row['user_id'] is not None else None
        old_paper_id = str(row['paper_id'] or '').strip()
        if old_user_id is None or not old_paper_id:
            continue

        new_user_id = user_map.get(old_user_id)
        new_paper_id = paper_map.get(old_paper_id)
        if new_user_id is None or not new_paper_id:
            continue

        payload = {c: row[c] for c in copy_cols}
        payload['user_id'] = new_user_id
        payload['paper_id'] = new_paper_id
        _insert_or_ignore_row(dst, table_name, payload)
        imported += 1
    return imported


def import_database_file(source_db: Path, *, delete_source: bool = True) -> ImportSummary:
    paths = get_paths()
    target_db = paths.database_file.resolve()
    files_root = paths.library_files_dir.resolve()
    source_db = source_db.resolve()

    if source_db == target_db:
        raise ValueError('Source DB cannot be the active target DB')

    summary = ImportSummary(source_db=str(source_db))
    source_tag = source_db.stem

    src = sqlite3.connect(f'file:{source_db}?mode=ro', uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(target_db.as_posix())
    dst.row_factory = sqlite3.Row

    try:
        dst.execute('PRAGMA foreign_keys=ON')
        dst.execute('BEGIN')

        user_map = _import_users(src, dst, summary)
        library_map = _import_libraries(src, dst, user_map, source_tag, summary)
        paper_map = _import_papers(
            src,
            dst,
            src_db_path=source_db,
            files_root=files_root,
            source_tag=source_tag,
            library_map=library_map,
            summary=summary,
        )
        marker_map = _import_markers(src, dst, user_map=user_map, summary=summary)
        _import_paper_markers(src, dst, paper_map=paper_map, marker_map=marker_map, summary=summary)
        summary.favorites_imported = _import_user_paper_links(
            table_name='paper_favorites',
            src=src,
            dst=dst,
            user_map=user_map,
            paper_map=paper_map,
        )
        summary.to_read_imported = _import_user_paper_links(
            table_name='paper_to_read',
            src=src,
            dst=dst,
            user_map=user_map,
            paper_map=paper_map,
        )

        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()

    if delete_source:
        source_db.unlink(missing_ok=True)

    return summary


def import_databases_from_folder() -> list[ImportSummary]:
    """Import legacy sqlite databases found in the configured import directory.

    Environment variables:
    - PAPERVISOR_IMPORT_ON_START (default: 1)
    - PAPERVISOR_IMPORT_DIR (default: /data/import)
    - PAPERVISOR_IMPORT_DELETE_SOURCE (default: 1)
    - PAPERVISOR_IMPORT_ACCEPT_ALL_DB (default: 0)
    """

    if not _parse_bool_env('PAPERVISOR_IMPORT_ON_START', True):
        return []

    import_dir = _import_dir_path()

    accept_all = _parse_bool_env('PAPERVISOR_IMPORT_ACCEPT_ALL_DB', False)
    delete_source = _parse_bool_env('PAPERVISOR_IMPORT_DELETE_SOURCE', True)
    target_db = get_paths().database_file.resolve()

    candidates = _collect_candidates(import_dir=import_dir, target_db=target_db, accept_all=accept_all)

    summaries: list[ImportSummary] = []
    for db_path in candidates:
        try:
            summary = import_database_file(db_path, delete_source=delete_source)
            summaries.append(summary)
            logger.info(
                'Imported DB %s: users=%s (matched=%s), libraries=%s, papers=%s, markers=%s, '
                'paper_markers=%s, favorites=%s, to_read=%s, docs_backed_up=%s, docs_missing=%s',
                db_path,
                summary.users_imported,
                summary.users_matched,
                summary.libraries_imported,
                summary.papers_imported,
                summary.markers_imported,
                summary.paper_markers_imported,
                summary.favorites_imported,
                summary.to_read_imported,
                summary.documents_backed_up,
                summary.documents_missing,
            )
        except Exception:
            logger.exception('Failed to import database %s', db_path)

    return summaries


def run_import_queue(*, force: bool = False, dry_run: bool = False) -> dict[str, object]:
    """Run import queue and record a reportable run entry for admin API."""
    started = _now_iso()
    import_dir = _import_dir_path()
    target_db = get_paths().database_file.resolve()
    accept_all = _parse_bool_env('PAPERVISOR_IMPORT_ACCEPT_ALL_DB', False)
    candidates = _collect_candidates(import_dir=import_dir, target_db=target_db, accept_all=accept_all)

    imported_count = 0
    if dry_run:
        message = 'dry run completed'
    else:
        previous = os.environ.get('PAPERVISOR_IMPORT_ON_START')
        try:
            if force:
                os.environ['PAPERVISOR_IMPORT_ON_START'] = '1'
            summaries = import_databases_from_folder()
            imported_count = len(summaries)
            message = 'queue run completed'
        finally:
            if force:
                if previous is None:
                    os.environ.pop('PAPERVISOR_IMPORT_ON_START', None)
                else:
                    os.environ['PAPERVISOR_IMPORT_ON_START'] = previous

    run = ImportRun(
        started_at=started,
        completed_at=_now_iso(),
        status='ok',
        dry_run=bool(dry_run),
        force=bool(force),
        import_dir=str(import_dir),
        processed_files=len(candidates),
        imported_databases=imported_count,
        message=message,
    )
    _history.appendleft(run)

    return {
        'status': 'ok',
        'run': asdict(run),
    }


def get_import_report(*, limit: int = 20) -> dict[str, object]:
    import_dir = _import_dir_path()
    safe_limit = max(1, min(100, int(limit)))
    history_items = [asdict(item) for item in list(_history)[:safe_limit]]
    last_run = history_items[0] if history_items else None

    return {
        'status': 'ok',
        'config': {
            'import_dir': str(import_dir),
        },
        'last_run': last_run,
        'history': history_items,
    }
