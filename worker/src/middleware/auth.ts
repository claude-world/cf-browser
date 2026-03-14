import type { Context, Next } from "hono";
import type { AppEnv } from "../types.js";

/**
 * Constant-time string comparison to prevent timing side-channel attacks.
 * Uses Web Crypto API (available in Workers) to hash both values and compare.
 */
async function safeEqual(a: string, b: string): Promise<boolean> {
  // Always hash both inputs so the comparison is constant-time
  // regardless of input length (both digests are 32 bytes).
  const encoder = new TextEncoder();
  const [hashA, hashB] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(a)),
    crypto.subtle.digest("SHA-256", encoder.encode(b)),
  ]);
  const viewA = new Uint8Array(hashA);
  const viewB = new Uint8Array(hashB);
  let result = 0;
  for (let i = 0; i < viewA.length; i++) {
    result |= (viewA[i] ?? 0) ^ (viewB[i] ?? 0);
  }
  return result === 0;
}

/**
 * Auth middleware — validates `Authorization: Bearer <api-key>`.
 * Valid keys are stored in the API_KEYS env variable as a comma-separated list.
 * Uses timing-safe comparison to prevent key enumeration via latency.
 */
export async function authMiddleware(
  c: Context<AppEnv>,
  next: Next
): Promise<Response | void> {
  const authHeader = c.req.header("Authorization");

  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    return c.json({ error: "Missing or invalid Authorization header", status: 401 }, 401);
  }

  const token = authHeader.slice(7).trim();

  if (!token) {
    return c.json({ error: "API key is empty", status: 401 }, 401);
  }

  const validKeys = c.env.API_KEYS.split(",")
    .map((k) => k.trim())
    .filter(Boolean);

  let isValid = false;
  for (const k of validKeys) {
    if (await safeEqual(k, token)) {
      isValid = true;
      // do NOT break — must compare all keys to avoid positional timing leak
    }
  }

  if (!isValid) {
    return c.json({ error: "Invalid API key", status: 401 }, 401);
  }

  // Store full API key in context for rate-limiting (hashed there)
  c.set("apiKey", token);

  await next();
}
