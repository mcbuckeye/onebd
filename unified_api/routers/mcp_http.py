"""Hosted stateless Streamable HTTP transport for the OneBD MCP server."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from unified_api.config import settings
from unified_api.mcp_server import PROTOCOL_VERSION, OneBDMCPServer
from unified_api.services.api_credentials import authorize_mcp_request


router = APIRouter(tags=["MCP"])
MAX_REQUEST_BYTES = 1_000_000


def _api_key(request: Request) -> str | None:
    """Accept the existing header plus Bearer form used by remote MCP clients."""
    api_key = request.headers.get("x-api-key")
    authorization = request.headers.get("authorization", "")
    if not api_key and authorization.startswith("Bearer "):
        candidate = authorization.split(" ", 1)[1].strip()
        if candidate.startswith("onebd_"):
            api_key = candidate
    return api_key


def _allowed_origins(request: Request) -> set[str]:
    allowed = {str(request.base_url).rstrip("/")}
    app_url = getattr(settings, "app_url", None)
    if app_url:
        allowed.add(str(app_url).rstrip("/"))
    configured = getattr(settings, "allowed_origins", "")
    if configured and configured != "*":
        allowed.update(item.strip().rstrip("/") for item in configured.split(","))
    return allowed


def _validate_origin(request: Request) -> None:
    """Reject unexpected browser origins to prevent DNS-rebinding attacks."""
    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlparse(origin)
    normalized = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if normalized not in _allowed_origins(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin is not allowed for the MCP endpoint",
        )


async def _messages(request: Request) -> list[dict[str, Any]]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type.lower() != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="MCP requests must use application/json",
        )
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > MAX_REQUEST_BYTES
        except ValueError:
            too_large = False
        if too_large:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="MCP request is too large",
            )
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="MCP request is too large",
        )
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [{"jsonrpc": "2.0", "id": None, "method": "__parse_error__"}]
    messages = payload if isinstance(payload, list) else [payload]
    if not messages or not all(isinstance(item, dict) for item in messages):
        return [{"jsonrpc": "2.0", "id": None, "method": "__invalid__"}]
    return messages


@router.post("/mcp")
async def mcp(request: Request) -> Response:
    """Process MCP JSON-RPC requests over stateless Streamable HTTP."""
    _validate_origin(request)
    api_key = _api_key(request)
    authorize_mcp_request(request, api_key)
    messages = await _messages(request)

    # ASGITransport keeps tool calls inside the service while still traversing
    # the governed /api/v1 routes and all of their policy dependencies.
    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://onebd.internal",
        timeout=30.0,
    ) as client:
        server = OneBDMCPServer(
            base_url="http://onebd.internal/api/v1",
            api_key=api_key,
        )
        responses = []
        for message in messages:
            if message.get("method") == "__parse_error__":
                response = server._error(None, -32700, "Invalid JSON-RPC message")
            elif message.get("method") == "__invalid__":
                response = server._error(None, -32600, "Invalid JSON-RPC request")
            else:
                response = await server.handle_async(message, client)
            if response is not None:
                responses.append(response)

    if not responses:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    payload: Any = responses if len(messages) > 1 else responses[0]
    return JSONResponse(
        content=payload,
        headers={"MCP-Protocol-Version": PROTOCOL_VERSION},
    )


@router.get("/mcp")
async def mcp_event_stream_not_supported() -> Response:
    """The stateless server does not maintain an unsolicited SSE stream."""
    return JSONResponse(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        content={"detail": "This MCP endpoint accepts Streamable HTTP POST requests"},
        headers={"Allow": "POST"},
    )
