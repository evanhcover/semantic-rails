# Semantic Rails

[![PyPI](https://img.shields.io/pypi/v/semantic-rails.svg?label=PyPI)](https://pypi.org/project/semantic-rails/) [![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/semantic-rails/) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE) [![Docs](https://img.shields.io/badge/docs-semantic--rails.com-0f766e.svg)](https://semantic-rails.com/docs/)

<p align="center"><a href="https://semantic-rails.com"><picture><source media="(prefers-color-scheme: dark)" srcset="website/assets/images/logo-readme-dark.svg"><source media="(prefers-color-scheme: light)" srcset="website/assets/images/logo-readme-light.svg"><img src="website/assets/images/logo-readme-light.svg" alt="Semantic Rails" width="520"></picture></a></p>

> If your agent can't `discover → inspect → plan/build-options → valid-values → validate → compile → execute` before it queries, you don't have a semantic layer for agents — you have a SQL generator with a metric registry. Semantic Rails is the runtime that makes that loop deterministic.

Semantic Rails is an Apache-2.0-licensed, agent-first semantic layer. It ships an MCP server (stdio + HTTP) and an HTTP/JSON API where each step is a separately introspectable surface. Modeling errors — unknown metrics, dimension mismatches, invalid filters, policy violations — are structured envelopes that, where applicable, include `recovery_hints` and `closest_matches`; transport-level errors (invalid JSON, missing auth, unrouted paths) use a leaner envelope with a `code` and `message`. Every off-topic intent is routed through a relevance floor inside `discover` and `plan` before the runtime answers. DuckDB runs locally with zero setup; Snowflake, Postgres, BigQuery, Databricks, Athena, ClickHouse, MotherDuck, and DuckLake connect through optional drivers.

```bash
pip install semantic-rails
semantic-rails packages   # lists the bundled jaffle_shop proof package
semantic-rails query --package jaffle_shop --query-json '{
  "version": 1,
  "select": [{"expression": {"measure": "measure.jaffle.revenue_usd"}, "as": "revenue_usd"}],
  "group_by": ["dimension.jaffle_store_name"],
  "order_by": [{"field": "revenue_usd", "direction": "DESC"}],
  "limit": 5
}'
```

The Query IR payload works against `validate`, `compile`, and `query`; agents use
`discover`, `inspect`, `plan`, `build-options`, and `valid-values` to assemble it before
execution. Working from a clone instead (contributors, or to use the ready-made payloads
under `examples/`):

```bash
git clone https://github.com/semantic-rails/semantic-rails.git
cd semantic-rails
uv sync --group dev
uv run semantic-rails query --package jaffle_shop --query-json '@examples/jaffle_shop_revenue_by_store.json'
```

Website: [semantic-rails.com](https://semantic-rails.com) ·
[Try live](https://semantic-rails.com/try) ·
[Hosted MCP](https://semantic-rails.com/mcp-docs)

License: Apache 2.0; see [LICENSE](LICENSE). Community support, issue reporting, conduct, and security
reporting are documented in [SUPPORT.md](SUPPORT.md), [CONTRIBUTING.md](CONTRIBUTING.md),
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).

## First Value in 90 Seconds

| Goal | Fast path |
| --- | --- |
| Try the product without installing anything | Open [semantic-rails.com/try](https://semantic-rails.com/try) and run a synthetic Jaffle Shop query. |
| See the agent loop locally | `pip install semantic-rails`, then run the query above against the bundled `jaffle_shop` package. |
| Connect an MCP client | Use the hosted endpoint at `https://semantic-rails.com/mcp`, or run `semantic-rails mcp stdio --package jaffle_shop` locally. |
| Check whether it solves your layer problem | Read [comparisons/semantic_layers/](comparisons/semantic_layers/) for the executed comparison pack and [docs/CAPABILITIES.md](docs/CAPABILITIES.md) for supported primitives. |
| Author your own package | Start from [configs/examples/semantic_rails_package_starter.yml](configs/examples/semantic_rails_package_starter.yml), then run `semantic-rails check --package <id>`. |

What you should notice first: an agent can discover governed objects, ask for valid build options, validate a draft Query IR, compile SQL with an explain payload, and only then execute. That makes failures recoverable instead of turning every analytics question into a blind SQL-generation attempt.

## At a Glance

| Surface | Current release posture |
| --- | --- |
| Package | `semantic-rails` on PyPI, Python package `semantic_rails`, CLI `semantic-rails` |
| Interfaces | MCP stdio, MCP Streamable HTTP, HTTP `/api/v1/*`, CLI, and in-process Python |
| Default proof package | Synthetic `jaffle_shop` package with local DuckDB fixtures |
| Warehouse support | DuckDB by default; optional drivers for Snowflake, Postgres, BigQuery, Databricks, Athena, ClickHouse, MotherDuck, and DuckLake |
| Governance | Query IR validation, policy context, relevance floor, structured recovery envelopes, and compile-time explain metadata |
| Status | Beta `0.1.1`; open-source runtime, not a managed hosted cloud product |

## How It Is Different

Readers commonly compare Semantic Rails with three adjacent categories. None of them describe this project.

- **Not the Open Semantic Interface (OSI).** OSI is a metadata-interchange spec — "the JSON-Schema for semantic layers." Semantic Rails is a runtime: it compiles deterministic SQL, runs an MCP server that exposes `discover → inspect → plan/build-options → valid-values → validate → compile → execute` as separate tools, and ships governed primitives (`metric_predicate`, temporal-validity joins, same-store conversion, contextual entity-graph inheritance) with reviewed guardrails. OSI compatibility would be a metadata adapter we could add later. It would not be the product.
- **Not another MetricFlow / Cube / Malloy / Snowflake Semantic View / KtX / Kyvos-style semantic surface.** Those are SQL-generation, BI-semantic, or context-layer surfaces. Semantic Rails is an agent runtime where SQL generation is *one of seven steps an LLM can introspect*. See [comparisons/semantic_layers/](comparisons/semantic_layers/) — on the q01–q07 baseline nearly every executed layer scores 7 native (Cube takes one workaround, on q05), Kyvos is tracked as doc-backed, and the pack shows the cost of the workaround on q08–q16, where Semantic Rails's primitives are first-class.
- **Not dbt Semantic Layer Cloud.** dbt's Semantic Layer is a hosted product, and its MCP server exposes a handful of semantic tools shaped around list-metrics/get-dimensions/query. Semantic Rails is open-source Apache 2.0, runs locally on DuckDB or Snowflake, and exposes the full loop — discovery, inspection, guided building, validation, compile, and execution — as 13 separately introspectable MCP tools with structured recovery envelopes. The hostable-without-forking work (pluggable audit sinks, env-controlled CORS, per-request limits, in-process reload, public `Runtime.set_compile_cache` seam) makes a future hosted product possible — it is not the OSS product.

The shape of the runtime is the differentiator. An MCP server with a relevance floor, structured error envelopes, and seven introspectable steps is not the same primitive as a SQL renderer, even when both can answer "revenue by store last month."

## Runtime Shape

- Runtime package: `semantic_rails/`
- Package configs: `configs/semantic_rails/<package>/`
- Public website: `website/`
- Focused tests: `tests/semantic_rails/`

## Documentation

Start here depending on what you need:

- Project overview and first run: [README.md](README.md)
- Package authoring: [PACKAGE_AUTHORING.md](docs/PACKAGE_AUTHORING.md)
- Deployment: [DEPLOYMENT.md](docs/DEPLOYMENT.md)
- Agent quickstart: [AGENT_QUICKSTART.md](docs/AGENT_QUICKSTART.md)
- MCP interface: [MCP_INTERFACE.md](docs/MCP_INTERFACE.md)
- Agent API path: [AGENT_API_PATH.md](docs/AGENT_API_PATH.md)
- Query AST and API contracts: [QUERY_API.md](docs/QUERY_API.md)
- Query IR JSON Schema (Draft 2020-12): [QUERY_IR_SCHEMA.md](docs/QUERY_IR_SCHEMA.md) · [schemas/query_ir.v1.json](schemas/query_ir.v1.json)
- Supported capabilities and current limits: [CAPABILITIES.md](docs/CAPABILITIES.md)
- Benchmark evidence: [BENCHMARK_EVIDENCE.md](docs/BENCHMARK_EVIDENCE.md)
- Architecture spec: [ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Contributor guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Comparative capability evidence vs MetricFlow, Cube, Malloy, Snowflake Semantic Views, KtX, and doc-backed Kyvos: [comparisons/semantic_layers/](comparisons/semantic_layers/)
- Migrating from MetricFlow: `semantic-rails import --from metricflow` translates a dbt/MetricFlow project into a Semantic Rails package — see [mf2sr/](mf2sr/) for what translates and what is dropped with warnings
- Annotated reference artifact: [semantic_rails_capabilities_reference.yml](configs/examples/semantic_rails_capabilities_reference.yml)
- Starter package: [semantic_rails_package_starter.yml](configs/examples/semantic_rails_package_starter.yml)

## Package Naming

Semantic Rails is the public product name; the PyPI distribution is `semantic-rails`, the Python import package is `semantic_rails`, and the CLI is `semantic-rails`. The wheel ships the `semantic_rails` package and `mf2sr` (the MetricFlow translator behind `semantic-rails import`). (The project was developed under the `semantic_layer` name, but the unrelated PyPI project `semantic-layer` owns that import namespace, so everything was renamed before first publish — no compatibility shim ships.)

## Quickstart

Start from a clean checkout with Python 3.11+ and `uv` installed. If you do not have `uv`, install it from
[docs.astral.sh/uv](https://docs.astral.sh/uv/) and reopen your shell.

```bash
git clone https://github.com/semantic-rails/semantic-rails.git
cd semantic-rails
```

```bash
uv venv
uv sync --group dev
```

Build and smoke-test the installable wheel when checking the packaging path:

```bash
uv build --wheel
python3 -m venv /tmp/semantic-rails-wheel-smoke
/tmp/semantic-rails-wheel-smoke/bin/python -m pip install dist/semantic_rails-0.1.1-py3-none-any.whl
/tmp/semantic-rails-wheel-smoke/bin/semantic-rails packages
uv run python scripts/verify_package_distribution.py
```

Without `uv`, install the built wheel into any environment with plain pip:

```bash
python -m pip install dist/semantic_rails-0.1.1-py3-none-any.whl
```

The wheel includes the `semantic_rails` runtime, the `semantic-rails` console script, the bundled
`jaffle_shop` proof package, and its local DuckDB/CSV seed assets. The distribution verifier builds
a fresh wheel, installs it into an isolated virtual environment, and runs `packages`, `catalog`, and
`query` from that installed environment.

List packages:

```bash
uv run semantic-rails packages
```

Expected output includes the bundled proof package:

```text
jaffle_shop
```

Inspect catalog and package metadata:

```bash
uv run semantic-rails catalog --package jaffle_shop
uv run semantic-rails discover --package jaffle_shop --terms drinks
uv run semantic-rails inspect --package jaffle_shop --object-id measure.jaffle.order_count
uv run semantic-rails build-options --package jaffle_shop --query-json '@examples/jaffle_shop_revenue_by_store.json' --step group_by
uv run semantic-rails plan --package jaffle_shop --intent "new customer orders over time"
```

Validate, compile, and query:

```bash
uv run semantic-rails validate --package jaffle_shop --query-json '@examples/jaffle_shop_revenue_by_store.json'
uv run semantic-rails compile --package jaffle_shop --query-json '@examples/jaffle_shop_revenue_by_store.json'
uv run semantic-rails query --package jaffle_shop --query-json '@examples/jaffle_shop_revenue_by_store.json'
```

The `compile` response includes an `explain` payload with the semantic and physical plan, chosen relationship paths, candidate paths, and relationship contracts.

A successful query prints a JSON response with `rows`, `row_count`, `output_columns`, and execution metadata. For the
bundled example, the row data is grouped by store using the local DuckDB fixture at
`data/jaffle_shop.duckdb`.

Parse and validate authored package configs:

```bash
uv run semantic-rails parse-config --package jaffle_shop
uv run semantic-rails validate-config --package jaffle_shop
uv run semantic-rails run-examples --package jaffle_shop
uv run semantic-rails test-package --package jaffle_shop
uv run semantic-rails check --package jaffle_shop
uv run semantic-rails build-package --package jaffle_shop --output dist/jaffle_shop.semantic-rails.tar.gz
uv run semantic-rails impact-report --package jaffle_shop --base-ref main
uv run semantic-rails validate-config --path /path/to/package
```

`check` is the one-command package gate for GitHub-hosted configs. It runs parse, validation probes, package-local examples, package-local tests, and emits a manifest with the package hash. Pass `--artifact path/to/package.tar.gz` to write the deployable config artifact in the same run.

Snowflake packages are supported through `package.warehouse: snowflake` plus either
`package.connection.kind: snowflake_cli` or `snowflake_native`. The sample package is
[tpch_sf1_showcase](configs/semantic_rails/tpch_sf1_showcase); live validation uses the Snow CLI
and the configured `semantic_views_trial` connection documented in
[SNOWFLAKE_SHOWCASE_RUNBOOK.md](docs/SNOWFLAKE_SHOWCASE_RUNBOOK.md). Native Snowflake execution is
optional and keeps secrets in environment variables or files rather than package YAML.

Run the server:

```bash
uv run semantic-rails serve --package jaffle_shop --port 8081
```

Run the packaged MCP server:

```bash
uv run semantic-rails mcp stdio --package jaffle_shop
uv run semantic-rails mcp http --package jaffle_shop --host 127.0.0.1 --port 8091
```

For agent integration, start with [AGENT_QUICKSTART.md](docs/AGENT_QUICKSTART.md).
It separates the supported local runtime from the hosted synthetic-data demo and
spells out the intended tool order before execution.

The public launch endpoint is stateless MCP Streamable HTTP at
`https://semantic-rails.com/mcp` using protocol version `2025-11-25`. It is an anonymous,
scale-to-zero demo fixed to synthetic Jaffle Shop data: no uploads or external credentials,
100 executed rows maximum, 25 segment-preview rows maximum, and edge rate/body/deadline limits.
Use `summary`, `minimal`, or `compact` responses unless a debugging task requires `full`.

Run the deployable ASGI service locally:

```bash
uv run --extra server uvicorn semantic_rails.asgi:app --host 0.0.0.0 --port 8081
curl -s http://127.0.0.1:8081/api/v1/health
curl -s http://127.0.0.1:8081/api/v1/ready
```

Day-1 backend smoke (what a new contributor actually needs):

```bash
uv run pytest -q tests/semantic_rails -n auto
uv run semantic-rails check --package jaffle_shop
```

The full verification matrix — wheel smoke (`scripts/verify_package_distribution.py`),
release-readiness verifier (`scripts/verify_release_readiness.py`), benchmark gate
(`scripts/benchmark_plan.py --gate`), and public demo smoke
(`scripts/smoke_public_demo.py`) — is documented in
[CONTRIBUTING.md § Full Verification Matrix](CONTRIBUTING.md#full-verification-matrix).

Snowflake live smoke flow, after configuring the Snow CLI connection:

```bash
snow connection list
uv run semantic-rails parse-config --package tpch_sf1_showcase
uv run semantic-rails validate-config --package tpch_sf1_showcase
uv run semantic-rails serve --package tpch_sf1_showcase --port 8092
```

## Warehouses

Nine warehouses are registered: DuckDB (the zero-setup local default), Snowflake,
Postgres, BigQuery, Databricks, Athena, ClickHouse, MotherDuck, and DuckLake.
Each driver is an optional extra — install only what you connect to:

```bash
pip install 'semantic-rails[postgres]'    # also: snowflake, bigquery, databricks, athena, clickhouse
pip install 'semantic-rails[all]'         # every connector
```

MotherDuck and DuckLake ride on the core `duckdb` dependency, so they need no extra.
A package switches warehouse with `package.warehouse:` plus a `package.connection:`
block; secrets are never YAML literals — connection options use env-var indirection
(`password_env: MY_VAR`) or file paths, validated at parse time.

Every connector is held to the same bar by a cross-warehouse conformance suite
([tests/integration/](tests/integration/)): the full query battery (worked examples plus the
jaffle_shop package's own test queries) must match the DuckDB reference row-for-row over an
identical fixture. `make warehouses-up` starts local Postgres + ClickHouse in docker;
`make test-integration` runs the suite, skipping any warehouse whose credentials
(`.env.example`) are unset. Adding a dialect is one class + one adapter + one registry
entry — see [docs/ADDING_A_DIALECT.md](docs/ADDING_A_DIALECT.md).

## Example Query

```json
{
  "version": 1,
  "select": [
    { "expression": { "measure": "measure.jaffle.revenue_usd" }, "as": "revenue_usd" },
    { "expression": { "metric": "metric.sales.aov_usd" }, "as": "aov_usd" }
  ],
  "group_by": ["dimension.jaffle_store_name"],
  "time": {
    "temporal_role": "temporal_role.jaffle_order_time",
    "grain": "month"
  },
  "policy_context": {
    "environment": "production",
    "audience": "finance"
  },
  "order_by": [{ "field": "revenue_usd", "direction": "DESC" }],
  "limit": 25
}
```

For the full request shape and response contracts, use [QUERY_API.md](docs/QUERY_API.md).

## Use from Python

Everything the MCP server and CLI expose is available in-process. `Runtime.query` takes the
same Query IR payload and returns the same envelope, with `rows` as a list of dicts:

```python
from semantic_rails.runtime import Runtime

runtime = Runtime("jaffle_shop")
result = runtime.query(
    {
        "version": 1,
        "select": [
            {"expression": {"measure": "measure.jaffle.revenue_usd"}, "as": "revenue_usd"}
        ],
        "group_by": ["dimension.jaffle_store_name"],
        "order_by": [{"field": "revenue_usd", "direction": "DESC"}],
        "limit": 5,
    }
)
rows = result["rows"]            # list[dict] — pd.DataFrame(rows) if you want a frame
warnings = result["warnings"]    # advisory caveats, path warnings, rewrite notes
runtime.close()
```

`Runtime("<package-id>")` loads a registered package; `Runtime.from_path("path/to/package")`
loads a package directory or single-file YAML you are authoring.

## HTTP API

Routes are available under stable `/api/v1/*` paths. Discovery, authoring
assistance, execution, and segments make up the v1 surface of 16 routes —
the full list with request and response shapes is documented in
[QUERY_API.md](docs/QUERY_API.md#http-routes). Stability policy: from 0.1.0
on, `/api/v1` routes are append-only — removing a route or breaking a
request/response shape requires a new `/api/v2` prefix, even before 1.0.

Example:

```bash
curl -s -X POST http://127.0.0.1:8081/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "select": [
        { "expression": { "measure": "measure.jaffle.revenue_usd" }, "as": "revenue_usd" }
      ],
      "group_by": ["dimension.jaffle_store_name"],
      "time": { "temporal_role": "temporal_role.jaffle_order_time", "grain": "month" },
      "limit": 5
    }
  }'
```

## Active Scope

- The only supported runtime is `semantic_rails`.
- The only supported tests are in `tests/semantic_rails`.
- The active authored package is [configs/semantic_rails/jaffle_shop](configs/semantic_rails/jaffle_shop), the canonical proof package for release-quality metadata, examples, and package-local primitive tests.
- See [CONTRIBUTING.md](CONTRIBUTING.md) for the active package, metadata, compiler, and fixture paths.

Support tiers, stated plainly: the DuckDB runtime, MCP stdio server, HTTP/JSON API, and CLI are
the supported core — they run in CI on every change. The MetricFlow translator
([mf2sr/](mf2sr/), behind `semantic-rails import`) ships in the wheel and its tests run in
every gate, but its surface is younger than the core's. The non-DuckDB warehouse connectors
(Snowflake, Postgres, BigQuery, Databricks, Athena, ClickHouse, MotherDuck, DuckLake) have
dialect-level unit coverage in every gate plus the cross-warehouse conformance suite, but
live warehouse execution is exercised on demand, not in CI. The hosted public demo is synthetic
Jaffle data and is smoke-tested as a release operation, not as a per-PR gate. This is currently a single-maintainer project;
support is best-effort via [SUPPORT.md](SUPPORT.md).

## Current Boundaries

- Unsupported mixed-grain paths fail fast with `MIXED_GRAIN_INVALID` or `REWRITE_NOT_SUPPORTED`.
- Alias resolution returns stable IDs and ambiguity candidates.
- `build-options` is the primary builder API; `valid-values` searches categorical values for selected dimensions.
- Supported event-pair conversion metrics execute for the governed event-count model, including same-store variants.
- The `explain` payload returned by `compile` includes alias resolution, chosen paths, rewrite steps, logical plan, SQL AST, and rendered SQL.
- Shipped package configs use `expr` AST nodes for measure definitions.

## Relation-Pipeline Claim Boundary

Authored `relation:` pipelines are a compile-time primitive — they let authors
declare `json_explode`, `date_spine`, `anti_join`, and similar steps that lower into reviewed
SQL CTEs. There is no runtime SQL pipeline endpoint, no arbitrary CTE compiler, and no
transformation orchestrator. Shipped capabilities are the evidence-backed surface: package
models with `relation` metadata, graph entities, semantic joins, measures, metrics,
`metric_predicate`, supported conversion metrics, segments, Query IR, validation, compile,
explain (which surfaces `chosen_paths`, `candidates`, and `relationship_contract`), and
execution.

Semantic Rails is not a general ELT tool, transformation orchestrator, arbitrary CTE
pipeline compiler, managed materialization service, or unrestricted nested-predicate planner —
if you need those, pair it with the tools that do them well.

## License

This repository is open source under the Apache License 2.0. See [LICENSE](LICENSE) for the canonical
terms, [SUPPORT.md](SUPPORT.md) for community support channels, and
[SECURITY.md](SECURITY.md) for vulnerability reporting.
