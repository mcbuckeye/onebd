"""Competitor tracking — persistent per-user company watchlist."""
import structlog
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import text
from unified_api.services.database import get_cortellis_session
from unified_api.services.auth import get_current_user, TokenData

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/competitors", tags=["Competitors"])


class CompetitorOut(BaseModel):
    id: int
    company_id: int
    company_name: str
    company_type: Optional[str] = None
    total_deals: int = 0
    created_at: Optional[str] = None


class AddCompetitorRequest(BaseModel):
    company_id: int


@router.get("", response_model=List[CompetitorOut])
async def list_competitors(user: TokenData = Depends(get_current_user)):
    """List all tracked competitors for the current user."""
    with get_cortellis_session() as session:
        # Ensure table exists
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS tracked_competitors (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, company_id)
            )
        """))
        session.commit()
        
        results = session.execute(text("""
            SELECT tc.id, tc.company_id, c.name as company_name, c.company_type,
                   tc.created_at::text,
                   (SELECT COUNT(*) FROM deal_companies dc WHERE dc.company_id = tc.company_id) as total_deals
            FROM tracked_competitors tc
            JOIN companies c ON c.id = tc.company_id
            WHERE tc.user_id = :user_id
            ORDER BY tc.created_at DESC
        """), {"user_id": user.user_id})
        
        return [CompetitorOut(
            id=r.id,
            company_id=r.company_id,
            company_name=r.company_name,
            company_type=r.company_type,
            total_deals=r.total_deals,
            created_at=r.created_at,
        ) for r in results]


@router.post("", response_model=CompetitorOut)
async def add_competitor(req: AddCompetitorRequest, user: TokenData = Depends(get_current_user)):
    """Add a company to tracked competitors."""
    with get_cortellis_session() as session:
        # Ensure table exists
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS tracked_competitors (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, company_id)
            )
        """))
        
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
            session.commit()
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
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{company_id}")
async def remove_competitor(company_id: int, user: TokenData = Depends(get_current_user)):
    """Remove a company from tracked competitors."""
    with get_cortellis_session() as session:
        result = session.execute(text("""
            DELETE FROM tracked_competitors
            WHERE user_id = :user_id AND company_id = :company_id
        """), {"user_id": user.user_id, "company_id": company_id})
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Competitor not tracked")
        return {"status": "removed"}
