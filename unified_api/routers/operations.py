"""Administrator-only operational telemetry and database diagnostics."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from unified_api.routers.admin import require_admin
from unified_api.services.audit import log_audit
from unified_api.services.auth import TokenData
from unified_api.services.operations_reporting import (
    aggregate_sql,
    database_operations_overview,
    list_operation_jobs,
    list_operation_requests,
    operation_job_detail,
    operation_request_detail,
    operations_summary,
)
from unified_api.services.operations_telemetry import (
    capture_schema_snapshots_if_due,
    cleanup_telemetry,
    get_telemetry_settings,
    update_telemetry_settings,
)


router = APIRouter(prefix="/admin/operations", tags=["Admin Operations"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TelemetrySettingsRequest(StrictModel):
    enabled: bool = True
    capture_request_payloads: bool = True
    retain_normalized_sql: bool = True
    sql_min_duration_ms: float = Field(default=5, ge=0, le=60000)
    slow_request_ms: float = Field(default=1000, ge=1, le=600000)
    slow_sql_ms: float = Field(default=250, ge=1, le=600000)
    max_sql_spans_per_operation: int = Field(default=200, ge=1, le=5000)
    payload_max_bytes: int = Field(default=32768, ge=0, le=1000000)
    retention_days: int = Field(default=30, ge=1, le=3650)


class PurgeRequest(StrictModel):
    older_than_days: int = Field(ge=1, le=3650)


@router.get("/summary")
def summary(
    hours: int = Query(default=24, ge=1, le=24 * 365),
    _current_user: TokenData = Depends(require_admin),
):
    return operations_summary(hours)


@router.get("/requests")
def requests(
    hours: int = Query(default=24, ge=1, le=24 * 365),
    channel: str | None = Query(default=None, max_length=30),
    path: str | None = Query(default=None, max_length=300),
    principal: str | None = Query(default=None, max_length=300),
    status: Literal["success", "errors"] | None = None,
    min_duration_ms: float | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    _current_user: TokenData = Depends(require_admin),
):
    return list_operation_requests(
        hours=hours,
        channel=channel,
        path=path,
        principal=principal,
        status=status,
        min_duration_ms=min_duration_ms,
        limit=limit,
        offset=offset,
    )


@router.get("/requests/{request_id}")
def request_detail(
    request_id: str,
    _current_user: TokenData = Depends(require_admin),
):
    try:
        result = operation_request_detail(request_id)
    except Exception as exc:
        if "invalid input syntax for type uuid" in str(exc).lower():
            raise HTTPException(status_code=422, detail="Invalid request ID") from exc
        raise
    if result is None:
        raise HTTPException(status_code=404, detail="Request telemetry not found")
    return result


@router.get("/sql")
def sql_queries(
    hours: int = Query(default=24, ge=1, le=24 * 365),
    database_name: Literal["cortellis", "edgar"] | None = None,
    search: str | None = Query(default=None, max_length=300),
    min_duration_ms: float | None = Query(default=None, ge=0),
    errors_only: bool = False,
    sort: Literal["total", "average", "maximum", "calls", "errors"] = "total",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    _current_user: TokenData = Depends(require_admin),
):
    return aggregate_sql(
        hours=hours,
        database_name=database_name,
        search=search,
        min_duration_ms=min_duration_ms,
        errors_only=errors_only,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs")
def jobs(
    hours: int = Query(default=24 * 7, ge=1, le=24 * 365),
    status: str | None = Query(default=None, max_length=40),
    task_name: str | None = Query(default=None, max_length=300),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    _current_user: TokenData = Depends(require_admin),
):
    return list_operation_jobs(
        hours=hours,
        status=status,
        task_name=task_name,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{task_id}")
def job_detail(
    task_id: str,
    _current_user: TokenData = Depends(require_admin),
):
    result = operation_job_detail(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job telemetry not found")
    return result


@router.get("/databases")
def databases(_current_user: TokenData = Depends(require_admin)):
    return database_operations_overview()


@router.post("/databases/snapshot")
def capture_snapshot(current_user: TokenData = Depends(require_admin)):
    snapshots = capture_schema_snapshots_if_due(force=True)
    log_audit(
        "operations_schema_snapshot",
        user_id=current_user.user_id,
        entity_type="operations",
        metadata={"databases": [item["database_name"] for item in snapshots]},
    )
    return {"captured": len(snapshots), "databases": snapshots}


@router.get("/settings")
def telemetry_settings(_current_user: TokenData = Depends(require_admin)):
    return asdict(get_telemetry_settings(force=True))


@router.put("/settings")
def set_telemetry_settings(
    request: TelemetrySettingsRequest,
    current_user: TokenData = Depends(require_admin),
):
    try:
        result = update_telemetry_settings(
            request.model_dump(), current_user.user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_audit(
        "operations_telemetry_settings_updated",
        user_id=current_user.user_id,
        entity_type="operations",
        metadata=request.model_dump(),
    )
    return result


@router.post("/purge")
def purge(
    request: PurgeRequest,
    current_user: TokenData = Depends(require_admin),
):
    deleted = cleanup_telemetry(request.older_than_days)
    log_audit(
        "operations_telemetry_purged",
        user_id=current_user.user_id,
        entity_type="operations",
        metadata={"older_than_days": request.older_than_days, "deleted": deleted},
    )
    return {"deleted": deleted, "older_than_days": request.older_than_days}
