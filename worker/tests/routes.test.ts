/**
 * Integration tests for all route handlers.
 * The CF Browser Rendering API calls are mocked via global fetch.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import app from "../src/index.js";
import type { Env } from "../src/types.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeKv(): KVNamespace {
  const store = new Map<string, { value: string; metadata: unknown }>();
  return {
    get: async (key: string) => store.get(key)?.value ?? null,
    getWithMetadata: async (key: string) => ({
      value: store.get(key)?.value ?? null,
      metadata: store.get(key)?.metadata ?? null,
      cacheStatus: null,
    }),
    put: async (
      key: string,
      value: string,
      opts?: { metadata?: unknown; expirationTtl?: number }
    ) => {
      store.set(key, { value, metadata: opts?.metadata ?? null });
    },
    delete: async (key: string) => { store.delete(key); },
    list: async () => ({ keys: [], list_complete: true, cursor: "", cacheStatus: null }),
  } as unknown as KVNamespace;
}

function makeR2(): R2Bucket {
  const store = new Map<string, { body: ArrayBuffer | string; contentType: string }>();
  return {
    get: async (key: string) => {
      const item = store.get(key);
      if (!item) return null;
      return {
        arrayBuffer: async () =>
          typeof item.body === "string"
            ? new TextEncoder().encode(item.body).buffer
            : item.body,
        json: async () => JSON.parse(item.body as string),
        httpMetadata: { contentType: item.contentType },
        customMetadata: {},
      };
    },
    put: async (
      key: string,
      body: ArrayBuffer | string,
      opts?: { httpMetadata?: { contentType?: string } }
    ) => {
      store.set(key, {
        body,
        contentType: opts?.httpMetadata?.contentType ?? "application/octet-stream",
      });
    },
    delete: async (key: string) => { store.delete(key); },
    list: async () => ({ objects: [], truncated: false }),
    head: async () => null,
  } as unknown as R2Bucket;
}

function buildEnv(): Env {
  return {
    CF_ACCOUNT_ID: "test-account",
    CF_API_TOKEN: "test-token",
    API_KEYS: "valid-key",
    CACHE: makeKv(),
    RATE_LIMIT: makeKv(),
    STORAGE: makeR2(),
  };
}

function authHeaders() {
  return { Authorization: "Bearer valid-key", "Content-Type": "application/json" };
}

async function postJson(path: string, body: unknown, env: Env) {
  return app.fetch(
    new Request(`http://localhost${path}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
    }),
    env
  );
}

// ---------------------------------------------------------------------------
// Mock global fetch
// ---------------------------------------------------------------------------

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockCfText(body: string, contentType = "text/html") {
  fetchMock.mockResolvedValueOnce(
    new Response(body, { status: 200, headers: { "Content-Type": contentType } })
  );
}

function mockCfJson(data: unknown) {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(data), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  );
}

function mockCfBinary(buffer: ArrayBuffer, contentType: string) {
  fetchMock.mockResolvedValueOnce(
    new Response(buffer, { status: 200, headers: { "Content-Type": contentType } })
  );
}

function mockCfError(status: number, message: string) {
  fetchMock.mockResolvedValueOnce(new Response(message, { status }));
}

// ---------------------------------------------------------------------------
// POST /content
// ---------------------------------------------------------------------------

describe("POST /content", () => {
  it("returns 400 if url is missing", async () => {
    const env = buildEnv();
    const res = await postJson("/content", {}, env);
    expect(res.status).toBe(400);
  });

  it("proxies CF API and returns HTML on cache miss", async () => {
    const env = buildEnv();
    mockCfText("<html>hello</html>");
    const res = await postJson("/content", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    expect(res.headers.get("X-Cache")).toBe("MISS");
    const text = await res.text();
    expect(text).toBe("<html>hello</html>");
  });

  it("returns cached result on second request", async () => {
    const env = buildEnv();
    // First call — populates cache
    mockCfText("<html>cached</html>");
    await postJson("/content", { url: "https://example.com" }, env);
    // Second call — should hit cache, no fetch needed
    const res = await postJson("/content", { url: "https://example.com" }, env);
    expect(res.headers.get("X-Cache")).toBe("HIT");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("skips cache when no_cache is true", async () => {
    const env = buildEnv();
    mockCfText("<html>fresh</html>");
    mockCfText("<html>fresh again</html>");
    await postJson("/content", { url: "https://example.com", no_cache: true }, env);
    const res = await postJson("/content", { url: "https://example.com", no_cache: true }, env);
    expect(res.headers.get("X-Cache")).toBe("MISS");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("forwards CF API errors", async () => {
    const env = buildEnv();
    mockCfError(503, "Service unavailable");
    const res = await postJson("/content", { url: "https://example.com" }, env);
    expect(res.status).toBe(503);
    const body = await res.json<{ error: string }>();
    expect(body.error).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// POST /screenshot
// ---------------------------------------------------------------------------

describe("POST /screenshot", () => {
  it("returns PNG binary and stores in R2", async () => {
    const env = buildEnv();
    const pngData = new Uint8Array([137, 80, 78, 71]).buffer;
    mockCfBinary(pngData, "image/png");
    const res = await postJson("/screenshot", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("image/png");
    expect(res.headers.get("X-Cache")).toBe("MISS");
  });

  it("returns 400 if url missing", async () => {
    const env = buildEnv();
    const res = await postJson("/screenshot", {}, env);
    expect(res.status).toBe(400);
  });
});

// ---------------------------------------------------------------------------
// POST /pdf
// ---------------------------------------------------------------------------

describe("POST /pdf", () => {
  it("returns PDF binary", async () => {
    const env = buildEnv();
    const pdfData = new TextEncoder().encode("%PDF-1.4").buffer;
    mockCfBinary(pdfData, "application/pdf");
    const res = await postJson("/pdf", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("application/pdf");
  });
});

// ---------------------------------------------------------------------------
// POST /markdown
// ---------------------------------------------------------------------------

describe("POST /markdown", () => {
  it("returns markdown text", async () => {
    const env = buildEnv();
    mockCfText("# Hello\nWorld", "text/markdown");
    const res = await postJson("/markdown", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).toContain("# Hello");
  });
});

// ---------------------------------------------------------------------------
// POST /snapshot
// ---------------------------------------------------------------------------

describe("POST /snapshot", () => {
  it("returns JSON snapshot", async () => {
    const env = buildEnv();
    mockCfJson({ html: "<html/>", screenshot: "base64..." });
    const res = await postJson("/snapshot", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    const body = await res.json<Record<string, unknown>>();
    expect(body.html).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// POST /scrape
// ---------------------------------------------------------------------------

describe("POST /scrape", () => {
  it("returns scraped data", async () => {
    const env = buildEnv();
    mockCfJson({ elements: [{ selector: "h1", text: "Title" }] });
    const res = await postJson(
      "/scrape",
      { url: "https://example.com", elements: ["h1"] },
      env
    );
    expect(res.status).toBe(200);
  });
});

// ---------------------------------------------------------------------------
// POST /json
// ---------------------------------------------------------------------------

describe("POST /json", () => {
  it("returns extracted JSON and never caches", async () => {
    const env = buildEnv();
    mockCfJson({ title: "Example" });
    mockCfJson({ title: "Example 2" });
    await postJson("/json", { url: "https://example.com" }, env);
    const res = await postJson("/json", { url: "https://example.com" }, env);
    // Should have called CF API twice (no caching)
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(res.headers.get("X-Cache")).toBe("BYPASS");
  });
});

// ---------------------------------------------------------------------------
// POST /links
// ---------------------------------------------------------------------------

describe("POST /links", () => {
  it("returns links array", async () => {
    const env = buildEnv();
    mockCfJson({ links: ["https://example.com/a", "https://example.com/b"] });
    const res = await postJson("/links", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
  });
});

// ---------------------------------------------------------------------------
// POST /crawl + GET /crawl/:id
// ---------------------------------------------------------------------------

describe("POST /crawl", () => {
  it("starts a crawl job and returns 202 with job ID", async () => {
    const env = buildEnv();
    mockCfJson({ job_id: "job-abc-123", status: "pending" });
    const res = await postJson("/crawl", { url: "https://example.com" }, env);
    expect(res.status).toBe(202);
    const body = await res.json<{ job_id: string }>();
    expect(body.job_id).toBe("job-abc-123");
  });
});

describe("GET /crawl/:id", () => {
  it("polls crawl status from CF API when not in R2", async () => {
    const env = buildEnv();
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "running", progress: 10 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    const res = await app.fetch(
      new Request("http://localhost/crawl/a1b2c3d4-e5f6-7890-abcd-ef1234567890", {
        headers: { Authorization: "Bearer valid-key" },
      }),
      env
    );
    expect(res.status).toBe(200);
    const body = await res.json<{ status: string }>();
    expect(body.status).toBe("running");
    expect(res.headers.get("X-Cache")).toBe("MISS");
  });

  it("serves completed crawl from R2 on second poll", async () => {
    const env = buildEnv();
    // First poll — CF returns completed
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "complete", pages: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    await app.fetch(
      new Request("http://localhost/crawl/b2c3d4e5-f6a7-8901-bcde-f12345678901", {
        headers: { Authorization: "Bearer valid-key" },
      }),
      env
    );
    // Second poll — should hit R2
    const res = await app.fetch(
      new Request("http://localhost/crawl/b2c3d4e5-f6a7-8901-bcde-f12345678901", {
        headers: { Authorization: "Bearer valid-key" },
      }),
      env
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("X-Cache")).toBe("HIT");
    // CF API called only once
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// POST /a11y
// ---------------------------------------------------------------------------

describe("POST /a11y", () => {
  it("returns structured a11y data with screenshot stripped", async () => {
    const env = buildEnv();
    mockCfJson({ url: "https://example.com", title: "Example", html: "<h1>Hi</h1>", screenshot: "base64data..." });
    const res = await postJson("/a11y", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    const body = await res.json<Record<string, unknown>>();
    expect(body.type).toBe("accessibility_snapshot");
    expect(body.title).toBe("Example");
    expect(body.html).toBe("<h1>Hi</h1>");
    // Screenshot should be stripped to reduce token cost
    expect(body.screenshot).toBeUndefined();
  });

  it("returns 400 if url missing", async () => {
    const env = buildEnv();
    const res = await postJson("/a11y", {}, env);
    expect(res.status).toBe(400);
  });

  it("caches a11y results in KV", async () => {
    const env = buildEnv();
    mockCfJson({ url: "https://example.com", title: "Example" });
    await postJson("/a11y", { url: "https://example.com" }, env);
    const res = await postJson("/a11y", { url: "https://example.com" }, env);
    expect(res.headers.get("X-Cache")).toBe("HIT");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Cookie and header forwarding
// ---------------------------------------------------------------------------

describe("Cookie/header forwarding", () => {
  it("forwards cookies in request body to CF API", async () => {
    const env = buildEnv();
    mockCfText("<html>auth</html>");
    const cookies = [{ name: "session", value: "abc123", domain: ".example.com" }];
    const res = await postJson(
      "/content",
      { url: "https://example.com", cookies },
      env
    );
    expect(res.status).toBe(200);
    // Verify cookies were passed through to CF API
    const fetchCall = fetchMock.mock.calls[0];
    const sentBody = JSON.parse(fetchCall[1]?.body as string || fetchCall[0]?.body as string || "{}");
    expect(sentBody.cookies).toEqual(cookies);
  });

  it("forwards custom headers in request body to CF API", async () => {
    const env = buildEnv();
    mockCfText("# Auth Page", "text/markdown");
    const headers = { "X-Auth": "token123" };
    const res = await postJson(
      "/markdown",
      { url: "https://example.com", headers },
      env
    );
    expect(res.status).toBe(200);
  });
});

// ---------------------------------------------------------------------------
// Auth enforcement on protected routes
// ---------------------------------------------------------------------------

describe("Auth enforcement", () => {
  it("returns 401 on protected route without token", async () => {
    const env = buildEnv();
    const res = await app.fetch(
      new Request("http://localhost/content", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: "https://example.com" }),
      }),
      env
    );
    expect(res.status).toBe(401);
  });
});
