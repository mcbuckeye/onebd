"""Unit tests for owner-controlled API keys and data-access policy."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from unified_api.services import api_credentials


def _request(path: str = "/api/v1/deals"):
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        headers={},
    )


def _authorized_request(token: str = "valid-token"):
    request = _request()
    request.headers = {"authorization": f"Bearer {token}"}
    return request


def test_create_credential_stores_hash_and_returns_plaintext_once(monkeypatch):
    captured = {}

    class Result:
        def mappings(self):
            return self

        def one(self):
            return {
                "id": 7,
                "name": "BD team",
                "key_prefix": captured["params"]["key_prefix"],
                "scopes": ["data:read"],
                "created_at": datetime.now(timezone.utc),
                "expires_at": None,
            }

    class Session:
        def execute(self, _statement, params):
            captured["params"] = params
            return Result()

    @contextmanager
    def fake_session():
        yield Session()

    monkeypatch.setattr(api_credentials, "ensure_api_access_schema", lambda: None)
    monkeypatch.setattr(api_credentials, "get_cortellis_session", fake_session)

    result = api_credentials.create_api_credential(
        name="BD team",
        scopes=["data:read"],
        created_by=1,
    )

    assert result["api_key"].startswith("onebd_")
    assert captured["params"]["key_hash"] == hashlib.sha256(
        result["api_key"].encode()
    ).hexdigest()
    assert result["api_key"] not in captured["params"].values()


def test_create_credential_rejects_invalid_scope_and_past_expiry(monkeypatch):
    monkeypatch.setattr(api_credentials, "ensure_api_access_schema", lambda: None)
    with pytest.raises(ValueError, match="Unsupported API scopes"):
        api_credentials.create_api_credential(
            name="bad", scopes=["write:anything"], created_by=1
        )
    with pytest.raises(ValueError, match="future"):
        api_credentials.create_api_credential(
            name="expired",
            scopes=["data:read"],
            created_by=1,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )


def test_open_policy_allows_anonymous_access(monkeypatch):
    monkeypatch.setattr(api_credentials, "get_data_access_policy", lambda: {
        "access_mode": "open",
        "enforce_scopes": True,
        "disabled_datasets": [],
    })
    dependency = api_credentials.require_data_access(
        "deals:read", "cortellis_deals"
    )

    principal = asyncio.run(dependency(_request(), api_key=None))

    assert principal.principal_type == "anonymous"
    assert principal.scopes == ["data:read"]


def test_key_policy_enforces_scope(monkeypatch):
    monkeypatch.setattr(api_credentials, "get_data_access_policy", lambda: {
        "access_mode": "key_required",
        "enforce_scopes": True,
        "disabled_datasets": [],
    })
    monkeypatch.setattr(api_credentials, "_api_key_principal", lambda *_args: (
        api_credentials.DataPrincipal(
            principal_type="api_key",
            principal_id="4",
            name="limited",
            scopes=["catalog:read"],
        )
    ))
    dependency = api_credentials.require_data_access(
        "deals:read", "cortellis_deals"
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(_request(), api_key="onebd_test"))

    assert exc.value.status_code == 403
    assert "deals:read" in exc.value.detail


def test_scope_enforcement_can_be_disabled_by_owner(monkeypatch):
    monkeypatch.setattr(api_credentials, "get_data_access_policy", lambda: {
        "access_mode": "key_required",
        "enforce_scopes": False,
        "disabled_datasets": [],
    })
    monkeypatch.setattr(api_credentials, "_api_key_principal", lambda *_args: (
        api_credentials.DataPrincipal(
            principal_type="api_key",
            principal_id="4",
            name="limited",
            scopes=[],
        )
    ))
    dependency = api_credentials.require_data_access(
        "deals:read", "cortellis_deals"
    )

    principal = asyncio.run(dependency(_request(), api_key="onebd_test"))

    assert principal.name == "limited"


def test_owner_can_disable_a_dataset_even_in_open_mode(monkeypatch):
    monkeypatch.setattr(api_credentials, "get_data_access_policy", lambda: {
        "access_mode": "open",
        "enforce_scopes": False,
        "disabled_datasets": ["cortellis_deals"],
    })
    dependency = api_credentials.require_data_access(
        "deals:read", "cortellis_deals"
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(_request(), api_key=None))

    assert exc.value.status_code == 403
    assert "disabled" in exc.value.detail


def test_policy_validation_rejects_unknown_modes_and_datasets(monkeypatch):
    monkeypatch.setattr(api_credentials, "ensure_api_access_schema", lambda: None)
    with pytest.raises(ValueError, match="access mode"):
        api_credentials.update_data_access_policy(
            access_mode="license_dictates_access",
            enforce_scopes=True,
            allow_self_registration=False,
            protect_existing_api=False,
            disabled_datasets=[],
            updated_by=1,
        )
    with pytest.raises(ValueError, match="Unsupported datasets"):
        api_credentials.update_data_access_policy(
            access_mode="open",
            enforce_scopes=False,
            allow_self_registration=False,
            protect_existing_api=False,
            disabled_datasets=["imaginary"],
            updated_by=1,
        )


def test_legacy_api_protection_is_an_owner_opt_in(monkeypatch):
    monkeypatch.setattr(api_credentials, "get_data_access_policy", lambda: {
        "access_mode": "key_required",
        "enforce_scopes": True,
        "protect_existing_api": False,
    })

    principal = api_credentials.authorize_existing_api_request(
        _request("/api/deals")
    )

    assert principal is None


def test_owner_can_protect_existing_api_with_broad_key(monkeypatch):
    monkeypatch.setattr(api_credentials, "get_data_access_policy", lambda: {
        "access_mode": "key_required",
        "enforce_scopes": True,
        "protect_existing_api": True,
    })
    monkeypatch.setattr(api_credentials, "_api_key_principal", lambda *_args: (
        api_credentials.DataPrincipal(
            principal_type="api_key",
            principal_id="8",
            name="system integration",
            scopes=["data:read"],
        )
    ))

    principal = api_credentials.authorize_existing_api_request(
        _request("/api/dashboard")
    )

    assert principal.name == "system integration"


def test_bearer_principal_rechecks_live_account(monkeypatch):
    class Result:
        def mappings(self):
            return self

        def first(self):
            return {"id": 11, "email": "current@example.test"}

    class Session:
        def execute(self, _statement, params):
            assert params == {"user_id": 11}
            return Result()

    @contextmanager
    def fake_session():
        yield Session()

    monkeypatch.setattr(
        api_credentials,
        "decode_token",
        lambda _token: api_credentials.TokenData(
            user_id=11,
            email="stale@example.test",
            role="analyst",
        ),
    )
    monkeypatch.setattr(api_credentials, "get_cortellis_session", fake_session)

    principal = api_credentials._bearer_principal(_authorized_request())

    assert principal is not None
    assert principal.principal_id == "11"
    assert principal.name == "current@example.test"


def test_bearer_principal_rejects_disabled_or_missing_account(monkeypatch):
    class Result:
        def mappings(self):
            return self

        def first(self):
            return None

    class Session:
        def execute(self, _statement, _params):
            return Result()

    @contextmanager
    def fake_session():
        yield Session()

    monkeypatch.setattr(
        api_credentials,
        "decode_token",
        lambda _token: api_credentials.TokenData(
            user_id=11,
            email="disabled@example.test",
            role="analyst",
        ),
    )
    monkeypatch.setattr(api_credentials, "get_cortellis_session", fake_session)

    assert api_credentials._bearer_principal(_authorized_request()) is None
