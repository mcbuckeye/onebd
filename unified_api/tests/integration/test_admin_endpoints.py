"""
TDD: Admin endpoint tests — write these FIRST, then implement.
Tests admin user management endpoints.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_token(client):
    """Register an admin user and return auth token."""
    resp = client.post("/api/auth/register", json={
        "email": "admin_test@test.com",
        "password": "AdminPass123!",
        "name": "Test Admin",
        "role": "admin",
    })
    return resp.json()["access_token"]


@pytest.fixture
def analyst_token(client):
    """Register an analyst user and return auth token."""
    resp = client.post("/api/auth/register", json={
        "email": "analyst_test@test.com",
        "password": "AnalystPass123!",
        "name": "Test Analyst",
        "role": "analyst",
    })
    return resp.json()["access_token"]


class TestAdminListUsers:
    """Test GET /api/admin/users"""

    def test_list_users_as_admin_success(self, client, admin_token):
        resp = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Check user structure
        user = data[0]
        assert "id" in user
        assert "email" in user
        assert "name" in user
        assert "role" in user

    def test_list_users_as_analyst_fails(self, client, analyst_token):
        resp = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {analyst_token}"}
        )
        assert resp.status_code == 403

    def test_list_users_without_auth_fails(self, client):
        resp = client.get("/api/admin/users")
        assert resp.status_code == 401


class TestAdminCreateUser:
    """Test POST /api/admin/users"""

    def test_create_user_as_admin_success(self, client, admin_token):
        resp = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "email": "newuser_admin@test.com",
                "password": "NewPass123!",
                "name": "New User",
                "role": "analyst",
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "newuser_admin@test.com"
        assert data["name"] == "New User"
        assert data["role"] == "analyst"

    def test_create_user_as_analyst_fails(self, client, analyst_token):
        resp = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={
                "email": "blocked@test.com",
                "password": "Pass123!",
                "name": "Blocked",
                "role": "analyst",
            }
        )
        assert resp.status_code == 403

    def test_create_user_duplicate_email_fails(self, client, admin_token):
        # Create first user
        client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "email": "duplicate_admin@test.com",
                "password": "Pass123!",
                "name": "First",
                "role": "analyst",
            }
        )
        # Try duplicate
        resp = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "email": "duplicate_admin@test.com",
                "password": "Pass456!",
                "name": "Second",
                "role": "analyst",
            }
        )
        assert resp.status_code == 400


class TestAdminUpdateUser:
    """Test PUT /api/admin/users/{id}"""

    def test_update_user_as_admin_success(self, client, admin_token):
        # Create a user first
        create_resp = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "email": "update_test@test.com",
                "password": "Pass123!",
                "name": "Original Name",
                "role": "analyst",
            }
        )
        user_id = create_resp.json()["id"]

        # Update the user
        resp = client.put(
            f"/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "Updated Name",
                "role": "admin",
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated Name"
        assert data["role"] == "admin"

    def test_update_user_as_analyst_fails(self, client, admin_token, analyst_token):
        # Create a user as admin
        create_resp = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "email": "update_blocked@test.com",
                "password": "Pass123!",
                "name": "Test User",
                "role": "analyst",
            }
        )
        user_id = create_resp.json()["id"]

        # Try to update as analyst
        resp = client.put(
            f"/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={"name": "Hacked Name"}
        )
        assert resp.status_code == 403

    def test_update_nonexistent_user_fails(self, client, admin_token):
        resp = client.put(
            "/api/admin/users/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Ghost"}
        )
        assert resp.status_code == 404


class TestAdminDeleteUser:
    """Test DELETE /api/admin/users/{id}"""

    def test_delete_user_as_admin_success(self, client, admin_token):
        # Create a user first
        create_resp = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "email": "delete_test@test.com",
                "password": "Pass123!",
                "name": "To Delete",
                "role": "analyst",
            }
        )
        user_id = create_resp.json()["id"]

        # Delete the user
        resp = client.delete(
            f"/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200
        assert "message" in resp.json()

        # Verify user is disabled (can't login)
        login_resp = client.post("/api/auth/login", json={
            "email": "delete_test@test.com",
            "password": "Pass123!",
        })
        assert login_resp.status_code == 401

    def test_delete_user_as_analyst_fails(self, client, admin_token, analyst_token):
        # Create a user as admin
        create_resp = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "email": "delete_blocked@test.com",
                "password": "Pass123!",
                "name": "Protected",
                "role": "analyst",
            }
        )
        user_id = create_resp.json()["id"]

        # Try to delete as analyst
        resp = client.delete(
            f"/api/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {analyst_token}"}
        )
        assert resp.status_code == 403

    def test_delete_nonexistent_user_fails(self, client, admin_token):
        resp = client.delete(
            "/api/admin/users/999999",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 404


class TestAdminAuditLog:
    """Test GET /api/admin/audit-log"""

    def test_get_audit_log_as_admin_success(self, client, admin_token):
        # Perform some actions to generate audit logs
        client.post("/api/auth/login", json={
            "email": "admin_test@test.com",
            "password": "AdminPass123!",
        })
        
        # Get audit log
        resp = client.get(
            "/api/admin/audit-log",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert "total" in data
        assert isinstance(data["logs"], list)

    def test_get_audit_log_with_pagination(self, client, admin_token):
        resp = client.get(
            "/api/admin/audit-log?limit=10&offset=0",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["logs"]) <= 10

    def test_get_audit_log_as_analyst_fails(self, client, analyst_token):
        resp = client.get(
            "/api/admin/audit-log",
            headers={"Authorization": f"Bearer {analyst_token}"}
        )
        assert resp.status_code == 403

    def test_audit_log_contains_required_fields(self, client, admin_token):
        resp = client.get(
            "/api/admin/audit-log?limit=1",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp.status_code == 200
        logs = resp.json()["logs"]
        if len(logs) > 0:
            log = logs[0]
            assert "id" in log
            assert "user_id" in log
            assert "action" in log
            assert "created_at" in log
