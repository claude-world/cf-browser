import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { CfBrowserApi } from "../lib/cf-api.js";
import { validateUrl } from "../lib/validate-url.js";
import { mapToCfParams } from "../lib/param-map.js";
import { getCached, setCached, buildCacheKey } from "../middleware/cache.js";

const TTL = 60 * 5; // 5 minutes — a11y trees reflect live DOM state

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
  const cacheKey = await buildCacheKey("a11y", body);

  if (!noCache) {
    const cached = await getCached(c, cacheKey, "kv");
    if (cached.hit) {
      c.header("X-Cache", "HIT");
      c.header("Content-Type", "application/json");
      return c.body(cached.data as string);
    }
  }

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const { no_cache: _skip, ...cfBody } = body;
  const cfPayload = mapToCfParams(cfBody);

  // Use the /snapshot endpoint which returns structured DOM data
  const result = await api.snapshot(cfPayload);

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }

  // Extract a structured accessibility-oriented view from the snapshot
  const snapshot = result.data as Record<string, unknown>;
  const a11yData = extractA11yData(snapshot);

  if (!noCache) {
    await setCached(
      c,
      cacheKey,
      JSON.stringify(a11yData),
      "application/json",
      TTL,
      "kv"
    );
  }

  c.header("X-Cache", "MISS");
  return c.json(a11yData);
});

/**
 * Extract accessibility-relevant data from a CF snapshot response.
 *
 * The CF Browser Rendering /snapshot endpoint returns page data including
 * the rendered DOM. We wrap it with metadata indicating this is an
 * accessibility-oriented extraction, stripping binary data (screenshots)
 * to reduce token cost for LLM consumers.
 */
function extractA11yData(snapshot: Record<string, unknown>): Record<string, unknown> {
  // Remove the base64 screenshot to cut token cost — the main value
  // of the a11y endpoint is structured text without binary bloat.
  const { screenshot: _screenshot, ...textData } = snapshot;

  return {
    type: "accessibility_snapshot",
    ...textData,
  };
}

export default app;
