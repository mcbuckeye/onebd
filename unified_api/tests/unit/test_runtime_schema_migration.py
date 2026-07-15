"""Deployment-time operational schema migration tests."""

from unittest.mock import MagicMock, patch

from unified_api.scripts.migrate_runtime_schema import (
    MIGRATION_LOCK_ID,
    migrate_runtime_schema,
)


def test_runtime_schema_is_migrated_once_under_an_advisory_lock() -> None:
    engine = MagicMock()
    connection = (
        engine.connect.return_value.execution_options.return_value
        .__enter__.return_value
    )

    with (
        patch(
            "unified_api.scripts.migrate_runtime_schema.get_cortellis_engine",
            return_value=engine,
        ),
        patch(
            "unified_api.scripts.migrate_runtime_schema."
            "_apply_runtime_schema_migrations"
        ) as apply_migrations,
    ):
        migrate_runtime_schema()

    apply_migrations.assert_called_once_with()
    assert connection.execute.call_args_list[0].args[1] == {
        "lock_id": MIGRATION_LOCK_ID
    }
    assert connection.execute.call_args_list[-1].args[1] == {
        "lock_id": MIGRATION_LOCK_ID
    }


def test_runtime_schema_unlocks_when_a_migration_fails() -> None:
    engine = MagicMock()
    connection = (
        engine.connect.return_value.execution_options.return_value
        .__enter__.return_value
    )

    with (
        patch(
            "unified_api.scripts.migrate_runtime_schema.get_cortellis_engine",
            return_value=engine,
        ),
        patch(
            "unified_api.scripts.migrate_runtime_schema."
            "_apply_runtime_schema_migrations",
            side_effect=RuntimeError("migration failed"),
        ),
    ):
        try:
            migrate_runtime_schema()
        except RuntimeError:
            pass
        else:
            raise AssertionError("migration failure should propagate")

    assert connection.execute.call_count == 2
    assert connection.execute.call_args_list[-1].args[1] == {
        "lock_id": MIGRATION_LOCK_ID
    }
