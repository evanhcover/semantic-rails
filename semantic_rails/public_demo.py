"""Public demo policy for the hosted Jaffle Shop sandbox.

The OSS runtime remains unrestricted by default. Deployments opt into this
policy with ``SEMANTIC_RAILS_PUBLIC_DEMO=1`` to keep the anonymous hosted
surface fixed to synthetic data and bounded query responses.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from typing import Any

PUBLIC_DEMO_PACKAGE = "jaffle_shop"
PUBLIC_DEMO_MAX_ROWS = 100
PUBLIC_DEMO_MAX_SEGMENT_ROWS = 25
PUBLIC_DEMO_MAX_VALID_VALUES = 100
PUBLIC_DEMO_MAX_OFFSET = 10_000
PUBLIC_DEMO_STATEMENT_TIMEOUT_MS = 20_000


def public_demo_enabled() -> bool:
    return os.environ.get("SEMANTIC_RAILS_PUBLIC_DEMO", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bounded_positive_int(value: Any, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return maximum
    if parsed <= 0:
        return maximum
    return min(parsed, maximum)


def _bounded_query_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    raw_query = out.get("query")
    if isinstance(raw_query, Mapping):
        query = copy.deepcopy(dict(raw_query))
        out["query"] = query
    else:
        query = out

    raw_limits = query.get("limits")
    limits = dict(raw_limits) if isinstance(raw_limits, Mapping) else {}
    limits["max_rows"] = _bounded_positive_int(limits.get("max_rows"), PUBLIC_DEMO_MAX_ROWS)
    limits["statement_timeout_ms"] = _bounded_positive_int(
        limits.get("statement_timeout_ms"), PUBLIC_DEMO_STATEMENT_TIMEOUT_MS
    )
    query["limits"] = limits
    return out


def enforce_public_demo_http_payload(route: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    if route == "/query":
        return _bounded_query_payload(out)
    if route == "/segment-preview":
        out["limit"] = _bounded_positive_int(out.get("limit"), PUBLIC_DEMO_MAX_SEGMENT_ROWS)
    if route == "/valid-values":
        # allow_live_query runs a real warehouse query with caller-controlled
        # limit/offset that bypasses the /query row caps — bound both here.
        out["limit"] = _bounded_positive_int(out.get("limit"), PUBLIC_DEMO_MAX_VALID_VALUES)
        if "offset" in out:
            out["offset"] = _bounded_positive_int(out.get("offset"), PUBLIC_DEMO_MAX_OFFSET)
    return out


def enforce_public_demo_mcp_message(message: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(message))
    if str(out.get("method", "")) != "tools/call":
        return out
    raw_params = out.get("params")
    if not isinstance(raw_params, Mapping):
        return out
    params = copy.deepcopy(dict(raw_params))
    out["params"] = params
    raw_arguments = params.get("arguments")
    arguments = copy.deepcopy(dict(raw_arguments)) if isinstance(raw_arguments, Mapping) else {}
    params["arguments"] = arguments

    tool_name = str(params.get("name", ""))
    if tool_name == "execute":
        params["arguments"] = _bounded_query_payload(arguments)
    elif tool_name == "segment-preview":
        arguments["limit"] = _bounded_positive_int(
            arguments.get("limit"), PUBLIC_DEMO_MAX_SEGMENT_ROWS
        )
    elif tool_name == "valid-values":
        arguments["limit"] = _bounded_positive_int(
            arguments.get("limit"), PUBLIC_DEMO_MAX_VALID_VALUES
        )
        if "offset" in arguments:
            arguments["offset"] = _bounded_positive_int(
                arguments.get("offset"), PUBLIC_DEMO_MAX_OFFSET
            )
    return out
