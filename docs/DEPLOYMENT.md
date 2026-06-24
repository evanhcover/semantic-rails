# Deployment

Semantic Rails now has two runtime modes:

- `semantic-rails serve` for the dependency-light local/dev HTTP server.
- `uv run --extra server uvicorn semantic_rails.asgi:app` for a production-oriented ASGI service.

Both modes serve the same stable `/api/v1/*` semantic API. The ASGI path is the clean deploy target
for containers and process supervisors; it keeps authentication intentionally small so a future
hosted compile service can add tenant isolation and stronger auth without changing Query IR.
The ASGI app also serves stateless MCP Streamable HTTP at `/mcp`.

## Docker

Build the image:

```bash
docker build -t semantic-rails:local .
```

The image listens on port `8080` by default (`EXPOSE 8080`; override with
`SEMANTIC_RAILS_HOST` / `SEMANTIC_RAILS_PORT`). Bind the published port to
loopback unless you have configured API keys and a CORS allow-list — the API
ships unauthenticated by default.

Run the Jaffle package:

```bash
docker run --rm -p 127.0.0.1:8080:8080 \
  -e SEMANTIC_RAILS_PACKAGE=jaffle_shop \
  semantic-rails:local
```

Run a mounted package:

```bash
docker run --rm -p 127.0.0.1:8080:8080 \
  -e SEMANTIC_RAILS_PACKAGE_PATH=/packages/acme \
  -v "$PWD/configs/semantic_rails/jaffle_shop:/packages/acme:ro" \
  semantic-rails:local
```

Or use the compose example (which publishes `127.0.0.1:8080:8080` and documents
the API-key / CORS variables to set before exposing the service beyond
localhost):

```bash
docker compose up --build
```

## Environment

| Variable | Purpose |
| --- | --- |
| `SEMANTIC_RAILS_PACKAGE` | Built-in package id to load, default `jaffle_shop`. |
| `SEMANTIC_RAILS_PACKAGE_PATH` | Mounted package root containing `package.yml`; overrides package id when set. |
| `SEMANTIC_RAILS_HOST` | Interface uvicorn binds inside the container, default `0.0.0.0` (the container must bind all interfaces so the published port works; restrict exposure at the port mapping instead). |
| `SEMANTIC_RAILS_PORT` | Port uvicorn listens on inside the container, default `8080`. The Dockerfile and compose healthchecks read the same variable. |
| `SEMANTIC_RAILS_API_KEYS` | Optional comma-separated bearer/API keys. Auth is disabled when unset. |
| `SEMANTIC_RAILS_API_KEY_FILE` | Optional file containing comma- or newline-separated API keys. |
| `SEMANTIC_RAILS_AUDIT_LOGS` | Set to `1`, `true`, `yes`, or `on` to emit JSON audit events to stderr. |
| `SEMANTIC_RAILS_CORS_ORIGINS` | Comma-separated allow-list of browser origins. Unset (default) emits `Access-Control-Allow-Origin: *`. Set to `https://app.example.com,https://staging.example.com` for hosted browser-facing deployments; only matching `Origin` headers get the CORS response header. |
| `SEMANTIC_RAILS_PUBLIC_DEMO` | Set to `1` only for the public synthetic demo. Forces `jaffle_shop`, caps query rows at 100 and segment previews at 25, and ignores mounted package paths. |
| `SEMANTIC_RAILS_ALLOW_EXTERNAL_PACKAGE_PATHS` | Set to `1` to let `package.default_db` / `package.seed.*` point outside the package root (absolute paths or `..` segments). Off by default: shared packages are untrusted input, and external paths let a package read or replace files outside its own directory. Enable only for trusted local development. |
| `SEMANTIC_RAILS_MAX_VALID_VALUES_LIMIT` | Ceiling for caller-supplied `valid-values` `limit`, default `1000`. Values above the ceiling are clamped on every transport. |
| `SEMANTIC_RAILS_MAX_VALID_VALUES_OFFSET` | Ceiling for caller-supplied `valid-values` `offset`, default `100000`. |
| `SEMANTIC_RAILS_MAX_SEGMENT_PREVIEW_ROWS` | Ceiling for caller-supplied `segment-preview` `limit`, default `1000`. |

## Cloudflare Launch

The public deployment lives in [`deploy/cloudflare/`](../deploy/cloudflare/):

- Workers Static Assets serves `website/`.
- Only `/api/*` and `/mcp` run Worker code before assets.
- A fixed Durable Object name routes requests to one `basic` Container.
- The container sleeps after 10 idle minutes and scales to zero.
- Metadata GETs receive 60 requests/minute/client; compute and MCP receive 20.
- The edge enforces a 64 KiB body limit and 25-second response deadline.
- Public capabilities and catalog GETs cache for five minutes.

Cloudflare release commands, bindings, rollback, and account-specific runbooks are intentionally
kept outside the public repository. Public release validation should use the smoke script in
`scripts/smoke_public_demo.py` after deployment.

Health is cheap and dependency-light:

```bash
curl -s http://127.0.0.1:8080/api/v1/health
```

Readiness verifies the package is loaded. Add `X-Semantic-Check-Warehouse: true` only when the
platform should test warehouse connectivity:

```bash
curl -s http://127.0.0.1:8080/api/v1/ready
curl -s -H 'X-Semantic-Check-Warehouse: true' http://127.0.0.1:8080/api/v1/ready
```

## Request Context And API Key Shim

The runtime accepts trusted request context from headers or `policy_context`:

- `X-Request-ID` or `X-Correlation-ID`
- `X-Semantic-Actor`
- `X-Semantic-Tenant`
- `X-Semantic-Project`
- `X-Semantic-Roles`
- `X-Semantic-Environment`
- `X-Semantic-Audience`

When API keys are configured, clients may send either `Authorization: Bearer ...` or
`X-Semantic-API-Key`. This is a deployment shim, not a full enterprise auth system. JWT/JWKS,
RBAC administration, billing, tenant provisioning, secret rotation, and hosted package storage are
future service-layer concerns.

**The default resolver trusts these headers verbatim.** Any caller who can reach the service can
self-assert `audience`, `environment`, `roles`, and `tenant`, and policies keyed on those fields
(visibility, redaction, MNPI gating) will honor the asserted values. For any deployment that
serves callers you do not fully trust, replacing the resolver is a **required** production step,
not an optional hardening: install an identity-aware `PolicyContextResolver` via
`set_policy_context_resolver(...)` at startup so policy context derives from authenticated
identity (JWT, mTLS, signed session) instead of request headers. The stdlib HTTP and MCP HTTP
servers print a hard warning at startup when binding a non-loopback interface with the default
resolver still active.

## Logs

Enable audit logs for structured request events:

```bash
SEMANTIC_RAILS_AUDIT_LOGS=1 uv run --extra server uvicorn semantic_rails.asgi:app --host 0.0.0.0 --port 8081
```

Events include route/tool, package, request id, public request context, status, timing, and error
codes. They intentionally avoid secrets.

### Pluggable Audit Sink

By default audit events go to stderr as JSON lines. Hosted deployments
can route the same events into a structured pipeline (Kafka, an HTTP
collector, OpenTelemetry, etc.) by installing a custom `AuditSink`:

```python
from semantic_rails.request_context import AuditSink, set_audit_sink

class KafkaAuditSink:
    def __init__(self, producer):
        self._producer = producer

    def emit(self, payload):
        self._producer.send("semantic-rails-audit", value=payload)

set_audit_sink(KafkaAuditSink(producer=my_kafka_producer))
```

The sink receives already-scrubbed payloads (no `authorization`,
`api_key`, `password`, etc.). If the sink raises, the runtime falls
back to stderr so audit cannot be silenced by a misconfigured backend.
The default `StderrAuditSink` is appropriate for the OSS standalone
experience and any container deployment whose stderr is captured.

## Boundary

This deployment path does not ship managed cloud, managed acceleration, materialization refreshes,
tenant isolation, billing, or full enterprise authorization. It is a cloud-ready runtime surface:
packaged service entrypoints, mounted packages, health/readiness, request context, audit logs, and
warehouse adapters.
