"""Hashed API credentials and owner-controlled read-access policy."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import secrets
from typing import Any

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy import text

from unified_api.services.auth import TokenData, decode_token
from unified_api.services.database import get_cortellis_session


ALLOWED_SCOPES = frozenset({
    "catalog:read",
    "deals:read",
    "companies:read",
    "drugs:read",
    "trials:read",
    "biology:read",
    "sources:read",
    "data:read",
})
ACCESS_MODES = frozenset({"key_required", "authenticated", "open"})
DATASETS = frozenset({
    "catalog",
    "cortellis_deals",
    "integrated_companies",
    "integrated_drugs",
    "sec_edgar",
    "clinicaltrials_gov",
    "public_biology",
    "source_status",
})

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_schema_ready = False


class DataPrincipal(BaseModel):
    """Identity authorized to use the versioned colleague data API."""

    principal_type: str
    principal_id: str
    name: str
    scopes: list[str]


def ensure_api_access_schema() -> None:
    """Create the small credential and policy schema idempotently."""
    global _schema_ready
    if _schema_ready:
        return
    with get_cortellis_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS api_credentials (
                id BIGSERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                key_prefix VARCHAR(24) NOT NULL UNIQUE,
                key_hash CHAR(64) NOT NULL UNIQUE,
                scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_by INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ,
                revoked_at TIMESTAMPTZ,
                last_used_at TIMESTAMPTZ,
                last_used_path VARCHAR(500),
                use_count BIGINT NOT NULL DEFAULT 0
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_api_credentials_active
            ON api_credentials (key_hash)
            WHERE revoked_at IS NULL
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS data_access_policy (
                singleton BOOLEAN PRIMARY KEY DEFAULT TRUE
                    CHECK (singleton),
                access_mode VARCHAR(20) NOT NULL DEFAULT 'key_required',
                enforce_scopes BOOLEAN NOT NULL DEFAULT TRUE,
                allow_self_registration BOOLEAN NOT NULL DEFAULT FALSE,
                protect_existing_api BOOLEAN NOT NULL DEFAULT FALSE,
                disabled_datasets JSONB NOT NULL DEFAULT '[]'::jsonb,
                updated_by INTEGER,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CHECK (access_mode IN ('key_required', 'authenticated', 'open'))
            )
        """))
        session.execute(text("""
            INSERT INTO data_access_policy (singleton)
            VALUES (TRUE) ON CONFLICT (singleton) DO NOTHING
        """))
        session.execute(text("""
            ALTER TABLE data_access_policy
            ADD COLUMN IF NOT EXISTS allow_self_registration BOOLEAN
                NOT NULL DEFAULT FALSE
        """))
        session.execute(text("""
            ALTER TABLE data_access_policy
            ADD COLUMN IF NOT EXISTS protect_existing_api BOOLEAN
                NOT NULL DEFAULT FALSE
        """))
    _schema_ready = True


def _normalize_scopes(scopes: list[str]) -> list[str]:
    normalized = sorted(set(scopes))
    invalid = sorted(set(normalized) - ALLOWED_SCOPES)
    if invalid:
        raise ValueError(f"Unsupported API scopes: {', '.join(invalid)}")
    return normalized


def create_api_credential(
    *,
    name: str,
    scopes: list[str],
    created_by: int,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    """Create a credential and return its plaintext exactly once."""
    ensure_api_access_schema()
    scopes = _normalize_scopes(scopes)
    if not name.strip():
        raise ValueError("Credential name is required")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise ValueError("Credential expiry must be in the future")

    key_prefix = secrets.token_hex(6)
    plaintext = f"onebd_{key_prefix}_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    with get_cortellis_session() as session:
        row = session.execute(text("""
            INSERT INTO api_credentials (
                name, key_prefix, key_hash, scopes, created_by, expires_at
            ) VALUES (
                :name, :key_prefix, :key_hash, CAST(:scopes AS JSONB),
                :created_by, :expires_at
            )
            RETURNING id, name, key_prefix, scopes, created_at, expires_at
        """), {
            "name": name.strip(),
            "key_prefix": key_prefix,
            "key_hash": key_hash,
            "scopes": json.dumps(scopes),
            "created_by": created_by,
            "expires_at": expires_at,
        }).mappings().one()
    result = dict(row)
    result["api_key"] = plaintext
    return result


def list_api_credentials() -> list[dict[str, Any]]:
    ensure_api_access_schema()
    with get_cortellis_session() as session:
        rows = session.execute(text("""
            SELECT id, name, key_prefix, scopes, created_by, created_at,
                   expires_at, revoked_at, last_used_at, last_used_path,
                   use_count
            FROM api_credentials
            ORDER BY created_at DESC, id DESC
        """)).mappings().all()
    return [dict(row) for row in rows]


def revoke_api_credential(credential_id: int) -> bool:
    ensure_api_access_schema()
    with get_cortellis_session() as session:
        result = session.execute(text("""
            UPDATE api_credentials
            SET revoked_at = COALESCE(revoked_at, NOW())
            WHERE id = :credential_id
            RETURNING id
        """), {"credential_id": credential_id}).scalar()
    return result is not None


def get_data_access_policy() -> dict[str, Any]:
    ensure_api_access_schema()
    with get_cortellis_session() as session:
        row = session.execute(text("""
            SELECT access_mode, enforce_scopes, disabled_datasets,
                   allow_self_registration, protect_existing_api,
                   updated_by, updated_at
            FROM data_access_policy WHERE singleton = TRUE
        """)).mappings().one()
    return dict(row)


def update_data_access_policy(
    *,
    access_mode: str,
    enforce_scopes: bool,
    allow_self_registration: bool,
    protect_existing_api: bool,
    disabled_datasets: list[str],
    updated_by: int,
) -> dict[str, Any]:
    ensure_api_access_schema()
    if access_mode not in ACCESS_MODES:
        raise ValueError(f"Unsupported access mode: {access_mode}")
    disabled = sorted(set(disabled_datasets))
    invalid = sorted(set(disabled) - DATASETS)
    if invalid:
        raise ValueError(f"Unsupported datasets: {', '.join(invalid)}")
    with get_cortellis_session() as session:
        row = session.execute(text("""
            UPDATE data_access_policy
            SET access_mode = :access_mode,
                enforce_scopes = :enforce_scopes,
                allow_self_registration = :allow_self_registration,
                protect_existing_api = :protect_existing_api,
                disabled_datasets = CAST(:disabled AS JSONB),
                updated_by = :updated_by,
                updated_at = NOW()
            WHERE singleton = TRUE
            RETURNING access_mode, enforce_scopes, allow_self_registration,
                      protect_existing_api, disabled_datasets, updated_by,
                      updated_at
        """), {
            "access_mode": access_mode,
            "enforce_scopes": enforce_scopes,
            "allow_self_registration": allow_self_registration,
            "protect_existing_api": protect_existing_api,
            "disabled": json.dumps(disabled),
            "updated_by": updated_by,
        }).mappings().one()
    return dict(row)


def _bearer_principal(request: Request) -> DataPrincipal | None:
    """Resolve a signed-in user and re-check current account status."""
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token: TokenData | None = decode_token(authorization.split(" ", 1)[1])
    if token is None:
        return None
    with get_cortellis_session() as session:
        account = session.execute(text("""
            SELECT id, email
            FROM users
            WHERE id = :user_id AND disabled IS NOT TRUE
        """), {"user_id": token.user_id}).mappings().first()
    if account is None:
        return None
    return DataPrincipal(
        principal_type="user",
        principal_id=str(account["id"]),
        name=account["email"],
        scopes=["data:read"],
    )


def _api_key_principal(api_key: str | None, path: str) -> DataPrincipal | None:
    if not api_key:
        return None
    ensure_api_access_schema()
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    with get_cortellis_session() as session:
        row = session.execute(text("""
            SELECT id, name, scopes
            FROM api_credentials
            WHERE key_hash = :key_hash
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > NOW())
        """), {"key_hash": key_hash}).mappings().first()
        if row:
            session.execute(text("""
                UPDATE api_credentials
                SET last_used_at = NOW(), last_used_path = :path,
                    use_count = use_count + 1
                WHERE id = :credential_id
            """), {"path": path[:500], "credential_id": row["id"]})
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked API key",
        )
    return DataPrincipal(
        principal_type="api_key",
        principal_id=str(row["id"]),
        name=row["name"],
        scopes=list(row["scopes"] or []),
    )


def require_data_access(scope: str, dataset: str):
    """Build a FastAPI dependency honoring the mutable owner policy."""
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"Unsupported API scope: {scope}")
    if dataset not in DATASETS:
        raise ValueError(f"Unsupported dataset: {dataset}")

    async def dependency(
        request: Request,
        api_key: str | None = Security(api_key_header),
    ) -> DataPrincipal:
        policy = get_data_access_policy()
        if dataset in set(policy["disabled_datasets"] or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Dataset disabled by owner policy: {dataset}",
            )

        mode = policy["access_mode"]
        if mode == "open":
            principal = DataPrincipal(
                principal_type="anonymous",
                principal_id="anonymous",
                name="anonymous",
                scopes=["data:read"],
            )
        else:
            principal = _api_key_principal(api_key, request.url.path)
            if principal is None and mode == "authenticated":
                principal = _bearer_principal(request)
            if principal is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="A valid API key is required",
                )

        if policy["enforce_scopes"] and not (
            scope in principal.scopes or "data:read" in principal.scopes
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API credential lacks scope: {scope}",
            )
        return principal

    return dependency


def authorize_existing_api_request(request: Request) -> DataPrincipal | None:
    """Apply the owner policy to legacy application APIs when opted in."""
    policy = get_data_access_policy()
    if not policy["protect_existing_api"]:
        return None
    mode = policy["access_mode"]
    if mode == "open":
        return DataPrincipal(
            principal_type="anonymous",
            principal_id="anonymous",
            name="anonymous",
            scopes=["data:read"],
        )
    api_key = request.headers.get("x-api-key")
    principal = _api_key_principal(api_key, request.url.path)
    if principal is None and mode == "authenticated":
        principal = _bearer_principal(request)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid API key is required",
        )
    if policy["enforce_scopes"] and "data:read" not in principal.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API credential lacks scope: data:read",
        )
    return principal
