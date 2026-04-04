from __future__ import annotations

import hashlib
import time

from papervisor.core import rate_limit
from papervisor.core.rate_limit import RateLimiter


def test_rate_limiter_enforces_hard_cap_with_unique_keys(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, '_MAX_TRACKED_KEYS', 3)
    limiter = RateLimiter(max_attempts=5, window_seconds=3600, lockout_seconds=60)

    assert limiter.check('k1') is True
    assert limiter.check('k2') is True
    assert limiter.check('k3') is True
    assert limiter.check('k4') is True

    # Hard cap should be respected even when no entries are expired.
    assert len(limiter._buckets) <= 3


def test_rate_limiter_hashes_and_truncates_raw_keys() -> None:
    limiter = RateLimiter(max_attempts=5, window_seconds=3600, lockout_seconds=60)
    very_long = 'a' * 5000

    assert limiter.check(very_long) is True

    expected = hashlib.sha256(('a' * 1024).encode('utf-8')).hexdigest()
    assert expected in limiter._buckets
    assert all(len(key) == 64 for key in limiter._buckets)


def test_rate_limiter_reset_uses_normalized_key() -> None:
    limiter = RateLimiter(max_attempts=1, window_seconds=3600, lockout_seconds=60)
    key = 'b' * 2048

    assert limiter.check(key) is True
    assert limiter.check(key) is False
    assert limiter.remaining(key) == 0

    limiter.reset(key)

    assert limiter.remaining(key) == 1
    assert limiter.check(key) is True


def test_pruning_preserves_locked_bucket_when_unlocked_available(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, '_MAX_TRACKED_KEYS', 2)
    limiter = RateLimiter(max_attempts=1, window_seconds=3600, lockout_seconds=60)

    # Create a locked bucket.
    assert limiter.check('locked') is True
    assert limiter.check('locked') is False
    locked_key = limiter._bucket_key('locked')
    assert locked_key in limiter._buckets

    # Fill and overflow with unlocked buckets.
    assert limiter.check('u1') is True
    assert limiter.check('u2') is True

    # Locked bucket should be preserved while unlocked buckets are pruned first.
    assert locked_key in limiter._buckets
    assert len(limiter._buckets) <= 2


def test_saturated_locked_table_still_tracks_fresh_key(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, '_MAX_TRACKED_KEYS', 2)
    limiter = RateLimiter(max_attempts=1, window_seconds=3600, lockout_seconds=60)

    # Fill table with locked buckets.
    assert limiter.check('k1') is True
    assert limiter.check('k1') is False
    assert limiter.check('k2') is True
    assert limiter.check('k2') is False

    fresh_key = 'fresh'
    fresh_bucket = limiter._bucket_key(fresh_key)

    # First attempt is allowed and key must remain tracked.
    assert limiter.check(fresh_key) is True
    assert fresh_bucket in limiter._buckets

    # Second attempt must be blocked (not treated as another first attempt).
    assert limiter.check(fresh_key) is False
