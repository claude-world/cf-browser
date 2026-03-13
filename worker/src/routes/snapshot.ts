import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { CfBrowserApi } from "../lib/cf-api.js";
import { validateUrl } from "../lib/validate-url.js";
import { getCached, setCached, buildCacheKey } from "../middleware/cache.js";

const TTL = 60 * 30; // 30 minutes

const app = new Hono<AppEnv>();

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
    const cached = await getCached(c, cacheKey, "kv");
    if (cached.hit) {
      c.header("X-Cache", "HIT");
      // Stored as JSON string — parse and re-emit
      return c.json(JSON.parse(cached.data as string));
    }
  }

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const { no_cache: _skip, ...cfBody } = body;
  const result = await api.snapshot(cfBody);

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }

  if (!noCache) {
    await setCached(
      c,
      cacheKey,
      JSON.stringify(result.data),
      "application/json",
      TTL,
      "kv"
    );
  }

  c.header("X-Cache", "MISS");
  return c.json(result.data);
});

export default app;
