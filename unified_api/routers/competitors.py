"""Competitor tracking and durable first-observed entrant alerts."""
import structlog
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from sqlalchemy import text
from unified_api.services.database import get_cortellis_session
from unified_api.services.auth import TokenData
from unified_api.routers.auth import get_current_user
from unified_api.routers.admin import require_admin
from unified_api.services.company_entrant_alerts import (
    company_entrant_alert_status,
    ensure_company_entrant_alert_schema,
    scan_company_entrant_alerts,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/competitors", tags=["Competitors"])


class CompetitorDealOut(BaseModel):
    id: int
    title: str
    agreement_type: Optional[str] = None
    status: Optional[str] = None
    date_start: Optional[str] = None


class CompetitorOut(BaseModel):
    id: int
    company_id: int
    company_name: str
    company_type: Optional[str] = None
    total_deals: int = 0
    created_at: Optional[str] = None
    entrant_alerts_enabled: bool = True
    entrant_baselined_at: Optional[str] = None
    entrant_last_checked_at: Optional[str] = None
    unread_entrant_alerts: int = 0
    recent_deals: List[CompetitorDealOut] = Field(default_factory=list)


class AddCompetitorRequest(BaseModel):
    company_id: int


class EntrantAlertSettingsRequest(BaseModel):
    enabled: bool


class EntrantAlertActionRequest(BaseModel):
    action: Literal["read", "dismiss"]


class EntrantAlertOut(BaseModel):
    id: int
    subject_company_id: int
    subject_company_name: str
    entrant_company_id: int
    entrant_company_name: str
    indication_id: int
    indication_name: str
    first_observed_date: str
    observed_deals: int
    evidence_deal_ids: List[int]
    content: str
    created_at: str
    read_at: Optional[str] = None


@router.get("", response_model=List[CompetitorOut])
async def list_competitors(user: TokenData = Depends(get_current_user)):
    """List all tracked competitors for the current user."""
    with get_cortellis_session() as session:
        ensure_company_entrant_alert_schema(session)
        results = session.execute(text("""
            SELECT tc.id, tc.company_id, c.name as company_name, c.company_type,
                   tc.created_at::text,
                   tc.entrant_alerts_enabled,
                   tc.entrant_baselined_at::text,
                   tc.entrant_last_checked_at::text,
                   (SELECT COUNT(DISTINCT dc.deal_id) FROM deal_companies dc
                    WHERE dc.company_id = tc.company_id) AS total_deals,
                   (SELECT COUNT(*)
                    FROM company_entrant_alerts alert
                    WHERE alert.tracked_competitor_id = tc.id
                      AND alert.read_at IS NULL
                      AND alert.dismissed_at IS NULL) AS unread_entrant_alerts
            FROM tracked_competitors tc
            JOIN companies c ON c.id = tc.company_id
            WHERE tc.user_id = :user_id
            ORDER BY tc.created_at DESC
        """), {"user_id": user.user_id}).mappings().all()
        company_ids = [int(row["company_id"]) for row in results]
        recent_by_company: dict[int, list[CompetitorDealOut]] = {
            company_id: [] for company_id in company_ids
        }
        if company_ids:
            recent_rows = session.execute(text("""
                WITH company_deals AS (
                    SELECT DISTINCT company_id, deal_id
                    FROM deal_companies
                    WHERE company_id = ANY(:company_ids)
                ), ranked AS (
                    SELECT company_deal.company_id, deal.id, deal.title,
                           deal.agreement_type, deal.status,
                           deal.date_start::text,
                           ROW_NUMBER() OVER (
                               PARTITION BY company_deal.company_id
                               ORDER BY deal.date_start DESC NULLS LAST,
                                        deal.id DESC
                           ) AS row_number
                    FROM company_deals company_deal
                    JOIN deals deal ON deal.id = company_deal.deal_id
                )
                SELECT company_id, id, title, agreement_type, status, date_start
                FROM ranked WHERE row_number <= 5
                ORDER BY company_id, row_number
            """), {"company_ids": company_ids}).mappings().all()
            for row in recent_rows:
                recent_by_company[int(row["company_id"])].append(
                    CompetitorDealOut(
                        id=row["id"],
                        title=row["title"] or "Untitled",
                        agreement_type=row["agreement_type"],
                        status=row["status"],
                        date_start=row["date_start"],
                    )
                )

        return [CompetitorOut(
            id=row["id"],
            company_id=row["company_id"],
            company_name=row["company_name"],
            company_type=row["company_type"],
            total_deals=row["total_deals"],
            created_at=row["created_at"],
            entrant_alerts_enabled=row["entrant_alerts_enabled"],
            entrant_baselined_at=row["entrant_baselined_at"],
            entrant_last_checked_at=row["entrant_last_checked_at"],
            unread_entrant_alerts=row["unread_entrant_alerts"],
            recent_deals=recent_by_company[int(row["company_id"])],
        ) for row in results]


@router.post("", response_model=CompetitorOut)
async def add_competitor(req: AddCompetitorRequest, user: TokenData = Depends(get_current_user)):
    """Add a company to tracked competitors."""
    with get_cortellis_session() as session:
        ensure_company_entrant_alert_schema(session)
        # Check company exists
        company = session.execute(text("SELECT id, name, company_type FROM companies WHERE id = :id"), {"id": req.company_id}).fetchone()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        
        # Insert (ignore duplicate)
        try:
            result = session.execute(text("""
                INSERT INTO tracked_competitors (user_id, company_id)
                VALUES (:user_id, :company_id)
                ON CONFLICT (user_id, company_id) DO NOTHING
                RETURNING id, created_at::text
            """), {"user_id": user.user_id, "company_id": req.company_id})
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=409, detail="Already tracking this company")
            
            deal_count = session.execute(text("SELECT COUNT(*) FROM deal_companies WHERE company_id = :cid"), {"cid": req.company_id}).scalar()
            
            return CompetitorOut(
                id=row.id,
                company_id=req.company_id,
                company_name=company.name,
                company_type=company.company_type,
                total_deals=deal_count or 0,
                created_at=row.created_at,
            )
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            logger.error(
                "Failed to add tracked competitor",
                company_id=req.company_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to track competitor",
            ) from exc


@router.patch("/companies/{company_id}/entrant-alerts")
async def update_entrant_alert_settings(
    request: EntrantAlertSettingsRequest,
    company_id: int,
    user: TokenData = Depends(get_current_user),
):
    """Enable or disable baseline-safe entrant alerts for a tracked company."""
    with get_cortellis_session() as session:
        ensure_company_entrant_alert_schema(session)
        row = session.execute(text("""
            UPDATE tracked_competitors
            SET entrant_alerts_enabled = :enabled,
                entrant_baselined_at = CASE
                    WHEN :enabled AND entrant_alerts_enabled = FALSE THEN NULL
                    ELSE entrant_baselined_at
                END,
                entrant_last_checked_at = CASE
                    WHEN :enabled AND entrant_alerts_enabled = FALSE THEN NULL
                    ELSE entrant_last_checked_at
                END
            WHERE user_id = :user_id AND company_id = :company_id
            RETURNING entrant_alerts_enabled, entrant_baselined_at::text,
                      entrant_last_checked_at::text
        """), {
            "enabled": request.enabled,
            "user_id": user.user_id,
            "company_id": company_id,
        }).mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Competitor not tracked")
        return dict(row)


@router.get("/entrant-alerts", response_model=List[EntrantAlertOut])
async def list_entrant_alerts(
    limit: int = 50,
    user: TokenData = Depends(get_current_user),
):
    """List non-dismissed first-observed entrant alerts for the current user."""
    limit = max(1, min(200, int(limit)))
    with get_cortellis_session() as session:
        ensure_company_entrant_alert_schema(session)
        rows = session.execute(text("""
            SELECT alert.id,
                   detection.subject_company_id,
                   subject.name AS subject_company_name,
                   detection.entrant_company_id,
                   entrant.name AS entrant_company_name,
                   detection.indication_id,
                   indication.name AS indication_name,
                   detection.first_observed_date::text,
                   detection.observed_deals,
                   detection.evidence_deal_ids,
                   alert.content, alert.created_at::text, alert.read_at::text
            FROM company_entrant_alerts alert
            JOIN company_entrant_detections detection
              ON detection.id = alert.detection_id
            JOIN companies subject ON subject.id = detection.subject_company_id
            JOIN companies entrant ON entrant.id = detection.entrant_company_id
            JOIN indications indication ON indication.id = detection.indication_id
            WHERE alert.user_id = :user_id
              AND alert.dismissed_at IS NULL
            ORDER BY alert.created_at DESC
            LIMIT :limit
        """), {"user_id": user.user_id, "limit": limit}).mappings().all()
        return [EntrantAlertOut(**dict(row)) for row in rows]


@router.patch("/entrant-alerts/{alert_id}")
async def update_entrant_alert(
    alert_id: int,
    request: EntrantAlertActionRequest,
    user: TokenData = Depends(get_current_user),
):
    """Mark an entrant alert read or preserve it as dismissed history."""
    field = "read_at" if request.action == "read" else "dismissed_at"
    with get_cortellis_session() as session:
        ensure_company_entrant_alert_schema(session)
        row = session.execute(text(f"""
            UPDATE company_entrant_alerts SET {field} = NOW()
            WHERE id = :alert_id AND user_id = :user_id
            RETURNING id
        """), {
            "alert_id": alert_id,
            "user_id": user.user_id,
        }).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Entrant alert not found")
        return {"status": request.action, "id": alert_id}


@router.get("/entrant-alerts/status")
async def entrant_alert_status(
    _user: TokenData = Depends(get_current_user),
):
    """Return durable entrant-alert coverage and last scan time."""
    with get_cortellis_session() as session:
        return company_entrant_alert_status(session)


@router.post("/entrant-alerts/check")
async def check_entrant_alerts_now(
    _admin: TokenData = Depends(require_admin),
):
    """Run the same baseline-safe scan used by the scheduled worker."""
    with get_cortellis_session() as session:
        return scan_company_entrant_alerts(session)


@router.delete("/{company_id}")
async def remove_competitor(company_id: int, user: TokenData = Depends(get_current_user)):
    """Remove a company from tracked competitors."""
    with get_cortellis_session() as session:
        ensure_company_entrant_alert_schema(session)
        result = session.execute(text("""
            DELETE FROM tracked_competitors
            WHERE user_id = :user_id AND company_id = :company_id
        """), {"user_id": user.user_id, "company_id": company_id})
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Competitor not tracked")
        return {"status": "removed"}
