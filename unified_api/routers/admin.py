"""
Admin endpoints: user management
Only accessible to users with role='admin'
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Literal, Optional
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.auth import hash_password
from unified_api.services.audit import log_audit
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
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    role: Literal["analyst", "admin"] = "analyst"


class UpdateUserRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    role: Optional[Literal["analyst", "admin"]] = None


class MessageResponse(BaseModel):
    message: str


class CreateAPICredentialRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: List[str] = Field(default_factory=lambda: ["data:read"])
    expires_at: Optional[datetime] = None


class DataAccessPolicyRequest(BaseModel):
    access_mode: Literal["key_required", "authenticated", "open"] = "key_required"
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
    user_email: Optional[str] = None


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
        credential = create_api_credential(
            name=req.name,
            scopes=req.scopes,
            created_by=current_user.user_id,
            expires_at=req.expires_at,
        )
        log_audit(
            "api_credential_created",
            user_id=current_user.user_id,
            entity_type="api_credential",
            entity_id=str(credential["id"]),
            metadata={
                "name": credential["name"],
                "scopes": credential["scopes"],
                "expires_at": (
                    credential["expires_at"].isoformat()
                    if credential.get("expires_at")
                    else None
                ),
            },
        )
        return credential
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api-credentials/{credential_id}", response_model=MessageResponse)
async def revoke_credential(
    credential_id: int,
    current_user: TokenData = Depends(require_admin),
):
    """Immediately revoke a colleague or integration API key."""
    if not revoke_api_credential(credential_id):
        raise HTTPException(status_code=404, detail="API credential not found")
    log_audit(
        "api_credential_revoked",
        user_id=current_user.user_id,
        entity_type="api_credential",
        entity_id=str(credential_id),
    )
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
        policy = update_data_access_policy(
            access_mode=req.access_mode,
            enforce_scopes=req.enforce_scopes,
            allow_self_registration=req.allow_self_registration,
            protect_existing_api=req.protect_existing_api,
            disabled_datasets=req.disabled_datasets,
            updated_by=current_user.user_id,
        )
        log_audit(
            "data_access_policy_updated",
            user_id=current_user.user_id,
            entity_type="data_access_policy",
            entity_id="singleton",
            metadata={
                "access_mode": policy["access_mode"],
                "enforce_scopes": policy["enforce_scopes"],
                "allow_self_registration": policy["allow_self_registration"],
                "protect_existing_api": policy["protect_existing_api"],
                "disabled_datasets": policy["disabled_datasets"],
            },
        )
        return policy
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
    email = req.email.strip().lower()
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    with get_cortellis_session() as session:
        # Check if email exists
        existing = session.execute(
            text("SELECT id FROM users WHERE LOWER(email) = LOWER(:email)"),
            {"email": email}
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
                "email": email,
                "password_hash": hash_password(req.password),
                "name": name,
                "role": req.role,
            }
        )
        user_id = result.fetchone()[0]
        session.commit()

        logger.info("admin_created_user", admin_id=current_user.user_id, new_user_id=user_id)
        log_audit(
            "user_created",
            user_id=current_user.user_id,
            entity_type="user",
            entity_id=str(user_id),
            metadata={"email": email, "role": req.role},
        )

        return UserResponse(
            id=user_id,
            email=email,
            name=name,
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
            normalized_name = req.name.strip()
            if not normalized_name:
                raise HTTPException(status_code=422, detail="Name is required")
            updates.append("name = :name")
            params["name"] = normalized_name

        if req.role is not None:
            if user_row.id == current_user.user_id and req.role != "admin":
                admin_count = session.execute(text("""
                    SELECT COUNT(*) FROM users
                    WHERE role = 'admin' AND disabled IS NOT TRUE
                """)).scalar() or 0
                if admin_count <= 1:
                    raise HTTPException(
                        status_code=400,
                        detail="Create another admin before removing the last admin role",
                    )
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
        log_audit(
            "user_updated",
            user_id=current_user.user_id,
            entity_type="user",
            entity_id=str(user_id),
            metadata={
                "changed_fields": sorted(key for key in params if key != "id"),
            },
        )

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
    if user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    with get_cortellis_session() as session:
        # Check user exists
        user_row = session.execute(
            text("SELECT id FROM users WHERE id = :id AND disabled IS NOT TRUE"),
            {"id": user_id}
        ).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        role = session.execute(
            text("SELECT role FROM users WHERE id = :id"), {"id": user_id}
        ).scalar()
        if role == "admin":
            admin_count = session.execute(text("""
                SELECT COUNT(*) FROM users
                WHERE role = 'admin' AND disabled IS NOT TRUE
            """)).scalar() or 0
            if admin_count <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Create another admin before disabling the last admin",
                )

        # Disable user
        session.execute(
            text("UPDATE users SET disabled = TRUE WHERE id = :id"),
            {"id": user_id}
        )
        session.commit()

        logger.info("admin_deleted_user", admin_id=current_user.user_id, user_id=user_id)
        log_audit(
            "user_disabled",
            user_id=current_user.user_id,
            entity_type="user",
            entity_id=str(user_id),
        )

        return MessageResponse(message=f"User {user_id} has been disabled")


@router.get("/audit-log", response_model=AuditLogResponse)
async def get_audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    current_user: TokenData = Depends(require_admin)
):
    """Get paginated audit log (admin only)."""
    with get_cortellis_session() as session:
        # Get total count
        total_result = session.execute(text("SELECT COUNT(*) FROM audit_log")).fetchone()
        total = total_result[0] if total_result else 0

        # Get logs with pagination
        rows = session.execute(
            text("""
                SELECT 
                    id, user_id, action, entity_type, entity_id, 
                    audit_log.ip_address, audit_log.metadata,
                    audit_log.created_at, users.email AS user_email
                FROM audit_log
                LEFT JOIN users ON users.id = audit_log.user_id
                ORDER BY audit_log.created_at DESC
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
                created_at=row.created_at.isoformat() if row.created_at else None,
                user_email=row.user_email,
            )
            for row in rows
        ]

        return AuditLogResponse(
            logs=logs,
            total=total,
            limit=limit,
            offset=offset
        )
