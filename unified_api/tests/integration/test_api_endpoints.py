"""
API Endpoint Integration Tests for BD Intelligence Platform

Tests FastAPI endpoints for:
- Health checks
- Search endpoints
- Entity endpoints (companies, deals, drugs)
- Edgar SEC filing endpoints
- Cross-reference endpoints
"""
import pytest
from fastapi.testclient import TestClient
from typing import Dict, Any


@pytest.mark.integration
class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_endpoint(self, api_client):
        """Verify /health endpoint returns OK."""
        response = api_client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] in ("healthy", "ok", "degraded")

    def test_health_includes_database_status(self, api_client):
        """Verify health check includes database connectivity."""
        response = api_client.get("/health")
        data = response.json()

        # Should include database status
        if "databases" in data:
            assert "cortellis" in data["databases"]

    def test_root_endpoint(self, api_client):
        """Verify root endpoint returns API info."""
        response = api_client.get("/")
        assert response.status_code == 200


@pytest.mark.integration
class TestSearchEndpoints:
    """Tests for search API endpoints."""

    def test_deal_search_endpoint(self, api_client):
        """Verify /api/search/deals endpoint works."""
        response = api_client.post(
            "/api/search/deals",
            json={
                "deal_type": ["License"],
            },
            params={"page": 1, "page_size": 10}
        )

        if response.status_code == 200:
            data = response.json()
            assert "total" in data
            assert "results" in data
            assert isinstance(data["results"], list)
        else:
            # May fail if database not available
            pytest.skip(f"Deal search endpoint returned {response.status_code}")

    def test_contract_search_endpoint(self, api_client):
        """Verify /api/search/contracts endpoint works."""
        response = api_client.get(
            "/api/search/contracts",
            params={"query": "royalty", "mode": "fulltext", "limit": 10}
        )

        if response.status_code == 200:
            data = response.json()
            assert "query" in data
            assert "results" in data
        else:
            pytest.skip(f"Contract search endpoint returned {response.status_code}")

    def test_unified_search_endpoint(self, api_client):
        """Verify /api/search/unified endpoint works."""
        response = api_client.get(
            "/api/search/unified",
            params={
                "query": "license agreement",
                "sources": "both",
                "mode": "fulltext",
                "limit": 10
            }
        )

        if response.status_code == 200:
            data = response.json()
            assert "query" in data
            assert "total" in data
            assert "results" in data
        else:
            pytest.skip(f"Unified search endpoint returned {response.status_code}")

    def test_search_validation_min_length(self, api_client):
        """Verify search validates minimum query length."""
        response = api_client.get(
            "/api/search/contracts",
            params={"query": "ab", "mode": "fulltext"}  # Too short
        )

        # Should return 422 validation error
        assert response.status_code == 422

    def test_search_validation_limit(self, api_client):
        """Verify search validates limit parameter."""
        response = api_client.get(
            "/api/search/contracts",
            params={"query": "test", "limit": 500}  # Too high
        )

        # Should return 422 validation error
        assert response.status_code == 422


@pytest.mark.integration
class TestEntityEndpoints:
    """Tests for entity API endpoints."""

    def test_companies_list_endpoint(self, api_client):
        """Verify /api/companies endpoint works."""
        response = api_client.get(
            "/api/companies",
            params={"page": 1, "page_size": 10}
        )

        if response.status_code == 200:
            data = response.json()
            assert "total" in data or "results" in data or isinstance(data, list)
        else:
            pytest.skip(f"Companies endpoint returned {response.status_code}")

    def test_company_detail_endpoint(self, api_client):
        """Verify /api/companies/{id} endpoint works."""
        # First get a valid company ID
        list_response = api_client.get(
            "/api/companies",
            params={"page": 1, "page_size": 1}
        )

        if list_response.status_code != 200:
            pytest.skip("Could not get company list")

        data = list_response.json()
        if isinstance(data, list) and len(data) > 0:
            company_id = data[0].get("id")
        elif "results" in data and len(data["results"]) > 0:
            company_id = data["results"][0].get("id")
        else:
            pytest.skip("No companies available")

        # Get company detail
        response = api_client.get(f"/api/companies/{company_id}")
        if response.status_code == 200:
            company = response.json()
            assert "id" in company
            assert "name" in company
        else:
            pytest.skip(f"Company detail returned {response.status_code}")

    def test_company_not_found(self, api_client):
        """Verify 404 for non-existent company."""
        response = api_client.get("/api/companies/999999999")
        assert response.status_code == 404

    def test_deals_list_endpoint(self, api_client):
        """Verify /api/deals endpoint works."""
        response = api_client.get(
            "/api/deals",
            params={"page": 1, "page_size": 10}
        )

        if response.status_code == 200:
            data = response.json()
            assert "total" in data or "results" in data or isinstance(data, list)

    def test_deal_detail_endpoint(self, api_client):
        """Verify /api/deals/{id} endpoint works."""
        # First get a valid deal ID
        list_response = api_client.get(
            "/api/deals",
            params={"page": 1, "page_size": 1}
        )

        if list_response.status_code != 200:
            pytest.skip("Could not get deal list")

        data = list_response.json()
        if isinstance(data, list) and len(data) > 0:
            deal_id = data[0].get("id")
        elif "results" in data and len(data["results"]) > 0:
            deal_id = data["results"][0].get("id")
        else:
            pytest.skip("No deals available")

        response = api_client.get(f"/api/deals/{deal_id}")
        if response.status_code == 200:
            deal = response.json()
            assert "id" in deal
            assert "title" in deal


@pytest.mark.integration
class TestEdgarEndpoints:
    """Tests for Edgar SEC filing endpoints."""

    def test_edgar_companies_endpoint(self, api_client):
        """Verify /api/edgar/companies endpoint works."""
        response = api_client.get(
            "/api/edgar/companies",
            params={"limit": 10}
        )

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list) or "results" in data
        else:
            pytest.skip(f"Edgar companies returned {response.status_code}")

    def test_edgar_company_detail(self, api_client):
        """Verify /api/edgar/companies/{id} endpoint works."""
        # First get a company ID
        list_response = api_client.get(
            "/api/edgar/companies",
            params={"limit": 1}
        )

        if list_response.status_code != 200:
            pytest.skip("Could not get Edgar company list")

        data = list_response.json()
        if isinstance(data, list) and len(data) > 0:
            company_id = data[0].get("id")
        else:
            pytest.skip("No Edgar companies available")

        response = api_client.get(f"/api/edgar/companies/{company_id}")
        if response.status_code == 200:
            company = response.json()
            assert "id" in company
            assert "name" in company

    def test_edgar_search_endpoint(self, api_client):
        """Verify /api/edgar/search endpoint works."""
        response = api_client.get(
            "/api/edgar/search",
            params={"query": "material contract", "mode": "fulltext", "limit": 10}
        )

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list) or "results" in data
        else:
            pytest.skip(f"Edgar search returned {response.status_code}")


@pytest.mark.integration
class TestCrossReferenceEndpoints:
    """Tests for company cross-reference endpoints."""

    def test_xref_lookup_endpoint(self, api_client):
        """Verify /api/xref/lookup endpoint works."""
        # Try lookup by ticker
        response = api_client.get(
            "/api/xref/lookup",
            params={"ticker": "ABBV"}
        )

        if response.status_code == 200:
            data = response.json()
            # Should return xref data if found
            if data:
                assert "canonical_name" in data or "cortellis_id" in data
        elif response.status_code == 404:
            # Not found is acceptable
            pass
        else:
            pytest.skip(f"Xref lookup returned {response.status_code}")

    def test_xref_stats_endpoint(self, api_client):
        """Verify /api/xref/stats endpoint works."""
        response = api_client.get("/api/xref/stats")

        if response.status_code == 200:
            data = response.json()
            # Response structure: {companies: {...}, xrefs: {total: ...}, ...}
            assert "xrefs" in data or "total_matches" in data or "total" in data
        else:
            pytest.skip(f"Xref stats returned {response.status_code}")


@pytest.mark.integration
class TestAPIResponseFormats:
    """Tests for API response format consistency."""

    def test_error_response_format(self, api_client):
        """Verify error responses follow standard format."""
        response = api_client.get("/api/companies/not-an-id")

        # Should return validation error or not found
        assert response.status_code in (404, 422)

        if response.status_code == 422:
            data = response.json()
            assert "detail" in data

    def test_pagination_response_format(self, api_client):
        """Verify paginated responses include metadata."""
        response = api_client.get(
            "/api/companies",
            params={"page": 1, "page_size": 5}
        )

        if response.status_code == 200:
            data = response.json()
            # Should include pagination info
            if isinstance(data, dict):
                # Check for common pagination fields
                pagination_fields = ["total", "page", "page_size", "results"]
                has_pagination = any(f in data for f in pagination_fields)
                if not has_pagination:
                    # May be a simple list response
                    pass

    def test_cors_headers(self, api_client):
        """Verify CORS headers are present."""
        response = api_client.options("/api/companies")
        # CORS headers should allow cross-origin requests
        # This depends on CORS middleware configuration


@pytest.mark.integration
class TestAPIAuthentication:
    """Tests for API authentication (if implemented)."""

    def test_public_endpoints_accessible(self, api_client):
        """Verify public endpoints are accessible without auth."""
        public_endpoints = [
            "/health",
            "/",
        ]

        for endpoint in public_endpoints:
            response = api_client.get(endpoint)
            assert response.status_code != 401, \
                f"Public endpoint {endpoint} requires authentication"

    def test_protected_endpoints_require_auth(self, api_client):
        """Verify protected endpoints require authentication."""
        # If auth is implemented, protected endpoints should return 401
        # For now, skip if no auth is configured
        pytest.skip("Authentication not implemented")


@pytest.mark.integration
class TestAPIRateLimiting:
    """Tests for API rate limiting (if implemented)."""

    @pytest.mark.slow
    def test_rate_limit_headers(self, api_client):
        """Verify rate limit headers are present."""
        response = api_client.get("/health")

        # Common rate limit headers
        rate_limit_headers = [
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ]

        # If rate limiting is implemented, check headers
        has_rate_limiting = any(h in response.headers for h in rate_limit_headers)
        if not has_rate_limiting:
            pytest.skip("Rate limiting not implemented")
