"""Hosted MCP Streamable HTTP transport tests."""

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from unified_api.routers import mcp_http
from unified_api.services.api_credentials import DataPrincipal


def _app(monkeypatch):
    observed = {}

    def authorize(request, api_key):
        observed["authorized_key"] = api_key
        return DataPrincipal(
            principal_type="api_key",
            principal_id="1",
            name="test",
            scopes=["deals:read"],
        )

    monkeypatch.setattr(mcp_http, "authorize_mcp_request", authorize)
    app = FastAPI()

    @app.get("/api/v1/deals")
    async def deals(
        query: str | None = None,
        x_api_key: str | None = Header(default=None),
    ):
        observed.update(query=query, forwarded_key=x_api_key)
        return {"items": [{"id": 42, "summary": query}]}

    app.include_router(mcp_http.router)
    return app, observed


def test_initialize_and_tool_list_over_streamable_http(monkeypatch):
    app, observed = _app(monkeypatch)
    client = TestClient(app)

    initialized = client.post(
        "/mcp",
        headers={"X-API-Key": "onebd_test"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
    )
    tools = client.post(
        "/mcp",
        headers={"Authorization": "Bearer onebd_test"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )

    assert initialized.status_code == 200
    assert initialized.headers["MCP-Protocol-Version"] == "2025-06-18"
    assert initialized.json()["result"]["serverInfo"]["name"] == "onebd"
    assert tools.status_code == 200
    assert "search_deals" in {
        tool["name"] for tool in tools.json()["result"]["tools"]
    }
    assert observed["authorized_key"] == "onebd_test"


def test_tool_call_forwards_key_through_governed_api_route(monkeypatch):
    app, observed = _app(monkeypatch)
    response = TestClient(app).post(
        "/mcp",
        headers={"X-API-Key": "onebd_scoped"},
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search_deals",
                "arguments": {"query": "oncology"},
            },
        },
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["items"][0]["id"] == 42
    assert observed == {
        "authorized_key": "onebd_scoped",
        "query": "oncology",
        "forwarded_key": "onebd_scoped",
    }


def test_notification_is_acknowledged_without_json_body(monkeypatch):
    app, _observed = _app(monkeypatch)
    response = TestClient(app).post(
        "/mcp",
        headers={"X-API-Key": "onebd_test"},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    assert response.status_code == 202
    assert response.content == b""


def test_untrusted_browser_origin_is_rejected(monkeypatch):
    app, _observed = _app(monkeypatch)
    response = TestClient(app).post(
        "/mcp",
        headers={
            "X-API-Key": "onebd_test",
            "Origin": "https://attacker.example",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )

    assert response.status_code == 403


def test_invalid_params_return_json_rpc_error_instead_of_server_error(monkeypatch):
    app, _observed = _app(monkeypatch)
    response = TestClient(app).post(
        "/mcp",
        headers={"X-API-Key": "onebd_test"},
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": ["not", "an", "object"],
        },
    )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602
