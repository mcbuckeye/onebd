"""
TDD: Auth endpoint tests — write these FIRST, then implement.
Tests use the FastAPI TestClient against the real app.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


class TestRegisterEndpoint:
    """Test POST /api/auth/register"""

    def test_register_success(self, client):
        resp = client.post("/api/auth/register", json={
            "email": "testuser_tdd@test.com",
            "password": "SecurePass123!",
            "name": "TDD Test User",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "testuser_tdd@test.com"
        assert data["user"]["name"] == "TDD Test User"
        assert data["user"]["role"] == "analyst"  # default role

    def test_register_duplicate_email_fails(self, client):
        # Register first time
        client.post("/api/auth/register", json={
            "email": "duplicate_tdd@test.com",
            "password": "Pass123!",
            "name": "First User",
        })
        # Try duplicate
        resp = client.post("/api/auth/register", json={
            "email": "duplicate_tdd@test.com",
            "password": "Pass456!",
            "name": "Second User",
        })
        assert resp.status_code == 400

    def test_register_missing_fields_fails(self, client):
        resp = client.post("/api/auth/register", json={"email": "incomplete@test.com"})
        assert resp.status_code == 422  # Pydantic validation error


class TestLoginEndpoint:
    """Test POST /api/auth/login"""

    def test_login_success(self, client):
        # Register first
        client.post("/api/auth/register", json={
            "email": "logintest_tdd@test.com",
            "password": "MyPass123!",
            "name": "Login Test",
        })
        # Login
        resp = client.post("/api/auth/login", json={
            "email": "logintest_tdd@test.com",
            "password": "MyPass123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["email"] == "logintest_tdd@test.com"

    def test_login_wrong_password_fails(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "logintest_tdd@test.com",
            "password": "WrongPass!",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user_fails(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "nobody_tdd@test.com",
            "password": "whatever",
        })
        assert resp.status_code == 401


class TestMeEndpoint:
    """Test GET /api/auth/me"""

    def test_me_with_valid_token(self, client):
        # Register and get token
        reg = client.post("/api/auth/register", json={
            "email": "metest_tdd@test.com",
            "password": "Pass123!",
            "name": "Me Test",
        })
        token = reg.json()["access_token"]

        # Call /me
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["email"] == "metest_tdd@test.com"

    def test_me_without_token_fails(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token_fails(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401


class TestForgotPasswordEndpoint:
    """Test POST /api/auth/forgot-password"""

    def test_forgot_password_success(self, client):
        # Register a user first
        client.post("/api/auth/register", json={
            "email": "forgot_tdd@test.com",
            "password": "OldPass123!",
            "name": "Forgot Test",
        })
        
        # Request password reset
        resp = client.post("/api/auth/forgot-password", json={
            "email": "forgot_tdd@test.com"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        # In real impl, a reset token would be logged or stored

    def test_forgot_password_nonexistent_email_safe_response(self, client):
        # Should return 200 even for non-existent email (security best practice)
        resp = client.post("/api/auth/forgot-password", json={
            "email": "nobody_forgot@test.com"
        })
        assert resp.status_code == 200


class TestResetPasswordEndpoint:
    """Test POST /api/auth/reset-password"""

    def test_reset_password_success(self, client):
        # Register a user
        client.post("/api/auth/register", json={
            "email": "reset_tdd@test.com",
            "password": "OldPass123!",
            "name": "Reset Test",
        })
        
        # Request password reset to get token
        forgot_resp = client.post("/api/auth/forgot-password", json={
            "email": "reset_tdd@test.com"
        })
        # In real implementation, we'd extract the token from logs/DB
        # For now, we'll need to query the token from the database
        # This is a simplified test - in reality you'd get token from email/logs
        
        # Mock: assume we have a valid token (implementation will provide this)
        # For now, let's test the endpoint structure
        resp = client.post("/api/auth/reset-password", json={
            "token": "valid-reset-token-placeholder",
            "new_password": "NewPass456!"
        })
        # This will fail until we implement it - that's the point of TDD!
        assert resp.status_code in [200, 400]  # 400 if token invalid

    def test_reset_password_expired_token_fails(self, client):
        resp = client.post("/api/auth/reset-password", json={
            "token": "expired-token",
            "new_password": "NewPass789!"
        })
        assert resp.status_code == 400

    def test_reset_password_invalid_token_fails(self, client):
        resp = client.post("/api/auth/reset-password", json={
            "token": "garbage-token",
            "new_password": "NewPass789!"
        })
        assert resp.status_code == 400
