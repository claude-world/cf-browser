import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { CfBrowserApi } from "../lib/cf-api.js";
import { validateUrl } from "../lib/validate-url.js";
import { mapToCfParams } from "../lib/param-map.js";
import { getCached, setCached, buildCacheKey } from "../middleware/cache.js";

const TTL = 60 * 30; // 30 minutes

const app = new Hono<AppEnv>();

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

app.post("/", async (c) => {
  let body: Record<string, unknown>;
  try {
    body = await c.req.json<Record<string, unknown>>();
  } catch {
    return c.json({ error: "Invalid JSON body", status: 400 }, 400);
  }

  if (!body.url || typeof body.url !== "string") {
    return c.json({ error: "Missing required field: url", status: 400 }, 400);
  }

  const urlCheck = validateUrl(body.url as string);
  if (!urlCheck.valid) {
    return c.json({ error: urlCheck.error, status: 400 }, 400);
  }

  const noCache = body.no_cache === true;
  const cacheKey = await buildCacheKey("snapshot", body);

  if (!noCache) {
    const cached = await getCached(c, cacheKey, "r2");
    if (cached.hit) {
      c.header("X-Cache", "HIT");
      c.header("Content-Type", "application/json");
      return c.body(cached.data as string);
    }
  }

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const { no_cache: _skip, ...cfBody } = body;
  const cfPayload = mapToCfParams(cfBody);
  const result = await api.snapshot(cfPayload);

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }
  if (!isRecord(result.data)) {
    return c.json({ error: "Cloudflare returned malformed snapshot data", status: 502 }, 502);
  }

  if (!noCache) {
    await setCached(
      c,
      cacheKey,
      JSON.stringify(result.data),
      "application/json",
      TTL,
      "r2"
    );
  }

  c.header("X-Cache", "MISS");
  return c.json(result.data);
});

export default app;
