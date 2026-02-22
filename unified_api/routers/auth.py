"""
Authentication endpoints: register, login, get current user, password reset.
"""
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy import text
import structlog
import secrets
from datetime import datetime, timedelta

from unified_api.services.database import get_cortellis_session
from unified_api.services.auth import (
    hash_password, verify_password, create_access_token, decode_token, TokenData
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    role: str = "analyst"


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class MessageResponse(BaseModel):
    message: str


def get_current_user(authorization: Optional[str] = Header(None)) -> TokenData:
    """Extract and validate JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    data = decode_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return data


def _ensure_users_table(session):
    """Create users table if it doesn't exist."""
    # Check if table already exists to avoid pg_type conflicts
    result = session.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='users')"
    )).scalar()
    if result:
        return
    session.execute(text("""
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'analyst',
            preferences JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            last_login TIMESTAMP
        )
    """))
    session.commit()


def _ensure_password_reset_tokens_table(session):
    """Create password_reset_tokens table if it doesn't exist."""
    result = session.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='password_reset_tokens')"
    )).scalar()
    if result:
        return
    session.execute(text("""
        CREATE TABLE password_reset_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            token VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """))
    session.commit()


@router.post("/register", response_model=LoginResponse)
async def register(req: RegisterRequest):
    """Register a new user account."""
    with get_cortellis_session() as session:
        _ensure_users_table(session)

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

    token = create_access_token(user_id, req.email, req.role)
    return LoginResponse(
        access_token=token,
        user=UserResponse(id=user_id, email=req.email, name=req.name, role=req.role),
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Login with email and password."""
    with get_cortellis_session() as session:
        _ensure_users_table(session)

        row = session.execute(
            text("SELECT id, email, password_hash, name, role FROM users WHERE email = :email"),
            {"email": req.email}
        ).fetchone()

        if not row or not verify_password(req.password, row.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # Update last_login
        session.execute(
            text("UPDATE users SET last_login = NOW() WHERE id = :id"),
            {"id": row.id}
        )
        session.commit()

    token = create_access_token(row.id, row.email, row.role)
    return LoginResponse(
        access_token=token,
        user=UserResponse(id=row.id, email=row.email, name=row.name, role=row.role),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: TokenData = Depends(get_current_user)):
    """Get current authenticated user."""
    with get_cortellis_session() as session:
        row = session.execute(
            text("SELECT id, email, name, role FROM users WHERE id = :id"),
            {"id": current_user.user_id}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse(id=row.id, email=row.email, name=row.name, role=row.role)


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(req: ForgotPasswordRequest):
    """
    Request a password reset token.
    Returns success even if email doesn't exist (security best practice).
    Token is logged for now (no email service yet).
    """
    with get_cortellis_session() as session:
        _ensure_users_table(session)
        _ensure_password_reset_tokens_table(session)

        # Check if user exists
        user_row = session.execute(
            text("SELECT id, email FROM users WHERE email = :email"),
            {"email": req.email}
        ).fetchone()

        if user_row:
            # Generate reset token
            reset_token = secrets.token_urlsafe(32)
            expires_at = datetime.now() + timedelta(hours=1)  # Token valid for 1 hour

            # Store token in database
            session.execute(
                text("""
                    INSERT INTO password_reset_tokens (user_id, token, expires_at)
                    VALUES (:user_id, :token, :expires_at)
                """),
                {
                    "user_id": user_row.id,
                    "token": reset_token,
                    "expires_at": expires_at,
                }
            )
            session.commit()

            # Log the token (no email service yet)
            logger.info(
                "password_reset_token_generated",
                user_id=user_row.id,
                email=user_row.email,
                token=reset_token,
                expires_at=expires_at.isoformat()
            )

    # Always return success (don't reveal if email exists)
    return MessageResponse(message="If that email exists, a password reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(req: ResetPasswordRequest):
    """
    Reset password using a valid token.
    Token must not be expired or already used.
    """
    with get_cortellis_session() as session:
        _ensure_users_table(session)
        _ensure_password_reset_tokens_table(session)

        # Find valid token
        token_row = session.execute(
            text("""
                SELECT user_id, expires_at, used
                FROM password_reset_tokens
                WHERE token = :token
            """),
            {"token": req.token}
        ).fetchone()

        if not token_row:
            raise HTTPException(status_code=400, detail="Invalid reset token")

        if token_row.used:
            raise HTTPException(status_code=400, detail="Reset token already used")

        if datetime.now() > token_row.expires_at:
            raise HTTPException(status_code=400, detail="Reset token expired")

        # Update user password
        session.execute(
            text("""
                UPDATE users
                SET password_hash = :password_hash
                WHERE id = :user_id
            """),
            {
                "user_id": token_row.user_id,
                "password_hash": hash_password(req.new_password)
            }
        )

        # Mark token as used
        session.execute(
            text("""
                UPDATE password_reset_tokens
                SET used = TRUE
                WHERE token = :token
            """),
            {"token": req.token}
        )

        session.commit()

        logger.info("password_reset_successful", user_id=token_row.user_id)

    return MessageResponse(message="Password reset successful")
