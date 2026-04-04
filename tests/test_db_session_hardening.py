from __future__ import annotations

import sqlite3
import sys

sys.path.insert(0, '/home/pmmsoares/Documents/Python/PaperVisor')

from papervisor.db.session import _parse_int_env, _set_sqlite_pragma


def test_parse_int_env_bounds(monkeypatch) -> None:
    monkeypatch.setenv('PV_TEST_INT', '123')
    assert _parse_int_env('PV_TEST_INT', 5, min_value=0, max_value=200) == 123

    monkeypatch.setenv('PV_TEST_INT', '-50')
    assert _parse_int_env('PV_TEST_INT', 5, min_value=0, max_value=200) == 0

    monkeypatch.setenv('PV_TEST_INT', '999')
    assert _parse_int_env('PV_TEST_INT', 5, min_value=0, max_value=200) == 200

    monkeypatch.setenv('PV_TEST_INT', 'bad')
    assert _parse_int_env('PV_TEST_INT', 5, min_value=0, max_value=200) == 5


def test_set_sqlite_pragma_clamps_timeout_and_cache(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_SQLITE_WAL', '0')
    monkeypatch.setenv('PAPERVISOR_SQLITE_BUSY_TIMEOUT_MS', '999999')
    monkeypatch.setenv('PAPERVISOR_SQLITE_CACHE_KIB', '-999999')

    conn = sqlite3.connect(':memory:')
    _set_sqlite_pragma(conn, object())

    cur = conn.cursor()
    busy_timeout = int(cur.execute('PRAGMA busy_timeout').fetchone()[0])
    cache_size = int(cur.execute('PRAGMA cache_size').fetchone()[0])

    assert busy_timeout == 60000
    assert cache_size == -262144

    cur.close()
    conn.close()
