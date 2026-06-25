const MAX_BODY_BYTES = 64 * 1024;
const RESPONSE_DEADLINE_MS = 25_000;
const CACHE_TTL_SECONDS = 300;
const RETRY_AFTER_SECONDS = 60;

type RateLimiter = {
  limit(options: { key: string }): Promise<{ success: boolean }>;
};

type AssetsBinding = {
  fetch(request: Request): Promise<Response>;
};

export interface EdgeEnv {
  ASSETS: AssetsBinding;
  METADATA_RATE_LIMITER: RateLimiter;
  COMPUTE_RATE_LIMITER: RateLimiter;
  CANONICAL_HOST: string;
}

export type RouteClass = "asset" | "metadata" | "compute";

export function classifyRequest(request: Request): RouteClass {
  const { pathname } = new URL(request.url);
  if (pathname === "/mcp") {
    return "compute";
  }
  if (!pathname.startsWith("/api/")) {
    return "asset";
  }
  if (
    request.method === "GET" &&
    [
      "/api/v1/health",
      "/api/v1/ready",
      "/api/v1/capabilities",
      "/api/v1/catalog",
    ].includes(pathname)
  ) {
    return "metadata";
  }
  return "compute";
}

export function canonicalRedirect(
  request: Request,
  canonicalHost = "semantic-rails.com",
): Response | null {
  const url = new URL(request.url);
  const hostname = url.hostname.toLowerCase();
  const redirectHosts = new Set([
    `www.${canonicalHost}`,
    "semanticrails.cloud",
    "www.semanticrails.cloud",
  ]);
  if (url.protocol === "https:" && !redirectHosts.has(hostname)) {
    return null;
  }
  url.protocol = "https:";
  url.hostname = canonicalHost;
  url.port = "";
  return Response.redirect(url.toString(), 308);
}

export function docsRedirect(request: Request): Response | null {
  const url = new URL(request.url);
  if (url.pathname === "/mcp.html") {
    url.pathname = "/mcp-docs";
    return Response.redirect(url.toString(), 307);
  }
  if (
    url.pathname === "/docs/ontology-modeling" ||
    url.pathname === "/docs/ontology-modeling.html"
  ) {
    url.pathname = "/docs/package-authoring";
    return Response.redirect(url.toString(), 307);
  }
  return null;
}

export function jsonError(
  status: number,
  code: string,
  message: string,
  headers: HeadersInit = {},
): Response {
  return Response.json(
    {
      ok: false,
      status: "error",
      errors: [{ code, message }],
      error: { code, message },
    },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        ...headers,
      },
    },
  );
}

function clientKey(request: Request, routeClass: RouteClass): string {
  const client =
    request.headers.get("cf-connecting-ip") ??
    request.headers.get("x-forwarded-for")?.split(",", 1)[0]?.trim() ??
    "anonymous";
  return `${routeClass}:${client}`;
}

async function readBoundedBody(request: Request): Promise<Uint8Array | null> {
  if (request.method === "GET" || request.method === "HEAD") {
    return null;
  }
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) {
    throw new RangeError("request body too large");
  }
  if (!request.body) {
    return new Uint8Array();
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    total += value.byteLength;
    if (total > MAX_BODY_BYTES) {
      await reader.cancel();
      throw new RangeError("request body too large");
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

function cacheable(request: Request): boolean {
  if (request.method !== "GET") {
    return false;
  }
  const { pathname } = new URL(request.url);
  return pathname === "/api/v1/capabilities" || pathname === "/api/v1/catalog";
}

async function withDeadline(fetchPromise: Promise<Response>): Promise<Response> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<Response>((resolve) => {
    timer = setTimeout(
      () =>
        resolve(
          jsonError(
            504,
            "EDGE_RESPONSE_TIMEOUT",
            "The public demo did not respond within 25 seconds. Retry after the container warms.",
          ),
        ),
      RESPONSE_DEADLINE_MS,
    );
  });
  const response = await Promise.race([fetchPromise, timeout]);
  if (timer) {
    clearTimeout(timer);
  }
  return response;
}

export async function handleRequest(
  request: Request,
  env: EdgeEnv,
  fetchBackend: (request: Request) => Promise<Response>,
): Promise<Response> {
  const redirect = canonicalRedirect(request, env.CANONICAL_HOST);
  if (redirect) {
    return redirect;
  }
  const docs = docsRedirect(request);
  if (docs) {
    return docs;
  }

  const routeClass = classifyRequest(request);
  if (routeClass === "asset") {
    return env.ASSETS.fetch(request);
  }

  const limiter =
    routeClass === "metadata" ? env.METADATA_RATE_LIMITER : env.COMPUTE_RATE_LIMITER;
  const limited = await limiter.limit({ key: clientKey(request, routeClass) });
  if (!limited.success) {
    return jsonError(
      429,
      "RATE_LIMITED",
      `Anonymous ${routeClass} request limit exceeded. Retry in 60 seconds.`,
      { "Retry-After": String(RETRY_AFTER_SECONDS) },
    );
  }

  const cache = (caches as unknown as { default: Cache }).default;
  if (cacheable(request)) {
    const hit = await cache.match(request);
    if (hit) {
      return hit;
    }
  }

  let body: Uint8Array | null;
  try {
    body = await readBoundedBody(request);
  } catch (error) {
    if (error instanceof RangeError) {
      return jsonError(
        413,
        "REQUEST_BODY_TOO_LARGE",
        "Public demo request bodies are limited to 64 KiB.",
      );
    }
    throw error;
  }

  const forwarded =
    body === null
      ? request
      : new Request(request, {
          body,
          duplex: "half",
        } as RequestInit);

  let response: Response;
  try {
    response = await withDeadline(fetchBackend(forwarded));
  } catch (error) {
    console.error("Container request failed.", error);
    return jsonError(
      503,
      "DEMO_CONTAINER_UNAVAILABLE",
      "The public demo container is starting or temporarily unavailable. Retry shortly.",
      { "Retry-After": "5" },
    );
  }

  if (cacheable(request) && response.ok) {
    const cached = new Response(response.body, response);
    cached.headers.set("Cache-Control", `public, max-age=${CACHE_TTL_SECONDS}`);
    // The backend computes Access-Control-Allow-Origin per request; without
    // Vary the first requester's CORS header would be served to everyone for
    // the cache TTL.
    cached.headers.set("Vary", "Origin");
    await cache.put(request, cached.clone());
    return cached;
  }
  return response;
}
