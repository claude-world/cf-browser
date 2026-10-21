import { describe, it, expect } from "vitest";
import { Hono } from "hono";
import { rateLimitMiddleware } from "../src/middleware/rate-limit.js";
import type { AppEnv } from "../src/types.js";

function makeRateLimiter(limit = 60): RateLimit {
  let count = 0;
  return {
    limit: async () => ({ success: ++count <= limit }),
  } as RateLimit;
}

function buildApp(rateLimiter: RateLimit) {
  const app = new Hono<AppEnv>();

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
        RATE_LIMITER: rateLimiter,
        STORAGE: {} as R2Bucket,
      }),
  };
}

describe("rateLimitMiddleware", () => {
  it("allows requests below the limit", async () => {
    const app = buildApp(makeRateLimiter());
    const res = await app.fetch(new Request("http://localhost/"));
    expect(res.status).toBe(200);
    expect(res.headers.get("X-RateLimit-Limit")).toBe("60");
    expect(res.headers.has("X-RateLimit-Remaining")).toBe(false);
  });

  it("blocks the 61st request in the same minute bucket", async () => {
    const app = buildApp(makeRateLimiter());
    for (let i = 0; i < 60; i++) {
      expect((await app.fetch(new Request("http://localhost/"))).status).toBe(200);
    }
    const res = await app.fetch(new Request("http://localhost/"));
    expect(res.status).toBe(429);
    expect(res.headers.has("Retry-After")).toBe(true);
  });

  it("does not write per-request counters to KV", async () => {
    const limiter = makeRateLimiter();
    const app = buildApp(limiter);
    expect((await app.fetch(new Request("http://localhost/"))).status).toBe(200);
  });
});
