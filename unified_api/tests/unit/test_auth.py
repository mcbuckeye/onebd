"""
TDD: Auth service tests — write these FIRST, then implement.
"""
import pytest
from unittest.mock import patch, MagicMock
import asyncio
from fastapi import HTTPException


class TestPasswordHashing:
    """Test password hashing and verification."""

    def test_hash_password_returns_string(self):
        from unified_api.services.auth import hash_password
        result = hash_password("testpassword123")
        assert isinstance(result, str)
        assert len(result) > 20  # bcrypt hashes are ~60 chars

    def test_hash_password_not_plaintext(self):
        from unified_api.services.auth import hash_password
        result = hash_password("testpassword123")
        assert result != "testpassword123"

    def test_verify_password_correct(self):
        from unified_api.services.auth import hash_password, verify_password
        hashed = hash_password("testpassword123")
        assert verify_password("testpassword123", hashed) is True

    def test_verify_password_incorrect(self):
        from unified_api.services.auth import hash_password, verify_password
        hashed = hash_password("testpassword123")
        assert verify_password("wrongpassword", hashed) is False

    def test_different_passwords_different_hashes(self):
        from unified_api.services.auth import hash_password
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2


class TestJWTTokens:
    """Test JWT token creation and decoding."""

    def test_create_access_token_returns_string(self):
        from unified_api.services.auth import create_access_token
        token = create_access_token(user_id=1, email="test@test.com", role="analyst")
        assert isinstance(token, str)
        assert len(token) > 50  # JWT tokens are long

    def test_decode_valid_token(self):
        from unified_api.services.auth import create_access_token, decode_token
        token = create_access_token(user_id=42, email="jvo@beigene.com", role="ceo")
        data = decode_token(token)
        assert data is not None
        assert data.user_id == 42
        assert data.email == "jvo@beigene.com"
        assert data.role == "ceo"

    def test_decode_invalid_token_returns_none(self):
        from unified_api.services.auth import decode_token
        data = decode_token("this.is.not.a.valid.token")
        assert data is None

    def test_decode_expired_token_returns_none(self):
        from unified_api.services.auth import decode_token, SECRET_KEY, ALGORITHM
        from jose import jwt
        from datetime import datetime, timedelta, timezone
        expired_payload = {
            "sub": "1",
            "email": "test@test.com",
            "role": "analyst",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)
        data = decode_token(expired_token)
        assert data is None

    def test_token_contains_correct_claims(self):
        from unified_api.services.auth import create_access_token, SECRET_KEY, ALGORITHM
        from jose import jwt
        token = create_access_token(user_id=5, email="analyst@company.com", role="analyst")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "5"
        assert payload["email"] == "analyst@company.com"
        assert payload["role"] == "analyst"
        assert "exp" in payload


class TestRegistrationPolicy:
    """Registration cannot create an admin or bypass owner policy."""

    def test_register_payload_cannot_choose_a_role(self):
        from unified_api.routers.auth import RegisterRequest

        request = RegisterRequest(
            email="attacker@example.com",
            password="not-used",
            name="Attacker",
            role="admin",
        )

        assert not hasattr(request, "role")

    def test_owner_can_disable_self_registration(self, monkeypatch):
        from unified_api.routers import auth

        monkeypatch.setattr(
            auth,
            "get_data_access_policy",
            lambda: {"allow_self_registration": False},
        )
        request = auth.RegisterRequest(
            email="analyst@example.com",
            password="not-used",
            name="Analyst",
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(auth.register(request))

        assert exc.value.status_code == 403
