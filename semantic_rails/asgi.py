"""ASGI app exposing the v1 HTTP API.

Provides :class:`SemanticASGIApp` — a minimal, dependency-free ASGI
callable suitable for ``uvicorn``, ``hypercorn``, or any 3.0/3.1
server. The application delegates routing and response shaping to
:class:`semantic_rails.http_core.SemanticHTTPService` so the threaded
:mod:`semantic_rails.api` server and this ASGI surface stay in lockstep.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs

from .http_core import (
    CORS_ALLOW_HEADERS,
    SemanticHTTPService,
    cors_origin_header,
    public_api_route,
    request_id_from_parts,
)
from .mcp import SemanticLayerMCPAdapter
from .mcp_streamable_http import MCP_MAX_REQUEST_BYTES, handle_streamable_http_request
from .public_demo import (
    PUBLIC_DEMO_PACKAGE,
    enforce_public_demo_http_payload,
    public_demo_enabled,
)
from .request_context import api_key_auth_result, emit_audit_event
from .runtime import Runtime

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    return {
        key.decode("latin1"): value.decode("latin1")
        for key, value in list(scope.get("headers", []) or [])
    }


def _query_params(scope: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_qs(bytes(scope.get("query_string", b"")).decode("utf-8"))
    return {key: values[-1] for key, values in parsed.items() if values}


class RequestBodyTooLarge(ValueError):
    pass


async def _read_body(receive: Receive, *, maximum: int = MCP_MAX_REQUEST_BYTES) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > maximum:
            raise RequestBodyTooLarge(f"Request body exceeds the {maximum}-byte limit.")
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


class SemanticLayerASGIApp:
    def __init__(
        self,
        *,
        package_id: str = "jaffle_shop",
        path: str = "",
        public_demo: bool | None = None,
    ) -> None:
        self.public_demo = public_demo_enabled() if public_demo is None else public_demo
        if self.public_demo:
            package_id = PUBLIC_DEMO_PACKAGE
            path = ""
        self.runtime = Runtime.from_path(path) if path else Runtime(package_id)
        self.package_id = self.runtime.package_id
        self.mcp_adapter = SemanticLayerMCPAdapter(self.runtime)

    def _service(self) -> SemanticHTTPService:
        return SemanticHTTPService(self.runtime, self.package_id)

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            return await self._lifespan(receive, send)
        if scope_type != "http":
            return None

        service = self._service()
        headers = _headers(scope)
        query_params = _query_params(scope)
        method = str(scope.get("method", "GET")).upper()
        raw_path = str(scope.get("path", "/"))
        started = time.perf_counter()
        request_id = request_id_from_parts(headers, query_params)
        request_origin = headers.get("origin") or headers.get("Origin")
        if raw_path.rstrip("/") == "/mcp":
            return await self._handle_mcp(
                method,
                headers,
                receive,
                send,
                request_id=request_id,
                request_origin=request_origin,
            )

        route = public_api_route(raw_path)
        if route is None:
            response = service.envelope(
                404,
                service.not_found_payload(),
                request_id=request_id,
                started=started,
            )
            self._audit(method, raw_path, 404, response)
            return await self._send(send, 404, response, request_origin=request_origin)

        if method == "OPTIONS":
            return await self._send_options(send, request_id, request_origin=request_origin)

        context = service.request_context(headers, request_id=request_id)
        if not service.auth_ok(route, headers):
            response = service.envelope(
                401,
                service.unauthorized_payload(),
                request_id=request_id,
                started=started,
                request_context=context,
            )
            self._audit(method, raw_path, 401, response)
            return await self._send(send, 401, response, request_origin=request_origin)

        payload: dict[str, Any] = {}
        if method == "POST":
            try:
                body = await _read_body(receive)
                decoded = json.loads(body.decode("utf-8") or "{}")
            except RequestBodyTooLarge as exc:
                response = service.envelope(
                    413,
                    service.invalid_request_payload(str(exc)),
                    request_id=request_id,
                    started=started,
                    request_context=context,
                )
                self._audit(method, raw_path, 413, response)
                return await self._send(send, 413, response, request_origin=request_origin)
            except json.JSONDecodeError as exc:
                response = service.envelope(
                    400,
                    service.invalid_json_payload(exc.msg),
                    request_id=request_id,
                    started=started,
                    request_context=context,
                )
                self._audit(method, raw_path, 400, response)
                return await self._send(send, 400, response, request_origin=request_origin)
            if not isinstance(decoded, dict):
                response = service.envelope(
                    400,
                    service.invalid_request_payload("Request body must be a JSON object."),
                    request_id=request_id,
                    started=started,
                    request_context=context,
                )
                self._audit(method, raw_path, 400, response)
                return await self._send(send, 400, response, request_origin=request_origin)
            payload = dict(decoded)
            if self.public_demo:
                payload = enforce_public_demo_http_payload(route, payload)
            request_id = request_id_from_parts(headers, query_params, payload)
            context = service.request_context(headers, payload=payload, request_id=request_id)

        try:
            result, status = service.handle(
                method, route, payload, headers=headers, query_params=query_params, context=context
            )
        except Exception as exc:  # pragma: no cover - defensive ASGI boundary
            result, status = service.exception_payload(exc, stage="asgi")
        response = service.envelope(
            status, result, request_id=request_id, started=started, request_context=context
        )
        self._audit(method, raw_path, status, response)
        pretty = str(query_params.get("pretty", "")).strip().lower() in {"1", "true", "yes", "on"}
        await self._send(send, status, response, pretty=pretty, request_origin=request_origin)

    async def _handle_mcp(
        self,
        method: str,
        headers: dict[str, str],
        receive: Receive,
        send: Send,
        *,
        request_id: str,
        request_origin: str | None,
    ) -> None:
        # The same bearer API keys that guard /api/v1/* guard /mcp — when no
        # keys are configured (local dev, public demo) auth stays disabled.
        # The execute tool lives behind this endpoint, so leaving it open
        # while operators believe SEMANTIC_RAILS_API_KEYS protects the
        # deployment would be a silent auth bypass.
        auth_ok, _ = api_key_auth_result(headers)
        if not auth_ok:
            return await self._send(
                send,
                401,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32001,
                        "message": "Missing or invalid bearer API key.",
                    },
                },
                request_origin=request_origin,
                request_id=request_id,
                allow_methods="POST, OPTIONS",
            )
        body = b""
        if method == "POST":
            try:
                body = await _read_body(receive)
            except RequestBodyTooLarge:
                body = b"x" * (MCP_MAX_REQUEST_BYTES + 1)
        response = handle_streamable_http_request(
            self.mcp_adapter,
            method=method,
            headers=headers,
            body=body,
            public_demo=self.public_demo,
        )
        extra_headers = dict(response.headers)
        if response.payload is None:
            return await self._send_empty(
                send,
                response.status,
                request_id=request_id,
                request_origin=request_origin,
                extra_headers=extra_headers,
                allow_methods="POST, OPTIONS",
            )
        return await self._send(
            send,
            response.status,
            response.payload,
            request_origin=request_origin,
            request_id=request_id,
            extra_headers=extra_headers,
            allow_methods="POST, OPTIONS",
        )

    def _audit(self, method: str, path: str, status: int, response: dict[str, Any]) -> None:
        emit_audit_event(
            "asgi_http_request",
            method=method,
            path=path,
            status_code=status,
            package_id=str(response.get("package_id", self.package_id)),
            request_id=str(response.get("request_id", "")),
            request_context=dict(response.get("request_context", {}) or {}),
            error_codes=[
                str(error.get("code", ""))
                for error in list(response.get("errors", []) or [])
                if isinstance(error, dict)
            ],
            timing_ms=response.get("timing_ms"),
        )

    async def _send_options(
        self, send: Send, request_id: str, *, request_origin: str | None = None
    ) -> None:
        allow_origin = cors_origin_header(request_origin)
        headers = [
            (b"access-control-allow-headers", CORS_ALLOW_HEADERS.encode("latin1")),
            (b"access-control-expose-headers", b"X-Request-ID"),
            (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
            (b"x-request-id", request_id.encode("latin1", errors="ignore")),
            (b"content-length", b"0"),
        ]
        if allow_origin:
            headers.insert(0, (b"access-control-allow-origin", allow_origin.encode("latin1")))
        await send({"type": "http.response.start", "status": 204, "headers": headers})
        await send({"type": "http.response.body", "body": b""})

    async def _send(
        self,
        send: Send,
        status: int,
        payload: dict[str, Any],
        *,
        pretty: bool = False,
        request_origin: str | None = None,
        request_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
        allow_methods: str = "GET, POST, OPTIONS",
    ) -> None:
        # Pretty-printing is opt-in via `?pretty=true`. The default is
        # compact JSON so large catalog payloads do not double bandwidth
        # on every response in a hosted deployment.
        if pretty:
            body = json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")
        else:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode(
                "utf-8"
            )
        request_id = request_id or str(payload.get("request_id", "") or "")
        allow_origin = cors_origin_header(request_origin)
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"x-request-id", request_id.encode("latin1", errors="ignore")),
            (b"access-control-allow-headers", CORS_ALLOW_HEADERS.encode("latin1")),
            (b"access-control-expose-headers", b"X-Request-ID"),
            (b"access-control-allow-methods", allow_methods.encode("latin1")),
        ]
        for key, value in dict(extra_headers or {}).items():
            headers.append(
                (
                    key.lower().encode("latin1", errors="ignore"),
                    value.encode("latin1", errors="ignore"),
                )
            )
        if allow_origin:
            headers.append((b"access-control-allow-origin", allow_origin.encode("latin1")))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def _send_empty(
        self,
        send: Send,
        status: int,
        *,
        request_id: str,
        request_origin: str | None = None,
        extra_headers: dict[str, str] | None = None,
        allow_methods: str = "GET, POST, OPTIONS",
    ) -> None:
        allow_origin = cors_origin_header(request_origin)
        headers = [
            (b"content-length", b"0"),
            (b"x-request-id", request_id.encode("latin1", errors="ignore")),
            (b"access-control-allow-headers", CORS_ALLOW_HEADERS.encode("latin1")),
            (b"access-control-expose-headers", b"X-Request-ID, MCP-Protocol-Version"),
            (b"access-control-allow-methods", allow_methods.encode("latin1")),
        ]
        for key, value in dict(extra_headers or {}).items():
            headers.append(
                (
                    key.lower().encode("latin1", errors="ignore"),
                    value.encode("latin1", errors="ignore"),
                )
            )
        if allow_origin:
            headers.append((b"access-control-allow-origin", allow_origin.encode("latin1")))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": b""})

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message_type == "lifespan.shutdown":
                self.mcp_adapter.close()
                await send({"type": "lifespan.shutdown.complete"})
                return None
            else:
                return None


class PackageLoadFailureApp:
    """Minimal ASGI app that surfaces a package-load failure as 503 on every
    request instead of crashing the worker at import time.

    Without this, ``uvicorn semantic_rails.asgi:app`` raises during module
    import when ``SEMANTIC_RAILS_PACKAGE`` points at a missing or invalid
    package — the worker dies before lifespan starts, there is no /health to
    hit, and the user only sees an opaque traceback. This app responds with a
    structured 503 envelope so misconfiguration is recoverable.
    """

    def __init__(self, *, package_id: str, error: Exception) -> None:
        self.package_id = package_id
        self.error = error

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            while True:
                message = await receive()
                if message.get("type") == "lifespan.startup":
                    # Complete startup successfully so uvicorn keeps the worker
                    # alive and routes HTTP requests to us. Every request will
                    # return a structured 503 with the recovery hint. Sending
                    # `lifespan.startup.failed` would cause uvicorn to abort
                    # the worker — the operator would see only an opaque
                    # traceback and no /health to hit. Log the error to stderr
                    # so it still surfaces in uvicorn output.
                    print(
                        json.dumps(
                            {
                                "event": "package_load_failed",
                                "package_id": self.package_id,
                                "error": str(self.error),
                            }
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
                    await send({"type": "lifespan.startup.complete"})
                    continue
                if message.get("type") == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return None
        if scope_type != "http":
            return None
        body = json.dumps(
            {
                "ok": False,
                "package_id": self.package_id,
                "errors": [
                    {
                        "code": "PACKAGE_LOAD_FAILED",
                        "message": str(self.error),
                        "hint": (
                            "Check SEMANTIC_RAILS_PACKAGE / SEMANTIC_RAILS_PACKAGE_PATH "
                            "and re-validate the package config with `semantic-rails parse-config`."
                        ),
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"access-control-allow-origin", b"*"),
        ]
        await send({"type": "http.response.start", "status": 503, "headers": headers})
        await send({"type": "http.response.body", "body": body})


def create_app() -> SemanticLayerASGIApp | PackageLoadFailureApp:
    import os

    demo = public_demo_enabled()
    package_id = (
        PUBLIC_DEMO_PACKAGE if demo else os.environ.get("SEMANTIC_RAILS_PACKAGE", "jaffle_shop")
    )
    path = "" if demo else os.environ.get("SEMANTIC_RAILS_PACKAGE_PATH", "")
    try:
        return SemanticLayerASGIApp(package_id=package_id, path=path, public_demo=demo)
    except Exception as exc:  # noqa: BLE001 — defer all package-load errors
        # Module import must succeed even if the package config is invalid;
        # otherwise the uvicorn worker dies with no useful error path for the
        # caller. The fallback app returns a structured 503 on every request.
        return PackageLoadFailureApp(package_id=package_id, error=exc)


app = create_app()
