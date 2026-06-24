# Agent Quickstart

This guide is for agents and agent applications that need governed analytics without giving the
model direct warehouse access. The core contract is:

```text
discover -> inspect -> plan/build-options -> valid-values -> validate -> compile -> execute
```

Use the earliest tool that can answer the next question. Do not skip straight to `execute` unless
the query has already passed validation or was produced by `plan` with an `ok` status.

## Local MCP

Start the bundled MCP server against the synthetic Jaffle Shop package:

```bash
uv run semantic-rails mcp stdio --package jaffle_shop
```

For HTTP clients, run the local Streamable HTTP server:

```bash
uv run semantic-rails mcp http --package jaffle_shop --host 127.0.0.1 --port 8091
```

Then list tools:

```bash
curl http://127.0.0.1:8091/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-11-25' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

The public demo endpoint is `https://semantic-rails.com/mcp`. It is synthetic-data-only and rate
limited. Do not send secrets, proprietary query text, or customer data to the public demo.

## Recommended Agent Policy

1. Call `capabilities` once per package to learn expression shapes, limits, and unsupported
   capabilities.
2. Call `discover` with business terms before selecting IDs. Treat low-relevance or off-topic
   responses as a stop condition.
3. Call `inspect` on candidate metrics, measures, dimensions, or segments before composing a query.
4. Use `plan` for natural-language questions, or `build-options` plus `valid-values` when the
   agent is interactively assembling Query IR.
5. Call `validate` before `compile` or `execute` when the Query IR did not come from an `ok` plan.
6. Prefer `compile` when the user wants SQL, lineage, path selection, or explain output.
7. Call `execute` only when the user explicitly wants rows and the query has passed the governed
   path.

Use `summary`, `minimal`, or `compact` verbosity unless the user asks for debugging detail. Request
`full` only for explainability, test failure triage, or query review.

## Client Patterns

### MCP Desktop Clients

Point the client at the stdio command above for local work, or at the Streamable HTTP endpoint for
the public synthetic demo. The server exposes the same tool names across transports, so the agent
prompt should reference tool semantics, not transport details.

### Tool-Calling Agents

If a framework does not speak MCP directly, wrap each `/api/v1/*` route as a tool with the same
loop policy:

```text
discover terms -> inspect object_id -> plan intent -> validate query -> compile query -> execute query
```

Keep warehouse credentials outside the model context. The model should receive structured results
and recovery hints, not raw credentials or arbitrary SQL execution privileges.

### Graph-Style Agents

Model the loop as explicit nodes:

```text
orient -> discover -> inspect -> draft -> validate -> compile -> execute
```

Branch on structured status fields. `INVALID_QUERY`, `PATH_JOIN_CONFLICT`,
`MIXED_GRAIN_INVALID`, `POLICY_DENIED`, and low-relevance results should route to repair or refusal
nodes instead of being retried as raw SQL.

## Local Warehouse Defaults

DuckDB is the default zero-setup runtime and runs in every gate. Snowflake, Postgres, BigQuery,
Databricks, Athena, ClickHouse, MotherDuck, and DuckLake are optional connectors with dialect-level
coverage. Live cloud warehouse execution depends on local credentials and is exercised on demand,
not in every PR gate.

## Supported vs Experimental

Supported core:

- DuckDB local runtime, CLI, local MCP stdio, local MCP HTTP, and stable `/api/v1/*` routes.
- Package authoring, package checks, examples, tests, validation, compile, explain, and
  local/customer-side execution.
- Snowflake execution through Snow CLI or the optional native connector when a package connection
  is configured.

Supported with guardrails:

- Mixed-grain rewrites for supported shapes.
- Historical slicing through declared temporal-validity joins.
- `metric_predicate` for contextual and entity-only predicate shapes.
- Event-count conversion metrics for the supported execution model.
- Non-DuckDB warehouse connectors through optional drivers and conformance tests; live credentials
  are exercised on demand, not in every CI run.

Experimental or out of scope:

- Hosted demo execution-on-behalf for real customer data.
- Managed acceleration, billing, tenant administration, JWT/JWKS, and production observability.
- Arbitrary chained SQL pipelines, user-authored CTE orchestration, managed materialization refresh,
  or a general ELT runtime.
- Fully general nested predicate planning beyond the supported predicate shapes.

When a request falls outside the supported surface, the agent should surface the structured error and
recovery hints instead of inventing SQL.
