"""Admin API-access mutations are safely validated and audit logged."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

from unified_api.routers import admin
from unified_api.services.auth import TokenData


ADMIN = TokenData(user_id=9, email="owner@example.test", role="admin")


def test_issue_api_credential_audits_metadata_without_plaintext(monkeypatch):
    created_at = datetime.now(timezone.utc)
    monkeypatch.setattr(admin, "create_api_credential", lambda **_kwargs: {
        "id": 17,
        "name": "Colleague",
        "key_prefix": "prefix",
        "scopes": ["deals:read"],
        "created_at": created_at,
        "expires_at": None,
        "api_key": "onebd_plaintext-secret",
    })
    audit = MagicMock()
    monkeypatch.setattr(admin, "log_audit", audit)

    result = asyncio.run(admin.issue_api_credential(
        admin.CreateAPICredentialRequest(
            name="Colleague",
            scopes=["deals:read"],
        ),
        ADMIN,
    ))

    assert result["api_key"] == "onebd_plaintext-secret"
    audit.assert_called_once()
    assert "onebd_plaintext-secret" not in repr(audit.call_args)
    assert audit.call_args.kwargs["entity_id"] == "17"


def test_revoke_api_credential_is_audited(monkeypatch):
    monkeypatch.setattr(admin, "revoke_api_credential", lambda _id: True)
    audit = MagicMock()
    monkeypatch.setattr(admin, "log_audit", audit)

    response = asyncio.run(admin.revoke_credential(17, ADMIN))

    assert response.message == "API credential 17 revoked"
    audit.assert_called_once_with(
        "api_credential_revoked",
        user_id=9,
        entity_type="api_credential",
        entity_id="17",
    )


def test_policy_update_preserves_owner_choices_and_audits(monkeypatch):
    updated = {
        "access_mode": "open",
        "enforce_scopes": False,
        "allow_self_registration": True,
        "protect_existing_api": False,
        "disabled_datasets": ["cortellis_deals"],
        "updated_by": 9,
        "updated_at": datetime.now(timezone.utc),
    }
    update = MagicMock(return_value=updated)
    audit = MagicMock()
    monkeypatch.setattr(admin, "update_data_access_policy", update)
    monkeypatch.setattr(admin, "log_audit", audit)

    result = asyncio.run(admin.set_data_access_policy(
        admin.DataAccessPolicyRequest(
            access_mode="open",
            enforce_scopes=False,
            allow_self_registration=True,
            protect_existing_api=False,
            disabled_datasets=["cortellis_deals"],
        ),
        ADMIN,
    ))

    assert result == updated
    update.assert_called_once_with(
        access_mode="open",
        enforce_scopes=False,
        allow_self_registration=True,
        protect_existing_api=False,
        disabled_datasets=["cortellis_deals"],
        updated_by=9,
    )
    assert audit.call_args.kwargs["metadata"]["access_mode"] == "open"
