import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { CfBrowserApi } from "../lib/cf-api.js";
import { validateUrl } from "../lib/validate-url.js";
import { mapToCfParams } from "../lib/param-map.js";
import { normalizeLinksResponse } from "../lib/response-normalizers.js";
import { getCached, setCached, buildCacheKey } from "../middleware/cache.js";

const TTL = 60 * 60; // 1 hour

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
  const cacheKey = await buildCacheKey("links", body);

  if (!noCache) {
    const cached = await getCached(c, cacheKey, "kv");
    if (cached.hit) {
      c.header("X-Cache", "HIT");
      c.header("Content-Type", "application/json");
      return c.body(cached.data as string);
    }
  }

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const { no_cache: _skip, include_external, visible_only, ...cfBody } = body;
  if (include_external !== undefined) {
    if (typeof include_external !== "boolean") {
      return c.json({ error: "include_external must be a boolean", status: 400 }, 400);
    }
    cfBody.excludeExternalLinks = !include_external;
  }
  if (visible_only !== undefined) {
    if (typeof visible_only !== "boolean") {
      return c.json({ error: "visible_only must be a boolean", status: 400 }, 400);
    }
    cfBody.visibleLinksOnly = visible_only;
  }
  const cfPayload = mapToCfParams(cfBody);
  const result = await api.links(cfPayload);

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }

  const normalized = normalizeLinksResponse(result.data);
  if (normalized === null) {
    return c.json({ error: "Cloudflare returned malformed links data", status: 502 }, 502);
  }

  if (!noCache) {
    await setCached(
      c,
      cacheKey,
      JSON.stringify(normalized),
      "application/json",
      TTL,
      "kv"
    );
  }

  c.header("X-Cache", "MISS");
  return c.json(normalized);
});

export default app;
