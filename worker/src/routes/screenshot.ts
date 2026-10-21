import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { CfBrowserApi } from "../lib/cf-api.js";
import { validateUrl } from "../lib/validate-url.js";
import { mapToCfParams } from "../lib/param-map.js";
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

  if (body.width !== undefined && (
    typeof body.width !== "number" || !Number.isSafeInteger(body.width) ||
    body.width < 1 || body.width > 7680
  )) {
    return c.json({ error: "width must be an integer between 1 and 7680", status: 400 }, 400);
  }
  if (body.height !== undefined && (
    typeof body.height !== "number" || !Number.isSafeInteger(body.height) ||
    body.height < 1 || body.height > 4320
  )) {
    return c.json({ error: "height must be an integer between 1 and 4320", status: 400 }, 400);
  }
  if (body.full_page !== undefined && typeof body.full_page !== "boolean") {
    return c.json({ error: "full_page must be a boolean", status: 400 }, 400);
  }
  for (const option of ["viewport", "screenshotOptions"] as const) {
    if (
      body[option] !== undefined &&
      (typeof body[option] !== "object" || body[option] === null || Array.isArray(body[option]))
    ) {
      return c.json({ error: `${option} must be an object`, status: 400 }, 400);
    }
  }
  if (
    body.screenshotOptions &&
    typeof body.screenshotOptions === "object" &&
    (body.screenshotOptions as Record<string, unknown>).encoding !== undefined &&
    (body.screenshotOptions as Record<string, unknown>).encoding !== "binary"
  ) {
    return c.json({ error: "screenshotOptions.encoding must be binary", status: 400 }, 400);
  }
  if (
    body.screenshotOptions &&
    typeof body.screenshotOptions === "object" &&
    (body.screenshotOptions as Record<string, unknown>).fullPage !== undefined &&
    typeof (body.screenshotOptions as Record<string, unknown>).fullPage !== "boolean"
  ) {
    return c.json({ error: "screenshotOptions.fullPage must be a boolean", status: 400 }, 400);
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
      ...((cfBody.viewport as Record<string, unknown> | undefined) ?? {}),
      width: (width as number | undefined) ??
        (cfBody.viewport as Record<string, unknown> | undefined)?.width ?? 1920,
      height: (height as number | undefined) ??
        (cfBody.viewport as Record<string, unknown> | undefined)?.height ?? 1080,
    };
  }
  if (full_page !== undefined) {
    cfBody.screenshotOptions = {
      ...((cfBody.screenshotOptions as Record<string, unknown> | undefined) ?? {}),
      fullPage: full_page,
    };
  }

  const cfPayload = mapToCfParams(cfBody);
  const result = await api.screenshot(cfPayload);

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
