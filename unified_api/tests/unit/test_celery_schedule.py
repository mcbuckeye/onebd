"""Periodic scheduling safety tests."""

from pathlib import Path

from unified_api.workers.celery_app import celery_app


def test_non_beat_process_has_no_periodic_schedule(monkeypatch) -> None:
    monkeypatch.delenv("ONEBD_PROCESS_ROLE", raising=False)
    assert celery_app.conf.beat_schedule == {}


def test_compose_assigns_periodic_schedule_only_to_beat() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count("ONEBD_PROCESS_ROLE=beat") == 1
    assert compose.count("ONEBD_PROCESS_ROLE=api") == 1
    assert compose.count("ONEBD_PROCESS_ROLE=worker") == 2
    assert compose.count("ONEBD_RUNTIME_SCHEMA_MIGRATED=true") == 4
