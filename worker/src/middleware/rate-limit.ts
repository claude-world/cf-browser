import type { Context, Next } from "hono";
import type { AppEnv } from "../types.js";

const REQUESTS_PER_MINUTE = 60;

/** Hash an API key before it is used in infrastructure identifiers or metadata. */
export async function hashApiKey(apiKey: string): Promise<string> {
  const data = new TextEncoder().encode(apiKey);
  const hash = await crypto.subtle.digest("SHA-256", data);
  const bytes = new Uint8Array(hash);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Per-key limiter backed by Cloudflare's native Rate Limiting binding.
 * Counters are intentionally keyed by a digest so raw API keys never leave
 * request memory. Cloudflare applies the configured 60 request / 60 second
 * policy and returns only an allow/deny outcome.
 */
export async function rateLimitMiddleware(
  c: Context<AppEnv>,
  next: Next
): Promise<Response | void> {
  // apiKey is set by authMiddleware
  const apiKey: string = (c.get("apiKey") as string | undefined) ?? "anonymous";
  const keyHash = await hashApiKey(apiKey);
  const { success } = await c.env.RATE_LIMITER.limit({ key: keyHash });

  if (!success) {
    c.header("Retry-After", "60");
    c.header("X-RateLimit-Limit", String(REQUESTS_PER_MINUTE));
    c.header("X-RateLimit-Remaining", "0");
    return c.json({ error: "Rate limit exceeded", status: 429 }, 429);
  }

  c.header("X-RateLimit-Limit", String(REQUESTS_PER_MINUTE));

  await next();
}
