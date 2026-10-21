import { Hono } from "hono";
import type { Context } from "hono";
import type { AppEnv } from "../types.js";
import { CfBrowserApi } from "../lib/cf-api.js";
import { validateUrl } from "../lib/validate-url.js";
import { mapToCfParams } from "../lib/param-map.js";
import { hashApiKey } from "../middleware/rate-limit.js";

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
const OWNER_KEY_PREFIX = "crawl-owner:";
const FALLBACK_OWNER_KEY_PREFIX = "crawl-owner-fallback:";
const KV_TOMBSTONE_KEY_PREFIX = "crawl-tombstone:";
const R2_TOMBSTONE_KEY_PREFIX = "crawl-tombstone:";
const RETENTION_MS = 7 * 24 * 60 * 60 * 1_000;
const RETENTION_SECONDS = RETENTION_MS / 1_000;
// UUID format check for job IDs (CF API returns UUIDs)
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_CRAWL_PAGES = 100_000;
const MAX_CACHE_AGE = 604_800;
const TERMINAL_CRAWL_STATUSES = new Set(["complete", "completed", "done"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyStringArray(value: unknown, allowed?: Set<string>): value is string[] {
  return Array.isArray(value) && value.length > 0 && value.every((item) =>
    typeof item === "string" && item.trim().length > 0 && (!allowed || allowed.has(item))
  );
}

function normalizeCrawlStatus(
  jobId: string,
  data: unknown,
): { ok: true; data: Record<string, unknown> } | { ok: false } {
  if (!isRecord(data)) return { ok: false };
  if (
    typeof data.status !== "string" || data.status.trim().length === 0 ||
    data.status.length > 128
  ) return { ok: false };
  const terminal = TERMINAL_CRAWL_STATUSES.has(data.status);
  if (data.id !== undefined && (typeof data.id !== "string" || data.id !== jobId)) {
    return { ok: false };
  }
  if (
    data.records !== undefined &&
    (!Array.isArray(data.records) || !data.records.every((record) => isRecord(record)))
  ) return { ok: false };
  if (terminal && (data.id !== jobId || !Array.isArray(data.records))) return { ok: false };
  if (data.browserSecondsUsed !== undefined && (
    typeof data.browserSecondsUsed !== "number" || !Number.isFinite(data.browserSecondsUsed) ||
    data.browserSecondsUsed < 0
  )) return { ok: false };
  for (const field of ["finished", "skipped", "total"] as const) {
    const value = data[field];
    if (value !== undefined && (
      typeof value !== "number" || !Number.isSafeInteger(value) || value < 0
    )) return { ok: false };
  }
  const cursor = data.cursor;
  const validCursor =
    cursor === undefined || cursor === null || cursor === "" ||
    typeof cursor === "string" && cursor.length <= 2_048 && !/[\r\n]/.test(cursor) ||
    typeof cursor === "number" && Number.isSafeInteger(cursor) && cursor >= 0;
  if (!validCursor) return { ok: false };
  return {
    ok: true,
    data: {
      ...data,
      job_id: jobId,
      status: data.status,
    },
  };
}

function isConfirmedCancellation(jobId: string, data: unknown): boolean {
  return isRecord(data) && data.job_id === jobId &&
    typeof data.message === "string" && data.message.trim().length > 0 &&
    data.message.length <= 2_000;
}

function normalizeCrawlBody(
  input: Record<string, unknown>,
): { ok: true; body: Record<string, unknown>; cacheTTL?: number } | { ok: false; error: string } {
  const {
    no_cache: noCache,
    cache_ttl: snakeCacheTtl,
    cacheTTL: camelCacheTtl,
    ...raw
  } = input;
  if (noCache !== undefined && typeof noCache !== "boolean") {
    return { ok: false, error: "no_cache must be a boolean" };
  }
  if (snakeCacheTtl !== undefined && camelCacheTtl !== undefined) {
    return { ok: false, error: "Use either cache_ttl or cacheTTL, not both" };
  }
  const explicitCacheTtl = snakeCacheTtl ?? camelCacheTtl;
  if (explicitCacheTtl !== undefined && (
    typeof explicitCacheTtl !== "number" || !Number.isSafeInteger(explicitCacheTtl) ||
    explicitCacheTtl < 0 || explicitCacheTtl > 86_400
  )) {
    return { ok: false, error: "cache_ttl must be an integer between 0 and 86400" };
  }
  if (noCache === true && explicitCacheTtl !== undefined && explicitCacheTtl !== 0) {
    return { ok: false, error: "no_cache=true conflicts with a non-zero cache_ttl" };
  }
  const cacheTTL = noCache === true ? 0 : explicitCacheTtl as number | undefined;
  const out = mapToCfParams(raw);

  const alias = (snake: string, camel: string): string | null => {
    if (out[snake] === undefined) return null;
    if (out[camel] !== undefined) return `Use either ${snake} or ${camel}, not both`;
    out[camel] = out[snake];
    delete out[snake];
    return null;
  };
  for (const [snake, camel] of [
    ["crawl_purposes", "crawlPurposes"],
    ["max_age", "maxAge"],
    ["modified_since", "modifiedSince"],
    ["json_options", "jsonOptions"],
    ["reject_request_patterns", "rejectRequestPattern"],
    ["allow_request_patterns", "allowRequestPattern"],
    ["allow_resource_types", "allowResourceTypes"],
    ["javascript_enabled", "setJavaScriptEnabled"],
    ["action_timeout", "actionTimeout"],
    ["wait_for_timeout", "waitForTimeout"],
    ["best_attempt", "bestAttempt"],
    ["emulate_media_type", "emulateMediaType"],
  ] as const) {
    const error = alias(snake, camel);
    if (error) return { ok: false, error };
  }

  const maxPages = out.max_pages;
  delete out.max_pages;
  if (maxPages !== undefined && out.limit !== undefined) {
    return { ok: false, error: "Use either max_pages or limit, not both" };
  }
  if (maxPages !== undefined && (
    typeof maxPages !== "number" || !Number.isSafeInteger(maxPages) || maxPages < 1 ||
    maxPages > MAX_CRAWL_PAGES
  )) {
    return { ok: false, error: "max_pages must be an integer between 1 and 100000" };
  }
  if (maxPages !== undefined && out.limit === undefined) out.limit = maxPages;
  if (out.render === undefined) out.render = true;
  if (out.source === undefined) out.source = "all";

  if (!isRecord(out.options) && out.options !== undefined) {
    return { ok: false, error: "options must be an object" };
  }
  const options: Record<string, unknown> = { ...(isRecord(out.options) ? out.options : {}) };
  for (const [snake, camel] of [
    ["include_external", "includeExternalLinks"],
    ["include_subdomains", "includeSubdomains"],
    ["include_patterns", "includePatterns"],
    ["exclude_patterns", "excludePatterns"],
  ] as const) {
    if (out[snake] === undefined) continue;
    if (options[camel] !== undefined) {
      return { ok: false, error: `Use either ${snake} or options.${camel}, not both` };
    }
    options[camel] = out[snake];
    delete out[snake];
  }
  if (options.includeExternalLinks === undefined) options.includeExternalLinks = false;
  if (options.includeSubdomains === undefined) options.includeSubdomains = false;
  for (const field of ["includeExternalLinks", "includeSubdomains"]) {
    if (typeof options[field] !== "boolean") {
      return { ok: false, error: `options.${field} must be a boolean` };
    }
  }
  for (const field of ["includePatterns", "excludePatterns"]) {
    if (options[field] !== undefined && !isNonEmptyStringArray(options[field])) {
      return { ok: false, error: `options.${field} must be a non-empty array of strings` };
    }
  }
  out.options = options;

  for (const field of ["limit", "depth"]) {
    const value = out[field];
    if (value !== undefined && (
      typeof value !== "number" || !Number.isSafeInteger(value) || value < 1 ||
      value > MAX_CRAWL_PAGES
    )) {
      return { ok: false, error: `${field} must be an integer between 1 and 100000` };
    }
  }
  if (typeof out.render !== "boolean") return { ok: false, error: "render must be a boolean" };
  if (typeof out.source !== "string" || !["all", "links", "sitemaps"].includes(out.source)) {
    return { ok: false, error: "source must be all, links, or sitemaps" };
  }
  const formats = out.formats;
  if (formats !== undefined && !isNonEmptyStringArray(
    formats, new Set(["html", "markdown", "json"]),
  )) {
    return { ok: false, error: "formats must be a non-empty array of html, markdown, or json" };
  }
  const purposes = out.crawlPurposes;
  if (purposes !== undefined && !isNonEmptyStringArray(
    purposes, new Set(["search", "ai-input", "ai-train"]),
  )) {
    return { ok: false, error: "crawl_purposes must contain search, ai-input, or ai-train" };
  }
  const maxAge = out.maxAge;
  if (maxAge !== undefined && (
    typeof maxAge !== "number" || !Number.isSafeInteger(maxAge) || maxAge < 0 ||
    maxAge > MAX_CACHE_AGE
  )) {
    return { ok: false, error: "max_age must be an integer between 0 and 604800" };
  }
  const modifiedSince = out.modifiedSince;
  const now = Math.floor(Date.now() / 1000);
  if (modifiedSince !== undefined && (
    typeof modifiedSince !== "number" || !Number.isSafeInteger(modifiedSince) ||
    modifiedSince < now - 365 * 24 * 60 * 60 || modifiedSince > now
  )) {
    return { ok: false, error: "modified_since must be a Unix timestamp within the past year" };
  }
  if (out.jsonOptions !== undefined && !isRecord(out.jsonOptions)) {
    return { ok: false, error: "json_options must be an object" };
  }
  if (Array.isArray(formats) && formats.includes("json") && out.jsonOptions === undefined) {
    return { ok: false, error: "json_options is required when formats includes json" };
  }
  if (out.jsonOptions !== undefined && (!Array.isArray(formats) || !formats.includes("json"))) {
    return { ok: false, error: "json_options requires formats to include json" };
  }

  for (const field of ["rejectRequestPattern", "allowRequestPattern", "allowResourceTypes"]) {
    if (out[field] !== undefined && !isNonEmptyStringArray(out[field])) {
      return { ok: false, error: `${field} must be a non-empty array of strings` };
    }
  }
  for (const field of ["setJavaScriptEnabled", "bestAttempt"]) {
    if (out[field] !== undefined && typeof out[field] !== "boolean") {
      return { ok: false, error: `${field} must be a boolean` };
    }
  }
  for (const field of ["actionTimeout", "waitForTimeout"]) {
    const value = out[field];
    if (value !== undefined && (
      typeof value !== "number" || !Number.isSafeInteger(value) || value < 1 || value > 120_000
    )) {
      return { ok: false, error: `${field} must be an integer between 1 and 120000` };
    }
  }
  if (out.emulateMediaType !== undefined && (
    typeof out.emulateMediaType !== "string" || out.emulateMediaType.trim().length === 0
  )) {
    return { ok: false, error: "emulateMediaType must be a non-empty string" };
  }
  if (out.viewport !== undefined && !isRecord(out.viewport)) {
    return { ok: false, error: "viewport must be an object" };
  }

  if (out.userAgent !== undefined) {
    return { ok: false, error: "user_agent is not supported by the crawl endpoint" };
  }
  if (out.render === false) {
    const renderedOnlyOptions = [
      "cookies", "setExtraHTTPHeaders", "authenticate", "waitForSelector", "gotoOptions",
      "addScriptTag", "addStyleTag", "rejectResourceTypes", "rejectRequestPattern",
      "allowRequestPattern", "allowResourceTypes", "setJavaScriptEnabled", "actionTimeout",
      "waitForTimeout", "bestAttempt", "emulateMediaType", "viewport",
    ];
    if (renderedOnlyOptions.some((field) => out[field] !== undefined)) {
      return { ok: false, error: "Browser options require render=true for crawl requests" };
    }
  }
  return {
    ok: true,
    body: out,
    ...(cacheTTL !== undefined ? { cacheTTL } : {}),
  };
}

async function recordOwner(c: Context<AppEnv>, jobId: string) {
  const apiKey = c.get("apiKey") as string;
  await c.env.STORAGE.put(`${OWNER_KEY_PREFIX}${jobId}`, await hashApiKey(apiKey), {
    httpMetadata: { contentType: "text/plain" },
    customMetadata: { created_at: String(Date.now()) },
  });
}

async function recordFallbackOwner(c: Context<AppEnv>, jobId: string) {
  const apiKey = c.get("apiKey") as string;
  await c.env.CACHE.put(`${FALLBACK_OWNER_KEY_PREFIX}${jobId}`, await hashApiKey(apiKey), {
    expirationTtl: RETENTION_SECONDS,
    metadata: { created_at: Date.now() },
  });
}

async function fallbackOwnsJob(c: Context<AppEnv>, jobId: string, expectedOwner: string) {
  try {
    return await c.env.CACHE.get(`${FALLBACK_OWNER_KEY_PREFIX}${jobId}`) === expectedOwner;
  } catch (error) {
    console.warn("Crawl fallback ownership read failed", error);
    return false;
  }
}

type LocalCleanupResult = {
  complete: boolean;
  durableDenial: boolean;
  failures: unknown[];
};

async function deleteLocalCrawlState(
  c: Context<AppEnv>,
  jobId: string,
): Promise<LocalCleanupResult> {
  const results = await Promise.allSettled([
    c.env.STORAGE.delete(`${R2_KEY_PREFIX}${jobId}`),
    c.env.STORAGE.delete(`${OWNER_KEY_PREFIX}${jobId}`),
    c.env.CACHE.delete(`${FALLBACK_OWNER_KEY_PREFIX}${jobId}`),
  ]);
  const succeeded = results.map((result) => result.status === "fulfilled");
  return {
    complete: succeeded.every(Boolean),
    durableDenial: succeeded[1] === true && succeeded[2] === true,
    failures: results.flatMap((result) => result.status === "rejected" ? [result.reason] : []),
  };
}

type TombstoneState = "present" | "absent" | "unknown";

async function crawlTombstoneState(c: Context<AppEnv>, jobId: string): Promise<TombstoneState> {
  const [kv, r2] = await Promise.allSettled([
    c.env.CACHE.get(`${KV_TOMBSTONE_KEY_PREFIX}${jobId}`),
    c.env.STORAGE.get(`${R2_TOMBSTONE_KEY_PREFIX}${jobId}`),
  ]);
  if (
    kv.status === "fulfilled" && kv.value !== null ||
    r2.status === "fulfilled" && r2.value !== null
  ) return "present";
  if (kv.status === "rejected" || r2.status === "rejected") return "unknown";
  return "absent";
}

async function establishDeletionTombstone(c: Context<AppEnv>, jobId: string): Promise<boolean> {
  const createdAt = String(Date.now());
  const results = await Promise.allSettled([
    c.env.CACHE.put(`${KV_TOMBSTONE_KEY_PREFIX}${jobId}`, "deleted", {
      expirationTtl: RETENTION_SECONDS,
      metadata: { created_at: Number(createdAt) },
    }),
    c.env.STORAGE.put(`${R2_TOMBSTONE_KEY_PREFIX}${jobId}`, "deleted", {
      httpMetadata: { contentType: "text/plain" },
      customMetadata: { created_at: createdAt },
    }),
  ]);
  return results.some((result) => result.status === "fulfilled");
}

function scheduleLocalCleanupRetry(c: Context<AppEnv>, jobId: string): void {
  try {
    c.executionCtx.waitUntil((async () => {
      const retry = await deleteLocalCrawlState(c, jobId);
      if (!retry.complete && !retry.durableDenial) {
        console.warn("Crawl local deletion retry remained incomplete", {
          jobId,
          failures: retry.failures,
        });
      }
    })());
  } catch {
    // Unit tests and some non-Worker adapters do not provide an ExecutionContext.
  }
}

async function ownsJob(c: Context<AppEnv>, jobId: string) {
  const expectedOwner = await hashApiKey(c.get("apiKey") as string);
  let owner: R2ObjectBody | null;
  try {
    owner = await c.env.STORAGE.get(`${OWNER_KEY_PREFIX}${jobId}`);
  } catch (error) {
    console.warn("Crawl primary ownership read failed; checking fallback", error);
    return fallbackOwnsJob(c, jobId, expectedOwner);
  }
  if (owner === null) {
    return fallbackOwnsJob(c, jobId, expectedOwner);
  }
  const createdAt = Number(owner.customMetadata?.created_at);
  if (!Number.isFinite(createdAt) || Date.now() >= createdAt + RETENTION_MS) {
    await deleteLocalCrawlState(c, jobId);
    return false;
  }
  return (await owner.text()) === expectedOwner;
}

async function rejectNonOwner(c: Context<AppEnv>, jobId: string) {
  const tombstone = await crawlTombstoneState(c, jobId);
  if (tombstone === "present") {
    return c.json({ error: "Crawl job not found", status: 404 }, 404);
  }
  if (tombstone === "unknown") {
    return c.json({ error: "Unable to verify crawl deletion state", status: 503 }, 503);
  }
  if (await ownsJob(c, jobId)) return null;
  return c.json({ error: "Crawl job not found", status: 404 }, 404);
}

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

  const normalized = normalizeCrawlBody(body);
  if (!normalized.ok) return c.json({ error: normalized.error, status: 400 }, 400);

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const result = await api.crawl(
    normalized.body,
    normalized.cacheTTL === undefined ? {} : { cacheTTL: normalized.cacheTTL },
  );

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }

  // After cf-api unwrap, result.data is either the UUID string directly,
  // or an object with id/job_id
  const data = result.data;
  const jobId = typeof data === "string"
    ? data
    : data !== null && typeof data === "object" && !Array.isArray(data)
      ? (data as Record<string, unknown>).id ?? (data as Record<string, unknown>).job_id
      : undefined;
  if (typeof jobId !== "string" || !UUID_RE.test(jobId)) {
    return c.json({ error: "Cloudflare crawl response missing job ID", status: 502 }, 502);
  }
  try {
    await recordOwner(c, jobId);
  } catch (error) {
    const cancelled = await api.deleteCrawl(jobId);
    const cancellationConfirmed = cancelled.ok && isConfirmedCancellation(jobId, cancelled.data);
    console.warn("Crawl owner write failed; attempted upstream cancellation", {
      error,
      cancelled: cancellationConfirmed,
    });
    if (!cancellationConfirmed) {
      try {
        await recordFallbackOwner(c, jobId);
        console.warn("Crawl cancellation failed; ownership retained in KV fallback", { jobId });
        return c.json({ job_id: jobId, status: "started" }, 202);
      } catch (fallbackError) {
        console.warn("Crawl fallback ownership write failed", { jobId, fallbackError });
        return c.json({
          error: "Unable to persist crawl ownership or cancel the upstream job",
          job_id: jobId,
          status: 503,
        }, 503);
      }
    }
    return c.json({ error: "Unable to persist crawl ownership", status: 503 }, 503);
  }
  return c.json({ job_id: jobId, status: "started" }, 202);
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

  const ownerError = await rejectNonOwner(c, jobId);
  if (ownerError) return ownerError;

  const r2Key = `${R2_KEY_PREFIX}${jobId}`;
  const cursorRaw = c.req.query("cursor");
  const limitRaw = c.req.query("limit");
  const statusRaw = c.req.query("status");
  const recordStatuses = new Set([
    "queued", "errored", "completed", "disallowed", "skipped", "cancelled",
  ]);
  const cursor = cursorRaw;
  const limit = limitRaw === undefined ? undefined : Number(limitRaw);

  if (cursor !== undefined && (cursor.length === 0 || cursor.length > 2_048 || /[\r\n]/.test(cursor))) {
    return c.json({ error: "cursor must be a valid opaque cursor", status: 400 }, 400);
  }
  if (limit !== undefined && (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_CRAWL_PAGES)) {
    return c.json({ error: "limit must be an integer between 1 and 100000", status: 400 }, 400);
  }
  if (statusRaw !== undefined && !recordStatuses.has(statusRaw)) {
    return c.json({ error: "Invalid crawl record status", status: 400 }, 400);
  }
  const hasQuery = cursor !== undefined || limit !== undefined || statusRaw !== undefined;

  // Check R2 for a completed result first
  if (!hasQuery) {
    try {
      const stored = await c.env.STORAGE.get(r2Key);
      if (stored !== null) {
        const completedAt = Number(stored.customMetadata?.completed_at);
        if (!Number.isFinite(completedAt) || Date.now() >= completedAt + RETENTION_MS) {
          await c.env.STORAGE.delete(r2Key);
        } else {
          const cached = normalizeCrawlStatus(jobId, await stored.json());
          if (cached.ok) {
            c.header("X-Cache", "HIT");
            return c.json(cached.data);
          }
          await c.env.STORAGE.delete(r2Key);
        }
      }
    } catch (error) {
      console.warn("Crawl result cache read failed; polling upstream", error);
    }
  }

  // Not in R2 — poll CF API
  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const result = await api.getCrawlStatus(jobId, {
    ...(cursor !== undefined ? { cursor } : {}),
    ...(limit !== undefined ? { limit } : {}),
    ...(statusRaw !== undefined ? {
      status: statusRaw as "queued" | "errored" | "completed" | "disallowed" | "skipped" | "cancelled",
    } : {}),
  });

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }

  // After cf-api unwrap, result.data is the inner status object directly
  const normalizedStatus = normalizeCrawlStatus(jobId, result.data);
  if (!normalizedStatus.ok) {
    return c.json({ error: "Cloudflare crawl status response was malformed", status: 502 }, 502);
  }
  const statusData = normalizedStatus.data;

  // If crawl is complete, persist to R2 so future polls are served from cache
  const responseCursor = statusData.cursor;
  const hasMore =
    typeof responseCursor === "string" && responseCursor.length > 0 ||
    typeof responseCursor === "number";
  if (!hasQuery && !hasMore && ["complete", "completed", "done"].includes(String(statusData.status))) {
    try {
      await c.env.STORAGE.put(r2Key, JSON.stringify(statusData), {
        httpMetadata: { contentType: "application/json" },
        customMetadata: { completed_at: String(Date.now()) },
      });
    } catch (error) {
      console.warn("Crawl result cache write failed; returning upstream status", error);
    }
  }

  c.header("X-Cache", hasQuery ? "BYPASS" : "MISS");
  return c.json(statusData);
});

// DELETE /crawl/:id — cancel the upstream job and remove local state
app.delete("/:id", async (c) => {
  const jobId = c.req.param("id");
  if (!jobId) {
    return c.json({ error: "Missing job ID", status: 400 }, 400);
  }

  if (!UUID_RE.test(jobId)) {
    return c.json({ error: "Invalid job ID format", status: 400 }, 400);
  }

  const ownerError = await rejectNonOwner(c, jobId);
  if (ownerError) return ownerError;

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const result = await api.deleteCrawl(jobId);
  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }
  if (!isConfirmedCancellation(jobId, result.data)) {
    return c.json({ error: "Cloudflare crawl cancellation response was malformed", status: 502 }, 502);
  }

  const tombstoneEstablished = await establishDeletionTombstone(c, jobId);
  const cleanup = await deleteLocalCrawlState(c, jobId);
  if (!cleanup.complete) {
    console.warn("Crawl local deletion was incomplete", {
      jobId,
      tombstoneEstablished,
      failures: cleanup.failures,
    });
    scheduleLocalCleanupRetry(c, jobId);
  }
  if (cleanup.complete || cleanup.durableDenial || tombstoneEstablished) {
    return c.body(null, 204);
  }
  return c.json({ error: "Unable to durably remove local crawl state", status: 503 }, 503);
});

export default app;
