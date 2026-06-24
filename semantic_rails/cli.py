"""``semantic-rails`` console-script implementation.

Builds the argparse tree and dispatches each subcommand
(``catalog``, ``discover``, ``inspect``, ``plan``, ``validate``,
``compile``, ``query``, ``serve``, ``mcp``,
``parse-config``, ``test-package``, …). Each command function delegates
to the corresponding metadata or runtime entry point and prints a JSON
envelope to stdout. :func:`main` is also re-exported by
:mod:`semantic_rails.__main__`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

from .api import serve
from .config import (
    get_package_config,
    list_package_ids,
    load_package_config,
    package_root_for_source,
    resolve_repo_path,
)
from .config_validation import (
    parse_config_report,
    resolve_package_reference,
    validate_config_report,
)
from .diagnostics import exception_issue
from .errors import SemanticLayerError
from .mcp import SemanticLayerMCPAdapter
from .mcp_server import serve_http as serve_mcp_http
from .mcp_server import serve_stdio as serve_mcp_stdio
from .metadata import (
    build_options_payload,
    catalog_payload,
    discover_payload,
    inspect_payload,
    valid_values_payload,
)
from .package_tools import (
    build_package_artifact_report,
    check_package_report,
    check_warehouse_column_reachability_report,
    diff_package_report,
    impact_report,
    promote_package_report,
    run_examples_report,
    run_package_tests_report,
)
from .planner import plan_payload
from .runtime import Runtime, _enrich_runtime_error

__all__ = [
    "Runtime",
    "SemanticLayerError",
    "SemanticLayerMCPAdapter",
    "build_options_payload",
    "build_package_artifact_report",
    "catalog_payload",
    "check_package_report",
    "diff_package_report",
    "discover_payload",
    "exception_issue",
    "impact_report",
    "inspect_payload",
    "list_package_ids",
    "main",
    "plan_payload",
    "parse_config_report",
    "promote_package_report",
    "resolve_package_reference",
    "run_examples_report",
    "run_package_tests_report",
    "serve",
    "serve_mcp_http",
    "serve_mcp_stdio",
    "valid_values_payload",
    "validate_config_report",
]


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("@"):
        with open(text[1:], encoding="utf-8") as f:
            text = f.read()
    return dict(json.loads(text) or {})


def _with_ok(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure the CLI JSON envelope carries a boolean ``ok`` field.

    Mirrors the HTTP envelope contract (documented in docs/QUERY_API.md):
    every response must expose ``ok`` as ``True`` on success and ``False``
    on error. Without this, ``jq '.ok'`` against CLI output returns
    ``null`` for successful calls.
    """
    if not isinstance(payload, dict):
        return payload
    existing = payload.get("ok")
    if isinstance(existing, bool):
        return payload
    out = dict(payload)
    status = str(out.get("status", "") or "").lower()
    errors = list(out.get("errors", []) or [])
    if status == "error" or errors:
        out["ok"] = False
    else:
        # Success path: status was "ok" or unset on a normal payload.
        out["ok"] = True
    return out


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(_with_ok(payload), indent=2, sort_keys=True, default=str))


def _print_stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _print_error_envelope(issue: dict[str, Any]) -> None:
    """Print the CLI error envelope to stdout (exactly once).

    The structured issue — code, ``details.closest_matches``, and
    ``recovery_hints`` — is emitted once under ``error``. Earlier
    versions also repeated the full issue under ``errors`` and hoisted
    ``recovery_hints`` to the top level, so every CLI failure printed
    the same payload three times. ``jq '.error.code'`` /
    ``jq '.error.recovery_hints'`` remain stable.
    """
    _print({"ok": False, "status": "error", "error": issue})


def _config_for_error_enrichment(args: argparse.Namespace) -> Any | None:
    """Best-effort ``PackageConfig`` lookup for diagnostics enrichment.

    Mirrors :func:`_runtime_from_package_or_path` precedence (``--path``
    wins over ``--package``). Returns ``None`` when the command carries
    no package reference or the config itself fails to load — error
    enrichment must never mask the original error.
    """
    path = str(getattr(args, "path", "") or "").strip()
    package = str(getattr(args, "package", "") or "").strip()
    with contextlib.suppress(Exception):
        if path:
            return load_package_config(path)
        if package:
            return get_package_config(package)
    return None


def _policy_context_from_args(args: argparse.Namespace) -> dict[str, Any]:
    environment = str(getattr(args, "environment", "") or "")
    audience = str(getattr(args, "audience", "") or "")
    return {
        key: value
        for key, value in {"environment": environment, "audience": audience}.items()
        if value
    }


def _query_with_policy_context(
    query: dict[str, Any] | None, args: argparse.Namespace
) -> dict[str, Any] | None:
    policy_context = _policy_context_from_args(args)
    if not policy_context:
        return dict(query or {}) if query is not None else None
    payload = dict(query or {})
    payload["policy_context"] = policy_context
    return payload


def _add_policy_context_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--environment",
        default="",
        help="Policy environment to evaluate against (e.g. 'dev', 'prod'). Optional.",
    )
    parser.add_argument(
        "--audience",
        default="",
        help="Policy audience to evaluate against (e.g. 'analyst', 'agent'). Optional.",
    )


def _runtime_from_package_or_path(args: argparse.Namespace) -> Runtime:
    path = str(getattr(args, "path", "") or "").strip()
    package = str(getattr(args, "package", "") or "").strip()
    if path:
        return Runtime.from_path(path)
    return Runtime(package)


def _add_package_or_path_args(parser: argparse.ArgumentParser, package_choices: list[str]) -> None:
    parser.add_argument(
        "--package",
        choices=package_choices,
        default=package_choices[0] if package_choices else "",
        help="Registered package id from configs/semantic_rails/.",
    )
    parser.add_argument(
        "--path",
        default="",
        help="Path to a package directory or single-file YAML. Overrides --package when set.",
    )


def cmd_packages(_: argparse.Namespace) -> None:
    _print({"packages": list_package_ids()})


def cmd_catalog(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    try:
        _print(
            {
                "catalog": catalog_payload(
                    runtime,
                    view=args.view,
                    verbosity=args.verbosity,
                    kind=args.kind,
                    search=args.search,
                    entity=args.entity,
                    policy_context=_policy_context_from_args(args),
                )
            }
        )
    finally:
        runtime.close()


def cmd_discover(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    try:
        query = _query_with_policy_context(
            _parse_json(args.query_json) if args.query_json else None, args
        )
        _print(
            discover_payload(
                runtime,
                terms=args.terms,
                kinds=[part for part in args.kinds.split(",") if part],
                partial_query=query,
                stage=args.stage,
                verbosity=args.verbosity,
                limit=args.limit,
                enforce_scope=True,
            )
        )
    finally:
        runtime.close()


def cmd_inspect(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    try:
        query = _query_with_policy_context(
            _parse_json(args.query_json) if args.query_json else None, args
        )
        _print(
            inspect_payload(
                runtime, object_id=args.object_id, partial_query=query, verbosity=args.verbosity
            )
        )
    finally:
        runtime.close()


def cmd_validate(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    try:
        _print(
            runtime.validate(_query_with_policy_context(_parse_json(args.query_json), args) or {})
        )
    finally:
        runtime.close()


def cmd_compile(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    try:
        _print(
            runtime.compile(_query_with_policy_context(_parse_json(args.query_json), args) or {})
        )
    finally:
        runtime.close()


def cmd_query(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    try:
        _print(runtime.query(_query_with_policy_context(_parse_json(args.query_json), args) or {}))
    finally:
        runtime.close()


def cmd_segment_validate(args: argparse.Namespace) -> None:
    runtime = Runtime(args.package)
    try:
        _print(runtime.segment_validate(args.segment_id))
    finally:
        runtime.close()


def cmd_segment_explain(args: argparse.Namespace) -> None:
    runtime = Runtime(args.package)
    try:
        _print(runtime.segment_explain(args.segment_id))
    finally:
        runtime.close()


def cmd_segment_preview(args: argparse.Namespace) -> None:
    runtime = Runtime(args.package)
    try:
        _print(runtime.segment_preview(args.segment_id, limit=args.limit))
    finally:
        runtime.close()


def cmd_valid_values(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    try:
        query = _query_with_policy_context(
            _parse_json(args.query_json) if args.query_json else None, args
        )
        _print(
            valid_values_payload(
                runtime,
                dimension_id=args.dimension,
                query=query,
                search=args.search,
                limit=args.limit,
                offset=args.offset,
                include_counts=args.include_counts,
            )
        )
    finally:
        runtime.close()


def cmd_build_options(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    try:
        query = _query_with_policy_context(_parse_json(args.query_json), args) or {}
        _print(
            build_options_payload(
                runtime,
                partial_query=query,
                focus_terms=args.focus_terms,
                focus_object_id=args.focus_object_id,
                step=args.step,
                stage=args.stage,
                verbosity=args.verbosity,
                include_blocked=args.include_blocked,
                limit=args.limit,
            )
        )
    finally:
        runtime.close()


def cmd_plan(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    try:
        query = _query_with_policy_context(
            _parse_json(args.query_json) if args.query_json else None, args
        )
        _print(
            plan_payload(
                runtime,
                intent=args.intent,
                partial_query=query,
                limit=args.limit,
                detail=args.detail,
            )
        )
    finally:
        runtime.close()


def cmd_mcp_stdio(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    adapter = SemanticLayerMCPAdapter(runtime)
    try:
        adapter.list_tools()
        serve_mcp_stdio(adapter)
    finally:
        adapter.close()


def cmd_mcp_http(args: argparse.Namespace) -> None:
    runtime = _runtime_from_package_or_path(args)
    adapter = SemanticLayerMCPAdapter(runtime)
    try:
        adapter.list_tools()
        serve_mcp_http(adapter, host=args.host, port=args.port)
    finally:
        adapter.close()


def cmd_doctor(args: argparse.Namespace) -> None:
    checks = []
    ref = resolve_package_reference(
        package_id=getattr(args, "package", ""), path=getattr(args, "path", "")
    )
    parse_report, _ = parse_config_report(ref, progress=lambda _: None)
    checks.append(
        {
            "name": "parse_config",
            "ok": bool(parse_report.get("ok")),
            "errors": list(parse_report.get("errors", []) or []),
        }
    )
    validate_report = (
        validate_config_report(ref, progress=lambda _: None)
        if parse_report.get("ok")
        else {"ok": False, "errors": parse_report.get("errors", [])}
    )
    checks.append(
        {
            "name": "validate_config",
            "ok": bool(validate_report.get("ok")),
            "errors": list(validate_report.get("errors", []) or []),
        }
    )
    try:
        runtime = Runtime.from_path(ref.source_path) if ref.source_path else Runtime(ref.package_id)
        try:
            adapter = SemanticLayerMCPAdapter(runtime)
            checks.append(
                {
                    "name": "mcp_adapter",
                    "ok": bool(adapter.list_tools()),
                    "tool_count": len(adapter.list_tools()),
                }
            )
            checks.append(
                {
                    "name": "warehouse_config",
                    "ok": True,
                    "warehouse": runtime.warehouse,
                    "connection_kind": runtime.config.package.connection.kind,
                    "connectivity_checked": False,
                }
            )
        finally:
            runtime.close()
    except Exception as exc:
        checks.append(
            {
                "name": "runtime_load",
                "ok": False,
                "error": str(exc),
                "hint": "The package failed to load — fix the errors above, then re-run doctor.",
            }
        )
    # Dockerfile presence is informational only: a standalone package
    # author has no Dockerfile and that must not fail doctor. Look next
    # to the package source, not the current working directory.
    package_root = Path(package_root_for_source(ref.source_path)) if ref.source_path else Path(".")
    dockerfile = package_root / "Dockerfile"
    checks.append(
        {
            "name": "dockerfile",
            "ok": True,
            "present": dockerfile.exists(),
            "path": str(dockerfile),
            "note": ("informational — only needed for container deploys; see docs/DEPLOYMENT.md"),
        }
    )
    failing = [check for check in checks if not bool(check.get("ok"))]
    _print(
        {
            "ok": not failing,
            "package": ref.display_name,
            "checks": checks,
            "failing_checks": [str(check.get("name", "")) for check in failing],
        }
    )


def cmd_init(args: argparse.Namespace) -> None:
    target = Path(args.output).expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not args.force:
        raise SemanticLayerError(
            "INVALID_CONFIG",
            f"Target directory '{target}' is not empty; pass --force to overwrite starter files",
        )
    target.mkdir(parents=True, exist_ok=True)
    # resolve_repo_path checks the repo root and the installed data-files
    # root (share/semantic-rails/), so this works from a source checkout and
    # from a pip-installed wheel — the starter template ships as a data file.
    starter = Path(resolve_repo_path("configs/examples/semantic_rails_package_starter.yml"))
    if not starter.exists():
        raise SemanticLayerError(
            "INVALID_CONFIG",
            "Bundled starter template not found "
            "(configs/examples/semantic_rails_package_starter.yml). Reinstall the "
            "package or run from a source checkout.",
        )
    package_text = starter.read_text(encoding="utf-8")
    package_id = str(args.package_id or target.name).strip()
    namespace = str(args.namespace or package_id.replace("-", "_")).strip()
    package_text = package_text.replace("id: shop_starter", f"id: {package_id}")
    package_text = package_text.replace("namespace: shop", f"namespace: {namespace}")
    # Fully-qualified ids in the template are derived from the starter's
    # `namespace: shop`; rewrite them so expression references (e.g.
    # measure.shop.line_revenue_usd) keep resolving under the new namespace.
    for kind in ("entity", "dimension", "measure", "metric", "segment"):
        package_text = package_text.replace(f"{kind}.shop.", f"{kind}.{namespace}.")
    package_text = package_text.replace(
        "default_db: data/shop_starter.duckdb", f"default_db: data/{package_id}.duckdb"
    )
    package_text = package_text.replace(
        "source: data/seed_shop.sql", "source: data/seed_example.sql"
    )
    # The starter header tells readers to validate the repo-internal
    # template path; point the generated file's header at itself instead.
    package_text = package_text.replace(
        "uv run semantic-rails parse-config --path "
        "configs/examples/semantic_rails_package_starter.yml",
        f"semantic-rails validate-config --path {target / 'package.yml'}",
    )
    (target / "package.yml").write_text(package_text, encoding="utf-8")
    data_dir = target / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "seed_example.sql").write_text(
        """
CREATE OR REPLACE TABLE shop_customer AS
SELECT 'customer_1' AS customer_id, 'new' AS customer_type, TIMESTAMP '2026-01-01 00:00:00' AS first_ordered_at;

CREATE OR REPLACE TABLE shop_order AS
SELECT 'order_1' AS order_id, 'customer_1' AS customer_id, 'web' AS channel, 4200 AS order_total_cents, TIMESTAMP '2026-01-02 00:00:00' AS ordered_at;

CREATE OR REPLACE TABLE shop_order_item AS
SELECT 'item_1' AS order_item_id, 'order_1' AS order_id, 'product_1' AS product_id, 1 AS quantity, 4200 AS line_total_cents;

CREATE OR REPLACE TABLE shop_product AS
SELECT 'product_1' AS product_id, 'beverage' AS product_type;
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _print(
        {
            "ok": True,
            "path": str(target),
            "package_id": package_id,
            "files": ["package.yml", "data/seed_example.sql"],
        }
    )


def cmd_import(args: argparse.Namespace) -> None:
    """Translate an external semantic-layer config into a Semantic Rails
    package directory. Today supports `--from metricflow` (a MetricFlow
    YAML directory or a dbt-emitted `semantic_manifest.json`). No
    MetricFlow runtime is required — the translator reads YAML/JSON
    files standalone."""
    if args.source_format == "metricflow":
        from mf2sr import translate

        report = translate(
            Path(args.source),
            Path(args.output),
            package_id=args.package_id,
            namespace=args.namespace,
            warehouse=args.warehouse,
            default_db=args.default_db,
            description=args.description,
        )
        _print(
            {
                "ok": True,
                "package_dir": str(report.package_dir),
                "models_emitted": report.models_emitted,
                "metrics_emitted": report.metrics_emitted,
                "warnings": report.warnings,
            }
        )
        return
    raise SemanticLayerError(
        "INVALID_CONFIG",
        f"--from {args.source_format!r} is not a supported source format",
    )


def cmd_parse_config(args: argparse.Namespace) -> None:
    ref = resolve_package_reference(package_id=args.package, path=args.path)
    report, _ = parse_config_report(ref, progress=_print_stderr)
    _print(report)
    if not report["ok"]:
        raise SystemExit(1)


def cmd_validate_config(args: argparse.Namespace) -> None:
    ref = resolve_package_reference(package_id=args.package, path=args.path)
    report = validate_config_report(ref, progress=None if args.quiet else _print_stderr)
    # Column reachability runs here too (not just in `check`): a dimension
    # or measure pointing at a column the warehouse doesn't have should
    # fail the command the author actually runs first, not query time.
    if report["ok"]:
        reachability = check_warehouse_column_reachability_report(ref)
        report["column_reachability"] = {
            "ok": reachability["ok"],
            "summary": dict(reachability.get("summary", {})),
            "errors": list(reachability.get("errors", [])),
        }
        if not reachability["ok"]:
            report["ok"] = False
            report["errors"] = list(report.get("errors", [])) + list(reachability.get("errors", []))
    _print(report)
    if not report["ok"]:
        raise SystemExit(1)
    if not getattr(args, "no_manifest", False):
        from .manifest import write_manifest

        runtime = Runtime.from_path(ref.source_path) if ref.source_path else Runtime(ref.package_id)
        try:
            path = write_manifest(runtime)
        except Exception as exc:  # noqa: BLE001 — manifest write is best-effort
            # Always surface a write failure — best-effort doesn't mean silent.
            _print_stderr(f"manifest write failed: {exc}")
        else:
            if not args.quiet:
                _print_stderr(f"manifest written: {path}")


def cmd_check(args: argparse.Namespace) -> None:
    ref = resolve_package_reference(package_id=args.package, path=args.path)
    report = check_package_report(
        ref,
        compare_path=args.compare_path,
        base_ref=args.base_ref,
        artifact_path=args.artifact,
    )
    _print(_check_cli_payload(report, full=args.full))
    if not report["ok"]:
        raise SystemExit(1)


def cmd_build_package(args: argparse.Namespace) -> None:
    ref = resolve_package_reference(package_id=args.package, path=args.path)
    report = build_package_artifact_report(
        ref,
        output_path=args.output,
        compare_path=args.compare_path,
        base_ref=args.base_ref,
    )
    _print(report)
    if not report["ok"]:
        raise SystemExit(1)


def cmd_run_examples(args: argparse.Namespace) -> None:
    ref = resolve_package_reference(package_id=args.package, path=args.path)
    report = run_examples_report(ref)
    _print(report)
    if not report["ok"]:
        raise SystemExit(1)


def cmd_test_package(args: argparse.Namespace) -> None:
    ref = resolve_package_reference(package_id=args.package, path=args.path)
    report = run_package_tests_report(ref)
    _print(report)
    if not report["ok"]:
        raise SystemExit(1)


def cmd_diff_package(args: argparse.Namespace) -> None:
    ref = resolve_package_reference(package_id=args.package, path=args.path)
    _print(diff_package_report(ref, compare_path=args.compare_path, base_ref=args.base_ref))


def cmd_impact_report(args: argparse.Namespace) -> None:
    ref = resolve_package_reference(package_id=args.package, path=args.path)
    _print(impact_report(ref, compare_path=args.compare_path, base_ref=args.base_ref))


def cmd_promote_package(args: argparse.Namespace) -> None:
    ref = resolve_package_reference(package_id=args.package, path=args.path)
    report = promote_package_report(
        ref, environment=args.environment, compare_path=args.compare_path, base_ref=args.base_ref
    )
    _print(report)
    if not report["ok"]:
        raise SystemExit(1)


def _add_config_reference_args(parser: argparse.ArgumentParser, package_choices: list[str]) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--package",
        choices=package_choices,
        help="Registered package id from configs/semantic_rails/. Mutually exclusive with --path.",
    )
    source.add_argument(
        "--path",
        default="",
        help="Path to a package directory or single-file YAML. Mutually exclusive with --package.",
    )


def _check_cli_payload(report: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    if full:
        return report
    payload = {
        "ok": bool(report.get("ok", False)),
        "package": dict(report.get("package", {}) or {}),
        "package_hash": str(report.get("package_hash", "") or ""),
        "summary": dict(report.get("summary", {}) or {}),
        "manifest": dict(report.get("manifest", {}) or {}),
        "artifact": dict(report.get("artifact", {}) or {}),
        "blockers": list(report.get("blockers", []) or []),
    }
    if not payload["ok"]:
        errors = []
        for name, check in dict(report.get("checks", {}) or {}).items():
            if name == "impact" or not isinstance(check, dict):
                continue
            for error in list(check.get("errors", []) or []):
                errors.append({"check": name, **dict(error)})
        payload["errors"] = errors
    return payload


def main() -> None:
    package_choices = list_package_ids()
    parser = argparse.ArgumentParser(
        prog="semantic-rails",
        description=(
            "Semantic Rails CLI — inspect, validate, compile, and execute "
            "Semantic Rails packages. See docs/QUERY_API.md and docs/CURRENT_RUNTIME.md "
            "for the agent loop and supported runtime surfaces."
        ),
    )
    from semantic_rails import __version__

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_packages = sub.add_parser(
        "packages",
        description="List the registered package ids under configs/semantic_rails/.",
    )
    p_packages.set_defaults(func=cmd_packages)

    p_catalog = sub.add_parser(
        "catalog",
        description="Print the package catalog (entities, dimensions, measures, metrics, segments).",
    )
    _add_package_or_path_args(p_catalog, package_choices)
    p_catalog.add_argument(
        "--view",
        default="summary",
        help="Catalog view shape: 'summary' (default) or 'full'.",
    )
    p_catalog.add_argument(
        "--verbosity",
        default="compact",
        help="Output verbosity: 'compact' (default) or 'detailed'.",
    )
    p_catalog.add_argument(
        "--kind",
        default="",
        help="Filter to a single object kind (entity, dimension, measure, metric, segment).",
    )
    p_catalog.add_argument(
        "--search",
        default="",
        help="Substring filter against object names and aliases.",
    )
    p_catalog.add_argument(
        "--entity",
        default="",
        help="Filter to objects attached to a single entity id.",
    )
    _add_policy_context_args(p_catalog)
    p_catalog.set_defaults(func=cmd_catalog)

    p_discover = sub.add_parser(
        "discover",
        description="Rank catalog objects by multi-term relevance for an in-progress query (the recommended agent entry point).",
    )
    _add_package_or_path_args(p_discover, package_choices)
    p_discover.add_argument(
        "--terms",
        required=True,
        help="Comma- or whitespace-separated list of terms to match.",
    )
    p_discover.add_argument(
        "--kinds",
        default="",
        help="Comma-separated kinds to include (entity, dimension, measure, metric, segment).",
    )
    p_discover.add_argument(
        "--query-json",
        default="",
        help="Optional partial query (JSON or @file) to bias ranking against an in-progress build.",
    )
    p_discover.add_argument(
        "--stage",
        default="",
        help="Target builder stage to filter relevance against (e.g. 'metric', 'dimension').",
    )
    p_discover.add_argument(
        "--verbosity",
        default="compact",
        help="Output verbosity: 'compact' (default) or 'detailed'.",
    )
    p_discover.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of ranked candidates to return (default: 10).",
    )
    _add_policy_context_args(p_discover)
    p_discover.set_defaults(func=cmd_discover)

    p_inspect = sub.add_parser(
        "inspect",
        description="Inspect a single object id and return its full metadata, including paths and constraints.",
    )
    _add_package_or_path_args(p_inspect, package_choices)
    p_inspect.add_argument(
        "--object-id",
        required=True,
        help="Fully qualified object id (e.g. 'metric.revenue', 'dimension.order_status').",
    )
    p_inspect.add_argument(
        "--query-json",
        default="",
        help="Optional partial query (JSON or @file) for path-aware inspection in context.",
    )
    p_inspect.add_argument(
        "--verbosity",
        default="compact",
        help="Output verbosity: 'compact' (default) or 'detailed'.",
    )
    _add_policy_context_args(p_inspect)
    p_inspect.set_defaults(func=cmd_inspect)

    p_validate = sub.add_parser(
        "validate",
        description="Validate a query payload against the package without compiling SQL. Returns issues and recovery hints.",
    )
    _add_package_or_path_args(p_validate, package_choices)
    p_validate.add_argument(
        "--query-json",
        required=True,
        help="Query IR payload as JSON, or @path/to/file.json to load from disk.",
    )
    _add_policy_context_args(p_validate)
    p_validate.set_defaults(func=cmd_validate)

    p_compile = sub.add_parser(
        "compile",
        description="Compile a query to SQL without executing it. Returns SQL, output columns, dialect, and physical plan.",
    )
    _add_package_or_path_args(p_compile, package_choices)
    p_compile.add_argument(
        "--query-json",
        required=True,
        help="Query IR payload as JSON, or @path/to/file.json to load from disk.",
    )
    _add_policy_context_args(p_compile)
    p_compile.set_defaults(func=cmd_compile)

    p_parse_config = sub.add_parser(
        "parse-config",
        description="Parse a package config and return the normalized PackageConfig dataclass payload.",
    )
    _add_config_reference_args(p_parse_config, package_choices)
    p_parse_config.set_defaults(func=cmd_parse_config)

    p_validate_config = sub.add_parser(
        "validate-config",
        description="Validate a package config (entities, joins, measures, metrics) and report structural errors.",
    )
    _add_config_reference_args(p_validate_config, package_choices)
    p_validate_config.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages while keeping the JSON validation report.",
    )
    p_validate_config.add_argument(
        "--no-manifest",
        action="store_true",
        help="Skip writing .compiled/manifest.json after successful validation.",
    )
    p_validate_config.set_defaults(func=cmd_validate_config)

    p_check = sub.add_parser(
        "check",
        description="One-command package gate: parse + validate + run examples + run tests, optionally write a manifest-backed artifact.",
    )
    _add_config_reference_args(p_check, package_choices)
    p_check.add_argument(
        "--compare-path",
        default="",
        help="Optional path to a baseline package for diff/impact comparison.",
    )
    p_check.add_argument(
        "--base-ref",
        default="",
        help="Optional git ref (e.g. 'main') to use as a baseline if --compare-path is not given.",
    )
    p_check.add_argument(
        "--artifact",
        default="",
        help="Path to write a manifest-backed deployable artifact (.tar.gz). Optional.",
    )
    p_check.add_argument(
        "--full",
        action="store_true",
        help="Print the full check report instead of the compact summary.",
    )
    p_check.set_defaults(func=cmd_check)

    p_build_package = sub.add_parser(
        "build-package",
        description="Build a manifest-backed deployable package artifact (.tar.gz) from a config.",
    )
    _add_config_reference_args(p_build_package, package_choices)
    p_build_package.add_argument(
        "--output",
        required=True,
        help="Output path for the artifact (typically ending in .tar.gz).",
    )
    p_build_package.add_argument(
        "--compare-path",
        default="",
        help="Optional path to a baseline package for diff/impact comparison.",
    )
    p_build_package.add_argument(
        "--base-ref",
        default="",
        help="Optional git ref (e.g. 'main') to use as a baseline if --compare-path is not given.",
    )
    p_build_package.set_defaults(func=cmd_build_package)

    p_run_examples = sub.add_parser(
        "run-examples",
        description="Run the package-local example queries (declared in examples blocks) against the package.",
    )
    _add_config_reference_args(p_run_examples, package_choices)
    p_run_examples.set_defaults(func=cmd_run_examples)

    p_test_package = sub.add_parser(
        "test-package",
        description="Run the package-local tests (declared in tests blocks) against the package.",
    )
    _add_config_reference_args(p_test_package, package_choices)
    p_test_package.set_defaults(func=cmd_test_package)

    p_diff_package = sub.add_parser(
        "diff-package",
        description="Diff a package config against a baseline (path or git ref) and report structural changes.",
    )
    _add_config_reference_args(p_diff_package, package_choices)
    p_diff_package.add_argument(
        "--compare-path",
        default="",
        help="Path to a baseline package config to diff against.",
    )
    p_diff_package.add_argument(
        "--base-ref",
        default="",
        help="Git ref (e.g. 'main') to use as a baseline if --compare-path is not given.",
    )
    p_diff_package.set_defaults(func=cmd_diff_package)

    p_impact_report = sub.add_parser(
        "impact-report",
        description="Report the downstream impact of changes between a config and a baseline (path or git ref).",
    )
    _add_config_reference_args(p_impact_report, package_choices)
    p_impact_report.add_argument(
        "--compare-path",
        default="",
        help="Path to a baseline package config for impact comparison.",
    )
    p_impact_report.add_argument(
        "--base-ref",
        default="",
        help="Git ref (e.g. 'main') to use as a baseline if --compare-path is not given.",
    )
    p_impact_report.set_defaults(func=cmd_impact_report)

    p_promote_package = sub.add_parser(
        "promote-package",
        description="Promote a package to a target environment (gates on validation + impact + tests).",
    )
    _add_config_reference_args(p_promote_package, package_choices)
    p_promote_package.add_argument(
        "--environment",
        required=True,
        help="Target environment to promote to (e.g. 'staging', 'production').",
    )
    p_promote_package.add_argument(
        "--compare-path",
        default="",
        help="Path to a baseline package config for impact comparison.",
    )
    p_promote_package.add_argument(
        "--base-ref",
        default="",
        help="Git ref (e.g. 'main') to use as a baseline if --compare-path is not given.",
    )
    p_promote_package.set_defaults(func=cmd_promote_package)

    p_query = sub.add_parser(
        "query",
        description="Compile and execute a query against the configured warehouse (DuckDB by default).",
    )
    _add_package_or_path_args(p_query, package_choices)
    p_query.add_argument(
        "--query-json",
        required=True,
        help="Query IR payload as JSON, or @path/to/file.json to load from disk.",
    )
    _add_policy_context_args(p_query)
    p_query.set_defaults(func=cmd_query)

    p_segment_validate = sub.add_parser(
        "segment-validate",
        description="Validate a named segment definition against the package.",
    )
    p_segment_validate.add_argument(
        "--package",
        choices=package_choices,
        default=package_choices[0] if package_choices else "",
        help="Registered package id from configs/semantic_rails/.",
    )
    p_segment_validate.add_argument(
        "--segment-id",
        required=True,
        help="Segment id (e.g. 'segment.high_value_customers').",
    )
    p_segment_validate.set_defaults(func=cmd_segment_validate)

    p_segment_explain = sub.add_parser(
        "segment-explain",
        description="Explain a segment: the basis metric, predicates, anchor entity, and chosen path.",
    )
    p_segment_explain.add_argument(
        "--package",
        choices=package_choices,
        default=package_choices[0] if package_choices else "",
        help="Registered package id from configs/semantic_rails/.",
    )
    p_segment_explain.add_argument(
        "--segment-id",
        required=True,
        help="Segment id (e.g. 'segment.high_value_customers').",
    )
    p_segment_explain.set_defaults(func=cmd_segment_explain)

    p_segment_preview = sub.add_parser(
        "segment-preview",
        description="Preview the resolved member list for a segment (executes against the warehouse).",
    )
    p_segment_preview.add_argument(
        "--package",
        choices=package_choices,
        default=package_choices[0] if package_choices else "",
        help="Registered package id from configs/semantic_rails/.",
    )
    p_segment_preview.add_argument(
        "--segment-id",
        required=True,
        help="Segment id (e.g. 'segment.high_value_customers').",
    )
    p_segment_preview.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum members to return in the preview (default: 50).",
    )
    p_segment_preview.set_defaults(func=cmd_segment_preview)

    p_values = sub.add_parser(
        "valid-values",
        description="List the curated allowed values for a dimension (paginated, supports search).",
    )
    _add_package_or_path_args(p_values, package_choices)
    p_values.add_argument(
        "--dimension",
        required=True,
        help="Dimension id (e.g. 'dimension.order_status').",
    )
    p_values.add_argument(
        "--query-json",
        default="",
        help="Optional partial query (JSON or @file) to scope value retrieval to the in-progress build.",
    )
    p_values.add_argument(
        "--search",
        default="",
        help="Substring filter against the dimension values.",
    )
    p_values.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum values to return (default: 100).",
    )
    p_values.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pagination offset (default: 0).",
    )
    p_values.add_argument(
        "--include-counts",
        action="store_true",
        help="Include row counts per value (executes a count query against the warehouse).",
    )
    _add_policy_context_args(p_values)
    p_values.set_defaults(func=cmd_valid_values)

    p_build = sub.add_parser(
        "build-options",
        description="Ranked builder surface: the recommended next-edit candidates for an in-progress query.",
    )
    _add_package_or_path_args(p_build, package_choices)
    p_build.add_argument(
        "--query-json",
        required=True,
        help="Current query IR payload as JSON, or @path/to/file.json to load from disk.",
    )
    p_build.add_argument(
        "--focus-terms",
        default="",
        help="Comma- or whitespace-separated terms to bias ranking around.",
    )
    p_build.add_argument(
        "--focus-object-id",
        default="",
        help="Object id to focus the build options around.",
    )
    p_build.add_argument(
        "--step",
        default="",
        help="Restrict to a specific builder step (e.g. 'add_dimension', 'add_filter').",
    )
    p_build.add_argument(
        "--stage",
        default="",
        help="Target builder stage filter (e.g. 'metric', 'dimension').",
    )
    p_build.add_argument(
        "--verbosity",
        default="compact",
        help="Output verbosity: 'compact' (default) or 'detailed'.",
    )
    p_build.add_argument(
        "--include-blocked",
        action="store_true",
        help="Include candidates that are currently blocked by guardrails (with reasons).",
    )
    p_build.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of candidates to return (default: 10).",
    )
    _add_policy_context_args(p_build)
    p_build.set_defaults(func=cmd_build_options)

    p_plan = sub.add_parser(
        "plan",
        description="Plan one best Query IR from a free-text intent and optional partial query.",
    )
    _add_package_or_path_args(p_plan, package_choices)
    p_plan.add_argument(
        "--intent",
        required=True,
        help="Free-text intent (e.g. 'monthly revenue by channel for the last quarter').",
    )
    p_plan.add_argument(
        "--query-json",
        default="",
        help="Optional partial query (JSON or @file) to preserve and plan against.",
    )
    p_plan.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Maximum number of planner alternatives to return when detail is full/debug (default: 3).",
    )
    p_plan.add_argument(
        "--detail",
        choices=["best", "full", "debug"],
        default="best",
        help="Planner response detail (default: best). Use full for alternatives/blocked, debug for compose hints.",
    )
    _add_policy_context_args(p_plan)
    p_plan.set_defaults(func=cmd_plan)

    p_mcp = sub.add_parser(
        "mcp",
        description="Run the packaged Model Context Protocol (MCP) server (stdio or HTTP/SSE transport).",
    )
    mcp_sub = p_mcp.add_subparsers(dest="mcp_cmd", required=True)

    p_mcp_stdio = mcp_sub.add_parser(
        "stdio",
        description="Run the MCP server over stdio (for desktop hosts like Claude Desktop).",
    )
    _add_package_or_path_args(p_mcp_stdio, package_choices)
    p_mcp_stdio.set_defaults(func=cmd_mcp_stdio)

    p_mcp_http = mcp_sub.add_parser(
        "http",
        description="Run the MCP server over HTTP/SSE for remote agent integration.",
    )
    _add_package_or_path_args(p_mcp_http, package_choices)
    p_mcp_http.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1).",
    )
    p_mcp_http.add_argument(
        "--port",
        type=int,
        default=8091,
        help="Port to bind (default: 8091).",
    )
    p_mcp_http.set_defaults(func=cmd_mcp_http)

    p_doctor = sub.add_parser(
        "doctor",
        description="Run a configuration doctor against a package: structural checks, common authoring pitfalls, fix hints.",
    )
    _add_config_reference_args(p_doctor, package_choices)
    p_doctor.set_defaults(func=cmd_doctor)

    p_init = sub.add_parser(
        "init",
        description="Scaffold a new single-file package at --output (writes package.yml + data/seed_example.sql). Load it by pointing --path at the package.yml.",
    )
    p_init.add_argument(
        "--output",
        required=True,
        help="Target directory for the new package (created if it does not exist).",
    )
    p_init.add_argument(
        "--package-id",
        default="",
        help="Package id to write into package.yml. Defaults to the output directory name.",
    )
    p_init.add_argument(
        "--namespace",
        default="",
        help="Namespace for derived ids. Defaults to the package id.",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing non-empty output directory.",
    )
    p_init.set_defaults(func=cmd_init)

    p_import = sub.add_parser(
        "import",
        description=(
            "Import a package from an external semantic-layer format. "
            "Today supports `--from metricflow` (a MetricFlow YAML "
            "directory or a dbt-emitted semantic_manifest.json). No "
            "MetricFlow runtime is required — the translator reads "
            "YAML/JSON files standalone."
        ),
    )
    p_import.add_argument(
        "--from",
        dest="source_format",
        required=True,
        choices=["metricflow"],
        help="Source format. Today: 'metricflow' (YAML dir or semantic_manifest.json).",
    )
    p_import.add_argument(
        "--source",
        required=True,
        help="Path to the source artifact (directory or JSON file).",
    )
    p_import.add_argument(
        "--output",
        required=True,
        help="Directory under which <package-id>/ will be created.",
    )
    p_import.add_argument(
        "--package-id",
        required=True,
        help="Semantic Rails package id (drives namespace by default).",
    )
    p_import.add_argument(
        "--namespace",
        default=None,
        help="Namespace prefix for auto-derived ids. Defaults to --package-id.",
    )
    p_import.add_argument(
        "--warehouse",
        default="duckdb",
        choices=("duckdb", "snowflake"),
        help="Warehouse kind to declare in the emitted package.yml.",
    )
    p_import.add_argument(
        "--default-db",
        default=None,
        help="DuckDB file path; recommended for --warehouse duckdb.",
    )
    p_import.add_argument(
        "--description",
        default=None,
        help="Optional package description.",
    )
    p_import.set_defaults(func=cmd_import)

    p_serve = sub.add_parser(
        "serve",
        description="Start the local HTTP API server (foreground/blocking) on --host:--port.",
    )
    p_serve.add_argument(
        "--package",
        choices=package_choices,
        default=package_choices[0] if package_choices else "",
        help="Registered package id from configs/semantic_rails/.",
    )
    p_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1).",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=8090,
        help="Port to bind (default: 8090).",
    )
    p_serve.set_defaults(func=lambda args: serve(args.package, host=args.host, port=args.port))

    args = parser.parse_args()
    try:
        args.func(args)
    except SemanticLayerError as exc:
        # Same diagnostics enrichment as the HTTP boundary
        # (SemanticHTTPService.exception_payload) and the MCP adapter
        # (_error_response) — closest_matches on OBJECT_NOT_FOUND etc.
        # Enrichment is a pure read on the in-memory config, but it must
        # never mask the original error, hence the suppress.
        config = _config_for_error_enrichment(args)
        if config is not None:
            with contextlib.suppress(Exception):
                exc = _enrich_runtime_error(exc, config)
        _print_error_envelope(exception_issue(exc, stage="cli"))
        raise SystemExit(1) from exc
    except Exception as exc:  # pragma: no cover - defensive CLI guardrail
        _print_error_envelope(
            {
                "code": "INTERNAL_ERROR",
                "message": str(exc),
                "severity": "error",
                "stage": "cli",
                "details": {},
                "object_ids": [],
                "path": "",
                "recovery_hints": [],
            }
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    # ``python -m semantic_rails.cli`` previously exited 0 having done
    # nothing, which reads as a silent success.
    main()
