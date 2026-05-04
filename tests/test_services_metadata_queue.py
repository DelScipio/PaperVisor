from __future__ import annotations

import threading
import time

from papervisor.services import metadata_queue


def test_get_metadata_task_queue_is_thread_safe_singleton(monkeypatch) -> None:
    created = {'count': 0}

    class _FakeQueue:
        def __init__(self) -> None:
            created['count'] += 1
            # Widen race window to exercise singleton guard.
            time.sleep(0.01)

    monkeypatch.setattr(metadata_queue, '_queue_singleton', None)
    monkeypatch.setattr(metadata_queue, 'MetadataTaskQueue', _FakeQueue)

    results: list[object] = []
    errors: list[Exception] = []
    lock = threading.Lock()
    start_gate = threading.Barrier(16)

    def _worker() -> None:
        try:
            start_gate.wait(timeout=2.0)
            q = metadata_queue.get_metadata_task_queue()
            with lock:
                results.append(q)
        except Exception as ex:
            with lock:
                errors.append(ex)

    threads = [threading.Thread(target=_worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    assert not errors
    assert len(results) == 16
    assert created['count'] == 1
    assert len({id(x) for x in results}) == 1
