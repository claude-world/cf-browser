import { describe, it, expect } from "vitest";
import app from "../src/index.js";
import type { Env } from "../src/types.js";

const env: Env = {
  CF_ACCOUNT_ID: "acct",
  CF_API_TOKEN: "token",
  API_KEYS: "test-key",
  CACHE: {} as KVNamespace,
  RATE_LIMIT: {} as KVNamespace,
  STORAGE: {} as R2Bucket,
};

describe("GET /health", () => {
  it("returns 200 with status ok and version", async () => {
    const res = await app.fetch(new Request("http://localhost/health"), env);
    expect(res.status).toBe(200);
    const body = await res.json<{ status: string; version: string }>();
    expect(body.status).toBe("ok");
    expect(body.version).toBe("2.0.1");
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
