"""Tests for scheduled report preference persistence."""

from contextlib import contextmanager

import pytest

from unified_api.routers import settings as settings_router
from unified_api.services.auth import TokenData


class _Session:
    def __init__(self):
        self.calls = []
        self.committed = False

    def execute(self, statement, params=None):
        self.calls.append((statement, params))

    def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_update_digest_settings_binds_json_and_catalyst_preferences(monkeypatch):
    session = _Session()

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(settings_router, "get_cortellis_session", fake_session)
    preferences = settings_router.DigestSettings(
        enabled=True,
        frequency="weekly",
        therapy_areas=["Oncology"],
        company_ids=[42],
        email="analyst@example.test",
        include_catalysts=True,
        catalyst_days=60,
    )

    result = await settings_router.update_digest_settings(
        preferences,
        TokenData(user_id=7, email="analyst@example.test", role="analyst"),
    )

    insert_statement, params = session.calls[-1]
    assert set(insert_statement._bindparams) >= {
        "therapy_areas",
        "company_ids",
        "include_catalysts",
        "catalyst_days",
    }
    assert params["therapy_areas"] == '["Oncology"]'
    assert params["company_ids"] == "[42]"
    assert params["catalyst_days"] == 60
    assert session.committed is True
    assert result == preferences
