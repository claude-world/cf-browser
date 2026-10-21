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

  const noCache = body.no_cache === true;
  const cacheKey = await buildCacheKey("pdf", body);

  if (!noCache) {
    const cached = await getCached(c, cacheKey, "r2");
    if (cached.hit) {
      c.header("X-Cache", "HIT");
      c.header("Content-Type", cached.contentType);
      return c.body(cached.data as ArrayBuffer);
    }
  }

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const { no_cache: _skip, format, landscape, ...cfBody } = body;

  const allowedFormats = new Set([
    "letter", "legal", "tabloid", "ledger", "a0", "a1", "a2", "a3", "a4", "a5", "a6",
  ]);
  if (format !== undefined && (typeof format !== "string" || !allowedFormats.has(format.toLowerCase()))) {
    return c.json({ error: "Unsupported PDF format", status: 400 }, 400);
  }
  if (landscape !== undefined && typeof landscape !== "boolean") {
    return c.json({ error: "landscape must be a boolean", status: 400 }, 400);
  }
  if (
    cfBody.pdfOptions !== undefined &&
    (typeof cfBody.pdfOptions !== "object" ||
      cfBody.pdfOptions === null ||
      Array.isArray(cfBody.pdfOptions))
  ) {
    return c.json({ error: "pdfOptions must be an object", status: 400 }, 400);
  }

  const existingPdfOptions =
    cfBody.pdfOptions && typeof cfBody.pdfOptions === "object" && !Array.isArray(cfBody.pdfOptions)
      ? cfBody.pdfOptions as Record<string, unknown>
      : {};
  if (existingPdfOptions.format !== undefined && (
    typeof existingPdfOptions.format !== "string" ||
    !allowedFormats.has(existingPdfOptions.format.toLowerCase())
  )) {
    return c.json({ error: "Unsupported pdfOptions.format", status: 400 }, 400);
  }
  if (existingPdfOptions.landscape !== undefined && typeof existingPdfOptions.landscape !== "boolean") {
    return c.json({ error: "pdfOptions.landscape must be a boolean", status: 400 }, 400);
  }
  if (format !== undefined || landscape !== undefined) {
    cfBody.pdfOptions = {
      ...existingPdfOptions,
      ...(format !== undefined ? { format: format.toLowerCase() } : {}),
      ...(landscape !== undefined ? { landscape } : {}),
    };
  }
  const cfPayload = mapToCfParams(cfBody);

  const result = await api.pdf(cfPayload);

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
