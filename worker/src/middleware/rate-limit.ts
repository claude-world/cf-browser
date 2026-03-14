import type { Context, Next } from "hono";
import type { AppEnv } from "../types.js";

const REQUESTS_PER_MINUTE = 60;

/**
 * Hash the API key to a short hex string for use as a KV bucket identifier.
 * Avoids leaking partial key material into KV key names.
 */
async function hashKey(apiKey: string): Promise<string> {
  const data = new TextEncoder().encode(apiKey);
  const hash = await crypto.subtle.digest("SHA-256", data);
  const bytes = new Uint8Array(hash);
  return Array.from(bytes.slice(0, 8))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * KV-based per-key rate limiter.
 *
 * Key format: `rl:{hashed_key}:{minute_bucket}`
 * - hashed_key: SHA-256 prefix of the API key (no raw key material in KV)
 * - minute_bucket: floor(Date.now() / 60000)
 *
 * Note: KV read-then-write has a TOCTOU race under concurrency, so limits
 * may be exceeded by a small margin. This is a known KV limitation.
 *
 * Returns 429 with Retry-After header when limit is exceeded.
 */
export async function rateLimitMiddleware(
  c: Context<AppEnv>,
  next: Next
): Promise<Response | void> {
  // apiKey is set by authMiddleware
  const apiKey: string = (c.get("apiKey") as string | undefined) ?? "anonymous";
  const keyHash = await hashKey(apiKey);
  const now = Date.now();
  const minuteBucket = Math.floor(now / 60_000);
  const kvKey = `rl:${keyHash}:${minuteBucket}`;

  // Read current count
  const current = await c.env.RATE_LIMIT.get(kvKey);
  const count = current ? parseInt(current, 10) : 0;

  if (count >= REQUESTS_PER_MINUTE) {
    // Tell client how many seconds until the bucket resets
    const secondsUntilReset = 60 - (Math.floor(now / 1_000) % 60);
    c.header("Retry-After", String(secondsUntilReset));
    c.header("X-RateLimit-Limit", String(REQUESTS_PER_MINUTE));
    c.header("X-RateLimit-Remaining", "0");
    return c.json({ error: "Rate limit exceeded", status: 429 }, 429);
  }

  // Increment counter; TTL of 120s ensures cleanup even if the bucket rolls over
  await c.env.RATE_LIMIT.put(kvKey, String(count + 1), { expirationTtl: 120 });

  c.header("X-RateLimit-Limit", String(REQUESTS_PER_MINUTE));
  c.header("X-RateLimit-Remaining", String(REQUESTS_PER_MINUTE - count - 1));

  await next();
}
