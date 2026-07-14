"""
Admin endpoints: user management
Only accessible to users with role='admin'
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.auth import hash_password
from unified_api.services.api_credentials import (
    ACCESS_MODES,
    ALLOWED_SCOPES,
    DATASETS,
    create_api_credential,
    get_data_access_policy,
    list_api_credentials,
    revoke_api_credential,
    update_data_access_policy,
)
from unified_api.routers.auth import get_current_user, TokenData, UserResponse

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    email: str
    password: str
    name: str
    role: str = "analyst"


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None


class MessageResponse(BaseModel):
    message: str


class CreateAPICredentialRequest(BaseModel):
    name: str
    scopes: List[str] = Field(default_factory=lambda: ["data:read"])
    expires_at: Optional[datetime] = None


class DataAccessPolicyRequest(BaseModel):
    access_mode: str = "key_required"
    enforce_scopes: bool = True
    allow_self_registration: bool = False
    protect_existing_api: bool = False
    disabled_datasets: List[str] = Field(default_factory=list)


class AuditLogEntry(BaseModel):
    id: int
    user_id: Optional[int]
    action: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    ip_address: Optional[str]
    metadata: Optional[dict]
    created_at: str


class AuditLogResponse(BaseModel):
    logs: List[AuditLogEntry]
    total: int
    limit: int
    offset: int


def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Dependency to ensure current user is admin."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def _ensure_audit_log_table(session):
    """Create audit_log table if it doesn't exist."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action VARCHAR(100) NOT NULL,
            entity_type VARCHAR(50),
            entity_id VARCHAR(255),
            ip_address VARCHAR(45),
            metadata JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """))
    # Add index for efficient querying
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC)
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id)
    """))
    session.commit()


@router.get("/api-credentials")
async def get_api_credentials(
    _current_user: TokenData = Depends(require_admin),
):
    """List API credentials without ever returning their secret values."""
    return {
        "allowed_scopes": sorted(ALLOWED_SCOPES),
        "credentials": list_api_credentials(),
    }


@router.post("/api-credentials", status_code=201)
async def issue_api_credential(
    req: CreateAPICredentialRequest,
    current_user: TokenData = Depends(require_admin),
):
    """Issue a scoped API key; the plaintext is returned exactly once."""
    try:
        return create_api_credential(
            name=req.name,
            scopes=req.scopes,
            created_by=current_user.user_id,
            expires_at=req.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api-credentials/{credential_id}", response_model=MessageResponse)
async def revoke_credential(
    credential_id: int,
    _current_user: TokenData = Depends(require_admin),
):
    """Immediately revoke a colleague or integration API key."""
    if not revoke_api_credential(credential_id):
        raise HTTPException(status_code=404, detail="API credential not found")
    return MessageResponse(message=f"API credential {credential_id} revoked")


@router.get("/data-access-policy")
async def read_data_access_policy(
    _current_user: TokenData = Depends(require_admin),
):
    """Return the owner-controlled enforcement policy and valid options."""
    return {
        "policy": get_data_access_policy(),
        "allowed_access_modes": sorted(ACCESS_MODES),
        "available_datasets": sorted(DATASETS),
        "license_metadata_is_advisory": True,
    }


@router.put("/data-access-policy")
async def set_data_access_policy(
    req: DataAccessPolicyRequest,
    current_user: TokenData = Depends(require_admin),
):
    """Choose open, signed-in, or API-key access and dataset/scope enforcement."""
    try:
        return update_data_access_policy(
            access_mode=req.access_mode,
            enforce_scopes=req.enforce_scopes,
            allow_self_registration=req.allow_self_registration,
            protect_existing_api=req.protect_existing_api,
            disabled_datasets=req.disabled_datasets,
            updated_by=current_user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/users", response_model=List[UserResponse])
async def list_users(current_user: TokenData = Depends(require_admin)):
    """List all users (admin only)."""
    with get_cortellis_session() as session:
        rows = session.execute(
            text("""
                SELECT id, email, name, role
                FROM users
                WHERE disabled IS NOT TRUE
                ORDER BY created_at DESC
            """)
        ).fetchall()

        return [
            UserResponse(id=row.id, email=row.email, name=row.name, role=row.role)
            for row in rows
        ]


@router.post("/users", response_model=UserResponse)
async def create_user(
    req: CreateUserRequest,
    current_user: TokenData = Depends(require_admin)
):
    """Create a new user (admin only)."""
    with get_cortellis_session() as session:
        # Check if email exists
        existing = session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": req.email}
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")

        # Create user
        result = session.execute(
            text("""
                INSERT INTO users (email, password_hash, name, role)
                VALUES (:email, :password_hash, :name, :role)
                RETURNING id
            """),
            {
                "email": req.email,
                "password_hash": hash_password(req.password),
                "name": req.name,
                "role": req.role,
            }
        )
        user_id = result.fetchone()[0]
        session.commit()

        logger.info("admin_created_user", admin_id=current_user.user_id, new_user_id=user_id)

        return UserResponse(
            id=user_id,
            email=req.email,
            name=req.name,
            role=req.role
        )


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    current_user: TokenData = Depends(require_admin)
):
    """Update user name and/or role (admin only)."""
    with get_cortellis_session() as session:
        # Check user exists
        user_row = session.execute(
            text("SELECT id, email FROM users WHERE id = :id AND disabled IS NOT TRUE"),
            {"id": user_id}
        ).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        # Build update query dynamically
        updates = []
        params = {"id": user_id}

        if req.name is not None:
            updates.append("name = :name")
            params["name"] = req.name

        if req.role is not None:
            updates.append("role = :role")
            params["role"] = req.role

        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        query = f"UPDATE users SET {', '.join(updates)} WHERE id = :id"
        session.execute(text(query), params)
        session.commit()

        # Fetch updated user
        updated = session.execute(
            text("SELECT id, email, name, role FROM users WHERE id = :id"),
            {"id": user_id}
        ).fetchone()

        logger.info("admin_updated_user", admin_id=current_user.user_id, user_id=user_id, updates=list(params.keys()))

        return UserResponse(
            id=updated.id,
            email=updated.email,
            name=updated.name,
            role=updated.role
        )


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: int,
    current_user: TokenData = Depends(require_admin)
):
    """Disable user (admin only). Soft delete - sets disabled flag."""
    with get_cortellis_session() as session:
        # Check user exists
        user_row = session.execute(
            text("SELECT id FROM users WHERE id = :id AND disabled IS NOT TRUE"),
            {"id": user_id}
        ).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        # Ensure 'disabled' column exists (soft delete)
        session.execute(text("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled BOOLEAN DEFAULT FALSE
        """))

        # Disable user
        session.execute(
            text("UPDATE users SET disabled = TRUE WHERE id = :id"),
            {"id": user_id}
        )
        session.commit()

        logger.info("admin_deleted_user", admin_id=current_user.user_id, user_id=user_id)

        return MessageResponse(message=f"User {user_id} has been disabled")


@router.get("/audit-log", response_model=AuditLogResponse)
async def get_audit_log(
    limit: int = 50,
    offset: int = 0,
    current_user: TokenData = Depends(require_admin)
):
    """Get paginated audit log (admin only)."""
    with get_cortellis_session() as session:
        _ensure_audit_log_table(session)

        # Get total count
        total_result = session.execute(text("SELECT COUNT(*) FROM audit_log")).fetchone()
        total = total_result[0] if total_result else 0

        # Get logs with pagination
        rows = session.execute(
            text("""
                SELECT 
                    id, user_id, action, entity_type, entity_id, 
                    ip_address, metadata, created_at
                FROM audit_log
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": limit, "offset": offset}
        ).fetchall()

        logs = [
            AuditLogEntry(
                id=row.id,
                user_id=row.user_id,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                ip_address=row.ip_address,
                metadata=row.metadata,
                created_at=row.created_at.isoformat() if row.created_at else None
            )
            for row in rows
        ]

        return AuditLogResponse(
            logs=logs,
            total=total,
            limit=limit,
            offset=offset
        )
