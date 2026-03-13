import { describe, it, expect } from "vitest";
import { Hono } from "hono";
import { authMiddleware } from "../src/middleware/auth.js";
import type { Env } from "../src/types.js";

function buildApp(apiKeys: string) {
  const app = new Hono<{ Bindings: Env }>();
  app.use("*", authMiddleware);
  app.get("/", (c) => c.json({ ok: true }));

  // Simulate bindings by overriding fetch with env injection
  return {
    fetch: (req: Request) =>
      app.fetch(req, {
        CF_ACCOUNT_ID: "acct",
        CF_API_TOKEN: "token",
        API_KEYS: apiKeys,
        CACHE: {} as KVNamespace,
        RATE_LIMIT: {} as KVNamespace,
        STORAGE: {} as R2Bucket,
      }),
  };
}

describe("authMiddleware", () => {
  it("returns 401 when no Authorization header", async () => {
    const app = buildApp("key-abc");
    const res = await app.fetch(new Request("http://localhost/"));
    expect(res.status).toBe(401);
  });

  it("returns 401 for wrong bearer token", async () => {
    const app = buildApp("key-abc");
    const res = await app.fetch(
      new Request("http://localhost/", {
        headers: { Authorization: "Bearer wrong-key" },
      })
    );
    expect(res.status).toBe(401);
  });

  it("returns 200 for valid bearer token", async () => {
    const app = buildApp("key-abc,key-xyz");
    const res = await app.fetch(
      new Request("http://localhost/", {
        headers: { Authorization: "Bearer key-abc" },
      })
    );
    expect(res.status).toBe(200);
  });

  it("accepts any key in a comma-separated list", async () => {
    const app = buildApp("  key-1 , key-2 , key-3  ");
    const res = await app.fetch(
      new Request("http://localhost/", {
        headers: { Authorization: "Bearer key-3" },
      })
    );
    expect(res.status).toBe(200);
  });

  it("returns 401 when Authorization is not Bearer", async () => {
    const app = buildApp("key-abc");
    const res = await app.fetch(
      new Request("http://localhost/", {
        headers: { Authorization: "Basic key-abc" },
      })
    );
    expect(res.status).toBe(401);
  });
});
