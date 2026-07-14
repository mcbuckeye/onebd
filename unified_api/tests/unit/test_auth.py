"""
TDD: Auth service tests — write these FIRST, then implement.
"""
import pytest
from unittest.mock import patch, MagicMock
import asyncio
from contextlib import contextmanager
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


class TestLiveAccountValidation:
    """A valid JWT cannot outlive account disablement or role changes."""

    def test_current_user_uses_live_role(self, monkeypatch):
        from unified_api.routers import auth
        from unified_api.services.auth import TokenData

        row = MagicMock(id=7, email="person@example.com", role="analyst")
        result = MagicMock()
        result.fetchone.return_value = row
        session = MagicMock()
        session.execute.return_value = result

        @contextmanager
        def fake_session():
            yield session

        monkeypatch.setattr(
            auth,
            "decode_token",
            lambda _token: TokenData(user_id=7, email="old@example.com", role="admin"),
        )
        monkeypatch.setattr(auth, "get_cortellis_session", fake_session)

        user = auth.get_current_user("Bearer token")

        assert user.email == "person@example.com"
        assert user.role == "analyst"

    def test_disabled_user_is_rejected(self, monkeypatch):
        from unified_api.routers import auth
        from unified_api.services.auth import TokenData

        result = MagicMock()
        result.fetchone.return_value = None
        session = MagicMock()
        session.execute.return_value = result

        @contextmanager
        def fake_session():
            yield session

        monkeypatch.setattr(
            auth,
            "decode_token",
            lambda _token: TokenData(user_id=7, email="person@example.com", role="admin"),
        )
        monkeypatch.setattr(auth, "get_cortellis_session", fake_session)

        with pytest.raises(HTTPException) as exc:
            auth.get_current_user("Bearer token")

        assert exc.value.status_code == 401


class TestPasswordResetDelivery:
    """Reset links are delivered safely after the database transaction closes."""

    def test_forgot_password_delivers_without_logging_token(self, monkeypatch):
        from unified_api.routers import auth
        from unified_api.services import email_digest

        user = MagicMock(id=23, email="person@example.test")
        session = MagicMock()
        session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=user)),
            MagicMock(scalar=MagicMock(return_value=False)),
            MagicMock(),
            MagicMock(),
        ]
        state = {"session_open": False}

        @contextmanager
        def fake_session():
            state["session_open"] = True
            try:
                yield session
            finally:
                state["session_open"] = False

        deliveries = []

        async def fake_threadpool(function, *args):
            assert state["session_open"] is False
            return function(*args)

        def fake_delivery(to_email, subject, html):
            deliveries.append((to_email, subject, html))
            return email_digest.EmailDeliveryResult(True, "smtp", 250)

        log_info = MagicMock()
        log_warning = MagicMock()
        monkeypatch.setattr(auth, "get_cortellis_session", fake_session)
        monkeypatch.setattr(auth, "_ensure_users_table", lambda _session: None)
        monkeypatch.setattr(
            auth, "_ensure_password_reset_tokens_table", lambda _session: None
        )
        monkeypatch.setattr(auth.secrets, "token_urlsafe", lambda _length: "private-token")
        monkeypatch.setattr(auth, "run_in_threadpool", fake_threadpool)
        monkeypatch.setattr(auth.logger, "info", log_info)
        monkeypatch.setattr(auth.logger, "warning", log_warning)
        monkeypatch.setattr(email_digest, "deliver_email", fake_delivery)
        monkeypatch.setattr(
            email_digest,
            "get_email_delivery_status",
            lambda: {"app_url": "https://onebd.example"},
        )

        response = asyncio.run(
            auth.forgot_password(auth.ForgotPasswordRequest(email=user.email))
        )

        assert response.message.startswith("If that email exists")
        assert session.commit.called
        assert deliveries == [
            (
                user.email,
                "Reset your OneBD password",
                email_digest.build_password_reset_email(
                    "https://onebd.example/reset-password?token=private-token"
                ),
            )
        ]
        logged = repr(log_info.call_args_list) + repr(log_warning.call_args_list)
        assert "private-token" not in logged

    def test_recent_request_does_not_create_or_deliver_token(self, monkeypatch):
        from unified_api.routers import auth

        user = MagicMock(id=23, email="person@example.test")
        session = MagicMock()
        session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=user)),
            MagicMock(scalar=MagicMock(return_value=True)),
        ]

        @contextmanager
        def fake_session():
            yield session

        monkeypatch.setattr(auth, "get_cortellis_session", fake_session)
        monkeypatch.setattr(auth, "_ensure_users_table", lambda _session: None)
        monkeypatch.setattr(
            auth, "_ensure_password_reset_tokens_table", lambda _session: None
        )
        token_generator = MagicMock(return_value="should-not-exist")
        monkeypatch.setattr(auth.secrets, "token_urlsafe", token_generator)

        response = asyncio.run(
            auth.forgot_password(auth.ForgotPasswordRequest(email=user.email))
        )

        assert response.message.startswith("If that email exists")
        token_generator.assert_not_called()
        assert session.execute.call_count == 2
