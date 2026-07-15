"""Account isolation and team collaboration contracts."""

import inspect
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from unified_api.routers import watchlist
from unified_api.routers.collaboration import SharedItemRequest
from unified_api.services import account_schema
from unified_api.services.collaboration import membership_role, require_team_role


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _RoleSession:
    def __init__(self, role):
        self.role = role

    def execute(self, _statement, _params):
        return _ScalarResult(self.role)


def test_account_schema_upgrades_existing_users_table():
    statements = []

    class Session:
        def execute(self, statement):
            statements.append(str(statement))

        def commit(self):
            return None

    account_schema.migrate_account_schema(Session())

    ddl = "\n".join(statements)
    assert "ADD COLUMN IF NOT EXISTS disabled" in ddl
    assert "idx_users_email_lower" in ddl
    assert "password_reset_tokens" in ddl


def test_personal_workspace_endpoints_cannot_accept_another_user_id():
    protected = [
        watchlist.get_watchlist,
        watchlist.add_to_watchlist,
        watchlist.get_deal_notes,
        watchlist.create_saved_search,
        watchlist.get_notifications,
    ]

    for endpoint in protected:
        assert "user_id" not in inspect.signature(endpoint).parameters
        assert "user" in inspect.signature(endpoint).parameters


def test_team_role_helpers_hide_nonmember_teams_and_enforce_editing():
    assert membership_role(_RoleSession("editor"), 4, 7) == "editor"
    assert require_team_role(_RoleSession("owner"), 4, 7, {"owner"}) == "owner"

    with pytest.raises(HTTPException) as missing:
        membership_role(_RoleSession(None), 4, 7)
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as forbidden:
        require_team_role(_RoleSession("viewer"), 4, 7, {"owner", "editor"})
    assert forbidden.value.status_code == 403


def test_shared_items_have_a_bounded_resource_catalog():
    valid = SharedItemRequest(resource_type="filing", title="Important 8-K")
    assert valid.resource_type == "filing"

    with pytest.raises(ValidationError):
        SharedItemRequest(resource_type="arbitrary_sql_table", title="No")
