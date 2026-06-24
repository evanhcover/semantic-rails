import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  canonicalRedirect,
  classifyRequest,
  docsRedirect,
  handleRequest,
  jsonError,
  type EdgeEnv,
} from "../src/edge";

function rateLimiter(success = true) {
  return { limit: vi.fn().mockResolvedValue({ success }) };
}

function testEnv(overrides: Partial<EdgeEnv> = {}): EdgeEnv {
  return {
    ASSETS: { fetch: vi.fn().mockResolvedValue(new Response("asset")) },
    METADATA_RATE_LIMITER: rateLimiter(),
    COMPUTE_RATE_LIMITER: rateLimiter(),
    CANONICAL_HOST: "semantic-rails.com",
    ...overrides,
  };
}

const backend = vi.fn().mockResolvedValue(new Response("backend"));

describe("Cloudflare edge routing", () => {
  beforeEach(() => {
    backend.mockReset();
    backend.mockResolvedValue(new Response("backend"));
    Object.defineProperty(globalThis, "caches", {
      configurable: true,
      value: {
        default: {
          match: vi.fn().mockResolvedValue(undefined),
          put: vi.fn().mockResolvedValue(undefined),
        },
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("classifies static, metadata, compute, and MCP requests", () => {
    expect(classifyRequest(new Request("https://semantic-rails.com/try.html"))).toBe("asset");
    expect(
      classifyRequest(new Request("https://semantic-rails.com/api/v1/capabilities")),
    ).toBe("metadata");
    expect(
      classifyRequest(
        new Request("https://semantic-rails.com/api/v1/query", { method: "POST" }),
      ),
    ).toBe("compute");
    expect(
      classifyRequest(new Request("https://semantic-rails.com/mcp", { method: "POST" })),
    ).toBe("compute");
  });

  it("builds canonical redirects without dropping paths or queries", () => {
    const response = canonicalRedirect(
      new Request("http://www.semantic-rails.com/mcp?source=test"),
    );
    expect(response?.status).toBe(308);
    expect(response?.headers.get("location")).toBe(
      "https://semantic-rails.com/mcp?source=test",
    );
  });

  it("keeps the MCP docs page from colliding with the MCP endpoint", async () => {
    const redirect = docsRedirect(new Request("https://semantic-rails.com/mcp.html"));
    expect(redirect?.status).toBe(307);
    expect(redirect?.headers.get("location")).toBe(
      "https://semantic-rails.com/mcp-docs",
    );

    const response = await handleRequest(
      new Request("https://semantic-rails.com/mcp.html"),
      testEnv(),
      backend,
    );
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "https://semantic-rails.com/mcp-docs",
    );
    expect(backend).not.toHaveBeenCalled();
  });

  it("redirects the old package authoring docs route", async () => {
    const extensionless = docsRedirect(
      new Request("https://semantic-rails.com/docs/ontology-modeling?source=old"),
    );
    expect(extensionless?.status).toBe(307);
    expect(extensionless?.headers.get("location")).toBe(
      "https://semantic-rails.com/docs/package-authoring?source=old",
    );

    const html = docsRedirect(
      new Request("https://semantic-rails.com/docs/ontology-modeling.html"),
    );
    expect(html?.status).toBe(307);
    expect(html?.headers.get("location")).toBe(
      "https://semantic-rails.com/docs/package-authoring",
    );
  });

  it("returns structured rate-limit responses", async () => {
    const env = testEnv({ COMPUTE_RATE_LIMITER: rateLimiter(false) });
    const response = await handleRequest(
      new Request("https://semantic-rails.com/api/v1/query", { method: "POST" }),
      env,
      backend,
    );
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("60");
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "RATE_LIMITED" },
    });
  });

  it("rejects declared and streamed bodies over 64 KiB", async () => {
    const declared = await handleRequest(
      new Request("https://semantic-rails.com/mcp", {
        method: "POST",
        headers: { "Content-Length": "65537" },
        body: "{}",
      }),
      testEnv(),
      backend,
    );
    const streamed = await handleRequest(
      new Request("https://semantic-rails.com/mcp", {
        method: "POST",
        body: new Uint8Array(65_537),
      }),
      testEnv(),
      backend,
    );
    expect(declared.status).toBe(413);
    expect(streamed.status).toBe(413);
  });

  it("serves ordinary files directly from the static-assets binding", async () => {
    const assets = { fetch: vi.fn().mockResolvedValue(new Response("try live")) };
    const response = await handleRequest(
      new Request("https://semantic-rails.com/try.html"),
      testEnv({ ASSETS: assets }),
      backend,
    );
    expect(await response.text()).toBe("try live");
    expect(assets.fetch).toHaveBeenCalledOnce();
  });

  it("caches successful public catalog responses for five minutes", async () => {
    const cache = ((globalThis as unknown as { caches: { default: {
      match: ReturnType<typeof vi.fn>;
      put: ReturnType<typeof vi.fn>;
    } } }).caches).default;
    backend.mockResolvedValue(
      Response.json({ ok: true, catalog: {} }, { headers: { "X-Origin": "container" } }),
    );

    const response = await handleRequest(
      new Request("https://semantic-rails.com/api/v1/catalog"),
      testEnv(),
      backend,
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("public, max-age=300");
    expect(cache.put).toHaveBeenCalledOnce();
  });

  it("returns a structured 503 when the container cannot start", async () => {
    backend.mockRejectedValue(new Error("container unavailable"));
    const response = await handleRequest(
      new Request("https://semantic-rails.com/api/v1/query", {
        method: "POST",
        body: "{}",
      }),
      testEnv(),
      backend,
    );

    expect(response.status).toBe(503);
    expect(response.headers.get("retry-after")).toBe("5");
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "DEMO_CONTAINER_UNAVAILABLE" },
    });
  });

  it("returns a structured 504 after the 25-second edge deadline", async () => {
    vi.useFakeTimers();
    backend.mockImplementation(() => new Promise<Response>(() => {}));
    const pending = handleRequest(
      new Request("https://semantic-rails.com/api/v1/query", {
        method: "POST",
        body: "{}",
      }),
      testEnv(),
      backend,
    );
    await vi.advanceTimersByTimeAsync(25_000);
    const response = await pending;
    vi.useRealTimers();

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "EDGE_RESPONSE_TIMEOUT" },
    });
  });

  it("uses stable structured JSON errors", async () => {
    const response = jsonError(503, "DEMO_CONTAINER_UNAVAILABLE", "warming");
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      ok: false,
      status: "error",
      error: { code: "DEMO_CONTAINER_UNAVAILABLE", message: "warming" },
      errors: [{ code: "DEMO_CONTAINER_UNAVAILABLE", message: "warming" }],
    });
  });
});
