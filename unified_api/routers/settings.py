"""User settings — email digest preferences."""
import structlog
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import text
from unified_api.services.database import get_cortellis_session
from unified_api.services.auth import TokenData
from unified_api.routers.auth import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/settings", tags=["Settings"])


class DigestSettings(BaseModel):
    enabled: bool = False
    frequency: str = "weekly"  # daily, weekly, off
    therapy_areas: List[str] = []
    company_ids: List[int] = []
    email: Optional[str] = None


@router.get("/digest", response_model=DigestSettings)
async def get_digest_settings(user: TokenData = Depends(get_current_user)):
    """Get the current user's email digest preferences."""
    with get_cortellis_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS user_digest_settings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE,
                enabled BOOLEAN DEFAULT FALSE,
                frequency VARCHAR(20) DEFAULT 'weekly',
                therapy_areas JSONB DEFAULT '[]',
                company_ids JSONB DEFAULT '[]',
                email VARCHAR(255),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        session.commit()
        
        result = session.execute(text("""
            SELECT enabled, frequency, therapy_areas, company_ids, email
            FROM user_digest_settings WHERE user_id = :uid
        """), {"uid": user.user_id}).fetchone()
        
        if not result:
            return DigestSettings()
        
        return DigestSettings(
            enabled=result.enabled,
            frequency=result.frequency,
            therapy_areas=result.therapy_areas if isinstance(result.therapy_areas, list) else json.loads(result.therapy_areas or '[]'),
            company_ids=result.company_ids if isinstance(result.company_ids, list) else json.loads(result.company_ids or '[]'),
            email=result.email,
        )


@router.put("/digest", response_model=DigestSettings)
async def update_digest_settings(settings: DigestSettings, user: TokenData = Depends(get_current_user)):
    """Update the current user's email digest preferences."""
    if settings.frequency not in ('daily', 'weekly', 'off'):
        raise HTTPException(status_code=400, detail="frequency must be daily, weekly, or off")
    
    with get_cortellis_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS user_digest_settings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE,
                enabled BOOLEAN DEFAULT FALSE,
                frequency VARCHAR(20) DEFAULT 'weekly',
                therapy_areas JSONB DEFAULT '[]',
                company_ids JSONB DEFAULT '[]',
                email VARCHAR(255),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        
        session.execute(text("""
            INSERT INTO user_digest_settings (user_id, enabled, frequency, therapy_areas, company_ids, email, updated_at)
            VALUES (:uid, :enabled, :frequency, :therapy_areas::jsonb, :company_ids::jsonb, :email, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                enabled = :enabled,
                frequency = :frequency,
                therapy_areas = :therapy_areas::jsonb,
                company_ids = :company_ids::jsonb,
                email = :email,
                updated_at = NOW()
        """), {
            "uid": user.user_id,
            "enabled": settings.enabled,
            "frequency": settings.frequency,
            "therapy_areas": json.dumps(settings.therapy_areas),
            "company_ids": json.dumps(settings.company_ids),
            "email": settings.email,
        })
        session.commit()
        
        return settings
