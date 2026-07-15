"""Protocol and HTTP-boundary tests for the OneBD MCP adapter."""

import json

import httpx

from unified_api.mcp_server import OneBDMCPServer


def test_initialize_and_tool_listing_are_valid_json_rpc():
    server = OneBDMCPServer(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(500))
        )
    )

    initialized = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert initialized["result"]["serverInfo"]["name"] == "onebd"
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert {
        "get_entity_counts",
        "get_data_catalog",
        "search_deals",
        "search_deals_advanced",
        "search_assets_advanced",
        "get_deal",
        "search_financial_terms",
        "get_company_oncology_assets",
        "get_company_asset_rights",
        "get_company_manufacturing_relationships",
    } <= names


def test_entity_counts_tool_uses_dedicated_endpoint():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"deals": 172643, "companies": 67177, "assets": 33912},
        )

    server = OneBDMCPServer(
        base_url="https://onebd.example/api/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {"name": "get_entity_counts", "arguments": {}},
        }
    )

    assert observed["url"] == "https://onebd.example/api/v1/counts"
    assert response["result"]["structuredContent"]["assets"] == 33912


def test_advanced_search_tools_publish_nested_schema_and_post_json():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["url"] = str(request.url)
        observed["body"] = json.loads(request.content)
        observed["key"] = request.headers.get("X-API-Key")
        return httpx.Response(200, json={"items": [{"id": 7}]})

    server = OneBDMCPServer(
        base_url="https://onebd.example/api/v1",
        api_key="onebd_secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "search_assets_advanced",
                "arguments": {
                    "companies": {"any": [{"name": "DotBio"}]},
                    "dates": [{"field": "date_start", "gte": "2020-01-01"}],
                    "limit": 10,
                },
            },
        }
    )

    tools = server.handle({"jsonrpc": "2.0", "id": 13, "method": "tools/list"})
    schema = next(
        tool["inputSchema"]
        for tool in tools["result"]["tools"]
        if tool["name"] == "search_assets_advanced"
    )
    assert "companies" in schema["properties"]
    assert "dates" in schema["properties"]
    assert "values" in schema["properties"]
    assert observed == {
        "method": "POST",
        "url": "https://onebd.example/api/v1/assets/search",
        "body": {
            "companies": {"any": [{"name": "DotBio"}]},
            "dates": [{"field": "date_start", "gte": "2020-01-01"}],
            "limit": 10,
        },
        "key": "onebd_secret",
    }
    assert response["result"]["structuredContent"]["items"][0]["id"] == 7


def test_advanced_search_tool_rejects_invalid_nested_filters_before_post():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    server = OneBDMCPServer(client=httpx.Client(transport=httpx.MockTransport(handler)))
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "search_deals_advanced",
                "arguments": {
                    "dates": [
                        {
                            "field": "date_start",
                            "gte": "2025-02-01",
                            "lte": "2025-01-01",
                        }
                    ]
                },
            },
        }
    )

    assert response["error"]["code"] == -32602
    assert "Date range" in response["error"]["message"]
    assert called is False


def test_initialize_negotiates_a_supported_version_and_notifications_are_silent():
    server = OneBDMCPServer(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(500))
        )
    )

    initialized = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "initialize",
            "params": {"protocolVersion": "2099-01-01"},
        }
    )

    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert (
        server.handle(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
        )
        is None
    )


def test_tool_arguments_are_validated_before_http_call():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    server = OneBDMCPServer(client=httpx.Client(transport=httpx.MockTransport(handler)))
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "search_deals",
                "arguments": {"limit": 101, "unrecognized": "value"},
            },
        }
    )

    assert response["error"]["code"] == -32602
    assert called is False


def test_tool_call_uses_governed_api_key_and_query_parameters():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["key"] = request.headers.get("X-API-Key")
        return httpx.Response(200, json={"items": [{"id": 42}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    server = OneBDMCPServer(
        base_url="https://onebd.example/api/v1",
        api_key="onebd_secret",
        client=client,
    )

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search_deals",
                "arguments": {"query": "oncology", "limit": 10},
            },
        }
    )

    result = response["result"]
    assert result["structuredContent"] == {"items": [{"id": 42}]}
    assert json.loads(result["content"][0]["text"])["items"][0]["id"] == 42
    assert observed["key"] == "onebd_secret"
    assert "query=oncology" in observed["url"]
    assert "limit=10" in observed["url"]


def test_get_deal_moves_identifier_into_path():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        return httpx.Response(200, json={"id": 123})

    server = OneBDMCPServer(
        base_url="https://onebd.example/api/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_deal", "arguments": {"deal_id": 123}},
        }
    )

    assert response["result"]["structuredContent"]["id"] == 123
    assert observed["url"] == "https://onebd.example/api/v1/deals/123"


def test_company_intelligence_tool_moves_company_identifier_into_path():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        return httpx.Response(200, json={"assets": [{"asset_name": "HCB-101"}]})

    server = OneBDMCPServer(
        base_url="https://onebd.example/api/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "get_company_oncology_assets",
                "arguments": {"company_id": 1319537},
            },
        }
    )

    assert (
        response["result"]["structuredContent"]["assets"][0]["asset_name"] == "HCB-101"
    )
    assert observed["url"] == (
        "https://onebd.example/api/v1/companies/1319537/oncology-assets"
    )


def test_financial_terms_tool_uses_governed_filter_parameters():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        return httpx.Response(200, json={"items": [{"id": 99}]})

    server = OneBDMCPServer(
        base_url="https://onebd.example/api/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "search_financial_terms",
                "arguments": {
                    "term_type": "upfront_payment",
                    "min_amount_usd_millions": 100.5,
                    "limit": 10,
                },
            },
        }
    )

    assert response["result"]["structuredContent"]["items"][0]["id"] == 99
    assert "term_type=upfront_payment" in observed["url"]
    assert "min_amount_usd_millions=100.5" in observed["url"]
    assert "limit=10" in observed["url"]


def test_financial_terms_number_filters_reject_booleans_and_bounds():
    server = OneBDMCPServer(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
        )
    )

    boolean = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "search_financial_terms",
                "arguments": {"min_amount_usd_millions": True},
            },
        }
    )
    too_high = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "search_financial_terms",
                "arguments": {"min_rate_pct": 101},
            },
        }
    )

    assert boolean["error"]["code"] == -32602
    assert too_high["error"]["code"] == -32602


def test_http_errors_do_not_echo_api_key():
    server = OneBDMCPServer(
        api_key="onebd_do_not_leak",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    403, request=request, json={"detail": "Dataset disabled"}
                )
            )
        ),
    )
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "get_data_catalog", "arguments": {}},
        }
    )

    text = response["result"]["content"][0]["text"]
    assert response["result"]["isError"] is True
    assert "Dataset disabled" in text
    assert "onebd_do_not_leak" not in text
