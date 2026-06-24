"""CLI envelope contract — every command must emit a boolean ``ok`` field.

The HTTP envelope (documented in docs/QUERY_API.md) sets ``ok`` to a
bool on every response. The CLI is supposed to mirror that contract so
shell scripts piping through ``jq '.ok'`` see a usable value on both
success and error paths.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(*args: str) -> dict:
    """Invoke the CLI via ``python -m semantic_rails`` and return JSON stdout."""
    proc = subprocess.run(
        [sys.executable, "-m", "semantic_rails", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if not proc.stdout.strip():
        raise AssertionError(f"CLI produced no stdout. args={args!r} stderr={proc.stderr!r}")
    return json.loads(proc.stdout)


def test_cli_compile_sets_ok_true_on_success() -> None:
    query = {
        "version": 1,
        "select": [
            {"expression": {"metric": "metric.sales.aov_usd"}, "as": "aov_usd"},
        ],
        "time": {
            "temporal_role": "temporal_role.jaffle_order_time",
            "grain": "month",
        },
    }
    payload = _run_cli(
        "compile",
        "--package",
        "jaffle_shop",
        "--query-json",
        json.dumps(query),
    )
    assert isinstance(payload.get("ok"), bool), (
        f"expected bool ok, got {type(payload.get('ok')).__name__}: {payload.get('ok')!r}"
    )
    assert payload["ok"] is True
    assert payload.get("status") == "ok"


def test_cli_plan_rejects_empty_intent_with_json_error() -> None:
    payload = _run_cli("plan", "--package", "jaffle_shop", "--intent", "")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_QUERY"
    assert payload["error"]["details"]["path"] == "intent"


def test_cli_query_accepts_path_flag_for_unregistered_packages() -> None:
    """`query` / `compile` / `validate` must accept --path the
    same way `parse-config`, `validate-config`, and `mcp http` do — the
    blind UX walkthrough cliffed off at "I just authored a package and
    now I can't query it without copying it into configs/semantic_rails/".
    Run a real query against the jaffle_shop package directory as a path,
    bypassing the registered-package lookup.
    """
    package_path = REPO_ROOT / "configs" / "semantic_rails" / "jaffle_shop"
    assert package_path.is_dir(), f"missing jaffle_shop package: {package_path}"
    query = {
        "version": 1,
        "select": [
            {"expression": {"metric": "metric.sales.aov_usd"}, "as": "aov_usd"},
        ],
        "time": {
            "temporal_role": "temporal_role.jaffle_order_time",
            "grain": "month",
        },
        "limit": 1,
    }
    # query
    payload = _run_cli(
        "query",
        "--path",
        str(package_path),
        "--query-json",
        json.dumps(query),
    )
    assert isinstance(payload.get("ok"), bool)
    assert payload["ok"] is True, payload
    assert payload.get("rows"), "expected at least one row from jaffle_shop"

    # compile + validate must also accept --path (parity with
    # the other lifecycle commands, per the blind UX cliff).
    for command in ("compile", "validate"):
        verified = _run_cli(
            command,
            "--path",
            str(package_path),
            "--query-json",
            json.dumps(query),
        )
        assert isinstance(verified.get("ok"), bool), (
            f"{command} --path produced non-boolean ok: {verified.get('ok')!r}"
        )
        assert verified["ok"] is True, f"{command} --path failed: {verified}"
