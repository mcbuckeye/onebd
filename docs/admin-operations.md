# Admin Operations and Performance Telemetry

OneBD includes an administrator-only Operations console for understanding API,
hosted MCP, PostgreSQL, and background-worker behavior over time. Open **Admin →
Operations** in the web application. The corresponding endpoints are under
`/api/admin/operations` and require an authenticated administrator; colleague
API keys cannot read or change operational telemetry.

## What is captured

Every API and hosted MCP request receives an `X-Request-ID`. The durable request
record includes:

- start/end time, duration, HTTP method, route and response status;
- channel (`api`, `mcp`, or `http`) and MCP tool names;
- authenticated user, API-key identity, or anonymous principal attribution;
- client address, user agent, request/response byte counts and deployment SHA;
- sanitized query parameters and, when enabled, bounded JSON request metadata;
- correlated SQL call count, database time, slow-query count and dropped-span
  count.

MCP tool requests are linked to the governed REST calls they make through a
parent request ID. Celery jobs have a separate ledger containing task/queue,
worker, status, retries, runtime, sanitized arguments/results and correlated SQL
spans.

SQLAlchemy instrumentation records a span for Cortellis and EDGAR statements:
database, duration, row count when the driver reports it, success/error type,
referenced table names, statement type, and a stable fingerprint. Fingerprints
make differently parameterized executions of the same query shape aggregate
together.

The database view also reports live PostgreSQL connection/cache statistics,
active query shapes, table/index size and scan activity, dead tuples,
`pg_stat_statements` aggregates when the extension is active, and daily schema
size snapshots. Recommendations are diagnostic prompts, not automatic schema
changes: an apparently unused index can still be necessary for rare workloads.

## Privacy and security behavior

Telemetry is designed not to become a credential store:

- Authorization and cookie headers are never retained.
- SQL bind parameters are never passed to the collector. String and numeric
  literals embedded directly in SQL are replaced before storage.
- JSON fields whose names resemble password, secret, token, API key, SMTP,
  OpenAI, authorization, or cookie fields are recursively replaced with
  `[REDACTED]`.
- Payloads, strings, collection depth and collection cardinality are bounded.
- Normalized SQL retention and sanitized JSON retention can each be disabled.
- Only administrators can read telemetry or change the policy.

Sanitized request metadata can still contain non-secret business questions,
company names, filters or other operational context. An owner who does not want
that context retained should disable **Retain sanitized JSON**. The data-access
license policy and telemetry policy are independent owner controls; OneBD does
not force dataset restrictions merely because advisory license metadata exists.

## Console views

- **Overview** — volume, active principals, error rate, latency percentiles,
  database time, channel split and slow routes.
- **Requests & MCP** — filter by path, user/API key, channel, status and minimum
  runtime; inspect request metadata and its SQL timeline.
- **SQL** — aggregate by fingerprint and database; sort by total, average,
  maximum, calls or errors; search by table, query shape or hash.
- **Jobs** — inspect worker task status, runtime, retries, sanitized inputs/result
  summaries and SQL.
- **DB & Schema** — live work, connections, cache hit rate, table/index behavior,
  `pg_stat_statements`, recommendations, and schema growth history.
- **Settings** — capture toggles, slow thresholds, minimum retained SQL duration,
  span/payload bounds, retention and manual purge.

The console can auto-refresh every 15 seconds. Live database diagnostics are
queried only while the DB & Schema view is loaded or its API is called.

## Admin API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/admin/operations/summary?hours=24` | Latency, error, channel and route overview |
| `GET` | `/api/admin/operations/requests` | Filtered request/MCP ledger |
| `GET` | `/api/admin/operations/requests/{request_id}` | Request, SQL spans and child requests |
| `GET` | `/api/admin/operations/sql` | SQL fingerprint aggregates |
| `GET` | `/api/admin/operations/jobs` | Filtered worker-job ledger |
| `GET` | `/api/admin/operations/jobs/{task_id}` | Job and correlated SQL detail |
| `GET` | `/api/admin/operations/databases` | Live DB/schema diagnostics and snapshot history |
| `POST` | `/api/admin/operations/databases/snapshot` | Force a Cortellis and EDGAR snapshot |
| `GET` | `/api/admin/operations/settings` | Current telemetry policy |
| `PUT` | `/api/admin/operations/settings` | Replace the telemetry policy |
| `POST` | `/api/admin/operations/purge` | Delete records older than an explicit day count |

The request and SQL list endpoints support bounded pagination. OpenAPI documents
the exact filters and validation rules at `/docs`.

## Storage and retention

The application creates five tables in the Cortellis PostgreSQL database:

- `operations_telemetry_settings`
- `operations_request_log`
- `operations_sql_log`
- `operations_job_log`
- `operations_schema_snapshots`

Indexes cover time, route/channel, principal, duration, operation ID, SQL
fingerprint, and task name access paths. The default retention is 30 days. A
nightly Celery task at 03:20 UTC deletes expired request, SQL, job and snapshot
rows. Administrators can change retention or run a manual purge. Schema setup is
idempotent and protected with PostgreSQL advisory locks across API/worker
processes.

## Using telemetry to improve the system

Start with total SQL time, p95 latency and call count—not one unusually slow
execution. A useful tuning loop is:

1. Select a high-total-time route or SQL fingerprint.
2. Open representative request traces to distinguish application time from DB
   time and see whether MCP created child calls.
3. Check the referenced table's sequential/index scans, size and dead tuples.
4. Reproduce the normalized shape with safe parameters and use `EXPLAIN
   (ANALYZE, BUFFERS)` in a non-destructive environment.
5. Add or revise an index/query, test correctness and latency, deploy, then
   compare the same fingerprint and route over equivalent windows.

Application telemetry complements PostgreSQL `pg_stat_statements`: the former
has user/API/MCP/job correlation and a controlled retention window; the latter
has server-wide aggregates and buffer statistics, including SQL outside the
application collector. EDGAR will show application spans even when
`pg_stat_statements` is not enabled there.
