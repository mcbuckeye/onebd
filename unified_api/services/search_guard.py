"""Distributed guardrails for database-intensive governed searches."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import os
import time
from typing import Iterator

import redis
from redis.exceptions import LockError
import structlog

from unified_api.services.cache import get_redis


logger = structlog.get_logger(__name__)

SEARCH_RATE_PER_MINUTE = int(os.getenv("ONEBD_SEARCH_RATE_PER_MINUTE", "30"))
SEARCH_GLOBAL_CONCURRENCY = int(os.getenv("ONEBD_SEARCH_GLOBAL_CONCURRENCY", "4"))
SEARCH_LOCK_SECONDS = int(os.getenv("ONEBD_SEARCH_LOCK_SECONDS", "40"))


class SearchRateLimited(RuntimeError):
    """The caller exceeded its configured heavy-search request rate."""


class SearchBusy(RuntimeError):
    """The caller or global search pool already has enough active work."""


def _principal_token(principal) -> str:
    raw = f"{principal.principal_type}:{principal.principal_id}"
    return sha256(raw.encode()).hexdigest()[:24]


@contextmanager
def advanced_search_guard(principal) -> Iterator[None]:
    """Limit each principal to one search and bound global search concurrency.

    Redis failures are deliberately fail-open because PostgreSQL statement
    timeouts remain the final safety boundary.
    """
    if principal is None:
        yield
        return

    client = None
    principal_lock = None
    slot_lock = None
    try:
        client = get_redis()
        token = _principal_token(principal)
        minute = int(time.time() // 60)
        rate_key = f"bd:advanced-search:rate:{token}:{minute}"
        count = int(client.incr(rate_key))
        if count == 1:
            client.expire(rate_key, 90)
        if count > SEARCH_RATE_PER_MINUTE:
            raise SearchRateLimited("Advanced-search rate limit exceeded")

        principal_lock = client.lock(
            f"bd:advanced-search:principal:{token}",
            timeout=SEARCH_LOCK_SECONDS,
            blocking_timeout=0,
        )
        if not principal_lock.acquire(blocking=False):
            raise SearchBusy("An advanced search is already running for this credential")

        for slot in range(max(1, SEARCH_GLOBAL_CONCURRENCY)):
            candidate = client.lock(
                f"bd:advanced-search:slot:{slot}",
                timeout=SEARCH_LOCK_SECONDS,
                blocking_timeout=0,
            )
            if candidate.acquire(blocking=False):
                slot_lock = candidate
                break
        if slot_lock is None:
            raise SearchBusy("The advanced-search pool is currently full")
    except (redis.ConnectionError, redis.TimeoutError) as exc:
        logger.warning("advanced_search_guard_unavailable", error=str(exc))
        principal_lock = None
        slot_lock = None
    except (SearchRateLimited, SearchBusy):
        for lock in (slot_lock, principal_lock):
            if lock is None:
                continue
            try:
                lock.release()
            except LockError:
                pass
        raise

    try:
        yield
    finally:
        for lock in (slot_lock, principal_lock):
            if lock is None:
                continue
            try:
                lock.release()
            except LockError:
                pass
