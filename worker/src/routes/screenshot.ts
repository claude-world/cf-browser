import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { CfBrowserApi } from "../lib/cf-api.js";
import { validateUrl } from "../lib/validate-url.js";
import { getCached, setCached, buildCacheKey } from "../middleware/cache.js";

const TTL = 60 * 60 * 24; // 24 hours

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
  const cacheKey = await buildCacheKey("screenshot", body);

  if (!noCache) {
    const cached = await getCached(c, cacheKey, "r2");
    if (cached.hit) {
      c.header("X-Cache", "HIT");
      c.header("Content-Type", cached.contentType);
      return c.body(cached.data as ArrayBuffer);
    }
  }

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const { no_cache: _skip, width, height, full_page, ...cfBody } = body;

  // Map user-friendly params → CF API nested format
  if (width || height) {
    cfBody.viewport = {
      width: (width as number) ?? 1920,
      height: (height as number) ?? 1080,
    };
  }
  if (full_page) {
    cfBody.screenshotOptions = { fullPage: true };
  }

  const result = await api.screenshot(cfBody);

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }

  if (!noCache) {
    await setCached(c, cacheKey, result.data, result.contentType, TTL, "r2");
  }

  c.header("X-Cache", "MISS");
  c.header("Content-Type", result.contentType);
  return c.body(result.data);
});

export default app;
