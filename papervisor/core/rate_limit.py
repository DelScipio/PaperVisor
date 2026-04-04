"""Lightweight in-process rate limiter.

Provides per-key (typically per-IP) sliding-window rate limiting without
external dependencies.  Used to protect login, registration, and OPDS
Basic Auth endpoints from brute-force attacks.

The limiter is intentionally simple — a fixed-window counter with automatic
expiry.  For most single-process PaperVisor deployments this is sufficient.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)

# ── Default configuration (overridable via environment) ─────────────────

_DEFAULT_MAX_ATTEMPTS = 10        # requests per window
_DEFAULT_WINDOW_SECONDS = 300     # 5-minute window
_DEFAULT_LOCKOUT_SECONDS = 600    # 10-minute lockout after exceeding max

# Maximum number of tracked keys to prevent unbounded memory growth.
_MAX_TRACKED_KEYS = 50_000

# Raw key input is normalized to a fixed-size digest before storage.
_MAX_RAW_KEY_CHARS = 1024


@dataclass
class _BucketEntry:
    count: int = 0
    window_start: float = 0.0
    locked_until: float = 0.0


@dataclass
class RateLimiter:
    """Fixed-window rate limiter with automatic lockout.

    Parameters
    ----------
    max_attempts:
        Maximum number of allowed calls per window.
    window_seconds:
        Length of the counting window in seconds.
    lockout_seconds:
        How long to lock a key after it exceeds *max_attempts*.
    """

    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    window_seconds: float = _DEFAULT_WINDOW_SECONDS
    lockout_seconds: float = _DEFAULT_LOCKOUT_SECONDS

    _buckets: dict[str, _BucketEntry] = field(default_factory=dict, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    # ── Public API ──────────────────────────────────────────────────────

    def check(self, key: str) -> bool:
        """Record one attempt for *key* and return ``True`` if allowed.

        Returns ``False`` (rate-limited) when the key has exceeded its
        budget for the current window or is locked out.
        """
        now = time.monotonic()
        bucket_key = self._bucket_key(key)

        with self._lock:
            self._maybe_evict(now)
            entry = self._buckets.get(bucket_key)

            if entry is None:
                entry = _BucketEntry(count=1, window_start=now)
                self._buckets[bucket_key] = entry
                self._maybe_evict(now, preserve_key=bucket_key)
                return True

            # Still locked out?
            if entry.locked_until > now:
                return False

            # Window expired → reset.
            if now - entry.window_start >= self.window_seconds:
                entry.count = 1
                entry.window_start = now
                entry.locked_until = 0.0
                return True

            entry.count += 1

            if entry.count > self.max_attempts:
                entry.locked_until = now + self.lockout_seconds
                logger.warning(
                    'Rate limit exceeded for key=%r (%d attempts in %.0fs); '
                    'locked out for %.0fs',
                    bucket_key,
                    entry.count,
                    self.window_seconds,
                    self.lockout_seconds,
                )
                return False

            return True

    def remaining(self, key: str) -> int:
        """Return how many attempts remain for *key* in the current window."""
        now = time.monotonic()
        bucket_key = self._bucket_key(key)
        with self._lock:
            entry = self._buckets.get(bucket_key)
            if entry is None:
                return self.max_attempts
            if entry.locked_until > now:
                return 0
            if now - entry.window_start >= self.window_seconds:
                return self.max_attempts
            return max(0, self.max_attempts - entry.count)

    def reset(self, key: str) -> None:
        """Clear rate-limit state for *key* (e.g. after a successful login)."""
        bucket_key = self._bucket_key(key)
        with self._lock:
            self._buckets.pop(bucket_key, None)

    # ── Internals ───────────────────────────────────────────────────────

    def _bucket_key(self, key: str) -> str:
        """Return fixed-size bucket identifier for untrusted key input."""
        raw = str(key or '')
        if len(raw) > _MAX_RAW_KEY_CHARS:
            raw = raw[:_MAX_RAW_KEY_CHARS]
        return hashlib.sha256(raw.encode('utf-8', errors='ignore')).hexdigest()

    def _maybe_evict(self, now: float, preserve_key: str | None = None) -> None:
        """Prevent unbounded memory growth by purging or pruning old entries."""
        if len(self._buckets) <= _MAX_TRACKED_KEYS:
            return

        expired = [
            k
            for k, e in self._buckets.items()
            if now - e.window_start >= self.window_seconds and e.locked_until <= now
        ]
        for k in expired:
            del self._buckets[k]

        if len(self._buckets) <= _MAX_TRACKED_KEYS:
            return

        overflow = len(self._buckets) - _MAX_TRACKED_KEYS
        # Preserve active lockouts as long as possible; prune unlocked buckets first.
        unlocked = [
            item
            for item in self._buckets.items()
            if item[1].locked_until <= now and item[0] != preserve_key
        ]
        oldest_unlocked = sorted(unlocked, key=lambda item: item[1].window_start)[:overflow]
        for key, _ in oldest_unlocked:
            del self._buckets[key]

        if len(self._buckets) <= _MAX_TRACKED_KEYS:
            return

        # Fallback: if all entries are locked and still above cap, prune oldest locked entries.
        overflow = len(self._buckets) - _MAX_TRACKED_KEYS
        locked_candidates = [item for item in self._buckets.items() if item[0] != preserve_key]
        oldest_locked = sorted(locked_candidates, key=lambda item: item[1].window_start)[:overflow]
        for key, _ in oldest_locked:
            del self._buckets[key]


# ── Shared instances for the application ────────────────────────────────

#: Protects UI login + registration pages.
login_limiter = RateLimiter(max_attempts=10, window_seconds=300, lockout_seconds=600)

#: Protects OPDS Basic Auth / API-key auth (separate budget).
opds_auth_limiter = RateLimiter(max_attempts=20, window_seconds=300, lockout_seconds=600)
