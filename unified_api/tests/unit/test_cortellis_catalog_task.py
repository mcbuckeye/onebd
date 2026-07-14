"""Concurrency tests for the exhaustive Cortellis catalog worker."""

from importlib import import_module
from unittest.mock import Mock, patch


worker_module = import_module("unified_api.workers.celery_app")


def _connection(*, acquired: bool) -> Mock:
    connection = Mock()
    connection.execute.return_value.scalar.return_value = acquired
    return connection


def test_catalog_reconciliation_skips_before_touching_shared_state_when_locked():
    connection = _connection(acquired=False)
    engine = Mock()
    engine.connect.return_value = connection

    with (
        patch(
            "unified_api.services.database.get_cortellis_engine",
            return_value=engine,
        ),
        patch.object(worker_module, "_start_source_job") as start_job,
        patch.object(worker_module, "_cortellis_sync_service") as sync_service,
    ):
        result = worker_module.reconcile_cortellis_catalog.run()

    assert result == {
        "status": "skipped",
        "reason": "Cortellis catalog reconciliation already running",
    }
    start_job.assert_not_called()
    sync_service.assert_not_called()
    connection.close.assert_called_once_with()


def test_catalog_reconciliation_releases_lock_after_no_credentials():
    connection = _connection(acquired=True)
    engine = Mock()
    engine.connect.return_value = connection

    with (
        patch(
            "unified_api.services.database.get_cortellis_engine",
            return_value=engine,
        ),
        patch.object(worker_module.settings, "cortellis_api_username", ""),
        patch.object(worker_module.settings, "cortellis_api_password", ""),
        patch.object(worker_module, "_start_source_job") as start_job,
        patch.object(
            worker_module,
            "_finish_source_job",
            side_effect=lambda _source, result: result,
        ),
    ):
        result = worker_module.reconcile_cortellis_catalog.run()

    assert result == {"status": "skipped", "reason": "no credentials"}
    start_job.assert_called_once_with("cortellis_catalog")
    assert connection.execute.call_count == 2
    connection.close.assert_called_once_with()
