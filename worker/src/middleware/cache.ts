import type { Context } from "hono";
import type { AppEnv, CacheMeta } from "../types.js";
import { generateCacheKey } from "../lib/cache-key.js";

export type CacheStorage = "kv" | "r2";

export type CachedItem =
  | { hit: true; data: string | ArrayBuffer; contentType: string }
  | { hit: false };

/**
 * Reads a cached response.
 * - Text/JSON entries are stored in KV.
 * - Binary entries (images, PDFs) are stored in R2.
 */
export async function getCached(
  c: Context<AppEnv>,
  cacheKey: string,
  storage: CacheStorage
): Promise<CachedItem> {
  if (storage === "kv") {
    const meta = await c.env.CACHE.getWithMetadata<CacheMeta>(cacheKey, "text");
    if (meta.value === null) return { hit: false };
    return {
      hit: true,
      data: meta.value,
      contentType: meta.metadata?.content_type ?? "text/plain",
    };
  }

  // R2
  const obj = await c.env.STORAGE.get(cacheKey);
  if (obj === null) return { hit: false };
  const buffer = await obj.arrayBuffer();
  const contentType =
    obj.httpMetadata?.contentType ?? "application/octet-stream";
  return { hit: true, data: buffer, contentType };
}

/**
 * Writes a response to the cache.
 */
export async function setCached(
  c: Context<AppEnv>,
  cacheKey: string,
  data: string | ArrayBuffer,
  contentType: string,
  ttlSeconds: number,
  storage: CacheStorage
): Promise<void> {
  if (storage === "kv") {
    if (typeof data !== "string") {
      throw new Error("KV storage requires string data; use R2 for binary");
    }
    const meta: CacheMeta = {
      content_type: contentType,
      cached_at: Date.now(),
      ttl: ttlSeconds,
    };
    await c.env.CACHE.put(cacheKey, data, {
      expirationTtl: ttlSeconds,
      metadata: meta,
    });
    return;
  }

  // R2
  await c.env.STORAGE.put(cacheKey, data as ArrayBuffer, {
    httpMetadata: { contentType },
    customMetadata: { cached_at: String(Date.now()), ttl: String(ttlSeconds) },
  });
}

/**
 * Builds a cache key from the current request body.
 * Strips `no_cache` from the options before hashing.
 */
export async function buildCacheKey(
  endpoint: string,
  body: Record<string, unknown>
): Promise<string> {
  const { url, no_cache: _skip, ...options } = body;
  return generateCacheKey(endpoint, String(url), options);
}
