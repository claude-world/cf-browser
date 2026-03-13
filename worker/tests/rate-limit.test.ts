import { describe, it, expect, vi, beforeEach } from "vitest";
import { Hono } from "hono";
import { rateLimitMiddleware } from "../src/middleware/rate-limit.js";
import type { Env } from "../src/types.js";

/**
 * Creates a minimal in-memory KV stub.
 */
function makeKvStub(): KVNamespace {
  const store = new Map<string, string>();
  return {
    get: async (key: string) => store.get(key) ?? null,
    getWithMetadata: async (key: string) => ({
      value: store.get(key) ?? null,
      metadata: null,
      cacheStatus: null,
    }),
    put: async (key: string, value: string) => { store.set(key, value); },
    delete: async (key: string) => { store.delete(key); },
    list: async () => ({ keys: [], list_complete: true, cursor: "", cacheStatus: null }),
  } as unknown as KVNamespace;
}

function buildApp(rateLimitKv: KVNamespace) {
  const app = new Hono<{ Bindings: Env }>();

  // Seed apiKey as auth middleware would
  app.use("*", async (c, next) => {
    c.set("apiKey", "test-key-1234");
    await next();
  });
  app.use("*", rateLimitMiddleware);
  app.get("/", (c) => c.json({ ok: true }));

  return {
    fetch: (req: Request) =>
      app.fetch(req, {
        CF_ACCOUNT_ID: "acct",
        CF_API_TOKEN: "token",
        API_KEYS: "test-key-1234",
        CACHE: {} as KVNamespace,
        RATE_LIMIT: rateLimitKv,
        STORAGE: {} as R2Bucket,
      }),
  };
}

describe("rateLimitMiddleware", () => {
  it("allows requests below the limit", async () => {
    const kv = makeKvStub();
    const app = buildApp(kv);
    const res = await app.fetch(new Request("http://localhost/"));
    expect(res.status).toBe(200);
    expect(res.headers.get("X-RateLimit-Limit")).toBe("60");
    expect(res.headers.get("X-RateLimit-Remaining")).toBe("59");
  });

  it("blocks the 61st request in the same minute bucket", async () => {
    const kv = makeKvStub();
    // Pre-seed counter at 60 (the limit).
    // The middleware hashes the API key the same way as hashKey() in rate-limit.ts:
    // SHA-256 of the key, first 8 bytes as hex.
    const apiKey = "test-key-1234";
    const keyData = new TextEncoder().encode(apiKey);
    const hashBuffer = await crypto.subtle.digest("SHA-256", keyData);
    const keyHash = Array.from(new Uint8Array(hashBuffer).slice(0, 8))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    const minuteBucket = Math.floor(Date.now() / 60_000);
    await (kv as unknown as { put: (k: string, v: string) => Promise<void> }).put(
      `rl:${keyHash}:${minuteBucket}`,
      "60"
    );

    const app = buildApp(kv);
    const res = await app.fetch(new Request("http://localhost/"));
    expect(res.status).toBe(429);
    expect(res.headers.has("Retry-After")).toBe(true);
  });

  it("sets X-RateLimit-Remaining correctly on first call", async () => {
    const kv = makeKvStub();
    const app = buildApp(kv);
    const res = await app.fetch(new Request("http://localhost/"));
    const remaining = parseInt(res.headers.get("X-RateLimit-Remaining") ?? "-1", 10);
    expect(remaining).toBe(59);
  });
});
