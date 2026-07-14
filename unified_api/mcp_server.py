"""Dependency-free MCP stdio adapter for the governed OneBD data API.

Run with::

    ONEBD_API_URL=https://onebd.pchomelab.com/api/v1 \
    ONEBD_API_KEY=onebd_... python -m unified_api.mcp_server

The adapter intentionally calls the governed HTTP surface. It never receives
database credentials and therefore follows the same revocation, scope, dataset,
and owner-policy controls as other colleague integrations.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx


PROTOCOL_VERSION = "2025-06-18"


TOOLS = [
    {
        "name": "get_data_catalog",
        "description": "Get live OneBD dataset counts, provenance, and license notes.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_deals",
        "description": "Search cursor-paginated Cortellis deal summaries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "company_id": {"type": "integer"},
                "drug_id": {"type": "integer"},
                "indication_id": {"type": "integer"},
                "after_id": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_deal",
        "description": "Get one normalized Cortellis deal and its related entities.",
        "inputSchema": {
            "type": "object",
            "properties": {"deal_id": {"type": "integer", "minimum": 1}},
            "required": ["deal_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_financial_terms",
        "description": (
            "Search normalized Cortellis deal financial terms with source provenance."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "integer", "minimum": 1},
                "term_type": {"type": "string"},
                "basis": {"type": "string"},
                "disclosure_status": {"type": "string"},
                "min_amount_usd_millions": {"type": "number", "minimum": 0},
                "min_rate_pct": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                },
                "after_id": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_companies",
        "description": "Search deal-referenced companies and verified identifiers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "after_id": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_drugs",
        "description": "Search deal assets, aliases, phases, and public identifiers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "after_id": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_clinical_trials",
        "description": "List ClinicalTrials.gov records with exact company/drug filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "company_id": {"type": "integer"},
                "drug_id": {"type": "integer"},
                "after_nct_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_targets",
        "description": "List Open Targets concepts linked to OneBD drugs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "after_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_diseases",
        "description": "List disease concepts linked to OneBD drugs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "after_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_edgar_documents",
        "description": "List SEC filing metadata and canonical source URLs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "form": {"type": "string"},
                "cik": {"type": "string"},
                "after_id": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_source_status",
        "description": "Get monitored freshness and status for OneBD source jobs.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


TOOL_ROUTES = {
    "get_data_catalog": ("catalog", None),
    "search_deals": ("deals", None),
    "get_deal": ("deals/{deal_id}", "deal_id"),
    "search_financial_terms": ("financial-terms", None),
    "search_companies": ("companies", None),
    "search_drugs": ("drugs", None),
    "search_clinical_trials": ("clinical-trials", None),
    "list_targets": ("biology/targets", None),
    "list_diseases": ("biology/diseases", None),
    "list_edgar_documents": ("edgar/documents", None),
    "get_source_status": ("source-status", None),
}


class OneBDMCPServer:
    """Small JSON-RPC MCP server backed by the governed HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get(
                "ONEBD_API_URL", "https://onebd.pchomelab.com/api/v1"
            )
        ).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get(
            "ONEBD_API_KEY"
        )
        self.client = client or httpx.Client(timeout=30.0)

    def _result(self, request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error(
        self, request_id: Any, code: int, message: str
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        route = TOOL_ROUTES.get(name)
        if route is None:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }
        path, path_argument = route
        params = dict(arguments)
        if path_argument:
            if path_argument not in params:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Missing required argument: {path_argument}",
                    }],
                    "isError": True,
                }
            path = path.format(**{path_argument: params.pop(path_argument)})
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            response = self.client.get(
                f"{self.base_url}/{path}", params=params, headers=headers
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            message = f"OneBD API returned HTTP {exc.response.status_code}"
            try:
                detail = exc.response.json().get("detail")
                if detail:
                    message += f": {detail}"
            except (ValueError, AttributeError):
                pass
            return {
                "content": [{"type": "text", "text": message}],
                "isError": True,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "content": [{
                    "type": "text",
                    "text": f"OneBD API request failed: {type(exc).__name__}",
                }],
                "isError": True,
            }
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(payload, default=str, separators=(",", ":")),
            }],
            "structuredContent": payload,
            "isError": False,
        }

    def _validate_tool_arguments(
        self, name: str, arguments: dict[str, Any]
    ) -> str | None:
        tool = next((item for item in TOOLS if item["name"] == name), None)
        if tool is None:
            return f"Unknown tool: {name}"
        schema = tool["inputSchema"]
        properties = schema.get("properties", {})
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            return f"Unknown tool arguments: {', '.join(unknown)}"
        missing = sorted(set(schema.get("required", [])) - set(arguments))
        if missing:
            return f"Missing required arguments: {', '.join(missing)}"
        for key, value in arguments.items():
            specification = properties[key]
            expected = specification.get("type")
            valid_type = (
                (expected == "integer" and isinstance(value, int)
                 and not isinstance(value, bool))
                or (expected == "number" and isinstance(value, (int, float))
                    and not isinstance(value, bool))
                or (expected == "string" and isinstance(value, str))
            )
            if not valid_type:
                return f"Tool argument {key} must be a {expected}"
            if expected in {"integer", "number"}:
                if "minimum" in specification and value < specification["minimum"]:
                    return f"Tool argument {key} is below its minimum"
                if "maximum" in specification and value > specification["maximum"]:
                    return f"Tool argument {key} is above its maximum"
        return None

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        is_notification = "id" not in message
        if is_notification:
            return None
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid JSON-RPC request")
        if method == "initialize":
            requested = message.get("params", {}).get("protocolVersion")
            protocol = PROTOCOL_VERSION
            if requested == PROTOCOL_VERSION:
                protocol = requested
            return self._result(request_id, {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "onebd", "version": "1.0.0"},
                "instructions": (
                    "Read-only access to source-attributed OneBD data. License "
                    "metadata is advisory; owner policy controls access."
                ),
            })
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(request_id, {"tools": TOOLS})
        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return self._error(request_id, -32602, "Tool arguments must be an object")
            validation_error = self._validate_tool_arguments(name, arguments)
            if validation_error:
                return self._error(request_id, -32602, validation_error)
            return self._result(request_id, self._call_tool(name, arguments))
        return self._error(request_id, -32601, f"Method not found: {method}")


def main() -> None:
    server = OneBDMCPServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = server.handle(message)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            response = server._error(None, -32700, f"Invalid JSON-RPC message: {exc}")
        if response is not None:
            sys.stdout.write(json.dumps(response, default=str) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
