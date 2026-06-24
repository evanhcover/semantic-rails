from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from semantic_rails.asgi import SemanticLayerASGIApp
from semantic_rails.mcp import MCP_TOOL_DEFINITIONS
from semantic_rails.mcp_server import MCP_PROTOCOL_VERSION
from semantic_rails.mcp_streamable_http import (
    MCP_MAX_REQUEST_BYTES,
    handle_streamable_http_request,
)
from semantic_rails.public_demo import enforce_public_demo_http_payload

MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
}


class RecordingAdapter:
    package_id = "jaffle_shop"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self) -> list[dict[str, Any]]:
        return list(MCP_TOOL_DEFINITIONS)

    def list_resources(self) -> list[dict[str, Any]]:
        return [{"uri": "semantic-rails://capabilities", "name": "capabilities"}]

    def list_prompts(self) -> list[dict[str, Any]]:
        return [{"name": "semantic-rails-query-builder"}]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        copied = json.loads(json.dumps(arguments))
        self.calls.append((name, copied))
        return {"ok": True, "tool": name, "arguments": copied}

    def read_resource(self, uri: str) -> dict[str, Any]:
        return {"uri": uri, "mimeType": "application/json", "text": "{}"}

    def get_prompt(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "arguments": dict(arguments), "messages": []}


def _request(
    adapter: RecordingAdapter,
    message: dict[str, Any] | list[Any],
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    public_demo: bool = False,
):
    return handle_streamable_http_request(
        adapter,  # type: ignore[arg-type]
        method=method,
        headers=MCP_HEADERS if headers is None else headers,
        body=json.dumps(message).encode("utf-8"),
        public_demo=public_demo,
    )


def test_streamable_http_initializes_latest_protocol():
    response = _request(
        RecordingAdapter(),
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
        },
    )

    assert response.status == 200
    assert response.headers["MCP-Protocol-Version"] == MCP_PROTOCOL_VERSION
    assert response.payload
    assert response.payload["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert response.payload["result"]["capabilities"] == {
        "tools": {},
        "resources": {},
        "prompts": {},
    }


def test_streamable_http_notification_returns_202_without_body():
    response = _request(
        RecordingAdapter(),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    assert response.status == 202
    assert response.payload is None
    assert response.headers["MCP-Protocol-Version"] == MCP_PROTOCOL_VERSION


@pytest.mark.parametrize(
    ("method", "headers", "body", "expected_status"),
    [
        ("GET", {}, b"", 405),
        (
            "POST",
            {"Content-Type": "text/plain", "Accept": MCP_HEADERS["Accept"]},
            b"{}",
            415,
        ),
        (
            "POST",
            {"Content-Type": "application/json", "Accept": "application/json"},
            b"{}",
            406,
        ),
        (
            "POST",
            {
                **MCP_HEADERS,
                "MCP-Protocol-Version": "2099-01-01",
            },
            b"{}",
            400,
        ),
    ],
)
def test_streamable_http_rejects_invalid_method_and_headers(
    method: str,
    headers: dict[str, str],
    body: bytes,
    expected_status: int,
):
    response = handle_streamable_http_request(
        RecordingAdapter(),  # type: ignore[arg-type]
        method=method,
        headers=headers,
        body=body,
    )

    assert response.status == expected_status
    assert response.headers["MCP-Protocol-Version"] == MCP_PROTOCOL_VERSION
    assert response.payload
    assert response.payload["error"]["code"] == -32600


def test_streamable_http_rejects_disallowed_origin(monkeypatch):
    monkeypatch.setenv("SEMANTIC_RAILS_CORS_ORIGINS", "https://semantic-rails.com")
    response = _request(
        RecordingAdapter(),
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={**MCP_HEADERS, "Origin": "https://attacker.example"},
    )

    assert response.status == 403
    assert response.payload
    assert response.payload["error"]["code"] == -32003


def test_streamable_http_rejects_large_body_and_jsonrpc_batches():
    large = handle_streamable_http_request(
        RecordingAdapter(),  # type: ignore[arg-type]
        method="POST",
        headers=MCP_HEADERS,
        body=b"x" * (MCP_MAX_REQUEST_BYTES + 1),
    )
    batch = _request(RecordingAdapter(), [{"jsonrpc": "2.0", "id": 1, "method": "ping"}])

    assert large.status == 413
    assert batch.status == 400


@pytest.mark.parametrize("tool_name", [row["name"] for row in MCP_TOOL_DEFINITIONS])
def test_streamable_http_calls_every_advertised_tool(tool_name: str):
    adapter = RecordingAdapter()
    response = _request(
        adapter,
        {
            "jsonrpc": "2.0",
            "id": tool_name,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
        },
    )

    assert response.status == 200
    assert response.payload
    assert response.payload["result"]["structuredContent"]["tool"] == tool_name
    assert adapter.calls == [(tool_name, {})]


def test_streamable_http_public_demo_caps_execute_and_segment_preview():
    adapter = RecordingAdapter()
    execute = _request(
        adapter,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "execute",
                "arguments": {
                    "query": {
                        "version": 1,
                        "limits": {"max_rows": 50_000, "statement_timeout_ms": 60_000},
                    }
                },
            },
        },
        public_demo=True,
    )
    preview = _request(
        adapter,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "segment-preview", "arguments": {"limit": 500}},
        },
        public_demo=True,
    )

    assert execute.status == 200
    assert preview.status == 200
    assert adapter.calls[0][1]["query"]["limits"] == {
        "max_rows": 100,
        "statement_timeout_ms": 20_000,
    }
    assert adapter.calls[1][1]["limit"] == 25


def test_public_demo_caps_rest_query_and_segment_preview():
    query = enforce_public_demo_http_payload(
        "/query",
        {
            "query": {
                "version": 1,
                "limits": {"max_rows": 1_000, "statement_timeout_ms": 90_000},
            }
        },
    )
    preview = enforce_public_demo_http_payload("/segment-preview", {"limit": 5_000})

    assert query["query"]["limits"] == {
        "max_rows": 100,
        "statement_timeout_ms": 20_000,
    }
    assert preview["limit"] == 25


async def _asgi_mcp_call(
    app: SemanticLayerASGIApp,
    *,
    method: str,
    message: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    body = json.dumps(message).encode("utf-8") if message is not None else b""
    sent: list[dict[str, Any]] = []
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received:
            return {"type": "http.request", "body": b"", "more_body": False}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message_out: dict[str, Any]) -> None:
        sent.append(message_out)

    await app(
        {
            "type": "http",
            "method": method,
            "path": "/mcp",
            "query_string": b"",
            "headers": [
                (key.lower().encode("latin1"), value.encode("latin1"))
                for key, value in {**MCP_HEADERS, **(extra_headers or {})}.items()
            ],
        },
        receive,
        send,
    )
    start = next(
        message_out for message_out in sent if message_out["type"] == "http.response.start"
    )
    response_body = b"".join(
        message_out.get("body", b"")
        for message_out in sent
        if message_out["type"] == "http.response.body"
    )
    return start["status"], start["headers"], response_body


def test_asgi_exposes_stateless_mcp_with_single_protocol_header():
    app = SemanticLayerASGIApp(package_id="jaffle_shop")
    try:
        status, headers, body = asyncio.run(
            _asgi_mcp_call(
                app,
                method="POST",
                message={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
        )
    finally:
        app.mcp_adapter.close()

    decoded_headers = [
        (key.decode("latin1").lower(), value.decode("latin1")) for key, value in headers
    ]
    payload = json.loads(body)
    assert status == 200
    assert len([value for key, value in decoded_headers if key == "x-request-id"]) == 1
    assert len([value for key, value in decoded_headers if key == "mcp-protocol-version"]) == 1
    assert len(payload["result"]["tools"]) == 13


def test_asgi_mcp_requires_api_key_when_configured(monkeypatch):
    """/mcp must honor the same bearer API keys that guard /api/v1/* — the
    execute tool lives behind this endpoint, so a configured deployment must
    not expose it unauthenticated."""
    monkeypatch.setenv("SEMANTIC_RAILS_API_KEYS", "test-demo-key")
    app = SemanticLayerASGIApp(package_id="jaffle_shop")
    try:
        status, _, body = asyncio.run(
            _asgi_mcp_call(
                app,
                method="POST",
                message={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                },
            )
        )
        assert status == 401
        payload = json.loads(body)
        assert payload["error"]["message"] == "Missing or invalid bearer API key."

        status, _, _ = asyncio.run(
            _asgi_mcp_call(
                app,
                method="POST",
                message={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                },
                extra_headers={"authorization": "Bearer test-demo-key"},
            )
        )
        assert status == 200
    finally:
        app.runtime.close()


def test_public_demo_caps_valid_values_limits():
    from semantic_rails.public_demo import (
        PUBLIC_DEMO_MAX_OFFSET,
        PUBLIC_DEMO_MAX_VALID_VALUES,
        enforce_public_demo_mcp_message,
    )

    bounded = enforce_public_demo_http_payload(
        "/valid-values",
        {"dimension_id": "dimension.jaffle_store_name", "limit": 10**9, "offset": 10**9},
    )
    assert bounded["limit"] == PUBLIC_DEMO_MAX_VALID_VALUES
    assert bounded["offset"] == PUBLIC_DEMO_MAX_OFFSET

    message = enforce_public_demo_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "valid-values",
                "arguments": {"dimension_id": "dimension.jaffle_store_name", "limit": 10**9},
            },
        }
    )
    assert message["params"]["arguments"]["limit"] == PUBLIC_DEMO_MAX_VALID_VALUES
