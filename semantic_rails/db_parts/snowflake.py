"""Snowflake warehouse adapters and connection-option helpers.

Extracted from :mod:`semantic_rails.db` to keep that module under the
500-LOC ceiling. The public API is unchanged — :mod:`semantic_rails.db`
re-exports every name defined here, so external callers should keep
importing from ``semantic_rails.db``.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from typing import Any

from ..dialects import (
    SNOWFLAKE_CLI_CONNECTION_OPTIONS,
    SNOWFLAKE_NATIVE_CONNECTION_OPTIONS,
    normalize_connection_option_name,
    snowflake_native_direct_connect_errors,
)
from ..errors import SemanticLayerError
from .base import WarehouseAdapter, _clip_rows, _limit_timeout_seconds
from .common import (
    bounded_error_text as _bounded_error_text,
)
from .common import (
    env_value as _env_value,
)
from .common import (
    float_nullif_divisions,
    normalize_connection_options,
    require_missing_env,
    secret_value,
)


def _extract_snowflake_json_rows(stdout: str) -> list[dict[str, Any]]:
    text = str(stdout or "").strip()
    if not text:
        return []
    # CLI stdout may contain query result rows — never attach it to error
    # details, which flow into public HTTP/MCP/CLI error envelopes. Only
    # bounded metadata (length, JSON error position) is safe to surface.
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SemanticLayerError(
            "QUERY_EXECUTION_ERROR",
            f"Snowflake CLI returned invalid JSON_EXT output: {exc}",
            details={"engine": "snowflake", "stdout_bytes": len(text), "stdout_redacted": True},
        ) from exc
    if isinstance(payload, list):
        return [dict(row or {}) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [dict(row or {}) for row in payload["data"] if isinstance(row, dict)]
    raise SemanticLayerError(
        "QUERY_EXECUTION_ERROR",
        "Snowflake CLI returned an unexpected JSON_EXT payload",
        details={"engine": "snowflake", "stdout_bytes": len(text), "stdout_redacted": True},
    )


class SnowflakeCliAdapter(WarehouseAdapter):
    engine = "snowflake"
    # Honors statement_timeout_ms via ALTER SESSION wrapper around the SQL.
    supports_statement_timeout = True

    def __init__(self, connection_name: str, options: dict[str, Any] | None = None):
        self.connection_name = str(connection_name).strip()
        if not self.connection_name:
            raise SemanticLayerError(
                "INVALID_CONFIG", "Snowflake adapter requires a connection name"
            )
        self.options = _normalize_snowflake_cli_options(options or {})

    def query(self, sql: str, *, limits: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        timeout_s = _limit_timeout_seconds(limits)
        # Same DOUBLE-cast ratio compat pass as the native adapter (see
        # SnowflakeNativeAdapter.query) — keeps both Snowflake paths on
        # the cross-warehouse parity contract.
        effective_sql = float_nullif_divisions(sql, cast_type="DOUBLE")
        if timeout_s > 0:
            # Snowflake supports session-level statement timeout via ALTER SESSION.
            # Compose a multi-statement script so the timeout is set then released.
            effective_sql = (
                f"alter session set statement_timeout_in_seconds = {timeout_s};\n"
                f"{effective_sql};\n"
                "alter session unset statement_timeout_in_seconds;"
            )
        cmd = build_snowflake_cli_command(self.connection_name, effective_sql, self.options)
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            # Mirror the native adapter's redacted error shape: connection
            # NAME and option KEYS only, never option values, raw SQL, or
            # full stdout (which can carry result rows). stderr is bounded
            # into the message so authors still see Snowflake's compile
            # error; the runtime re-attaches raw SQL only when the request
            # asks for it AND the caller has the `debug` role.
            message = _bounded_error_text(result.stderr) or "snow sql failed"
            raise SemanticLayerError(
                "QUERY_EXECUTION_ERROR",
                f"Snowflake query execution failed: {message}",
                details={
                    "engine": self.engine,
                    "connection_kind": "snowflake_cli",
                    "connection": self.connection_name,
                    "option_keys": sorted(self.options),
                    "sql_redacted": True,
                    "exit_code": result.returncode,
                },
            )
        try:
            rows = _extract_snowflake_json_rows(result.stdout)
        except SemanticLayerError as exc:
            details = dict(exc.details)
            details.setdefault("connection_kind", "snowflake_cli")
            details.setdefault("connection", self.connection_name)
            details.setdefault("sql_redacted", True)
            raise SemanticLayerError(exc.code, str(exc), details=details) from exc
        return _clip_rows(rows, limits)

    def close(self) -> None:
        return None


class SnowflakeNativeAdapter(WarehouseAdapter):
    engine = "snowflake"
    # Honors statement_timeout_ms via ALTER SESSION on the session-level
    # STATEMENT_TIMEOUT_IN_SECONDS parameter.
    supports_statement_timeout = True

    def __init__(self, connection_name: str = "", options: dict[str, Any] | None = None):
        self.connection_name = str(connection_name).strip()
        self.options = _normalize_snowflake_native_options(options or {})
        if not self.connection_name:
            direct_errors = snowflake_native_direct_connect_errors(self.options)
            if direct_errors:
                raise SemanticLayerError(
                    "INVALID_CONFIG",
                    f"Snowflake native connection is incomplete: {'; '.join(direct_errors)}",
                )
        self._conn: Any = None

    def _uses_direct_connection(self) -> bool:
        return not snowflake_native_direct_connect_errors(self.options)

    def _connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.connection_name and not self._uses_direct_connection():
            kwargs["connection_name"] = self.connection_name
        missing_env: list[str] = []
        account = _env_value(self.options.get("account_env", ""), missing_env)
        user = _env_value(self.options.get("user_env", ""), missing_env)
        password = _env_value(self.options.get("password_env", ""), missing_env)
        token_file = self.options.get("token_file", "")
        token = _secret_value(
            "token",
            self.options.get("token_env", ""),
            token_file,
            missing_env if not token_file else None,
        )
        private_key_file = self.options.get("private_key_file", "")
        private_key = _secret_value(
            "private_key",
            self.options.get("private_key_env", ""),
            "",
            missing_env if not private_key_file else None,
        )
        private_key_passphrase = _env_value(
            self.options.get("private_key_passphrase_env", ""), missing_env
        )
        require_missing_env(
            missing_env,
            engine="snowflake",
            connection_kind="snowflake_native",
            label="Snowflake native",
        )
        if account:
            kwargs["account"] = account
        if user:
            kwargs["user"] = user
        if password:
            kwargs["password"] = password
        if token:
            kwargs["token"] = token
        if private_key:
            kwargs["private_key"] = private_key
        if private_key_file:
            kwargs["private_key_file"] = private_key_file
        if private_key_passphrase:
            kwargs["private_key_file_pwd"] = private_key_passphrase
        for key in ("authenticator", "database", "schema", "warehouse", "role"):
            if self.options.get(key):
                kwargs[key] = self.options[key]
        session_parameters: dict[str, Any] = {}
        if self.options.get("query_tag"):
            session_parameters["QUERY_TAG"] = self.options["query_tag"]
        if self.options.get("statement_timeout_seconds"):
            session_parameters["STATEMENT_TIMEOUT_IN_SECONDS"] = int(
                self.options["statement_timeout_seconds"]
            )
        if session_parameters:
            kwargs["session_parameters"] = session_parameters
        kwargs.setdefault("application", "semantic-rails")
        return kwargs

    def _connection(self) -> Any:
        if self._conn is None:
            try:
                import snowflake.connector
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise SemanticLayerError(
                    "MISSING_DEPENDENCY",
                    "Install semantic-rails[snowflake] to use package.connection.kind snowflake_native.",
                    details={"engine": "snowflake", "connection_kind": "snowflake_native"},
                ) from exc
            self._conn = snowflake.connector.connect(**self._connect_kwargs())
        return self._conn

    def query(self, sql: str, *, limits: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        timeout_s = _limit_timeout_seconds(limits)
        # Documented, literal-aware compat pass (same as the Postgres /
        # Databricks / Athena adapters): Snowflake NUMBER/NUMBER division
        # reduces the result scale (~6 digits live), drifting ratio metrics
        # off the cross-warehouse parity contract; cast the compiler's
        # `x / NULLIF(y, 0)` guard to DOUBLE.
        effective_sql = float_nullif_divisions(sql, cast_type="DOUBLE")
        try:
            cursor = self._connection().cursor()
            try:
                if timeout_s > 0:
                    cursor.execute(f"alter session set statement_timeout_in_seconds = {timeout_s}")
                cursor.execute(effective_sql)
                columns = [str(col[0]) for col in list(cursor.description or [])]
                rows = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
                return _clip_rows(rows, limits)
            finally:
                if timeout_s > 0:
                    with contextlib.suppress(Exception):  # best-effort reset
                        cursor.execute("alter session unset statement_timeout_in_seconds")
                cursor.close()
        except SemanticLayerError:
            raise
        except Exception as exc:
            raise SemanticLayerError(
                "QUERY_EXECUTION_ERROR",
                f"Snowflake native query execution failed: {exc}",
                details={
                    "engine": self.engine,
                    "connection_kind": "snowflake_native",
                    "connection": self.connection_name,
                    "option_keys": sorted(self.options),
                    "sql_redacted": True,
                },
            ) from exc

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _normalize_snowflake_options(
    kind: str, options: dict[str, Any], allowed: tuple[str, ...]
) -> dict[str, str]:
    # Shared logic (unknown-option rejection, literal-secret rejection,
    # key normalization) lives in db_parts.common so every adapter
    # enforces the same secrets contract.
    label = "Snowflake CLI" if kind == "snowflake_cli" else "Snowflake native"
    return normalize_connection_options("snowflake", kind, options, allowed, label=label)


def _normalize_snowflake_cli_options(options: dict[str, Any]) -> dict[str, str]:
    return _normalize_snowflake_options("snowflake_cli", options, SNOWFLAKE_CLI_CONNECTION_OPTIONS)


def _normalize_snowflake_native_options(options: dict[str, Any]) -> dict[str, str]:
    normalized = _normalize_snowflake_options(
        "snowflake_native", options, SNOWFLAKE_NATIVE_CONNECTION_OPTIONS
    )
    secret_literal_keys = {"password", "token", "private_key"}
    for key in secret_literal_keys:
        if key in {normalize_connection_option_name(str(raw_key)) for raw_key in (options or {})}:
            raise SemanticLayerError(
                "INVALID_CONFIG",
                f"Snowflake native package.connection option '{key}' is not allowed; use env/file indirection instead",
            )
    return normalized


def _secret_value(
    option_name: str, env_name: str, file_name: str, missing_env: list[str] | None = None
) -> str:
    return secret_value(
        option_name,
        env_name,
        file_name,
        missing_env,
        engine="snowflake",
        connection_kind="snowflake_native",
        label="Snowflake native",
    )


def create_adapter(package: Any, *, db_path: str = "") -> WarehouseAdapter:
    """Registry entry point for the snowflake warehouse (see dialects.py)."""
    kind = package.connection.kind
    if kind not in ("snowflake_cli", "snowflake_native"):
        raise SemanticLayerError(
            "INVALID_CONFIG",
            f"Unsupported Snowflake connection kind '{kind}'",
        )
    if kind == "snowflake_native":
        return SnowflakeNativeAdapter(package.connection.name, options=package.connection.options)
    return SnowflakeCliAdapter(package.connection.name, options=package.connection.options)


def build_snowflake_cli_command(
    connection_name: str, sql: str, options: dict[str, Any] | None = None
) -> list[str]:
    connection = str(connection_name).strip()
    if not connection:
        raise SemanticLayerError("INVALID_CONFIG", "Snowflake adapter requires a connection name")
    normalized = _normalize_snowflake_cli_options(options or {})
    cmd = ["snow", "sql", "-c", connection]
    option_flags = {
        "database": "--database",
        "schema": "--schema",
        "warehouse": "--warehouse",
        "role": "--role",
    }
    for option_name in SNOWFLAKE_CLI_CONNECTION_OPTIONS:
        if option_name in normalized:
            cmd.extend([option_flags[option_name], normalized[option_name]])
    cmd.extend(["--format", "JSON_EXT", "-q", sql])
    return cmd
