"""Admin Operations API routing and authorization tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from unified_api.routers import operations
from unified_api.services.auth import TokenData


ADMIN = TokenData(user_id=9, email="owner@example.test", role="admin")


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(operations.router, prefix="/api")
    app.dependency_overrides[operations.require_admin] = lambda: ADMIN
    return TestClient(app)


def test_summary_is_admin_routed_and_honors_time_window(monkeypatch):
    monkeypatch.setattr(
        operations,
        "operations_summary",
        lambda hours: {"hours": hours, "requests": {"requests": 7}},
    )

    response = _client().get("/api/admin/operations/summary?hours=6")

    assert response.status_code == 200
    assert response.json() == {"hours": 6, "requests": {"requests": 7}}


def test_request_filters_are_passed_to_reporting_layer(monkeypatch):
    captured = {}

    def list_requests(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "limit": kwargs["limit"], "offset": 0}

    monkeypatch.setattr(operations, "list_operation_requests", list_requests)

    response = _client().get(
        "/api/admin/operations/requests",
        params={
            "hours": 168,
            "channel": "mcp",
            "principal": "bdkey",
            "status": "errors",
            "min_duration_ms": 250,
            "limit": 25,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "hours": 168,
        "channel": "mcp",
        "path": None,
        "principal": "bdkey",
        "status": "errors",
        "min_duration_ms": 250.0,
        "limit": 25,
        "offset": 0,
    }


def test_settings_update_is_validated_and_audited(monkeypatch):
    values = {
        "enabled": True,
        "capture_request_payloads": False,
        "retain_normalized_sql": True,
        "sql_min_duration_ms": 5,
        "slow_request_ms": 750,
        "slow_sql_ms": 100,
        "max_sql_spans_per_operation": 100,
        "payload_max_bytes": 4096,
        "retention_days": 60,
    }
    updates = []
    audits = []
    monkeypatch.setattr(
        operations,
        "update_telemetry_settings",
        lambda settings, updated_by: updates.append((settings, updated_by)) or settings,
    )
    monkeypatch.setattr(
        operations,
        "log_audit",
        lambda event, **kwargs: audits.append((event, kwargs)),
    )

    response = _client().put("/api/admin/operations/settings", json=values)

    assert response.status_code == 200
    assert response.json() == values
    assert updates == [(values, 9)]
    assert audits[0][0] == "operations_telemetry_settings_updated"
    assert audits[0][1]["metadata"]["retention_days"] == 60


def test_invalid_settings_and_request_ids_return_client_errors(monkeypatch):
    invalid_settings = _client().put(
        "/api/admin/operations/settings",
        json={"enabled": True, "retention_days": 0},
    )
    assert invalid_settings.status_code == 422

    def invalid_uuid(_request_id):
        raise RuntimeError("invalid input syntax for type uuid")

    monkeypatch.setattr(operations, "operation_request_detail", invalid_uuid)
    invalid_request = _client().get("/api/admin/operations/requests/not-a-uuid")
    assert invalid_request.status_code == 422
