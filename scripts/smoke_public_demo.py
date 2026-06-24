#!/usr/bin/env python3
"""Read-only smoke checks for the public Semantic Rails demo."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://semantic-rails.com"
MCP_PROTOCOL_VERSION = "2025-11-25"
EXPECTED_MCP_TOOLS = 13
USER_AGENT = "semantic-rails-release-smoke/0.1"


@dataclass(frozen=True)
class SmokeResult:
    name: str
    ok: bool
    detail: str


class SmokeFailure(RuntimeError):
    """Raised when a public demo smoke check gets an invalid response."""


def _url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _request_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> dict[str, Any]:
    data = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        **dict(headers or {}),
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec - user-supplied smoke URL.
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise SmokeFailure(f"{method} {url} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise SmokeFailure(f"{method} {url} failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{method} {url} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{method} {url} returned a non-object JSON payload")
    return payload


def _request_text(url: str, *, timeout: float) -> str:
    request = Request(
        url,
        headers={"Accept": "text/html", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec - user-supplied smoke URL.
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise SmokeFailure(f"GET {url} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise SmokeFailure(f"GET {url} failed: {exc.reason}") from exc


def _require_ok_payload(name: str, payload: dict[str, Any]) -> SmokeResult:
    if payload.get("ok") is not True:
        raise SmokeFailure(f"{name} did not return ok=true: {payload!r}")
    package = payload.get("package")
    package_id = payload.get("package_id")
    if isinstance(package, dict):
        package_id = package.get("id") or package_id
    if package_id != "jaffle_shop":
        raise SmokeFailure(f"{name} returned unexpected package id: {package_id!r}")
    return SmokeResult(name, True, "ok=true package=jaffle_shop")


def _require_mcp_tools(payload: dict[str, Any], *, expected_tools: int) -> SmokeResult:
    tools = (payload.get("result") or {}).get("tools") or []
    if not isinstance(tools, list):
        raise SmokeFailure("MCP tools/list response did not include result.tools")
    if len(tools) != expected_tools:
        raise SmokeFailure(f"MCP tools/list expected {expected_tools} tools, got {len(tools)}")
    names = {str(tool.get("name")) for tool in tools if isinstance(tool, dict)}
    for required in ("capabilities", "discover", "inspect", "validate", "compile", "execute"):
        if required not in names:
            raise SmokeFailure(f"MCP tools/list missing required tool: {required}")
    return SmokeResult("mcp_tools", True, f"{len(tools)} tools")


def _require_try_page(html: str) -> SmokeResult:
    required = ("Semantic Rails", "plan", "validate", "compile")
    missing = [token for token in required if token not in html]
    if missing:
        raise SmokeFailure(f"/try page missing expected text: {missing}")
    return SmokeResult("try_page", True, "html reachable")


def run_smoke(base_url: str, *, timeout: float, expected_tools: int) -> list[SmokeResult]:
    results = [
        _require_ok_payload(
            "health",
            _request_json("GET", _url(base_url, "/api/v1/health"), timeout=timeout),
        ),
        _require_ok_payload(
            "ready",
            _request_json("GET", _url(base_url, "/api/v1/ready"), timeout=timeout),
        ),
    ]
    capabilities = _request_json("GET", _url(base_url, "/api/v1/capabilities"), timeout=timeout)
    results.append(_require_ok_payload("capabilities", capabilities))
    tools = _request_json(
        "POST",
        _url(base_url, "/mcp"),
        body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        },
        timeout=timeout,
    )
    results.append(_require_mcp_tools(tools, expected_tools=expected_tools))
    results.append(_require_try_page(_request_text(_url(base_url, "/try"), timeout=timeout)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--expected-tools", type=int, default=EXPECTED_MCP_TOOLS)
    args = parser.parse_args(argv)

    try:
        results = run_smoke(
            args.base_url,
            timeout=args.timeout,
            expected_tools=args.expected_tools,
        )
    except SmokeFailure as exc:
        print(f"Public demo smoke failed: {exc}", file=sys.stderr)
        return 1

    print(f"Public demo smoke passed for {args.base_url.rstrip('/')}")
    for result in results:
        print(f"- {result.name}: {result.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
