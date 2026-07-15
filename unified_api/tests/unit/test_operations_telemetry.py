"""Security, correlation, and SQL-capture tests for Operations telemetry."""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import create_engine, text

import unified_api.services.operations_telemetry as telemetry


def _settings(**overrides):
    values = {
        "enabled": True,
        "capture_request_payloads": True,
        "retain_normalized_sql": True,
        "sql_min_duration_ms": 0,
        "slow_request_ms": 1000,
        "slow_sql_ms": 1,
        "max_sql_spans_per_operation": 200,
        "payload_max_bytes": 32768,
        "retention_days": 30,
    }
    values.update(overrides)
    return telemetry.TelemetrySettings(**values)


def test_sanitize_value_recursively_redacts_secrets_and_bounds_text():
    result = telemetry.sanitize_value({
        "query": "oncology",
        "password": "never-store-me",
        "nested": {"api_key": "onebd_secret", "note": "x" * 800},
    })

    assert result["query"] == "oncology"
    assert result["password"] == "[REDACTED]"
    assert result["nested"]["api_key"] == "[REDACTED]"
    assert len(result["nested"]["note"]) == 501


def test_sanitize_sql_removes_values_and_produces_stable_fingerprint():
    first = telemetry.sanitize_sql(
        "SELECT * FROM deals d JOIN companies c ON c.id=d.id "
        "WHERE c.name='Pfizer' AND d.id=123"
    )
    second = telemetry.sanitize_sql(
        "SELECT * FROM deals d JOIN companies c ON c.id=d.id "
        "WHERE c.name='Merck' AND d.id=999"
    )

    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[2] == ["companies", "deals"]
    assert first[3] == "SELECT"
    assert "Pfizer" not in first[0]
    assert "123" not in first[0]


def test_sqlalchemy_listener_correlates_query_without_parameters(monkeypatch):
    monkeypatch.setattr(telemetry, "get_telemetry_settings", lambda **_kw: _settings())
    engine = create_engine("sqlite:///:memory:")
    telemetry.install_sqlalchemy_telemetry(engine, "test")
    operation, token = telemetry.start_operation("request")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE sample (id INTEGER, secret TEXT)"))
            connection.execute(
                text("INSERT INTO sample VALUES (:id, :secret)"),
                {"id": 42, "secret": "do-not-retain"},
            )
            connection.execute(
                text("SELECT * FROM sample WHERE id=:id"), {"id": 42}
            ).all()
    finally:
        telemetry._current_operation.reset(token)

    assert len(operation.spans) == 3
    assert {span.statement_type for span in operation.spans} == {
        "CREATE",
        "INSERT",
        "SELECT",
    }
    retained = " ".join(span.normalized_sql or "" for span in operation.spans)
    assert "do-not-retain" not in retained
    assert "42" not in retained


def test_sql_span_cap_counts_dropped_statements(monkeypatch):
    monkeypatch.setattr(
        telemetry,
        "get_telemetry_settings",
        lambda **_kw: _settings(max_sql_spans_per_operation=1),
    )
    engine = create_engine("sqlite:///:memory:")
    telemetry.install_sqlalchemy_telemetry(engine, "capped")
    operation, token = telemetry.start_operation("request")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            connection.execute(text("SELECT 2"))
    finally:
        telemetry._current_operation.reset(token)

    assert len(operation.spans) == 1
    assert operation.dropped_sql_spans == 1


def test_fast_sql_details_are_filtered_but_operation_totals_are_preserved(
    monkeypatch,
):
    monkeypatch.setattr(
        telemetry,
        "get_telemetry_settings",
        lambda **_kw: _settings(sql_min_duration_ms=1_000_000),
    )
    engine = create_engine("sqlite:///:memory:")
    telemetry.install_sqlalchemy_telemetry(engine, "filtered")
    operation, token = telemetry.start_operation("request")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        telemetry._current_operation.reset(token)

    assert operation.spans == []
    assert operation.sql_count == 1
    assert operation.sql_duration_ms > 0


def test_sql_errors_are_retained_below_the_duration_threshold(monkeypatch):
    monkeypatch.setattr(
        telemetry,
        "get_telemetry_settings",
        lambda **_kw: _settings(sql_min_duration_ms=1_000_000),
    )
    engine = create_engine("sqlite:///:memory:")
    telemetry.install_sqlalchemy_telemetry(engine, "errors")
    operation, token = telemetry.start_operation("request")
    try:
        with engine.connect() as connection:
            try:
                connection.execute(text("SELECT * FROM table_that_does_not_exist"))
            except Exception:
                pass
    finally:
        telemetry._current_operation.reset(token)

    assert operation.sql_count == 1
    assert len(operation.spans) == 1
    assert operation.spans[0].success is False


def test_disabled_policy_does_not_persist_job_telemetry(monkeypatch):
    monkeypatch.setattr(
        telemetry,
        "get_telemetry_settings",
        lambda **_kw: _settings(enabled=False),
    )
    telemetry.start_job_operation(
        "disabled-job",
        "tests.disabled",
        args=(),
        kwargs={},
    )

    telemetry.finish_job_operation("disabled-job", status="SUCCESS")

    assert telemetry.current_operation() is None


def test_asgi_middleware_captures_mcp_principal_and_redacted_body(monkeypatch):
    records = []
    monkeypatch.setattr(telemetry, "get_telemetry_settings", lambda **_kw: _settings())
    monkeypatch.setattr(
        telemetry,
        "persist_request",
        lambda operation, record: records.append((operation, record)),
    )
    app = FastAPI()
    app.add_middleware(telemetry.OperationsTelemetryMiddleware)

    @app.post("/mcp")
    async def mcp(request: Request):
        request.state.telemetry_channel = "mcp"
        request.state.telemetry_operation_names = ["search_all_sources"]
        request.state.data_principal = type("Principal", (), {
            "principal_type": "api_key",
            "principal_id": "15",
            "name": "bdkey-all",
        })()
        await request.json()
        return {"ok": True}

    response = TestClient(app).post(
        "/mcp?mode=test",
        json={
            "method": "tools/call",
            "params": {"name": "search_all_sources", "api_key": "secret"},
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert len(records) == 1
    operation, record = records[0]
    assert record["channel"] == "mcp"
    assert record["operation_names"] == ["search_all_sources"]
    assert record["principal_name"] == "bdkey-all"
    assert record["request_metadata"]["query"] == {"mode": ["test"]}
    assert (
        record["request_metadata"]["body"]["params"]["api_key"]
        == "[REDACTED]"
    )
    assert operation.operation_type == "request"


def test_caught_semantic_error_is_persisted_even_with_http_200(monkeypatch):
    records = []
    monkeypatch.setattr(telemetry, "get_telemetry_settings", lambda **_kw: _settings())
    monkeypatch.setattr(
        telemetry,
        "persist_request",
        lambda operation, record: records.append((operation, record)),
    )
    app = FastAPI()
    app.add_middleware(telemetry.OperationsTelemetryMiddleware)

    @app.get("/caught-error")
    async def caught_error():
        telemetry.mark_current_operation_error(ValueError("query failed"))
        return {"ok": False}

    response = TestClient(app).get("/caught-error")

    assert response.status_code == 200
    assert records[0][1]["error_type"] == "ValueError"
    assert records[0][0].error_message == "query failed"


def test_nested_mcp_rest_request_preserves_parent_correlation(monkeypatch):
    records = []
    monkeypatch.setattr(telemetry, "get_telemetry_settings", lambda **_kw: _settings())
    monkeypatch.setattr(
        telemetry,
        "persist_request",
        lambda operation, record: records.append((operation, record)),
    )
    app = FastAPI()
    app.add_middleware(telemetry.OperationsTelemetryMiddleware)

    @app.get("/api/child")
    async def child():
        return {"source": "cortellis"}

    @app.post("/mcp")
    async def mcp(request: Request):
        request.state.telemetry_channel = "mcp"
        request.state.telemetry_operation_names = ["search_deals"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=request.app),
            base_url="http://onebd.internal",
        ) as client:
            response = await client.get("/api/child")
        return response.json()

    response = TestClient(app).post("/mcp")

    assert response.status_code == 200
    assert len(records) == 2
    child_operation, child_record = next(
        item for item in records if item[1]["path"] == "/api/child"
    )
    outer_operation, outer_record = next(
        item for item in records if item[1]["path"] == "/mcp"
    )
    assert child_record["parent_request_id"] == outer_operation.operation_id
    assert child_record["channel"] == "api"
    assert outer_record["channel"] == "mcp"
    assert outer_record["operation_names"] == ["search_deals"]
    assert child_operation.operation_id != outer_operation.operation_id
