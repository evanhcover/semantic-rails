from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from semantic_rails.db import (
    SnowflakeCliAdapter,
    SnowflakeNativeAdapter,
    build_snowflake_cli_command,
    create_warehouse_adapter,
)
from semantic_rails.dialects import (
    DuckDbDialect,
    SnowflakeDialect,
    supported_warehouses,
    warehouse_connector,
)
from semantic_rails.errors import SemanticLayerError
from semantic_rails.schema import ConnectionSpec, PackageMeta


def test_snowflake_cli_adapter_parses_json_ext_rows(monkeypatch: pytest.MonkeyPatch):
    commands = []

    def _fake_run(*args, **kwargs):
        commands.append(args[0])
        return SimpleNamespace(returncode=0, stdout='[{"ONE": 1, "TWO": "x"}]\n', stderr="")

    monkeypatch.setattr(
        "semantic_rails.db.subprocess.run",
        _fake_run,
    )

    rows = SnowflakeCliAdapter("semantic_views_trial").query("select 1")

    assert rows == [{"ONE": 1, "TWO": "x"}]
    assert commands == [
        ["snow", "sql", "-c", "semantic_views_trial", "--format", "JSON_EXT", "-q", "select 1"]
    ]


def test_snowflake_cli_adapter_casts_nullif_ratio_guards_to_double(
    monkeypatch: pytest.MonkeyPatch,
):
    # Snowflake NUMBER/NUMBER division reduces result scale (~6 digits
    # live), so both Snowflake adapters apply the shared DOUBLE-cast
    # compat pass to the compiler's ratio guard before executing.
    commands = []

    def _fake_run(*args, **kwargs):
        commands.append(args[0])
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr("semantic_rails.db.subprocess.run", _fake_run)

    SnowflakeCliAdapter("semantic_views_trial").query("SELECT a / NULLIF(b, 0) AS r FROM t")

    sent_sql = commands[0][-1]
    assert sent_sql == "SELECT a / CAST(NULLIF(b, 0) AS DOUBLE) AS r FROM t"


def test_snowflake_cli_adapter_maps_subprocess_failures(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "semantic_rails.db.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="connection failed"
        ),
    )

    with pytest.raises(SemanticLayerError) as exc:
        SnowflakeCliAdapter("semantic_views_trial").query("select 1")

    assert exc.value.code == "QUERY_EXECUTION_ERROR"
    assert exc.value.details["engine"] == "snowflake"
    # Adapter-level errors must NOT leak raw SQL — it is redacted by
    # default and only re-attached at the runtime layer when the caller
    # opts in and has the `debug` role.
    assert "sql" not in exc.value.details
    assert exc.value.details.get("sql_redacted") is True


def test_create_warehouse_adapter_selects_snowflake_cli():
    package = PackageMeta(
        package_id="snowflake_demo",
        name="snowflake_demo",
        description="snowflake demo",
        warehouse="snowflake",
        connection=ConnectionSpec(
            kind="snowflake_cli",
            name="semantic_views_trial",
            options={
                "database": "SNOWFLAKE_SAMPLE_DATA",
                "schema": "TPCH_SF1",
                "warehouse": "COMPUTE_WH",
                "role": "ANALYST",
            },
        ),
    )

    adapter = create_warehouse_adapter(package)

    assert isinstance(adapter, SnowflakeCliAdapter)
    assert adapter.connection_name == "semantic_views_trial"
    assert adapter.options == {
        "database": "SNOWFLAKE_SAMPLE_DATA",
        "schema": "TPCH_SF1",
        "warehouse": "COMPUTE_WH",
        "role": "ANALYST",
    }


def test_create_warehouse_adapter_selects_snowflake_native(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SNOW_ACCOUNT", "acct")
    monkeypatch.setenv("SNOW_USER", "svc_user")
    monkeypatch.setenv("SNOW_PASSWORD", "secret")
    package = PackageMeta(
        package_id="snowflake_demo",
        name="snowflake_demo",
        description="snowflake demo",
        warehouse="snowflake",
        connection=ConnectionSpec(
            kind="snowflake_native",
            name="prod_native",
            options={
                "account_env": "SNOW_ACCOUNT",
                "user_env": "SNOW_USER",
                "password_env": "SNOW_PASSWORD",
                "database": "ANALYTICS",
                "schema": "CORE",
                "warehouse": "COMPUTE_WH",
                "role": "ANALYST",
                "query_tag": "semantic-rails-test",
                "statement_timeout_seconds": "30",
            },
        ),
    )

    adapter = create_warehouse_adapter(package)

    assert isinstance(adapter, SnowflakeNativeAdapter)
    kwargs = adapter._connect_kwargs()
    assert "connection_name" not in kwargs
    assert kwargs["account"] == "acct"
    assert kwargs["user"] == "svc_user"
    assert kwargs["password"] == "secret"
    assert kwargs["database"] == "ANALYTICS"
    assert kwargs["session_parameters"] == {
        "QUERY_TAG": "semantic-rails-test",
        "STATEMENT_TIMEOUT_IN_SECONDS": 30,
    }


def test_snowflake_native_named_profile_keeps_connection_name_for_profile_mode():
    adapter = SnowflakeNativeAdapter(
        "prod_native",
        options={
            "database": "ANALYTICS",
            "schema": "CORE",
            "warehouse": "COMPUTE_WH",
            "role": "ANALYST",
        },
    )

    kwargs = adapter._connect_kwargs()

    assert kwargs["connection_name"] == "prod_native"
    assert kwargs["database"] == "ANALYTICS"
    assert kwargs["schema"] == "CORE"
    assert kwargs["warehouse"] == "COMPUTE_WH"
    assert kwargs["role"] == "ANALYST"


def test_create_warehouse_adapter_selects_snowflake_native_direct_connect(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SNOW_ACCOUNT", "acct")
    monkeypatch.setenv("SNOW_USER", "svc_user")
    monkeypatch.setenv("SNOW_PASSWORD", "secret")
    package = PackageMeta(
        package_id="snowflake_demo",
        name="snowflake_demo",
        description="snowflake demo",
        warehouse="snowflake",
        connection=ConnectionSpec(
            kind="snowflake_native",
            options={
                "account_env": "SNOW_ACCOUNT",
                "user_env": "SNOW_USER",
                "password_env": "SNOW_PASSWORD",
                "database": "ANALYTICS",
            },
        ),
    )

    adapter = create_warehouse_adapter(package)

    assert isinstance(adapter, SnowflakeNativeAdapter)
    kwargs = adapter._connect_kwargs()
    assert "connection_name" not in kwargs
    assert kwargs["account"] == "acct"
    assert kwargs["user"] == "svc_user"
    assert kwargs["password"] == "secret"
    assert kwargs["database"] == "ANALYTICS"


def test_snowflake_native_adapter_queries_with_optional_connector(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeCursor:
        description = [("ONE",), ("TWO",)]

        def execute(self, sql):
            captured["sql"] = sql

        def fetchall(self):
            return [(1, "x")]

        def close(self):
            captured["closed"] = True

    class FakeConnection:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def cursor(self):
            return FakeCursor()

        def close(self):
            captured["connection_closed"] = True

    connector_module = types.ModuleType("snowflake.connector")
    connector_module.connect = lambda **kwargs: FakeConnection(**kwargs)
    snowflake_module = types.ModuleType("snowflake")
    snowflake_module.connector = connector_module
    monkeypatch.setitem(sys.modules, "snowflake", snowflake_module)
    monkeypatch.setitem(sys.modules, "snowflake.connector", connector_module)
    monkeypatch.setenv("SNOW_ACCOUNT", "acct")
    monkeypatch.setenv("SNOW_TOKEN", "oauth-token")

    adapter = SnowflakeNativeAdapter(
        "prod_native",
        options={
            "account_env": "SNOW_ACCOUNT",
            "authenticator": "oauth",
            "token_env": "SNOW_TOKEN",
        },
    )
    rows = adapter.query("select 1")
    adapter.close()

    assert rows == [{"ONE": 1, "TWO": "x"}]
    assert captured["sql"] == "select 1"
    assert captured["kwargs"]["account"] == "acct"
    assert captured["kwargs"]["connection_name"] == "prod_native"
    assert captured["kwargs"]["authenticator"] == "oauth"
    assert captured["kwargs"]["token"] == "oauth-token"
    assert captured["closed"] is True
    assert captured["connection_closed"] is True


def test_snowflake_native_direct_connect_externalbrowser_omits_connection_name(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SNOW_ACCOUNT", "acct")
    monkeypatch.setenv("SNOW_USER", "svc_user")
    adapter = SnowflakeNativeAdapter(
        "custom_name",
        options={
            "account_env": "SNOW_ACCOUNT",
            "user_env": "SNOW_USER",
            "authenticator": "externalbrowser",
        },
    )

    kwargs = adapter._connect_kwargs()

    assert "connection_name" not in kwargs
    assert kwargs["account"] == "acct"
    assert kwargs["user"] == "svc_user"
    assert kwargs["authenticator"] == "externalbrowser"


def test_snowflake_native_direct_connect_reports_missing_env_without_secret_value(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SNOW_ACCOUNT", "acct")
    monkeypatch.setenv("SNOW_PASSWORD", "super-secret")
    adapter = SnowflakeNativeAdapter(
        options={
            "account_env": "SNOW_ACCOUNT",
            "user_env": "SNOW_USER",
            "password_env": "SNOW_PASSWORD",
        },
    )

    with pytest.raises(SemanticLayerError) as exc:
        adapter._connect_kwargs()

    assert exc.value.code == "INVALID_CONFIG"
    assert exc.value.details["missing_env"] == ["SNOW_USER"]
    assert "super-secret" not in str(exc.value)
    assert "super-secret" not in repr(exc.value.details)


def test_snowflake_native_adapter_rejects_incomplete_direct_connect_options():
    with pytest.raises(SemanticLayerError) as exc:
        SnowflakeNativeAdapter(options={"account_env": "SNOW_ACCOUNT", "user_env": "SNOW_USER"})

    assert exc.value.code == "INVALID_CONFIG"
    assert "direct connection" in str(exc.value)


def test_snowflake_cli_command_includes_standard_connection_options():
    cmd = build_snowflake_cli_command(
        "semantic_views_trial",
        "select 1",
        {
            "database": "SNOWFLAKE_SAMPLE_DATA",
            "schema": "TPCH_SF1",
            "warehouse": "COMPUTE_WH",
            "role": "ANALYST",
        },
    )

    assert cmd == [
        "snow",
        "sql",
        "-c",
        "semantic_views_trial",
        "--database",
        "SNOWFLAKE_SAMPLE_DATA",
        "--schema",
        "TPCH_SF1",
        "--warehouse",
        "COMPUTE_WH",
        "--role",
        "ANALYST",
        "--format",
        "JSON_EXT",
        "-q",
        "select 1",
    ]


def test_snowflake_cli_adapter_rejects_unsupported_options():
    with pytest.raises(SemanticLayerError) as exc:
        SnowflakeCliAdapter("semantic_views_trial", options={"authenticator": "externalbrowser"})

    assert exc.value.code == "INVALID_CONFIG"
    assert "unsupported package.connection option 'authenticator'" in str(exc.value)


def test_warehouse_connector_registry_exposes_first_class_duckdb_and_snowflake():
    assert supported_warehouses() == (
        "athena",
        "bigquery",
        "clickhouse",
        "databricks",
        "duckdb",
        "ducklake",
        "motherduck",
        "postgres",
        "snowflake",
    )

    duckdb = warehouse_connector("duckdb")
    snowflake = warehouse_connector("snowflake")

    assert duckdb is not None
    assert isinstance(duckdb.dialect, DuckDbDialect)
    assert duckdb.requires_default_db is True
    assert duckdb.requires_seed is True

    assert snowflake is not None
    assert isinstance(snowflake.dialect, SnowflakeDialect)
    assert snowflake.connection_kinds == ("snowflake_cli", "snowflake_native")
    assert "database" in snowflake.connection_options
    assert "account_env" in snowflake.connection_options
    assert "query_tag" in snowflake.connection_options
    assert snowflake.requires_connection_name is True


def test_every_registered_connector_names_an_adapter_entry_point():
    # Registry-driven factory contract: every supported warehouse must
    # carry a resolvable "module:callable" adapter entry point so
    # create_warehouse_adapter never needs per-warehouse branches.
    import importlib

    for name in supported_warehouses():
        connector = warehouse_connector(name)
        assert connector is not None
        assert connector.adapter, f"{name} connector has no adapter entry point"
        module_name, _, attr = connector.adapter.partition(":")
        factory = getattr(importlib.import_module(module_name), attr, None)
        assert callable(factory), f"{name} adapter entry point {connector.adapter} not callable"
