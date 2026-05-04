from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from queue import Queue
import threading
import time
import traceback
from typing import Any, Literal
from uuid import uuid4


JobStatus = Literal['queued', 'running', 'done', 'failed']
ProgressCallback = Callable[[int, int, str], None]
MetadataRunner = Callable[[ProgressCallback], Any]


@dataclass
class MetadataJobSnapshot:
    id: str
    label: str
    status: JobStatus
    current: int = 0
    total: int = 0
    item_label: str = ''
    result: Any | None = None
    error: str | None = None
    queued_ahead: int = 0
    queued_total: int = 0
    enqueued_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None


class MetadataTaskQueue:
    """Lightweight process-local worker queue for DOI/ISBN metadata jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, MetadataJobSnapshot] = {}
        self._runners: dict[str, MetadataRunner] = {}
        self._queue: Queue[str] = Queue()
        self._pending_order: list[str] = []
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._worker_loop, name='pv-metadata-worker', daemon=True)
        self._worker.start()

    def submit(self, *, label: str, runner: MetadataRunner) -> str:
        job_id = uuid4().hex
        snap = MetadataJobSnapshot(id=job_id, label=label, status='queued', enqueued_at=time.monotonic())
        with self._lock:
            self._jobs[job_id] = snap
            self._runners[job_id] = runner
            self._pending_order.append(job_id)
            self._refresh_queue_positions_locked()
        self._queue.put(job_id)
        return job_id

    def get(self, job_id: str) -> MetadataJobSnapshot | None:
        with self._lock:
            snap = self._jobs.get(job_id)
            if snap is None:
                return None
            self._refresh_queue_positions_locked()
            return MetadataJobSnapshot(**snap.__dict__)

    def _refresh_queue_positions_locked(self) -> None:
        pending = [jid for jid in self._pending_order if self._jobs.get(jid) and self._jobs[jid].status == 'queued']
        queued_total = len(pending)
        pos_by_id = {jid: idx for idx, jid in enumerate(pending)}
        for job in self._jobs.values():
            if job.status == 'queued':
                job.queued_ahead = int(pos_by_id.get(job.id, 0))
                job.queued_total = queued_total
            else:
                job.queued_ahead = 0
                job.queued_total = queued_total

    def _update_progress(self, job_id: str, current: int, total: int, item_label: str) -> None:
        with self._lock:
            snap = self._jobs.get(job_id)
            if snap is None:
                return
            snap.current = int(current or 0)
            snap.total = int(total or 0)
            snap.item_label = str(item_label or '')

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                with self._lock:
                    snap = self._jobs.get(job_id)
                    runner = self._runners.pop(job_id, None)
                    if snap is None or runner is None:
                        continue
                    if job_id in self._pending_order:
                        self._pending_order.remove(job_id)
                    snap.status = 'running'
                    snap.started_at = time.monotonic()
                    self._refresh_queue_positions_locked()

                def _on_progress(current: int, total: int, item_label: str) -> None:
                    self._update_progress(job_id, current, total, item_label)

                try:
                    result = runner(_on_progress)
                except Exception:
                    with self._lock:
                        snap = self._jobs.get(job_id)
                        if snap is not None:
                            snap.status = 'failed'
                            snap.error = traceback.format_exc(limit=8)
                            snap.finished_at = time.monotonic()
                            self._refresh_queue_positions_locked()
                else:
                    with self._lock:
                        snap = self._jobs.get(job_id)
                        if snap is not None:
                            snap.status = 'done'
                            snap.result = result
                            snap.finished_at = time.monotonic()
                            self._refresh_queue_positions_locked()
            finally:
                self._queue.task_done()


_queue_singleton: MetadataTaskQueue | None = None
_queue_singleton_lock = threading.Lock()


def get_metadata_task_queue() -> MetadataTaskQueue:
    global _queue_singleton
    if _queue_singleton is not None:
        return _queue_singleton

    with _queue_singleton_lock:
        if _queue_singleton is None:
            _queue_singleton = MetadataTaskQueue()
    return _queue_singleton
