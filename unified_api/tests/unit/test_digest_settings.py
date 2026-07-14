"""Tests for scheduled digest preference schema evolution."""

from unified_api.services.digest_settings import ensure_digest_settings_schema


class _Session:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(str(statement))


def test_digest_schema_adds_catalyst_schedule_preferences_idempotently():
    session = _Session()

    ensure_digest_settings_schema(session)

    sql = "\n".join(session.statements)
    assert "include_catalysts BOOLEAN NOT NULL DEFAULT TRUE" in sql
    assert "catalyst_days INTEGER NOT NULL DEFAULT 30" in sql
    assert "ADD COLUMN IF NOT EXISTS include_catalysts" in sql
    assert "ADD COLUMN IF NOT EXISTS catalyst_days" in sql
