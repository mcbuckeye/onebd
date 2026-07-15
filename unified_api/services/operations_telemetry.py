"""Durable, redacted request/job/SQL telemetry for the Admin Operations console.

The collector is deliberately application-owned. It correlates API, MCP, and
Celery activity with SQLAlchemy statements without retaining credentials or SQL
parameter values. Telemetry failures never fail the workload being observed.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import threading
import time
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from sqlalchemy import event, text
import structlog

from unified_api.services.database import (
    get_cortellis_engine,
    get_edgar_source_engine,
)


logger = structlog.get_logger(__name__)
SCHEMA_LOCK_ID = 61320260717
SNAPSHOT_LOCK_ID = 61320260718
_SECRET_KEY = re.compile(
    r"(?:pass(?:word)?|secret|token|api[_-]?key|authorization|cookie|smtp|openai)",
    re.IGNORECASE,
)
_SQL_STRING = re.compile(r"'(?:''|[^'])*'", re.DOTALL)
_SQL_DOLLAR_STRING = re.compile(r"\$[A-Za-z0-9_]*\$.*?\$[A-Za-z0-9_]*\$", re.DOTALL)
_SQL_NUMBER = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?(?![A-Za-z_])")
_SQL_COMMENT = re.compile(r"/\*.*?\*/|--[^\r\n]*", re.DOTALL)
_SQL_TABLE = re.compile(
    r"\b(?:from|join|update|into|delete\s+from)\s+([A-Za-z_][A-Za-z0-9_.]*)",
    re.IGNORECASE,
)
_installed_engines: set[int] = set()
_install_lock = threading.Lock()
_settings_cache: tuple[float, "TelemetrySettings"] | None = None
_settings_lock = threading.Lock()
_schema_ready = False
_schema_lock = threading.Lock()
_job_operations: dict[str, tuple["OperationContext", Token]] = {}
_job_lock = threading.Lock()


@dataclass(frozen=True)
class TelemetrySettings:
    enabled: bool = True
    capture_request_payloads: bool = True
    retain_normalized_sql: bool = True
    sql_min_duration_ms: float = 5.0
    slow_request_ms: float = 1000.0
    slow_sql_ms: float = 250.0
    max_sql_spans_per_operation: int = 200
    payload_max_bytes: int = 32768
    retention_days: int = 30


@dataclass
class SQLSpan:
    database_name: str
    occurred_at: datetime
    fingerprint: str
    statement_type: str
    table_names: list[str]
    normalized_sql: str | None
    duration_ms: float
    row_count: int | None
    success: bool = True
    error_type: str | None = None
    error_code: str | None = None


@dataclass
class OperationContext:
    operation_id: str
    operation_type: str
    started_at: datetime
    started_perf: float
    settings: TelemetrySettings
    spans: list[SQLSpan] = field(default_factory=list)
    sql_count: int = 0
    sql_duration_ms: float = 0.0
    dropped_sql_spans: int = 0
    error_type: str | None = None
    error_message: str | None = None


_current_operation: ContextVar[OperationContext | None] = ContextVar(
    "onebd_operations_context", default=None
)
_telemetry_suppressed: ContextVar[bool] = ContextVar(
    "onebd_telemetry_suppressed", default=False
)


DDL = (
    """
    CREATE TABLE IF NOT EXISTS operations_telemetry_schema_versions (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operations_telemetry_settings (
        singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        capture_request_payloads BOOLEAN NOT NULL DEFAULT TRUE,
        retain_normalized_sql BOOLEAN NOT NULL DEFAULT TRUE,
        sql_min_duration_ms DOUBLE PRECISION NOT NULL DEFAULT 5,
        slow_request_ms DOUBLE PRECISION NOT NULL DEFAULT 1000,
        slow_sql_ms DOUBLE PRECISION NOT NULL DEFAULT 250,
        max_sql_spans_per_operation INTEGER NOT NULL DEFAULT 200,
        payload_max_bytes INTEGER NOT NULL DEFAULT 32768,
        retention_days INTEGER NOT NULL DEFAULT 30,
        updated_by INTEGER,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (sql_min_duration_ms >= 0),
        CHECK (slow_request_ms >= 1),
        CHECK (slow_sql_ms >= 1),
        CHECK (max_sql_spans_per_operation BETWEEN 1 AND 5000),
        CHECK (payload_max_bytes BETWEEN 0 AND 1000000),
        CHECK (retention_days BETWEEN 1 AND 3650)
    )
    """,
    """
    INSERT INTO operations_telemetry_settings (singleton)
    VALUES (TRUE) ON CONFLICT (singleton) DO NOTHING
    """,
    """
    ALTER TABLE operations_telemetry_settings
    ALTER COLUMN sql_min_duration_ms SET DEFAULT 5
    """,
    """
    WITH applied AS (
        INSERT INTO operations_telemetry_schema_versions (version)
        VALUES (2)
        ON CONFLICT (version) DO NOTHING
        RETURNING version
    )
    UPDATE operations_telemetry_settings
    SET sql_min_duration_ms=5, updated_at=NOW()
    WHERE singleton=TRUE
      AND sql_min_duration_ms=0
      AND updated_by IS NULL
      AND EXISTS (SELECT 1 FROM applied)
    """,
    """
    CREATE TABLE IF NOT EXISTS operations_request_log (
        request_id UUID PRIMARY KEY,
        parent_request_id UUID,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ NOT NULL,
        duration_ms DOUBLE PRECISION NOT NULL,
        method VARCHAR(12) NOT NULL,
        path VARCHAR(1000) NOT NULL,
        route_template VARCHAR(1000),
        channel VARCHAR(30) NOT NULL,
        operation_names JSONB NOT NULL DEFAULT '[]'::jsonb,
        status_code INTEGER NOT NULL,
        principal_type VARCHAR(40),
        principal_id VARCHAR(100),
        principal_name VARCHAR(300),
        user_id INTEGER,
        client_ip VARCHAR(100),
        user_agent VARCHAR(500),
        request_bytes BIGINT,
        response_bytes BIGINT,
        request_metadata JSONB,
        sql_count INTEGER NOT NULL DEFAULT 0,
        sql_duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
        slow_sql_count INTEGER NOT NULL DEFAULT 0,
        dropped_sql_spans INTEGER NOT NULL DEFAULT 0,
        error_type VARCHAR(200),
        deployment_sha VARCHAR(80),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operations_sql_log (
        id BIGSERIAL PRIMARY KEY,
        operation_id VARCHAR(100) NOT NULL,
        operation_type VARCHAR(20) NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL,
        database_name VARCHAR(40) NOT NULL,
        fingerprint CHAR(64) NOT NULL,
        statement_type VARCHAR(30) NOT NULL,
        table_names TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
        normalized_sql TEXT,
        duration_ms DOUBLE PRECISION NOT NULL,
        row_count BIGINT,
        success BOOLEAN NOT NULL,
        error_type VARCHAR(200),
        error_code VARCHAR(50)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operations_job_log (
        task_id VARCHAR(100) PRIMARY KEY,
        task_name VARCHAR(300) NOT NULL,
        queue VARCHAR(100),
        worker VARCHAR(300),
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ NOT NULL,
        duration_ms DOUBLE PRECISION NOT NULL,
        status VARCHAR(40) NOT NULL,
        retries INTEGER NOT NULL DEFAULT 0,
        arguments JSONB,
        result_summary JSONB,
        sql_count INTEGER NOT NULL DEFAULT 0,
        sql_duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
        slow_sql_count INTEGER NOT NULL DEFAULT 0,
        dropped_sql_spans INTEGER NOT NULL DEFAULT 0,
        error_type VARCHAR(200),
        error_message VARCHAR(1000),
        deployment_sha VARCHAR(80),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operations_schema_snapshots (
        id BIGSERIAL PRIMARY KEY,
        database_name VARCHAR(40) NOT NULL,
        captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        database_bytes BIGINT,
        table_count INTEGER NOT NULL,
        index_count INTEGER NOT NULL,
        tables JSONB NOT NULL,
        database_metrics JSONB NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_operations_request_started ON operations_request_log (started_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_request_path_started ON operations_request_log (path, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_request_channel_started ON operations_request_log (channel, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_request_principal_started ON operations_request_log (principal_type, principal_id, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_request_parent ON operations_request_log (parent_request_id, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_operations_request_duration ON operations_request_log (duration_ms DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_sql_occurred ON operations_sql_log (occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_sql_operation ON operations_sql_log (operation_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS ix_operations_sql_fingerprint ON operations_sql_log (database_name, fingerprint, occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_sql_database_time ON operations_sql_log (database_name, occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_sql_duration ON operations_sql_log (duration_ms DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_job_started ON operations_job_log (started_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_job_name_started ON operations_job_log (task_name, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_operations_schema_database_time ON operations_schema_snapshots (database_name, captured_at DESC)",
)


def _deployment_sha() -> str | None:
    value = os.environ.get("GIT_COMMIT") or os.environ.get("BUILD_COMMIT")
    if value:
        return value.strip()[:80]
    try:
        with open("/app/BUILD_COMMIT", encoding="utf-8") as handle:
            return handle.read().strip()[:80]
    except OSError:
        return None


def ensure_operations_schema() -> None:
    """Verify the deployment migration installed the telemetry schema."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        token = _telemetry_suppressed.set(True)
        try:
            with get_cortellis_engine().connect() as connection:
                installed = connection.execute(text(
                    "SELECT to_regclass('public.operations_telemetry_settings') "
                    "IS NOT NULL"
                )).scalar()
            if not installed:
                raise RuntimeError(
                    "Operations telemetry schema is missing; run the runtime schema "
                    "migration before starting application processes"
                )
        finally:
            _telemetry_suppressed.reset(token)
        _schema_ready = True


def migrate_operations_schema() -> None:
    """Install or upgrade the telemetry schema during deployment."""
    global _schema_ready
    engine = get_cortellis_engine()
    token = _telemetry_suppressed.set(True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": SCHEMA_LOCK_ID},
            )
            for statement in DDL:
                connection.execute(text(statement))
        _schema_ready = True
    finally:
        _telemetry_suppressed.reset(token)


def _settings_from_row(row: Any) -> TelemetrySettings:
    values = dict(row)
    return TelemetrySettings(
        enabled=bool(values["enabled"]),
        capture_request_payloads=bool(values["capture_request_payloads"]),
        retain_normalized_sql=bool(values["retain_normalized_sql"]),
        sql_min_duration_ms=float(values["sql_min_duration_ms"]),
        slow_request_ms=float(values["slow_request_ms"]),
        slow_sql_ms=float(values["slow_sql_ms"]),
        max_sql_spans_per_operation=int(values["max_sql_spans_per_operation"]),
        payload_max_bytes=int(values["payload_max_bytes"]),
        retention_days=int(values["retention_days"]),
    )


def get_telemetry_settings(*, force: bool = False) -> TelemetrySettings:
    global _settings_cache
    now = time.monotonic()
    with _settings_lock:
        if not force and _settings_cache and now - _settings_cache[0] < 30:
            return _settings_cache[1]
    try:
        ensure_operations_schema()
        token = _telemetry_suppressed.set(True)
        try:
            with get_cortellis_engine().connect() as connection:
                row = connection.execute(text("""
                    SELECT enabled, capture_request_payloads,
                           retain_normalized_sql, sql_min_duration_ms,
                           slow_request_ms, slow_sql_ms,
                           max_sql_spans_per_operation, payload_max_bytes,
                           retention_days
                    FROM operations_telemetry_settings WHERE singleton=TRUE
                """)).mappings().one()
        finally:
            _telemetry_suppressed.reset(token)
        settings = _settings_from_row(row)
    except Exception as exc:
        logger.warning("operations_settings_unavailable", error_type=type(exc).__name__)
        settings = TelemetrySettings()
    with _settings_lock:
        _settings_cache = (now, settings)
    return settings


def update_telemetry_settings(values: dict[str, Any], updated_by: int) -> dict[str, Any]:
    global _settings_cache
    ensure_operations_schema()
    allowed = {
        "enabled",
        "capture_request_payloads",
        "retain_normalized_sql",
        "sql_min_duration_ms",
        "slow_request_ms",
        "slow_sql_ms",
        "max_sql_spans_per_operation",
        "payload_max_bytes",
        "retention_days",
    }
    if set(values) != allowed:
        raise ValueError("Complete telemetry settings document is required")
    token = _telemetry_suppressed.set(True)
    try:
        with get_cortellis_engine().begin() as connection:
            row = connection.execute(text("""
                UPDATE operations_telemetry_settings SET
                  enabled=:enabled,
                  capture_request_payloads=:capture_request_payloads,
                  retain_normalized_sql=:retain_normalized_sql,
                  sql_min_duration_ms=:sql_min_duration_ms,
                  slow_request_ms=:slow_request_ms,
                  slow_sql_ms=:slow_sql_ms,
                  max_sql_spans_per_operation=:max_sql_spans_per_operation,
                  payload_max_bytes=:payload_max_bytes,
                  retention_days=:retention_days,
                  updated_by=:updated_by,
                  updated_at=NOW()
                WHERE singleton=TRUE
                RETURNING *
            """), {**values, "updated_by": updated_by}).mappings().one()
    finally:
        _telemetry_suppressed.reset(token)
    updated_settings = _settings_from_row(row)
    with _settings_lock:
        _settings_cache = (time.monotonic(), updated_settings)
    return asdict(updated_settings)


def sanitize_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Bound and redact request/task material before durable storage."""
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if depth > 6:
        return "[MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:500] + "…"
    if isinstance(value, dict):
        return {
            str(item_key)[:100]: sanitize_value(
                item_value, key=str(item_key), depth=depth + 1
            )
            for item_key, item_value in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_value(item, depth=depth + 1) for item in list(value)[:100]]
    return sanitize_value(str(value), key=key, depth=depth + 1)


def sanitize_sql(statement: str) -> tuple[str, str, list[str], str]:
    """Return a value-free query shape, hash, referenced tables, and type."""
    cleaned = _SQL_COMMENT.sub(" ", statement or "")
    cleaned = _SQL_DOLLAR_STRING.sub("$?$", cleaned)
    cleaned = _SQL_STRING.sub("'?'", cleaned)
    cleaned = _SQL_NUMBER.sub("?", cleaned)
    cleaned = " ".join(cleaned.split())[:20000]
    fingerprint = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    first = cleaned.split(" ", 1)[0].upper() if cleaned else "UNKNOWN"
    tables = sorted({match.group(1).lower()[:200] for match in _SQL_TABLE.finditer(cleaned)})
    return cleaned, fingerprint, tables[:50], first[:30]


def _record_span(
    database_name: str,
    statement: str,
    started: float,
    cursor: Any,
    *,
    success: bool,
    error: BaseException | None = None,
) -> None:
    operation = _current_operation.get()
    if operation is None or _telemetry_suppressed.get() or not operation.settings.enabled:
        return
    duration_ms = (time.perf_counter() - started) * 1000
    operation.sql_count += 1
    operation.sql_duration_ms += duration_ms
    if success and duration_ms < operation.settings.sql_min_duration_ms:
        return
    if len(operation.spans) >= operation.settings.max_sql_spans_per_operation:
        operation.dropped_sql_spans += 1
        return
    normalized, fingerprint, tables, statement_type = sanitize_sql(statement)
    row_count = getattr(cursor, "rowcount", None)
    if not isinstance(row_count, int) or row_count < 0:
        row_count = None
    original = getattr(error, "orig", error)
    error_code = None
    if original is not None:
        error_code = getattr(original, "pgcode", None) or getattr(
            original, "sqlstate", None
        )
    operation.spans.append(SQLSpan(
        database_name=database_name,
        occurred_at=datetime.now(timezone.utc),
        fingerprint=fingerprint,
        statement_type=statement_type,
        table_names=tables,
        normalized_sql=(normalized if operation.settings.retain_normalized_sql else None),
        duration_ms=round(duration_ms, 3),
        row_count=row_count,
        success=success,
        error_type=type(original).__name__ if original is not None else None,
        error_code=str(error_code)[:50] if error_code else None,
    ))


def install_sqlalchemy_telemetry(engine: Any, database_name: str) -> None:
    """Attach SQL duration/error listeners to an engine once per process."""
    engine_id = id(engine)
    with _install_lock:
        if engine_id in _installed_engines:
            return
        _installed_engines.add(engine_id)

    def before_cursor_execute(_conn, _cursor, statement, _params, context, _many):
        if _current_operation.get() is not None and not _telemetry_suppressed.get():
            context._onebd_telemetry_start = time.perf_counter()
            context._onebd_telemetry_statement = statement

    def after_cursor_execute(_conn, cursor, statement, _params, context, _many):
        started = getattr(context, "_onebd_telemetry_start", None)
        if started is not None:
            _record_span(database_name, statement, started, cursor, success=True)
            context._onebd_telemetry_start = None

    def handle_error(exception_context):
        context = exception_context.execution_context
        started = getattr(context, "_onebd_telemetry_start", None) if context else None
        if started is not None:
            _record_span(
                database_name,
                getattr(context, "_onebd_telemetry_statement", ""),
                started,
                getattr(context, "cursor", None),
                success=False,
                error=exception_context.original_exception,
            )
            context._onebd_telemetry_start = None

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    event.listen(engine, "handle_error", handle_error)


def install_default_sql_telemetry() -> None:
    install_sqlalchemy_telemetry(get_cortellis_engine(), "cortellis")
    install_sqlalchemy_telemetry(get_edgar_source_engine(), "edgar")


def start_operation(operation_type: str, operation_id: str | None = None):
    settings = get_telemetry_settings()
    operation = OperationContext(
        operation_id=operation_id or str(uuid4()),
        operation_type=operation_type,
        started_at=datetime.now(timezone.utc),
        started_perf=time.perf_counter(),
        settings=settings,
    )
    return operation, _current_operation.set(operation)


def current_operation() -> OperationContext | None:
    return _current_operation.get()


def mark_current_operation_error(error: BaseException) -> None:
    """Mark a caught semantic failure on the active request or job operation."""
    operation = current_operation()
    if operation is None:
        return
    original = getattr(error, "orig", error)
    operation.error_type = type(original).__name__
    operation.error_message = str(original)[:1000]


def _sql_rows(operation: OperationContext) -> list[dict[str, Any]]:
    return [
        {
            "operation_id": operation.operation_id,
            "operation_type": operation.operation_type,
            "occurred_at": span.occurred_at,
            "database_name": span.database_name,
            "fingerprint": span.fingerprint,
            "statement_type": span.statement_type,
            "table_names": span.table_names,
            "normalized_sql": span.normalized_sql,
            "duration_ms": span.duration_ms,
            "row_count": span.row_count,
            "success": span.success,
            "error_type": span.error_type,
            "error_code": span.error_code,
        }
        for span in operation.spans
    ]


def _persist_sql(connection: Any, operation: OperationContext) -> None:
    rows = _sql_rows(operation)
    if rows:
        connection.execute(text("""
            INSERT INTO operations_sql_log (
              operation_id, operation_type, occurred_at, database_name,
              fingerprint, statement_type, table_names, normalized_sql,
              duration_ms, row_count, success, error_type, error_code
            ) VALUES (
              :operation_id, :operation_type, :occurred_at, :database_name,
              :fingerprint, :statement_type, :table_names, :normalized_sql,
              :duration_ms, :row_count, :success, :error_type, :error_code
            )
        """), rows)


def persist_request(operation: OperationContext, record: dict[str, Any]) -> None:
    """Write one request plus its captured SQL spans as a single transaction."""
    if not operation.settings.enabled:
        return
    duration_ms = (time.perf_counter() - operation.started_perf) * 1000
    slow_sql = sum(
        span.duration_ms >= operation.settings.slow_sql_ms for span in operation.spans
    )
    token = _telemetry_suppressed.set(True)
    try:
        with get_cortellis_engine().begin() as connection:
            connection.execute(text("""
                INSERT INTO operations_request_log (
                  request_id, parent_request_id, started_at, finished_at,
                  duration_ms, method, path, route_template, channel,
                  operation_names, status_code, principal_type, principal_id,
                  principal_name, user_id, client_ip, user_agent, request_bytes,
                  response_bytes, request_metadata, sql_count, sql_duration_ms,
                  slow_sql_count, dropped_sql_spans, error_type, deployment_sha
                ) VALUES (
                  CAST(:request_id AS UUID), CAST(:parent_request_id AS UUID),
                  :started_at, :finished_at, :duration_ms, :method, :path,
                  :route_template, :channel, CAST(:operation_names AS JSONB),
                  :status_code, :principal_type, :principal_id, :principal_name,
                  :user_id, :client_ip, :user_agent, :request_bytes,
                  :response_bytes, CAST(:request_metadata AS JSONB), :sql_count,
                  :sql_duration_ms, :slow_sql_count, :dropped_sql_spans,
                  :error_type, :deployment_sha
                ) ON CONFLICT (request_id) DO NOTHING
            """), {
                **record,
                "request_id": operation.operation_id,
                "started_at": operation.started_at,
                "finished_at": datetime.now(timezone.utc),
                "duration_ms": round(duration_ms, 3),
                "operation_names": json.dumps(record.get("operation_names") or []),
                "request_metadata": json.dumps(record.get("request_metadata")),
                "sql_count": operation.sql_count,
                "sql_duration_ms": round(operation.sql_duration_ms, 3),
                "slow_sql_count": slow_sql,
                "dropped_sql_spans": operation.dropped_sql_spans,
                "deployment_sha": _deployment_sha(),
            })
            _persist_sql(connection, operation)
    except Exception as exc:
        logger.error(
            "operations_request_persist_failed",
            error_type=type(exc).__name__,
            path=record.get("path"),
        )
    finally:
        _telemetry_suppressed.reset(token)


def _client_ip(scope: dict[str, Any]) -> str | None:
    headers = {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in scope.get("headers", [])
    }
    for name in ("cf-connecting-ip", "x-real-ip"):
        if headers.get(name):
            return headers[name][:100]
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:100]
    client = scope.get("client")
    return str(client[0])[:100] if client else None


def _request_metadata(
    scope: dict[str, Any], body: bytes, settings: TelemetrySettings
) -> dict[str, Any] | None:
    query = parse_qs(scope.get("query_string", b"").decode("utf-8", "replace"))
    metadata: dict[str, Any] = {
        "query": sanitize_value({key: value for key, value in query.items()})
    }
    if not settings.capture_request_payloads:
        return metadata
    headers = {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in scope.get("headers", [])
    }
    content_type = headers.get("content-type", "").split(";", 1)[0].lower()
    if body and len(body) <= settings.payload_max_bytes and content_type == "application/json":
        try:
            metadata["body"] = sanitize_value(json.loads(body))
        except (json.JSONDecodeError, UnicodeDecodeError):
            metadata["body"] = {"unparsed_bytes": len(body)}
    elif body:
        metadata["body"] = {
            "bytes": len(body),
            "retained": False,
            "reason": "capture disabled, non-JSON, or size limit",
        }
    return metadata


class OperationsTelemetryMiddleware:
    """Pure-ASGI request capture that does not consume downstream request bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") in {"/live", "/ready"}:
            await self.app(scope, receive, send)
            return
        parent_operation = current_operation()
        operation, token = start_operation("request")
        state = scope.setdefault("state", {})
        state["telemetry_request_id"] = operation.operation_id
        if parent_operation and parent_operation.operation_type == "request":
            state["telemetry_parent_request_id"] = parent_operation.operation_id
        body_parts: list[bytes] = []
        body_bytes = 0
        response_bytes = 0
        status_code = 500
        error_type = None

        async def capture_receive():
            nonlocal body_bytes
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"")
                body_bytes += len(chunk)
                if sum(len(item) for item in body_parts) < operation.settings.payload_max_bytes:
                    remaining = operation.settings.payload_max_bytes - sum(
                        len(item) for item in body_parts
                    )
                    body_parts.append(chunk[:remaining])
            return message

        async def capture_send(message):
            nonlocal response_bytes, status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", operation.operation_id.encode("ascii")))
                message["headers"] = headers
            elif message.get("type") == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, capture_receive, capture_send)
        except Exception as exc:
            error_type = type(exc).__name__
            operation.error_type = error_type
            raise
        finally:
            try:
                headers = {
                    key.decode("latin1").lower(): value.decode("latin1")
                    for key, value in scope.get("headers", [])
                }
                principal = state.get("data_principal")
                user_id = state.get("user_id")
                if principal is None:
                    auth = headers.get("authorization", "")
                    if auth.startswith("Bearer "):
                        try:
                            from unified_api.services.auth import decode_token

                            token_data = decode_token(auth.split(" ", 1)[1])
                            if token_data:
                                user_id = token_data.user_id
                                principal = type("Principal", (), {
                                    "principal_type": "user",
                                    "principal_id": str(token_data.user_id),
                                    "name": getattr(token_data, "email", None)
                                    or f"user:{token_data.user_id}",
                                })()
                        except Exception:
                            pass
                parent = state.get("telemetry_parent_request_id")
                route = scope.get("route")
                persist_request(operation, {
                    "parent_request_id": parent,
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "route_template": getattr(route, "path", None),
                    "channel": state.get("telemetry_channel")
                    or ("api" if scope.get("path", "").startswith("/api") else "http"),
                    "operation_names": state.get("telemetry_operation_names") or [],
                    "status_code": status_code,
                    "principal_type": getattr(principal, "principal_type", None),
                    "principal_id": getattr(principal, "principal_id", None),
                    "principal_name": getattr(principal, "name", None),
                    "user_id": user_id,
                    "client_ip": _client_ip(scope),
                    "user_agent": headers.get("user-agent", "")[:500] or None,
                    "request_bytes": body_bytes,
                    "response_bytes": response_bytes,
                    "request_metadata": _request_metadata(
                        scope, b"".join(body_parts), operation.settings
                    ),
                    "error_type": (
                        state.get("telemetry_error_type")
                        or error_type
                        or operation.error_type
                    ),
                })
            finally:
                _current_operation.reset(token)


def start_job_operation(
    task_id: str,
    task_name: str,
    *,
    args: Any,
    kwargs: Any,
) -> OperationContext:
    operation, token = start_operation("job", operation_id=task_id)
    operation.task_name = task_name
    operation.arguments = sanitize_value({"args": args, "kwargs": kwargs})
    with _job_lock:
        _job_operations[task_id] = (operation, token)
    return operation


def mark_job_failure(task_id: str, error: BaseException) -> None:
    with _job_lock:
        item = _job_operations.get(task_id)
    if item:
        operation = item[0]
        operation.error_type = type(error).__name__
        operation.error_message = str(error)[:1000]


def finish_job_operation(
    task_id: str,
    *,
    status: str,
    task: Any = None,
    result: Any = None,
) -> None:
    with _job_lock:
        item = _job_operations.pop(task_id, None)
    if not item:
        return
    operation, token = item
    if not operation.settings.enabled:
        _current_operation.reset(token)
        return
    duration_ms = (time.perf_counter() - operation.started_perf) * 1000
    slow_sql = sum(
        span.duration_ms >= operation.settings.slow_sql_ms for span in operation.spans
    )
    request = getattr(task, "request", None)
    delivery = getattr(request, "delivery_info", {}) or {}
    worker = getattr(request, "hostname", None)
    retries = int(getattr(request, "retries", 0) or 0)
    result_summary = sanitize_value(result)
    token_suppressed = _telemetry_suppressed.set(True)
    try:
        with get_cortellis_engine().begin() as connection:
            connection.execute(text("""
                INSERT INTO operations_job_log (
                  task_id, task_name, queue, worker, started_at, finished_at,
                  duration_ms, status, retries, arguments, result_summary,
                  sql_count, sql_duration_ms, slow_sql_count, dropped_sql_spans,
                  error_type, error_message, deployment_sha
                ) VALUES (
                  :task_id, :task_name, :queue, :worker, :started_at,
                  :finished_at, :duration_ms, :status, :retries,
                  CAST(:arguments AS JSONB), CAST(:result_summary AS JSONB),
                  :sql_count, :sql_duration_ms, :slow_sql_count,
                  :dropped_sql_spans, :error_type, :error_message,
                  :deployment_sha
                ) ON CONFLICT (task_id) DO UPDATE SET
                  finished_at=EXCLUDED.finished_at,
                  duration_ms=EXCLUDED.duration_ms,
                  status=EXCLUDED.status,
                  retries=EXCLUDED.retries,
                  result_summary=EXCLUDED.result_summary,
                  sql_count=EXCLUDED.sql_count,
                  sql_duration_ms=EXCLUDED.sql_duration_ms,
                  slow_sql_count=EXCLUDED.slow_sql_count,
                  dropped_sql_spans=EXCLUDED.dropped_sql_spans,
                  error_type=EXCLUDED.error_type,
                  error_message=EXCLUDED.error_message
            """), {
                "task_id": task_id,
                "task_name": getattr(operation, "task_name", "unknown"),
                "queue": delivery.get("routing_key") or delivery.get("exchange"),
                "worker": worker,
                "started_at": operation.started_at,
                "finished_at": datetime.now(timezone.utc),
                "duration_ms": round(duration_ms, 3),
                "status": status,
                "retries": retries,
                "arguments": json.dumps(getattr(operation, "arguments", None)),
                "result_summary": json.dumps(result_summary),
                "sql_count": operation.sql_count,
                "sql_duration_ms": round(operation.sql_duration_ms, 3),
                "slow_sql_count": slow_sql,
                "dropped_sql_spans": operation.dropped_sql_spans,
                "error_type": operation.error_type,
                "error_message": operation.error_message,
                "deployment_sha": _deployment_sha(),
            })
            _persist_sql(connection, operation)
    except Exception as exc:
        logger.error(
            "operations_job_persist_failed",
            task_name=getattr(operation, "task_name", "unknown"),
            error_type=type(exc).__name__,
        )
    finally:
        _telemetry_suppressed.reset(token_suppressed)
        _current_operation.reset(token)


def cleanup_telemetry(retention_days: int | None = None) -> dict[str, int]:
    settings = get_telemetry_settings(force=True)
    days = int(retention_days or settings.retention_days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    token = _telemetry_suppressed.set(True)
    deleted: dict[str, int] = {}
    try:
        with get_cortellis_engine().begin() as connection:
            for table, field in (
                ("operations_sql_log", "occurred_at"),
                ("operations_request_log", "started_at"),
                ("operations_job_log", "started_at"),
                ("operations_schema_snapshots", "captured_at"),
            ):
                result = connection.execute(
                    text(f"DELETE FROM {table} WHERE {field} < :cutoff"),
                    {"cutoff": cutoff},
                )
                deleted[table] = int(result.rowcount or 0)
    finally:
        _telemetry_suppressed.reset(token)
    return deleted


def _database_snapshot(engine: Any, database_name: str) -> dict[str, Any]:
    with engine.connect() as connection:
        database_bytes = connection.execute(
            text("SELECT pg_database_size(current_database())")
        ).scalar()
        tables = [dict(row) for row in connection.execute(text("""
            SELECT table_schema AS schema_name, table_name,
                   pg_total_relation_size(format('%I.%I', table_schema, table_name))
                     AS total_bytes,
                   pg_relation_size(format('%I.%I', table_schema, table_name))
                     AS table_bytes,
                   pg_indexes_size(format('%I.%I', table_schema, table_name))
                     AS index_bytes
            FROM information_schema.tables
            WHERE table_type='BASE TABLE'
              AND table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY total_bytes DESC
        """)).mappings().all()]
        index_count = connection.execute(text("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        """)).scalar()
        metrics = dict(connection.execute(text("""
            SELECT numbackends, xact_commit, xact_rollback,
                   blks_read, blks_hit, tup_returned, tup_fetched,
                   tup_inserted, tup_updated, tup_deleted,
                   temp_files, temp_bytes, deadlocks
            FROM pg_stat_database WHERE datname=current_database()
        """)).mappings().one())
    return {
        "database_name": database_name,
        "database_bytes": int(database_bytes or 0),
        "table_count": len(tables),
        "index_count": int(index_count or 0),
        "tables": tables,
        "database_metrics": metrics,
    }


def capture_schema_snapshots_if_due(*, force: bool = False) -> list[dict[str, Any]]:
    """Capture compact daily database/schema size history for trend analysis."""
    ensure_operations_schema()
    token = _telemetry_suppressed.set(True)
    captured: list[dict[str, Any]] = []
    try:
        with get_cortellis_engine().connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as lock_connection:
            acquired = bool(lock_connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": SNAPSHOT_LOCK_ID},
            ).scalar())
            if not acquired:
                return []
            try:
                if not force:
                    recent = lock_connection.execute(text("""
                        SELECT COUNT(DISTINCT database_name)
                        FROM operations_schema_snapshots
                        WHERE captured_at >= NOW() - INTERVAL '23 hours'
                    """)).scalar()
                    if int(recent or 0) >= 2:
                        return []
                for engine, name in (
                    (get_cortellis_engine(), "cortellis"),
                    (get_edgar_source_engine(), "edgar"),
                ):
                    if not force:
                        already_captured = lock_connection.execute(text("""
                            SELECT EXISTS (
                              SELECT 1 FROM operations_schema_snapshots
                              WHERE database_name=:database_name
                                AND captured_at >= NOW() - INTERVAL '23 hours'
                            )
                        """), {"database_name": name}).scalar()
                        if already_captured:
                            continue
                    try:
                        snapshot = _database_snapshot(engine, name)
                    except Exception as exc:
                        logger.warning(
                            "operations_schema_snapshot_failed",
                            database_name=name,
                            error_type=type(exc).__name__,
                        )
                        continue
                    with get_cortellis_engine().begin() as connection:
                        connection.execute(text("""
                            INSERT INTO operations_schema_snapshots (
                              database_name, database_bytes, table_count,
                              index_count, tables, database_metrics
                            ) VALUES (
                              :database_name, :database_bytes, :table_count,
                              :index_count, CAST(:tables AS JSONB),
                              CAST(:database_metrics AS JSONB)
                            )
                        """), {
                            **snapshot,
                            "tables": json.dumps(snapshot["tables"], default=str),
                            "database_metrics": json.dumps(
                                snapshot["database_metrics"], default=str
                            ),
                        })
                    captured.append(snapshot)
            finally:
                lock_connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": SNAPSHOT_LOCK_ID},
                )
    finally:
        _telemetry_suppressed.reset(token)
    return captured
