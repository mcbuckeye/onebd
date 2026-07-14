"""User settings — email digest preferences."""
import structlog
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy import text
from unified_api.services.database import get_cortellis_session
from unified_api.services.auth import TokenData
from unified_api.routers.auth import get_current_user
from unified_api.services.digest_settings import ensure_digest_settings_schema

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/settings", tags=["Settings"])


class DigestSettings(BaseModel):
    enabled: bool = False
    frequency: str = "weekly"  # daily, weekly, off
    therapy_areas: List[str] = Field(default_factory=list)
    company_ids: List[int] = Field(default_factory=list)
    email: Optional[str] = None
    include_catalysts: bool = True
    catalyst_days: int = Field(default=30, ge=7, le=365)


@router.get("/digest", response_model=DigestSettings)
async def get_digest_settings(user: TokenData = Depends(get_current_user)):
    """Get the current user's email digest preferences."""
    with get_cortellis_session() as session:
        ensure_digest_settings_schema(session)
        session.commit()
        
        result = session.execute(text("""
            SELECT enabled, frequency, therapy_areas, company_ids, email,
                   include_catalysts, catalyst_days
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
            include_catalysts=result.include_catalysts,
            catalyst_days=result.catalyst_days,
        )


@router.put("/digest", response_model=DigestSettings)
async def update_digest_settings(settings: DigestSettings, user: TokenData = Depends(get_current_user)):
    """Update the current user's email digest preferences."""
    if settings.frequency not in ('daily', 'weekly', 'off'):
        raise HTTPException(status_code=400, detail="frequency must be daily, weekly, or off")
    
    with get_cortellis_session() as session:
        ensure_digest_settings_schema(session)
        
        session.execute(text("""
            INSERT INTO user_digest_settings (
                user_id, enabled, frequency, therapy_areas, company_ids, email,
                include_catalysts, catalyst_days, updated_at
            )
            VALUES (
                :uid, :enabled, :frequency, CAST(:therapy_areas AS JSONB),
                CAST(:company_ids AS JSONB), :email, :include_catalysts,
                :catalyst_days, NOW()
            )
            ON CONFLICT (user_id) DO UPDATE SET
                enabled = :enabled,
                frequency = :frequency,
                therapy_areas = CAST(:therapy_areas AS JSONB),
                company_ids = CAST(:company_ids AS JSONB),
                email = :email,
                include_catalysts = :include_catalysts,
                catalyst_days = :catalyst_days,
                updated_at = NOW()
        """), {
            "uid": user.user_id,
            "enabled": settings.enabled,
            "frequency": settings.frequency,
            "therapy_areas": json.dumps(settings.therapy_areas),
            "company_ids": json.dumps(settings.company_ids),
            "email": settings.email,
            "include_catalysts": settings.include_catalysts,
            "catalyst_days": settings.catalyst_days,
        })
        session.commit()
        
        return settings
