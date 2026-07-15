"""Distributed advanced-search guard behavior."""

from dataclasses import dataclass

import pytest

import unified_api.services.search_guard as search_guard


@dataclass
class _Principal:
    principal_type: str = "api_key"
    principal_id: str = "7"


class _Lock:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.released = False

    def acquire(self, blocking=False):
        return self.acquired

    def release(self):
        self.released = True


class _Redis:
    def __init__(self, counts=None, locks=None):
        self.counts = list(counts or [1])
        self.locks = list(locks or [_Lock(), _Lock()])

    def incr(self, _key):
        return self.counts.pop(0)

    def expire(self, _key, _seconds):
        return True

    def lock(self, *_args, **_kwargs):
        return self.locks.pop(0)


def test_guard_releases_principal_and_global_slot(monkeypatch):
    principal_lock = _Lock()
    slot_lock = _Lock()
    monkeypatch.setattr(
        search_guard,
        "get_redis",
        lambda: _Redis(locks=[principal_lock, slot_lock]),
    )

    with search_guard.advanced_search_guard(_Principal()):
        pass

    assert principal_lock.released is True
    assert slot_lock.released is True


def test_guard_rejects_rate_limit_before_starting_work(monkeypatch):
    monkeypatch.setattr(
        search_guard,
        "get_redis",
        lambda: _Redis(counts=[search_guard.SEARCH_RATE_PER_MINUTE + 1]),
    )

    with pytest.raises(search_guard.SearchRateLimited):
        with search_guard.advanced_search_guard(_Principal()):
            raise AssertionError("guard should not yield")
