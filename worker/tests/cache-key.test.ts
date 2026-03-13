import { describe, it, expect } from "vitest";
import { generateCacheKey } from "../src/lib/cache-key.js";

describe("generateCacheKey", () => {
  it("produces a 64-char hex string", async () => {
    const key = await generateCacheKey("content", "https://example.com", {});
    expect(key).toMatch(/^[0-9a-f]{64}$/);
  });

  it("same inputs produce the same key", async () => {
    const a = await generateCacheKey("content", "https://example.com", { wait_for: ".body" });
    const b = await generateCacheKey("content", "https://example.com", { wait_for: ".body" });
    expect(a).toBe(b);
  });

  it("different endpoints produce different keys", async () => {
    const a = await generateCacheKey("content", "https://example.com", {});
    const b = await generateCacheKey("screenshot", "https://example.com", {});
    expect(a).not.toBe(b);
  });

  it("key is order-independent for options", async () => {
    const a = await generateCacheKey("scrape", "https://example.com", { b: 2, a: 1 });
    const b = await generateCacheKey("scrape", "https://example.com", { a: 1, b: 2 });
    expect(a).toBe(b);
  });

  it("different URLs produce different keys", async () => {
    const a = await generateCacheKey("content", "https://example.com", {});
    const b = await generateCacheKey("content", "https://other.com", {});
    expect(a).not.toBe(b);
  });
});
