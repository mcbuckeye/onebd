"""Read models for the administrator-facing Operations console."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from unified_api.services.database import (
    get_cortellis_engine,
    get_edgar_source_engine,
)
from unified_api.services.operations_telemetry import (
    ensure_operations_schema,
    get_telemetry_settings,
    sanitize_sql,
)


def _rows(result) -> list[dict[str, Any]]:
    return [dict(row) for row in result.mappings().all()]


def operations_summary(hours: int) -> dict[str, Any]:
    ensure_operations_schema()
    settings = get_telemetry_settings()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with get_cortellis_engine().connect() as connection:
        request = dict(connection.execute(text("""
            SELECT COUNT(*)::bigint AS requests,
                   COUNT(*) FILTER (
                     WHERE status_code >= 400 OR error_type IS NOT NULL
                   )::bigint AS errors,
                   COUNT(*) FILTER (WHERE duration_ms >= :slow_request_ms)::bigint
                     AS slow_requests,
                   AVG(duration_ms) AS average_ms,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms)
                     AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                     AS p95_ms,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms)
                     AS p99_ms,
                   SUM(sql_count)::bigint AS sql_calls,
                   SUM(sql_duration_ms) AS sql_time_ms,
                   SUM(dropped_sql_spans)::bigint AS dropped_sql_spans,
                   COUNT(DISTINCT NULLIF(principal_type || ':' || principal_id, ':'))
                     AS principals
            FROM operations_request_log WHERE started_at >= :since
        """), {
            "since": since,
            "slow_request_ms": settings.slow_request_ms,
        }).mappings().one())
        jobs = dict(connection.execute(text("""
            SELECT COUNT(*)::bigint AS jobs,
                   COUNT(*) FILTER (WHERE status NOT IN ('SUCCESS', 'success'))::bigint
                     AS unsuccessful_jobs,
                   AVG(duration_ms) AS average_ms,
                   MAX(duration_ms) AS maximum_ms,
                   SUM(sql_count)::bigint AS sql_calls
            FROM operations_job_log WHERE started_at >= :since
        """), {"since": since}).mappings().one())
        by_channel = _rows(connection.execute(text("""
            SELECT channel, COUNT(*)::bigint AS requests,
                   COUNT(*) FILTER (
                     WHERE status_code >= 400 OR error_type IS NOT NULL
                   )::bigint AS errors,
                   AVG(duration_ms) AS average_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                     AS p95_ms
            FROM operations_request_log WHERE started_at >= :since
            GROUP BY channel ORDER BY requests DESC
        """), {"since": since}))
        slow_routes = _rows(connection.execute(text("""
            SELECT COALESCE(route_template, path) AS route, method,
                   COUNT(*)::bigint AS calls,
                   AVG(duration_ms) AS average_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                     AS p95_ms,
                   MAX(duration_ms) AS maximum_ms,
                   SUM(sql_duration_ms) AS sql_time_ms,
                   COUNT(*) FILTER (
                     WHERE status_code >= 400 OR error_type IS NOT NULL
                   )::bigint AS errors
            FROM operations_request_log WHERE started_at >= :since
            GROUP BY COALESCE(route_template, path), method
            ORDER BY p95_ms DESC NULLS LAST LIMIT 12
        """), {"since": since}))
        hourly = _rows(connection.execute(text("""
            SELECT date_trunc('hour', started_at) AS bucket,
                   COUNT(*)::bigint AS requests,
                   COUNT(*) FILTER (
                     WHERE status_code >= 400 OR error_type IS NOT NULL
                   )::bigint AS errors,
                   AVG(duration_ms) AS average_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                     AS p95_ms
            FROM operations_request_log WHERE started_at >= :since
            GROUP BY bucket ORDER BY bucket
        """), {"since": since}))
        recent_errors = _rows(connection.execute(text("""
            SELECT request_id, started_at, method, path, channel, status_code,
                   duration_ms, principal_type, principal_name, error_type
            FROM operations_request_log
            WHERE started_at >= :since
              AND (status_code >= 400 OR error_type IS NOT NULL)
            ORDER BY started_at DESC LIMIT 10
        """), {"since": since}))
    request["error_rate"] = (
        float(request["errors"] or 0) / float(request["requests"] or 1)
    )
    return {
        "hours": hours,
        "since": since,
        "slow_request_ms": settings.slow_request_ms,
        "slow_sql_ms": settings.slow_sql_ms,
        "requests": request,
        "jobs": jobs,
        "by_channel": by_channel,
        "slow_routes": slow_routes,
        "hourly": hourly,
        "recent_errors": recent_errors,
    }


def list_operation_requests(
    *,
    hours: int,
    channel: str | None,
    path: str | None,
    principal: str | None,
    status: str | None,
    min_duration_ms: float | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    ensure_operations_schema()
    filters = ["started_at >= :since"]
    params: dict[str, Any] = {
        "since": datetime.now(timezone.utc) - timedelta(hours=hours),
        "limit": limit,
        "offset": offset,
    }
    if channel:
        filters.append("channel=:channel")
        params["channel"] = channel
    if path:
        filters.append("path ILIKE :path")
        params["path"] = f"%{path}%"
    if principal:
        filters.append(
            "(principal_name ILIKE :principal OR principal_id ILIKE :principal)"
        )
        params["principal"] = f"%{principal}%"
    if status == "errors":
        filters.append("(status_code >= 400 OR error_type IS NOT NULL)")
    elif status == "success":
        filters.append("status_code < 400 AND error_type IS NULL")
    if min_duration_ms is not None:
        filters.append("duration_ms >= :min_duration_ms")
        params["min_duration_ms"] = min_duration_ms
    where = " AND ".join(filters)
    with get_cortellis_engine().connect() as connection:
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM operations_request_log WHERE {where}"),
            params,
        ).scalar()
        items = _rows(connection.execute(text(f"""
            SELECT request_id, parent_request_id, started_at, finished_at,
                   duration_ms, method, path, route_template, channel,
                   operation_names, status_code, principal_type, principal_id,
                   principal_name, user_id, client_ip, user_agent,
                   request_bytes, response_bytes, sql_count, sql_duration_ms,
                   slow_sql_count, dropped_sql_spans, error_type, deployment_sha
            FROM operations_request_log WHERE {where}
            ORDER BY started_at DESC LIMIT :limit OFFSET :offset
        """), params))
    return {"items": items, "total": int(total or 0), "limit": limit, "offset": offset}


def operation_request_detail(request_id: str) -> dict[str, Any] | None:
    ensure_operations_schema()
    with get_cortellis_engine().connect() as connection:
        request = connection.execute(text("""
            SELECT * FROM operations_request_log
            WHERE request_id=CAST(:request_id AS UUID)
        """), {"request_id": request_id}).mappings().first()
        if not request:
            return None
        sql = _rows(connection.execute(text("""
            SELECT id, occurred_at, database_name, fingerprint,
                   statement_type, table_names, normalized_sql, duration_ms,
                   row_count, success, error_type, error_code
            FROM operations_sql_log
            WHERE operation_type='request' AND operation_id=:request_id
            ORDER BY occurred_at, id
        """), {"request_id": request_id}))
        children = _rows(connection.execute(text("""
            SELECT request_id, started_at, duration_ms, method, path, channel,
                   operation_names, status_code, sql_count, sql_duration_ms
            FROM operations_request_log
            WHERE parent_request_id=CAST(:request_id AS UUID)
            ORDER BY started_at
        """), {"request_id": request_id}))
    return {"request": dict(request), "sql": sql, "child_requests": children}


def aggregate_sql(
    *,
    hours: int,
    database_name: str | None,
    search: str | None,
    min_duration_ms: float | None,
    errors_only: bool,
    sort: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    ensure_operations_schema()
    filters = ["occurred_at >= :since"]
    params: dict[str, Any] = {
        "since": datetime.now(timezone.utc) - timedelta(hours=hours),
        "limit": limit,
        "offset": offset,
    }
    if database_name:
        filters.append("database_name=:database_name")
        params["database_name"] = database_name
    if search:
        filters.append(
            "(normalized_sql ILIKE :search OR :table_name = ANY(table_names) "
            "OR fingerprint ILIKE :search_prefix)"
        )
        params["search"] = f"%{search}%"
        params["table_name"] = search.lower()
        params["search_prefix"] = f"{search}%"
    if min_duration_ms is not None:
        filters.append("duration_ms >= :min_duration_ms")
        params["min_duration_ms"] = min_duration_ms
    if errors_only:
        filters.append("success=FALSE")
    order = {
        "total": "total_ms DESC",
        "average": "average_ms DESC",
        "maximum": "maximum_ms DESC",
        "calls": "calls DESC",
        "errors": "errors DESC, total_ms DESC",
    }.get(sort, "total_ms DESC")
    where = " AND ".join(filters)
    with get_cortellis_engine().connect() as connection:
        total = connection.execute(text(f"""
            SELECT COUNT(*) FROM (
              SELECT 1 FROM operations_sql_log WHERE {where}
              GROUP BY database_name, fingerprint, statement_type
            ) grouped
        """), params).scalar()
        items = _rows(connection.execute(text(f"""
            SELECT database_name, fingerprint, statement_type,
                   MAX(normalized_sql) AS normalized_sql,
                   STRING_TO_ARRAY(
                     STRING_AGG(
                       DISTINCT NULLIF(array_to_string(table_names, ','), ''), ','
                     ),
                     ','
                   ) AS table_names,
                   COUNT(*)::bigint AS calls,
                   COUNT(DISTINCT operation_id)::bigint AS operations,
                   SUM(duration_ms) AS total_ms,
                   AVG(duration_ms) AS average_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                     AS p95_ms,
                   MAX(duration_ms) AS maximum_ms,
                   SUM(COALESCE(row_count, 0))::bigint AS rows,
                   COUNT(*) FILTER (WHERE NOT success)::bigint AS errors,
                   MIN(occurred_at) AS first_seen_at,
                   MAX(occurred_at) AS last_seen_at
            FROM operations_sql_log
            WHERE {where}
            GROUP BY database_name, fingerprint, statement_type
            ORDER BY {order} LIMIT :limit OFFSET :offset
        """), params))
    return {"items": items, "total": int(total or 0), "limit": limit, "offset": offset}


def list_operation_jobs(
    *,
    hours: int,
    status: str | None,
    task_name: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    ensure_operations_schema()
    filters = ["started_at >= :since"]
    params: dict[str, Any] = {
        "since": datetime.now(timezone.utc) - timedelta(hours=hours),
        "limit": limit,
        "offset": offset,
    }
    if status:
        filters.append("LOWER(status)=LOWER(:status)")
        params["status"] = status
    if task_name:
        filters.append("task_name ILIKE :task_name")
        params["task_name"] = f"%{task_name}%"
    where = " AND ".join(filters)
    with get_cortellis_engine().connect() as connection:
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM operations_job_log WHERE {where}"), params
        ).scalar()
        items = _rows(connection.execute(text(f"""
            SELECT * FROM operations_job_log WHERE {where}
            ORDER BY started_at DESC LIMIT :limit OFFSET :offset
        """), params))
    return {"items": items, "total": int(total or 0), "limit": limit, "offset": offset}


def operation_job_detail(task_id: str) -> dict[str, Any] | None:
    ensure_operations_schema()
    with get_cortellis_engine().connect() as connection:
        job = connection.execute(
            text("SELECT * FROM operations_job_log WHERE task_id=:task_id"),
            {"task_id": task_id},
        ).mappings().first()
        if not job:
            return None
        sql = _rows(connection.execute(text("""
            SELECT * FROM operations_sql_log
            WHERE operation_type='job' AND operation_id=:task_id
            ORDER BY occurred_at, id
        """), {"task_id": task_id}))
    return {"job": dict(job), "sql": sql}


def _database_detail(engine: Any, name: str) -> dict[str, Any]:
    with engine.connect() as connection:
        overview = dict(connection.execute(text("""
            SELECT current_database() AS database,
                   pg_database_size(current_database()) AS database_bytes,
                   numbackends, xact_commit, xact_rollback, blks_read, blks_hit,
                   CASE WHEN blks_hit + blks_read > 0
                     THEN blks_hit::float / (blks_hit + blks_read) ELSE NULL END
                     AS cache_hit_ratio,
                   tup_returned, tup_fetched, tup_inserted, tup_updated,
                   tup_deleted, conflicts, temp_files, temp_bytes, deadlocks,
                   stats_reset
            FROM pg_stat_database WHERE datname=current_database()
        """)).mappings().one())
        settings = dict(connection.execute(text("""
            SELECT current_setting('server_version') AS server_version,
                   current_setting('shared_preload_libraries') AS preload,
                   current_setting('track_io_timing') AS track_io_timing,
                   current_setting('log_min_duration_statement')
                     AS log_min_duration_statement,
                   current_setting('logging_collector') AS logging_collector,
                   current_setting('max_connections')::int AS max_connections
        """)).mappings().one())
        connections = dict(connection.execute(text("""
            SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE state='active')::int AS active,
                   COUNT(*) FILTER (WHERE state='idle')::int AS idle,
                   COUNT(*) FILTER (
                     WHERE wait_event IS NOT NULL
                       AND wait_event_type <> 'Client')::int AS waiting
            FROM pg_stat_activity WHERE datname=current_database()
        """)).mappings().one())
        tables = _rows(connection.execute(text("""
            SELECT schemaname AS schema_name, relname AS table_name,
                   n_live_tup, n_dead_tup, seq_scan, seq_tup_read,
                   idx_scan, idx_tup_fetch, n_tup_ins, n_tup_upd, n_tup_del,
                   last_vacuum, last_autovacuum, last_analyze,
                   last_autoanalyze,
                   pg_total_relation_size(relid) AS total_bytes,
                   pg_relation_size(relid) AS table_bytes,
                   pg_indexes_size(relid) AS index_bytes
            FROM pg_stat_user_tables
            ORDER BY total_bytes DESC LIMIT 150
        """)))
        indexes = _rows(connection.execute(text("""
            SELECT stats.schemaname AS schema_name,
                   stats.relname AS table_name,
                   stats.indexrelname AS index_name, stats.idx_scan,
                   stats.idx_tup_read, stats.idx_tup_fetch,
                   pg_relation_size(stats.indexrelid) AS index_bytes,
                   index.indisvalid, index.indisready, index.indisunique,
                   pg_get_indexdef(stats.indexrelid) AS definition
            FROM pg_stat_user_indexes stats
            JOIN pg_index index ON index.indexrelid=stats.indexrelid
            ORDER BY index_bytes DESC LIMIT 200
        """)))
        schemas = _rows(connection.execute(text("""
            SELECT table_schema AS schema_name, COUNT(*)::int AS tables
            FROM information_schema.tables WHERE table_type='BASE TABLE'
              AND table_schema NOT IN ('pg_catalog', 'information_schema')
            GROUP BY table_schema ORDER BY table_schema
        """)))
        active = _rows(connection.execute(text("""
            SELECT pid, usename, application_name, client_addr, state,
                   wait_event_type, wait_event,
                   EXTRACT(EPOCH FROM (NOW()-query_start))*1000 AS duration_ms,
                   query
            FROM pg_stat_activity
            WHERE datname=current_database() AND pid <> pg_backend_pid()
              AND state <> 'idle'
            ORDER BY query_start LIMIT 25
        """)))
        for item in active:
            normalized, fingerprint, table_names, statement_type = sanitize_sql(
                item.pop("query") or ""
            )
            item.update({
                "normalized_sql": normalized,
                "fingerprint": fingerprint,
                "table_names": table_names,
                "statement_type": statement_type,
            })
        extension = connection.execute(text("""
            SELECT extversion FROM pg_extension WHERE extname='pg_stat_statements'
        """)).scalar()
        statements: list[dict[str, Any]] = []
        statements_error = None
        if extension:
            try:
                statements = _rows(connection.execute(text("""
                    SELECT calls, total_exec_time, mean_exec_time, max_exec_time,
                           rows, shared_blks_hit, shared_blks_read,
                           temp_blks_read, temp_blks_written, query
                    FROM pg_stat_statements
                    ORDER BY total_exec_time DESC LIMIT 30
                """)))
                for item in statements:
                    normalized, fingerprint, table_names, statement_type = sanitize_sql(
                        item.pop("query") or ""
                    )
                    item.update({
                        "normalized_sql": normalized,
                        "fingerprint": fingerprint,
                        "table_names": table_names,
                        "statement_type": statement_type,
                    })
            except SQLAlchemyError as exc:
                statements_error = type(getattr(exc, "orig", exc)).__name__
        recommendations = []
        for table in tables:
            if int(table.get("n_dead_tup") or 0) > max(
                10000, int(table.get("n_live_tup") or 0) * 0.2
            ):
                recommendations.append({
                    "severity": "warning",
                    "kind": "dead_tuples",
                    "object": f"{table['schema_name']}.{table['table_name']}",
                    "detail": f"{int(table['n_dead_tup'] or 0):,} estimated dead rows",
                })
            if int(table.get("seq_scan") or 0) > 1000 and int(
                table.get("seq_tup_read") or 0
            ) > 1_000_000:
                recommendations.append({
                    "severity": "review",
                    "kind": "sequential_scans",
                    "object": f"{table['schema_name']}.{table['table_name']}",
                    "detail": (
                        f"{int(table['seq_scan'] or 0):,} sequential scans read "
                        f"{int(table['seq_tup_read'] or 0):,} rows"
                    ),
                })
        for index in indexes:
            if (
                int(index.get("idx_scan") or 0) == 0
                and int(index.get("index_bytes") or 0) >= 10_000_000
                and not index.get("indisunique")
            ):
                recommendations.append({
                    "severity": "review",
                    "kind": "unused_index",
                    "object": index["index_name"],
                    "detail": (
                        f"No scans since statistics reset; uses "
                        f"{int(index['index_bytes'] or 0):,} bytes"
                    ),
                })
    return {
        "name": name,
        "overview": overview,
        "settings": settings,
        "connections": connections,
        "schemas": schemas,
        "tables": tables,
        "indexes": indexes,
        "active_queries": active,
        "pg_stat_statements": {
            "available": bool(extension and statements_error is None),
            "version": extension,
            "error": statements_error,
            "items": statements,
        },
        "recommendations": recommendations[:100],
    }


def database_operations_overview() -> dict[str, Any]:
    ensure_operations_schema()
    databases = []
    for engine, name in (
        (get_cortellis_engine(), "cortellis"),
        (get_edgar_source_engine(), "edgar"),
    ):
        try:
            databases.append(_database_detail(engine, name))
        except SQLAlchemyError as exc:
            databases.append({
                "name": name,
                "error": type(getattr(exc, "orig", exc)).__name__,
            })
    with get_cortellis_engine().connect() as connection:
        history = _rows(connection.execute(text("""
            SELECT id, database_name, captured_at, database_bytes,
                   table_count, index_count, database_metrics
            FROM operations_schema_snapshots
            WHERE captured_at >= NOW() - INTERVAL '90 days'
            ORDER BY captured_at, database_name
        """)))
    return {"databases": databases, "schema_history": history}
