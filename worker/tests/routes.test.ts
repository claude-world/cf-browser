/**
 * Integration tests for all route handlers.
 * The Cloudflare Browser Run API calls are mocked via global fetch.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import app from "../src/index.js";
import type { Env } from "../src/types.js";
import { hashApiKey } from "../src/middleware/rate-limit.js";
import { r2ObjectKey } from "../src/lib/r2-keys.js";
import {
  MAX_JSON_DEPTH,
  MAX_REQUEST_BODY_BYTES,
} from "../src/middleware/validate-request.js";

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
  const store = new Map<
    string,
    {
      body: ArrayBuffer | string;
      contentType: string;
      customMetadata: Record<string, string>;
    }
  >();
  return {
    get: async (key: string) => {
      const item = store.get(key);
      if (!item) return null;
      return {
        arrayBuffer: async () =>
          typeof item.body === "string"
            ? new TextEncoder().encode(item.body).buffer
            : item.body,
        text: async () =>
          typeof item.body === "string"
            ? item.body
            : new TextDecoder().decode(item.body),
        json: async () => JSON.parse(item.body as string),
        httpMetadata: { contentType: item.contentType },
        customMetadata: item.customMetadata,
      };
    },
    put: async (
      key: string,
      body: ArrayBuffer | string,
      opts?: {
        onlyIf?: { etagDoesNotMatch?: string };
        httpMetadata?: { contentType?: string };
        customMetadata?: Record<string, string>;
      }
    ) => {
      // Mirror R2: a failed precondition stores nothing and resolves to null.
      if (opts?.onlyIf?.etagDoesNotMatch === "*" && store.has(key)) return null;
      store.set(key, {
        body,
        contentType: opts?.httpMetadata?.contentType ?? "application/octet-stream",
        customMetadata: opts?.customMetadata ?? {},
      });
      return { key };
    },
    delete: async (key: string) => { store.delete(key); },
    list: async () => ({ objects: [], truncated: false }),
    head: async () => null,
  } as unknown as R2Bucket;
}

function buildEnv(): Env {
  const rateLimiter = { limit: async () => ({ success: true }) } as RateLimit;
  return {
    CF_ACCOUNT_ID: "test-account",
    CF_API_TOKEN: "test-token",
    API_KEYS: "valid-key",
    CACHE: makeKv(),
    RATE_LIMITER: rateLimiter,
    STORAGE: makeR2(),
  };
}

function authHeaders() {
  return { Authorization: "Bearer valid-key", "Content-Type": "application/json" };
}

async function putCrawlOwner(env: Env, jobId: string, apiKey = "valid-key") {
  await env.STORAGE.put(r2ObjectKey(`crawl-owner:${jobId}`), await hashApiKey(apiKey), {
    customMetadata: { created_at: String(Date.now()) },
  });
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
let cfResponses: Response[];

function dnsSuccessResponse(ip = "93.184.216.34") {
  return new Response(
    JSON.stringify({
      Status: 0,
      Answer: [{ data: ip }],
    }),
    {
      status: 200,
      headers: { "Content-Type": "application/dns-json" },
    }
  );
}

beforeEach(() => {
  cfResponses = [];
  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;

    if (url.startsWith("https://cloudflare-dns.com/dns-query")) {
      return dnsSuccessResponse();
    }

    const response = cfResponses.shift();
    if (!response) {
      throw new Error(`Unexpected fetch request: ${url}`);
    }

    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockCfText(body: string, contentType = "text/html") {
  cfResponses.push(
    new Response(body, { status: 200, headers: { "Content-Type": contentType } })
  );
}

function mockCfJson(data: unknown) {
  cfResponses.push(
    new Response(JSON.stringify(data), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  );
}

function mockCfBinary(buffer: ArrayBufferLike, contentType: string) {
  cfResponses.push(
    new Response(new Uint8Array(buffer), {
      status: 200,
      headers: { "Content-Type": contentType },
    })
  );
}

function mockCfError(status: number, message: string) {
  cfResponses.push(new Response(message, { status }));
}

function cfApiCalls() {
  return fetchMock.mock.calls.filter(([input]) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    return !url.startsWith("https://cloudflare-dns.com/dns-query");
  });
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

  it("unwraps the official Cloudflare JSON envelope with an HTML content type", async () => {
    const env = buildEnv();
    mockCfJson({ success: true, result: "<html>wrapped</html>" });
    const res = await postJson("/content", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("text/html");
    expect(await res.text()).toBe("<html>wrapped</html>");
  });

  it("rejects a successful content response with a non-string result", async () => {
    const env = buildEnv();
    mockCfJson({ success: true, result: { html: "<html>wrong shape</html>" } });
    const res = await postJson("/content", { url: "https://example.com" }, env);
    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({ error: "Cloudflare returned malformed content" });
  });

  it("does not convert success=false envelopes into successful responses", async () => {
    const env = buildEnv();
    mockCfJson({ success: false, errors: [{ message: "Rendering failed" }] });
    const res = await postJson("/content", { url: "https://example.com" }, env);
    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({ error: "Rendering failed", status: 502 });
  });

  it("returns cached result on second request", async () => {
    const env = buildEnv();
    // First call — populates cache
    mockCfText("<html>cached</html>");
    await postJson("/content", { url: "https://example.com" }, env);
    // Second call — should hit cache, no fetch needed
    const res = await postJson("/content", { url: "https://example.com" }, env);
    expect(res.headers.get("X-Cache")).toBe("HIT");
    expect(cfApiCalls()).toHaveLength(1);
  });

  it("skips cache when no_cache is true", async () => {
    const env = buildEnv();
    mockCfText("<html>fresh</html>");
    mockCfText("<html>fresh again</html>");
    await postJson("/content", { url: "https://example.com", no_cache: true }, env);
    const res = await postJson("/content", { url: "https://example.com", no_cache: true }, env);
    expect(res.headers.get("X-Cache")).toBe("MISS");
    expect(cfApiCalls()).toHaveLength(2);
  });

  it("forwards CF API errors", async () => {
    const env = buildEnv();
    mockCfError(503, "Service unavailable");
    const res = await postJson("/content", { url: "https://example.com" }, env);
    expect(res.status).toBe(503);
    const body = await res.json<{ error: string }>();
    expect(body.error).toBeTruthy();
  });

  it("rejects malformed shared options before calling Cloudflare", async () => {
    const env = buildEnv();
    const res = await postJson(
      "/content",
      { url: "https://example.com", timeout: "5000" },
      env
    );
    expect(res.status).toBe(400);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("rejects non-object gotoOptions before calling Cloudflare", async () => {
    const env = buildEnv();
    const res = await postJson(
      "/content",
      { url: "https://example.com", gotoOptions: [] },
      env
    );
    expect(res.status).toBe(400);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("validates nested camelCase navigation options", async () => {
    const env = buildEnv();
    for (const gotoOptions of [
      { timeout: 60_001 },
      { timeout: true },
      { waitUntil: 42 },
      { waitUntil: "eventually" },
    ]) {
      const res = await postJson(
        "/content",
        { url: "https://example.com", gotoOptions },
        env,
      );
      expect(res.status).toBe(400);
    }
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("rejects malformed canonical shared options before calling Cloudflare", async () => {
    const env = buildEnv();
    for (const options of [
      { waitForSelector: "#ready" },
      { waitForSelector: { selector: "" } },
      { waitForSelector: { selector: "#ready", timeout: 120_001 } },
      { waitForSelector: { selector: "#ready", hidden: true, visible: true } },
      { actionTimeout: 120_001 },
      { waitForTimeout: 0 },
      { bestAttempt: "true" },
      { setJavaScriptEnabled: 1 },
      { emulateMediaType: "" },
      { rejectRequestPattern: [""] },
      { allowResourceTypes: ["not-a-resource-type"] },
      { gotoOptions: { referer: 42 } },
      { addScriptTag: [{ content: "" }] },
    ]) {
      const res = await postJson("/content", { url: "https://example.com", ...options }, env);
      expect(res.status).toBe(400);
    }
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("forwards valid bounded canonical shared options", async () => {
    const env = buildEnv();
    mockCfText("<html>valid options</html>");
    const options = {
      waitForSelector: { selector: "#ready", timeout: 120_000, visible: true },
      actionTimeout: 120_000,
      waitForTimeout: 1,
      bestAttempt: true,
      setJavaScriptEnabled: false,
      emulateMediaType: "screen",
      rejectRequestPattern: ["*.png"],
      allowResourceTypes: ["document", "xhr"],
      gotoOptions: { referer: "https://example.com/source", referrerPolicy: "no-referrer" },
    };

    const res = await postJson("/content", { url: "https://example.com", ...options }, env);

    expect(res.status).toBe(200);
    const sent = JSON.parse(cfApiCalls()[0]?.[1]?.body as string);
    expect(sent).toMatchObject(options);
  });

  it("blocks private nested script and style URLs before calling Cloudflare", async () => {
    const env = buildEnv();
    for (const payload of [
      { add_script_tag: [{ url: "http://127.0.0.2/secret.js" }] },
      { addStyleTag: [{ url: "http://[ff02::1]/secret.css" }] },
    ]) {
      const res = await postJson(
        "/content",
        { url: "https://example.com", ...payload },
        env,
      );
      expect(res.status).toBe(400);
    }
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("continues upstream when a cache read fails", async () => {
    const env = buildEnv();
    env.CACHE.getWithMetadata = async () => {
      throw new Error("KV unavailable");
    };
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    mockCfText("<html>fresh despite cache outage</html>");

    const res = await postJson("/content", { url: "https://example.com" }, env);

    expect(res.status).toBe(200);
    expect(res.headers.get("X-Cache")).toBe("MISS");
    expect(await res.text()).toContain("fresh despite cache outage");
    expect(warning).toHaveBeenCalledWith(
      "Cache read failed; continuing without cache",
      expect.any(Error)
    );
  });

  it("returns the upstream response when a cache write fails", async () => {
    const env = buildEnv();
    env.CACHE.put = async () => {
      throw new Error("KV unavailable");
    };
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    mockCfText("<html>not cached</html>");

    const res = await postJson("/content", { url: "https://example.com" }, env);

    expect(res.status).toBe(200);
    expect(res.headers.get("X-Cache")).toBe("MISS");
    expect(await res.text()).toContain("not cached");
    expect(warning).toHaveBeenCalledWith(
      "Cache write failed; returning the upstream response",
      expect.any(Error)
    );
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

  it("uses a synchronous request timeout with completion overhead", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const env = buildEnv();
    mockCfBinary(new Uint8Array([137, 80, 78, 71]).buffer, "image/png");

    const res = await postJson("/screenshot", { url: "https://example.com" }, env);

    expect(res.status).toBe(200);
    expect(timeout).toHaveBeenCalledWith(130_000);
    timeout.mockRestore();
  });

  it("fails closed when a successful screenshot response is JSON", async () => {
    const env = buildEnv();
    mockCfJson({ success: true, result: { data: "not-binary" } });

    const res = await postJson("/screenshot", { url: "https://example.com" }, env);

    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({ error: "Cloudflare returned malformed screenshot" });
  });

  it("fails closed when screenshot MIME is correct but bytes are not an image", async () => {
    const env = buildEnv();
    mockCfBinary(new TextEncoder().encode("not-an-image").buffer, "image/png");

    const res = await postJson("/screenshot", { url: "https://example.com" }, env);

    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({ error: "Cloudflare returned malformed screenshot" });
  });

  it("returns 400 if url missing", async () => {
    const env = buildEnv();
    const res = await postJson("/screenshot", {}, env);
    expect(res.status).toBe(400);
  });

  it("rejects string viewport values instead of silently forwarding them", async () => {
    const env = buildEnv();
    const res = await postJson(
      "/screenshot",
      { url: "https://example.com", width: "1280" },
      env
    );
    expect(res.status).toBe(400);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("preserves existing nested screenshot options when applying friendly aliases", async () => {
    const env = buildEnv();
    mockCfBinary(new Uint8Array([137, 80, 78, 71]).buffer, "image/png");
    const res = await postJson(
      "/screenshot",
      {
        url: "https://example.com",
        width: 1280,
        full_page: true,
        viewport: { height: 900, deviceScaleFactor: 2 },
        screenshotOptions: { omitBackground: true },
      },
      env
    );
    expect(res.status).toBe(200);
    const sent = JSON.parse(cfApiCalls()[0]?.[1]?.body as string);
    expect(sent.viewport).toEqual({ width: 1280, height: 900, deviceScaleFactor: 2 });
    expect(sent.screenshotOptions).toEqual({ fullPage: true, omitBackground: true });
  });

  it("rejects base64 screenshot encoding to preserve the binary response contract", async () => {
    const env = buildEnv();
    const res = await postJson(
      "/screenshot",
      { url: "https://example.com", screenshotOptions: { encoding: "base64" } },
      env
    );
    expect(res.status).toBe(400);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it.each([
    [{ viewport: { width: 999_999 } }, "viewport.width"],
    [{ screenshotOptions: { fullPage: "yes" } }, "screenshotOptions.fullPage"],
  ])("rejects malformed nested screenshot options %#", async (options, message) => {
    const env = buildEnv();
    const res = await postJson(
      "/screenshot",
      { url: "https://example.com", ...options },
      env
    );
    expect(res.status).toBe(400);
    expect(await res.text()).toContain(message);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("expires R2 objects after their configured TTL", async () => {
    const env = buildEnv();
    const clock = vi.spyOn(Date, "now");
    clock.mockReturnValue(1_000_000);
    mockCfBinary(new Uint8Array([137, 80, 78, 71, 1]).buffer, "image/png");
    await postJson("/screenshot", { url: "https://example.com" }, env);

    clock.mockReturnValue(1_000_000 + 24 * 60 * 60 * 1_000 + 1);
    mockCfBinary(new Uint8Array([137, 80, 78, 71, 2]).buffer, "image/png");
    const refreshed = await postJson("/screenshot", { url: "https://example.com" }, env);
    expect(refreshed.headers.get("X-Cache")).toBe("MISS");
    expect(cfApiCalls()).toHaveLength(2);
    clock.mockRestore();
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

  it("allows the documented five-minute PDF completion window plus overhead", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const env = buildEnv();
    mockCfBinary(new TextEncoder().encode("%PDF-1.4").buffer, "application/pdf");

    const res = await postJson("/pdf", { url: "https://example.com" }, env);

    expect(res.status).toBe(200);
    expect(timeout).toHaveBeenCalledWith(310_000);
    timeout.mockRestore();
  });

  it("fails closed when a successful PDF response is JSON", async () => {
    const env = buildEnv();
    mockCfJson({ success: true, result: { data: "not-binary" } });

    const res = await postJson("/pdf", { url: "https://example.com" }, env);

    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({ error: "Cloudflare returned malformed PDF" });
  });

  it("fails closed when PDF MIME is correct but bytes lack a PDF signature", async () => {
    const env = buildEnv();
    mockCfBinary(new TextEncoder().encode("not-a-pdf").buffer, "application/pdf");

    const res = await postJson("/pdf", { url: "https://example.com" }, env);

    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({ error: "Cloudflare returned malformed PDF" });
  });

  it("maps format and landscape into Cloudflare pdfOptions", async () => {
    const env = buildEnv();
    const pdfData = new TextEncoder().encode("%PDF-1.4").buffer;
    mockCfBinary(pdfData, "application/pdf");

    const res = await postJson(
      "/pdf",
      { url: "https://example.com", format: "A4", landscape: true },
      env
    );

    expect(res.status).toBe(200);
    const fetchCall = cfApiCalls()[0]!;
    const sentBody = JSON.parse(fetchCall[1]?.body as string);
    expect(sentBody.pdfOptions).toEqual({ format: "a4", landscape: true });
  });

  it("rejects malformed pdfOptions before calling Cloudflare", async () => {
    const env = buildEnv();
    const res = await postJson(
      "/pdf",
      { url: "https://example.com", pdfOptions: [] },
      env
    );
    expect(res.status).toBe(400);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it.each([
    [{ format: "Poster" }, "pdfOptions.format"],
    [{ landscape: "yes" }, "pdfOptions.landscape"],
  ])("rejects malformed nested PDF options %#", async (pdfOptions, message) => {
    const env = buildEnv();
    const res = await postJson(
      "/pdf",
      { url: "https://example.com", pdfOptions },
      env
    );
    expect(res.status).toBe(400);
    expect(await res.text()).toContain(message);
    expect(cfApiCalls()).toHaveLength(0);
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

  it("unwraps the official Cloudflare envelope with a Markdown content type", async () => {
    const env = buildEnv();
    mockCfJson({ success: true, result: "# Wrapped" });
    const res = await postJson("/markdown", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toContain("text/markdown");
    expect(await res.text()).toBe("# Wrapped");
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

  it("returns the same complete snapshot on cache hits", async () => {
    const env = buildEnv();
    const snapshot = {
      content: "<html/>",
      screenshot: "base64-data",
      markdown: "# Example",
    };
    mockCfJson(snapshot);

    const first = await postJson("/snapshot", { url: "https://example.com" }, env);
    const second = await postJson("/snapshot", { url: "https://example.com" }, env);

    expect(first.headers.get("X-Cache")).toBe("MISS");
    expect(second.headers.get("X-Cache")).toBe("HIT");
    expect(await first.json()).toEqual(snapshot);
    expect(await second.json()).toEqual(snapshot);
    expect(cfApiCalls()).toHaveLength(1);
  });

  it("fails closed on a primitive snapshot response", async () => {
    const env = buildEnv();
    mockCfJson("not-a-snapshot");

    const res = await postJson("/snapshot", { url: "https://example.com" }, env);

    expect(res.status).toBe(502);
  });
});

// ---------------------------------------------------------------------------
// POST /scrape
// ---------------------------------------------------------------------------

describe("POST /scrape", () => {
  it("normalizes selector results into an elements envelope", async () => {
    const env = buildEnv();
    mockCfJson([{ selector: "h1", results: [{ text: "Title" }] }]);
    const res = await postJson(
      "/scrape",
      { url: "https://example.com", elements: ["h1"] },
      env
    );
    expect(res.status).toBe(200);
    const body = await res.json<{ elements: Array<{ selector: string }> }>();
    expect(body.elements[0]?.selector).toBe("h1");
  });

  it("fails closed on malformed scrape results", async () => {
    const env = buildEnv();
    mockCfJson([{ selector: "h1" }, "invalid-element"]);

    const res = await postJson(
      "/scrape",
      { url: "https://example.com", elements: ["h1"] },
      env,
    );

    expect(res.status).toBe(502);
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
    await postJson("/json", { url: "https://example.com", prompt: "Get title" }, env);
    const res = await postJson(
      "/json",
      { url: "https://example.com", prompt: "Get title" },
      env
    );
    // Should have called CF API twice (no caching)
    expect(cfApiCalls()).toHaveLength(2);
    expect(res.headers.get("X-Cache")).toBe("BYPASS");
  });

  it("maps the legacy schema alias to Cloudflare response_format", async () => {
    const env = buildEnv();
    mockCfJson({ title: "Example" });
    const schema = {
      type: "object",
      properties: { title: { type: "string" } },
    };
    const res = await postJson("/json", { url: "https://example.com", schema }, env);
    expect(res.status).toBe(200);
    const sent = JSON.parse(cfApiCalls()[0]?.[1]?.body as string);
    expect(sent.schema).toBeUndefined();
    expect(sent.response_format).toEqual({ type: "json_schema", json_schema: schema });
  });

  it("requires a prompt or response schema", async () => {
    const env = buildEnv();
    const res = await postJson("/json", { url: "https://example.com" }, env);
    expect(res.status).toBe(400);
  });

  it("rejects malformed response_format before calling Cloudflare", async () => {
    const env = buildEnv();
    const res = await postJson(
      "/json",
      { url: "https://example.com", response_format: { type: "json_schema" } },
      env
    );
    expect(res.status).toBe(400);
    expect(cfApiCalls()).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// POST /links
// ---------------------------------------------------------------------------

describe("POST /links", () => {
  it("normalizes links into href/text objects", async () => {
    const env = buildEnv();
    mockCfJson(["https://example.com/a", "https://example.com/b"]);
    const res = await postJson("/links", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    const body = await res.json<Array<{ href: string; text: string | null }>>();
    expect(body).toEqual([
      { href: "https://example.com/a", text: null },
      { href: "https://example.com/b", text: null },
    ]);
  });

  it("maps friendly filtering options to Cloudflare's current names", async () => {
    const env = buildEnv();
    mockCfJson([]);
    const res = await postJson(
      "/links",
      { url: "https://example.com", include_external: false, visible_only: true },
      env
    );
    expect(res.status).toBe(200);
    const sent = JSON.parse(cfApiCalls()[0]?.[1]?.body as string);
    expect(sent.excludeExternalLinks).toBe(true);
    expect(sent.visibleLinksOnly).toBe(true);
    expect(sent.include_external).toBeUndefined();
  });

  it("fails closed on malformed link results", async () => {
    const env = buildEnv();
    mockCfJson([{ href: "https://example.com/a", text: 42 }]);

    const res = await postJson("/links", { url: "https://example.com" }, env);

    expect(res.status).toBe(502);
  });
});

// ---------------------------------------------------------------------------
// POST /crawl + GET /crawl/:id
// ---------------------------------------------------------------------------

describe("POST /crawl", () => {
  it("starts a crawl job and returns 202 with job ID", async () => {
    const env = buildEnv();
    const jobId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
    mockCfJson({ job_id: jobId, status: "pending" });
    const res = await postJson("/crawl", { url: "https://example.com" }, env);
    expect(res.status).toBe(202);
    const body = await res.json<{ job_id: string }>();
    expect(body.job_id).toBe(jobId);
  });

  it.each([
    [{ cache_ttl: 60 }, "60"],
    [{ cacheTTL: 120 }, "120"],
    [{ no_cache: true }, "0"],
  ])("forwards crawl cache controls as the create query %#", async (cacheControl, expected) => {
    const env = buildEnv();
    const jobId = "0a1b2c3d-4e5f-6789-abcd-ef0123456789";
    mockCfJson({ job_id: jobId });

    const res = await postJson(
      "/crawl",
      { url: "https://example.com", ...cacheControl },
      env,
    );

    expect(res.status).toBe(202);
    const [requestUrl, requestOptions] = cfApiCalls()[0] ?? [];
    expect(String(requestUrl)).toContain(`/crawl?cacheTTL=${expected}`);
    const sent = JSON.parse(String(requestOptions?.body));
    expect(sent.cache_ttl).toBeUndefined();
    expect(sent.cacheTTL).toBeUndefined();
    expect(sent.no_cache).toBeUndefined();
  });

  it("rejects invalid or conflicting crawl cache controls", async () => {
    const env = buildEnv();
    for (const cacheControl of [
      { cache_ttl: -1 },
      { cache_ttl: 86_401 },
      { cache_ttl: 1.5 },
      { cache_ttl: "60" },
      { cache_ttl: 60, cacheTTL: 60 },
      { no_cache: "true" },
      { no_cache: true, cache_ttl: 60 },
    ]) {
      const res = await postJson(
        "/crawl",
        { url: "https://example.com", ...cacheControl },
        env,
      );
      expect(res.status).toBe(400);
    }
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("rejects a successful upstream response without a job ID", async () => {
    const env = buildEnv();
    mockCfJson({ success: true });
    const res = await postJson("/crawl", { url: "https://example.com" }, env);
    expect(res.status).toBe(502);
  });

  it("rejects a null upstream crawl response without throwing", async () => {
    const env = buildEnv();
    mockCfJson(null);
    const res = await postJson("/crawl", { url: "https://example.com" }, env);
    expect(res.status).toBe(502);
  });

  it("rejects a malformed upstream job ID", async () => {
    const env = buildEnv();
    mockCfJson({ job_id: "not-a-uuid" });
    const res = await postJson("/crawl", { url: "https://example.com" }, env);
    expect(res.status).toBe(502);
  });

  it("rejects browser-only options for static crawls", async () => {
    const env = buildEnv();
    const res = await postJson(
      "/crawl",
      { url: "https://example.com", render: false, headers: { "X-Test": "value" } },
      env
    );
    expect(res.status).toBe(400);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("rejects malformed crawl options and camelCase browser bypasses", async () => {
    const env = buildEnv();
    for (const payload of [
      { url: "https://example.com", render: "false" },
      { url: "https://example.com", render: null },
      { url: "https://example.com", options: [] },
      { url: "https://example.com", options: null },
      { url: "https://example.com", limit: 10, max_pages: "5" },
      { url: "https://example.com", limit: 10, max_pages: 5 },
      { url: "https://example.com", source: "robots" },
      { url: "https://example.com", render: false, setExtraHTTPHeaders: {} },
      { url: "https://example.com", userAgent: "CustomBot/1.0" },
    ]) {
      const res = await postJson("/crawl", payload, env);
      expect(res.status).toBe(400);
    }
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("maps and forwards the current crawl contract", async () => {
    const env = buildEnv();
    const jobId = "f5a6b7c8-d9e0-1234-abcd-456789012345";
    mockCfJson({ job_id: jobId });
    const modifiedSince = Math.floor(Date.now() / 1000) - 3600;
    const res = await postJson("/crawl", {
      url: "https://example.com/docs/",
      max_pages: 25,
      depth: 3,
      formats: ["markdown", "json"],
      crawl_purposes: ["search"],
      max_age: 3600,
      modified_since: modifiedSince,
      include_external: true,
      include_subdomains: true,
      include_patterns: ["**/docs/**"],
      exclude_patterns: ["**/private/**"],
      json_options: { prompt: "Extract the title" },
      reject_request_patterns: ["*.png"],
      javascript_enabled: false,
    }, env);
    expect(res.status).toBe(202);
    const request = cfApiCalls()[0];
    const sent = JSON.parse(String(request?.[1]?.body));
    expect(sent).toMatchObject({
      limit: 25,
      depth: 3,
      formats: ["markdown", "json"],
      crawlPurposes: ["search"],
      maxAge: 3600,
      modifiedSince,
      render: true,
      source: "all",
      options: {
        includeExternalLinks: true,
        includeSubdomains: true,
        includePatterns: ["**/docs/**"],
        excludePatterns: ["**/private/**"],
      },
      jsonOptions: { prompt: "Extract the title" },
      rejectRequestPattern: ["*.png"],
      setJavaScriptEnabled: false,
    });
    expect(sent.max_pages).toBeUndefined();
    expect(sent.crawl_purposes).toBeUndefined();
  });

  it("rejects malformed current crawl fields", async () => {
    const env = buildEnv();
    for (const payload of [
      { depth: 0 },
      { formats: ["text"] },
      { crawl_purposes: ["advertising"] },
      { max_age: 604_801 },
      { modified_since: Math.floor(Date.now() / 1000) + 60 },
      { include_patterns: [""] },
      { json_options: [] },
      { render: false, reject_request_patterns: ["*.png"] },
    ]) {
      const res = await postJson("/crawl", { url: "https://example.com", ...payload }, env);
      expect(res.status).toBe(400);
    }
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("cancels the upstream crawl when owner metadata cannot be stored", async () => {
    const env = buildEnv();
    env.STORAGE.put = async () => { throw new Error("R2 unavailable"); };
    const jobId = "a6b7c8d9-e0f1-2345-bcde-567890123456";
    mockCfJson({ job_id: jobId });
    mockCfJson({ job_id: jobId, message: "cancelled" });
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    const res = await postJson("/crawl", { url: "https://example.com" }, env);

    expect(res.status).toBe(503);
    expect(cfApiCalls().map((call) => call[1]?.method)).toEqual(["POST", "DELETE"]);
    expect(warning).toHaveBeenCalled();
  });

  it("retains recoverable ownership when both R2 storage and cancellation fail", async () => {
    const env = buildEnv();
    env.STORAGE.put = async () => { throw new Error("R2 unavailable"); };
    const jobId = "1a2b3c4d-5e6f-7890-abcd-ef1234567890";
    mockCfJson({ job_id: jobId });
    mockCfError(503, "Cancellation unavailable");
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    const created = await postJson("/crawl", { url: "https://example.com" }, env);

    expect(created.status).toBe(202);
    expect(await created.json()).toMatchObject({ job_id: jobId, status: "started" });

    mockCfJson({ status: "running", progress: 10 });
    const read = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      headers: { Authorization: "Bearer valid-key" },
    }), env);
    expect(read.status).toBe(200);
    expect(await read.json()).toMatchObject({ job_id: jobId, status: "running" });

    mockCfJson({ job_id: jobId, message: "cancelled" });
    const deleted = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      method: "DELETE",
      headers: { Authorization: "Bearer valid-key" },
    }), env);
    expect(deleted.status).toBe(204);

    const afterDelete = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      headers: { Authorization: "Bearer valid-key" },
    }), env);
    expect(afterDelete.status).toBe(404);
    expect(cfApiCalls().map((call) => call[1]?.method)).toEqual([
      "POST", "DELETE", "GET", "DELETE",
    ]);
    warning.mockRestore();
  });
});

describe("GET /crawl/:id", () => {
  it("fails closed when owner metadata is missing, even with one API key", async () => {
    const env = buildEnv();
    const res = await app.fetch(
      new Request("http://localhost/crawl/a1b2c3d4-e5f6-7890-abcd-ef1234567890", {
        headers: { Authorization: "Bearer valid-key" },
      }),
      env,
    );
    expect(res.status).toBe(404);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("polls crawl status from CF API when not in R2", async () => {
    const env = buildEnv();
    await putCrawlOwner(env, "a1b2c3d4-e5f6-7890-abcd-ef1234567890");
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

  it("rejects malformed crawl status responses without throwing", async () => {
    const env = buildEnv();
    await putCrawlOwner(env, "a1b2c3d4-e5f6-7890-abcd-ef1234567890");
    fetchMock.mockResolvedValueOnce(
      new Response("null", {
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
    expect(res.status).toBe(502);
  });

  it("fails closed when crawl status fields have the wrong type", async () => {
    const env = buildEnv();
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: 42, job_id: "wrong", status: 42 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    const jobId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
    await putCrawlOwner(env, jobId);
    const res = await app.fetch(
      new Request(`http://localhost/crawl/${jobId}`, {
        headers: { Authorization: "Bearer valid-key" },
      }),
      env
    );
    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({
      error: "Cloudflare crawl status response was malformed",
    });
  });

  it("rejects incomplete terminal crawl payloads and invalid counters", async () => {
    const env = buildEnv();
    const jobId = "a7b8c9d0-e1f2-3456-abcd-789012345678";
    await putCrawlOwner(env, jobId);
    for (const payload of [
      { status: "completed", records: [] },
      { id: jobId, status: "completed" },
      { id: jobId, status: "completed", records: [], browserSecondsUsed: -1 },
      { id: jobId, status: "completed", records: [], finished: 1.5 },
      { id: jobId, status: "completed", records: [], skipped: -1 },
      { id: jobId, status: "completed", records: [], total: "1" },
    ]) {
      mockCfJson(payload);
      const res = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
        headers: { Authorization: "Bearer valid-key" },
      }), env);
      expect(res.status).toBe(502);
    }
  });

  it("returns a completed upstream result when crawl cache writes fail", async () => {
    const env = buildEnv();
    const jobId = "a2b3c4d5-e6f7-8901-abcd-ef2345678901";
    await putCrawlOwner(env, jobId);
    env.STORAGE.put = async () => {
      throw new Error("R2 unavailable");
    };
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: jobId, status: "completed", records: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    const res = await app.fetch(
      new Request(`http://localhost/crawl/${jobId}`, {
        headers: { Authorization: "Bearer valid-key" },
      }),
      env
    );
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ status: "completed", records: [] });
    expect(warning).toHaveBeenCalledWith(
      "Crawl result cache write failed; returning upstream status",
      expect.any(Error)
    );
  });

  it("serves completed crawl from R2 on second poll", async () => {
    const env = buildEnv();
    const jobId = "b2c3d4e5-f6a7-8901-bcde-f12345678901";
    await putCrawlOwner(env, jobId);
    // First poll — CF returns completed
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: jobId, status: "complete", records: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    await app.fetch(
      new Request(`http://localhost/crawl/${jobId}`, {
        headers: { Authorization: "Bearer valid-key" },
      }),
      env
    );
    // Second poll — should hit R2
    const res = await app.fetch(
      new Request(`http://localhost/crawl/${jobId}`, {
        headers: { Authorization: "Bearer valid-key" },
      }),
      env
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("X-Cache")).toBe("HIT");
    // CF API called only once
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(["next", 20, 0])(
    "does not cache a completed crawl page while response cursor %j remains",
    async (responseCursor) => {
      const env = buildEnv();
      const jobId = "b3c4d5e6-f7a8-9012-cdef-234567890123";
      await putCrawlOwner(env, jobId);
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
        id: jobId,
        status: "completed", records: [{ url: "https://example.com/1" }], cursor: responseCursor,
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
        id: jobId,
        status: "completed", records: [{ url: "https://example.com/1" }], cursor: responseCursor,
      }), { status: 200, headers: { "Content-Type": "application/json" } }));

      const request = () => app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
        headers: { Authorization: "Bearer valid-key" },
      }), env);
      expect((await request()).headers.get("X-Cache")).toBe("MISS");
      expect((await request()).headers.get("X-Cache")).toBe("MISS");
      expect(cfApiCalls()).toHaveLength(2);
    },
  );

  it.each([-1, 1.5])("rejects invalid numeric response cursor %s", async (responseCursor) => {
    const env = buildEnv();
    const jobId = "b5c6d7e8-f9a0-1234-efab-456789012345";
    await putCrawlOwner(env, jobId);
    mockCfJson({ id: jobId, status: "completed", records: [], cursor: responseCursor });

    const res = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      headers: { Authorization: "Bearer valid-key" },
    }), env);

    expect(res.status).toBe(502);
  });

  it("rejects pagination limits above the crawl maximum", async () => {
    const env = buildEnv();
    const jobId = "b4c5d6e7-f8a9-0123-defa-345678901234";
    await putCrawlOwner(env, jobId);
    const res = await app.fetch(new Request(
      `http://localhost/crawl/${jobId}?limit=100001`,
      { headers: { Authorization: "Bearer valid-key" } },
    ), env);
    expect(res.status).toBe(400);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("forwards pagination query parameters without caching partial results", async () => {
    const env = buildEnv();
    const jobId = "c2d3e4f5-a6b7-8901-cdef-123456789012";
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: jobId, status: "completed", records: [], cursor: 20 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    await putCrawlOwner(env, jobId);
    const res = await app.fetch(
      new Request(`http://localhost/crawl/${jobId}?cursor=10&limit=10&status=completed`, {
        headers: { Authorization: "Bearer valid-key" },
      }),
      env
    );
    expect(res.status).toBe(200);
    const [requestUrl] = cfApiCalls()[0] ?? [];
    expect(String(requestUrl)).toContain(`/crawl/${jobId}?cursor=10&limit=10&status=completed`);
    expect(res.headers.get("X-Cache")).toBe("BYPASS");
  });

  it("does not expose a crawl job to a different configured API key", async () => {
    const env = buildEnv();
    env.API_KEYS = "key-a,key-b";
    const jobId = "d3e4f5a6-b7c8-9012-defa-234567890123";
    mockCfJson({ job_id: jobId });
    const create = await app.fetch(
      new Request("http://localhost/crawl", {
        method: "POST",
        headers: { Authorization: "Bearer key-a", "Content-Type": "application/json" },
        body: JSON.stringify({ url: "https://example.com" }),
      }),
      env
    );
    expect(create.status).toBe(202);

    const read = await app.fetch(
      new Request(`http://localhost/crawl/${jobId}`, {
        headers: { Authorization: "Bearer key-b" },
      }),
      env
    );
    expect(read.status).toBe(404);
    expect(cfApiCalls()).toHaveLength(1);
  });

  it("allows the owner to cancel the upstream crawl and clears local ownership", async () => {
    const env = buildEnv();
    env.API_KEYS = "key-a,key-b";
    const jobId = "e4f5a6b7-c8d9-0123-efab-345678901234";
    mockCfJson({ job_id: jobId });
    await app.fetch(
      new Request("http://localhost/crawl", {
        method: "POST",
        headers: { Authorization: "Bearer key-a", "Content-Type": "application/json" },
        body: JSON.stringify({ url: "https://example.com" }),
      }),
      env
    );
    mockCfJson({ job_id: jobId, message: "cancelled" });

    const cancelled = await app.fetch(
      new Request(`http://localhost/crawl/${jobId}`, {
        method: "DELETE",
        headers: { Authorization: "Bearer key-a" },
      }),
      env
    );
    expect(cancelled.status).toBe(204);
    const [requestUrl, options] = cfApiCalls()[1] ?? [];
    expect(String(requestUrl)).toContain(`/crawl/${jobId}`);
    expect(options?.method).toBe("DELETE");

    const readAfterDelete = await app.fetch(
      new Request(`http://localhost/crawl/${jobId}`, {
        headers: { Authorization: "Bearer key-a" },
      }),
      env
    );
    expect(readAfterDelete.status).toBe(404);
  });

  it("retains ownership when the upstream cancellation response is malformed", async () => {
    const env = buildEnv();
    const jobId = "f5a6b7c8-d9e0-1234-abcd-456789012345";
    await putCrawlOwner(env, jobId);
    mockCfJson({ job_id: "00000000-0000-0000-0000-000000000000", message: "cancelled" });

    const deleted = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      method: "DELETE",
      headers: { Authorization: "Bearer valid-key" },
    }), env);

    expect(deleted.status).toBe(502);
    mockCfJson({ status: "running" });
    const read = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      headers: { Authorization: "Bearer valid-key" },
    }), env);
    expect(read.status).toBe(200);
  });

  it("uses a tombstone to deny reads when local R2 cleanup fails", async () => {
    const env = buildEnv();
    const jobId = "f6a7b8c9-d0e1-2345-bcde-567890123456";
    await putCrawlOwner(env, jobId);
    env.STORAGE.delete = async () => { throw new Error("R2 delete unavailable"); };
    mockCfJson({ job_id: jobId, message: "cancelled" });
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    const deleted = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      method: "DELETE",
      headers: { Authorization: "Bearer valid-key" },
    }), env);

    expect(deleted.status).toBe(204);
    const read = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      headers: { Authorization: "Bearer valid-key" },
    }), env);
    expect(read.status).toBe(404);
    const repeatedDelete = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      method: "DELETE",
      headers: { Authorization: "Bearer valid-key" },
    }), env);
    expect(repeatedDelete.status).toBe(404);
    expect(cfApiCalls()).toHaveLength(1);
    expect(warning).toHaveBeenCalled();
    warning.mockRestore();
  });

  it("returns 503 when neither cleanup nor a durable denial marker succeeds", async () => {
    const env = buildEnv();
    const jobId = "f7a8b9c0-d1e2-3456-cdef-678901234567";
    await putCrawlOwner(env, jobId);
    env.CACHE.put = async () => { throw new Error("KV write unavailable"); };
    env.STORAGE.put = async () => { throw new Error("R2 write unavailable"); };
    env.STORAGE.delete = async () => { throw new Error("R2 delete unavailable"); };
    mockCfJson({ job_id: jobId, message: "cancelled" });
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    const deleted = await app.fetch(new Request(`http://localhost/crawl/${jobId}`, {
      method: "DELETE",
      headers: { Authorization: "Bearer valid-key" },
    }), env);

    expect(deleted.status).toBe(503);
    expect(await deleted.json()).toMatchObject({
      error: "Unable to durably remove local crawl state",
    });
    warning.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// POST /a11y
// ---------------------------------------------------------------------------

describe("POST /a11y", () => {
  it("returns the native accessibility tree endpoint response", async () => {
    const env = buildEnv();
    mockCfJson({
      type: "upstream-value",
      accessibilityTree: { role: "RootWebArea", name: "Example" },
    });
    const res = await postJson("/a11y", { url: "https://example.com" }, env);
    expect(res.status).toBe(200);
    const body = await res.json<Record<string, unknown>>();
    expect(body.type).toBe("accessibility_tree");
    expect(body.accessibilityTree).toEqual({ role: "RootWebArea", name: "Example" });
    const [requestUrl] = cfApiCalls()[0] ?? [];
    expect(String(requestUrl)).toContain("/browser-rendering/accessibilityTree");
  });

  it("returns 400 if url missing", async () => {
    const env = buildEnv();
    const res = await postJson("/a11y", {}, env);
    expect(res.status).toBe(400);
  });

  it("caches a11y results in KV", async () => {
    const env = buildEnv();
    mockCfJson({ accessibilityTree: { role: "RootWebArea" } });
    await postJson("/a11y", { url: "https://example.com" }, env);
    const res = await postJson("/a11y", { url: "https://example.com" }, env);
    expect(res.headers.get("X-Cache")).toBe("HIT");
    expect(cfApiCalls()).toHaveLength(1);
  });

  it("fails closed on a primitive accessibility tree response", async () => {
    const env = buildEnv();
    mockCfJson("not-an-accessibility-tree");

    const res = await postJson("/a11y", { url: "https://example.com" }, env);

    expect(res.status).toBe(502);
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
    const fetchCall = cfApiCalls()[0]!;
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

// ---------------------------------------------------------------------------
// Request hardening
// ---------------------------------------------------------------------------

describe("Request hardening", () => {
  it("never reads bodies of unauthenticated or unknown requests", async () => {
    const env = buildEnv();
    const post = (path: string, headers: Record<string, string> = {}) => app.fetch(
      new Request(`http://localhost${path}`, { method: "POST", headers, body: "{not json" }),
      env,
    );

    expect((await post("/content")).status).toBe(401);
    expect((await post("/health")).status).toBe(404);
    expect((await post("/nope", authHeaders())).status).toBe(404);
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("rejects oversized bodies with 413 before parsing them", async () => {
    const env = buildEnv();
    const oversized = JSON.stringify({
      url: "https://example.com",
      add_script_tag: [{ content: "x".repeat(MAX_REQUEST_BODY_BYTES) }],
    });

    const declared = await app.fetch(new Request("http://localhost/content", {
      method: "POST",
      headers: { ...authHeaders(), "Content-Length": String(oversized.length) },
      body: oversized,
    }), env);
    const streamed = await app.fetch(new Request("http://localhost/content", {
      method: "POST",
      headers: authHeaders(),
      body: new Blob([oversized]).stream(),
      duplex: "half",
    } as RequestInit), env);

    expect(declared.status).toBe(413);
    expect(streamed.status).toBe(413);
    expect(await streamed.json()).toMatchObject({ status: 413 });
    expect(cfApiCalls()).toHaveLength(0);
  });

  it("rejects __proto__ keys at any depth and excessive nesting", async () => {
    const env = buildEnv();
    const send = (raw: string) => app.fetch(new Request("http://localhost/content", {
      method: "POST",
      headers: authHeaders(),
      body: raw,
    }), env);
    let nested: unknown = "leaf";
    for (let depth = 0; depth < MAX_JSON_DEPTH; depth++) nested = { child: nested };

    const topLevel = await send('{"url":"https://example.com","__proto__":{"x":1}}');
    const deep = await send('{"url":"https://example.com","gotoOptions":{"__proto__":{"x":1}}}');
    const tooDeep = await send(JSON.stringify({ url: "https://example.com", nested }));

    expect(topLevel.status).toBe(400);
    expect(deep.status).toBe(400);
    expect(tooDeep.status).toBe(400);
    expect(await tooDeep.json()).toMatchObject({ error: expect.stringContaining("nested") });
    expect(cfApiCalls()).toHaveLength(0);
  });
});

describe("POST /crawl ownership", () => {
  it("never reassigns a job ID that another API key already owns", async () => {
    const env = buildEnv();
    env.API_KEYS = "valid-key,other-key";
    const jobId = "b1c2d3e4-f5a6-4789-9abc-def012345678";
    await putCrawlOwner(env, jobId, "other-key");
    mockCfJson({ job_id: jobId });

    const res = await postJson("/crawl", { url: "https://example.com" }, env);

    expect(res.status).toBe(409);
    expect(cfApiCalls().map((call) => call[1]?.method)).toEqual(["POST"]);
    const owner = await env.STORAGE.get(r2ObjectKey(`crawl-owner:${jobId}`));
    expect(await owner?.text()).toBe(await hashApiKey("other-key"));
  });

  it("accepts a reused job ID that the same API key already owns", async () => {
    const env = buildEnv();
    const jobId = "c2d3e4f5-a6b7-4890-8bcd-ef0123456789";
    await putCrawlOwner(env, jobId);
    mockCfJson({ job_id: jobId });

    const res = await postJson("/crawl", { url: "https://example.com" }, env);

    expect(res.status).toBe(202);
    expect(await res.json()).toMatchObject({ job_id: jobId, status: "started" });
  });

  it("stores crawl state under the managed R2 prefix", async () => {
    const env = buildEnv();
    const jobId = "d3e4f5a6-b7c8-4901-9cde-f01234567890";
    mockCfJson({ job_id: jobId });

    const res = await postJson("/crawl", { url: "https://example.com" }, env);

    expect(res.status).toBe(202);
    expect(await env.STORAGE.get(`crawl-owner:${jobId}`)).toBeNull();
    expect(await env.STORAGE.get(r2ObjectKey(`crawl-owner:${jobId}`))).not.toBeNull();
  });
});
