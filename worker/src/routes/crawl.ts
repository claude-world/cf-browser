import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { CfBrowserApi } from "../lib/cf-api.js";
import { validateUrl } from "../lib/validate-url.js";
import { mapToCfParams } from "../lib/param-map.js";

/**
 * Crawl routes:
 *   POST /crawl          — start a new crawl job, returns job ID
 *   GET  /crawl/:id      — poll status / retrieve completed results
 *
 * Completed results are stored in R2 under key `crawl:{jobId}` so subsequent
 * polls for a finished job don't hit the CF API again.
 */
const app = new Hono<AppEnv>();

const R2_KEY_PREFIX = "crawl:";
// UUID format check for job IDs (CF API returns UUIDs)
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// POST /crawl — start crawl job
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

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const { no_cache: _skip, max_pages, ...cfBody } = body;
  // Map user-friendly max_pages to CF API's limit param
  if (max_pages && !cfBody.limit) {
    cfBody.limit = max_pages;
  }
  const cfPayload = mapToCfParams(cfBody);
  const result = await api.crawl(cfPayload);

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }

  // After cf-api unwrap, result.data is either the UUID string directly,
  // or an object with id/job_id
  const data = result.data;
  const jobId = typeof data === "string"
    ? data
    : (data as Record<string, unknown>).id ?? (data as Record<string, unknown>).job_id;
  return c.json({ job_id: jobId }, 202);
});

// GET /crawl/:id — poll or retrieve crawl results
app.get("/:id", async (c) => {
  const jobId = c.req.param("id");
  if (!jobId) {
    return c.json({ error: "Missing job ID", status: 400 }, 400);
  }

  if (!UUID_RE.test(jobId)) {
    return c.json({ error: "Invalid job ID format", status: 400 }, 400);
  }

  const r2Key = `${R2_KEY_PREFIX}${jobId}`;

  // Check R2 for a completed result first
  const stored = await c.env.STORAGE.get(r2Key);
  if (stored !== null) {
    const data = await stored.json();
    c.header("X-Cache", "HIT");
    return c.json(data);
  }

  // Not in R2 — poll CF API
  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const result = await api.getCrawlStatus(jobId);

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }

  // After cf-api unwrap, result.data is the inner status object directly
  const inner = result.data as Record<string, unknown>;
  const statusData = {
    job_id: inner.id ?? jobId,
    status: inner.status ?? "unknown",
    ...inner,
  };

  // If crawl is complete, persist to R2 so future polls are served from cache
  if (
    statusData.status === "complete" ||
    statusData.status === "completed" ||
    statusData.status === "done"
  ) {
    await c.env.STORAGE.put(r2Key, JSON.stringify(statusData), {
      httpMetadata: { contentType: "application/json" },
      customMetadata: { completed_at: String(Date.now()) },
    });
  }

  c.header("X-Cache", "MISS");
  return c.json(statusData);
});

// DELETE /crawl/:id — delete cached crawl result
app.delete("/:id", async (c) => {
  const jobId = c.req.param("id");
  if (!jobId) {
    return c.json({ error: "Missing job ID", status: 400 }, 400);
  }

  if (!UUID_RE.test(jobId)) {
    return c.json({ error: "Invalid job ID format", status: 400 }, 400);
  }

  const r2Key = `${R2_KEY_PREFIX}${jobId}`;
  await c.env.STORAGE.delete(r2Key);
  return c.body(null, 204);
});

export default app;
