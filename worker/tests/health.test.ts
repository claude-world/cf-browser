import { describe, it, expect } from "vitest";
import app from "../src/index.js";
import type { Env } from "../src/types.js";

const env: Env = {
  CF_ACCOUNT_ID: "acct",
  CF_API_TOKEN: "token",
  API_KEYS: "test-key",
  CACHE: {} as KVNamespace,
  RATE_LIMITER: {} as RateLimit,
  STORAGE: {} as R2Bucket,
};

describe("GET /health", () => {
  it("returns 200 with status ok and version", async () => {
    const res = await app.fetch(new Request("http://localhost/health"), env);
    expect(res.status).toBe(200);
    const body = await res.json<{ status: string; ready: boolean; version: string }>();
    expect(body.status).toBe("ok");
    expect(body.ready).toBe(true);
    expect(body.version).toBe("2.1.0");
  });

  it("returns 503 when a required binding is missing", async () => {
    const broken = { ...env, RATE_LIMITER: undefined } as unknown as Env;
    const res = await app.fetch(new Request("http://localhost/health"), broken);
    expect(res.status).toBe(503);
    const body = await res.json<{ status: string; ready: boolean; missing: string[] }>();
    expect(body.status).toBe("degraded");
    expect(body.ready).toBe(false);
    expect(body.missing).toContain("RATE_LIMITER");
  });

  it("does not require Authorization", async () => {
    const res = await app.fetch(new Request("http://localhost/health"), env);
    expect(res.status).toBe(200);
  });
});

describe("404 fallback", () => {
  it("returns 404 JSON for unknown routes", async () => {
    const res = await app.fetch(
      new Request("http://localhost/does-not-exist", {
        headers: { Authorization: "Bearer test-key" },
      }),
      env
    );
    expect(res.status).toBe(404);
    const body = await res.json<{ error: string }>();
    expect(body.error).toBe("Not found");
  });
});
