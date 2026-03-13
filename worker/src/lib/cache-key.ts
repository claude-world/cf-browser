/**
 * Generates a deterministic SHA-256 cache key for a given endpoint, URL, and options.
 * Options are sorted by key to ensure the same options in different orders
 * produce the same key.
 */
export async function generateCacheKey(
  endpoint: string,
  url: string,
  options: Record<string, unknown>
): Promise<string> {
  const sortedOptions = sortObjectKeys(options);
  const raw = `${endpoint}:${url}:${JSON.stringify(sortedOptions)}`;

  const encoder = new TextEncoder();
  const data = encoder.encode(raw);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");

  return hashHex;
}

/**
 * Recursively sorts an object's keys to produce a canonical representation.
 */
function sortObjectKeys(obj: unknown): unknown {
  if (obj === null || typeof obj !== "object") {
    return obj;
  }
  if (Array.isArray(obj)) {
    return obj.map(sortObjectKeys);
  }
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(obj as Record<string, unknown>).sort()) {
    sorted[key] = sortObjectKeys((obj as Record<string, unknown>)[key]);
  }
  return sorted;
}
