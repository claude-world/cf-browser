import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import app from "../src/index.js";
import type { Env } from "../src/types.js";
import * as puppeteerLib from "../src/lib/puppeteer.js";
import { MAX_INTERACTION_OUTPUT_BYTES } from "../src/routes/interact.js";
import {
  MAX_INTERACTION_ERROR_BYTES,
  serializedByteLength,
} from "../src/lib/output-limit.js";

let screenshotResult = "base64-image";
let evaluateResult: unknown = null;
let evaluateError: Error | null = null;
let titleResult = "Updated";
let contentResult = "<html>updated</html>";

function makeKv(): KVNamespace {
  return {
    get: async () => null,
    getWithMetadata: async () => ({ value: null, metadata: null, cacheStatus: null }),
    put: async () => {},
    delete: async () => {},
    list: async () => ({ keys: [], list_complete: true, cursor: "", cacheStatus: null }),
  } as unknown as KVNamespace;
}

function makeR2(): R2Bucket {
  return {
    get: async () => null,
    put: async () => {},
    delete: async () => {},
    list: async () => ({ objects: [], truncated: false }),
    head: async () => null,
  } as unknown as R2Bucket;
}

function buildEnv(): Env {
  return {
    CF_ACCOUNT_ID: "test-account",
    CF_API_TOKEN: "test-token",
    API_KEYS: "valid-key",
    CACHE: makeKv(),
    RATE_LIMITER: { limit: async () => ({ success: true }) } as RateLimit,
    STORAGE: makeR2(),
  };
}

function authHeaders() {
  return { Authorization: "Bearer valid-key", "Content-Type": "application/json" };
}

async function postJson(path: string, body: unknown, env: Env) {
  return app.fetch(
    new Request(`http://localhost${path}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
    }),
    env,
  );
}

describe("interaction routes", () => {
  beforeEach(() => {
    screenshotResult = "base64-image";
    evaluateResult = null;
    evaluateError = null;
    titleResult = "Updated";
    contentResult = "<html>updated</html>";
    vi.spyOn(puppeteerLib, "withBrowser").mockImplementation(async (_env, _body, callback) => {
      const page = {
        click: vi.fn(async () => {}),
        type: vi.fn(async () => {}),
        title: vi.fn(async () => titleResult),
        content: vi.fn(async () => contentResult),
        url: vi.fn(() => "https://example.com/next"),
        waitForNavigation: vi.fn(async () => null),
        waitForSelector: vi.fn(async () => null),
        setDefaultTimeout: vi.fn(),
        select: vi.fn(async () => []),
        screenshot: vi.fn(async () => screenshotResult),
        keyboard: {
          press: vi.fn(async () => {}),
        },
        evaluate: vi.fn(async (script: string) => {
          if (evaluateError) throw evaluateError;
          if (script.includes("requestSubmit")) {
            return { ok: true, method: "requestSubmit" };
          }
          if (script.includes("document.title")) {
            return "Updated";
          }
          return evaluateResult;
        }),
      };

      return callback({
        page: page as unknown as any,
        browser: {} as any,
      });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns 400 when an interaction navigation is blocked", async () => {
    vi.spyOn(puppeteerLib, "withBrowser").mockRejectedValue(
      new puppeteerLib.BlockedNavigationError("URL resolves to a private or reserved IP address"),
    );
    for (const [path, payload] of [
      ["/click", { selector: "a" }],
      ["/type", { selector: "input", text: "hello" }],
      ["/evaluate", { script: "1 + 1" }],
      ["/interact", { actions: [{ action: "click", selector: "a" }] }],
      ["/submit-form", { fields: { "input[name=q]": "x" } }],
    ] as const) {
      const res = await postJson(path, { url: "https://example.com", ...payload }, buildEnv());
      expect(res.status, path).toBe(400);
      expect(await res.json()).toMatchObject({
        error: "URL resolves to a private or reserved IP address",
        status: 400,
      });
    }
  });

  it("POST /click returns page state", async () => {
    const res = await postJson("/click", { url: "https://example.com", selector: "a.next" }, buildEnv());
    expect(res.status).toBe(200);
    const body = await res.json<{ title: string; url: string }>();
    expect(body.title).toBe("Updated");
    expect(body.url).toBe("https://example.com/next");
  });

  it("POST /type returns page state after typing", async () => {
    const res = await postJson(
      "/type",
      { url: "https://example.com", selector: "#email", text: "user@example.com", clear: true },
      buildEnv(),
    );
    expect(res.status).toBe(200);
    const body = await res.json<{ content: string }>();
    expect(body.content).toContain("updated");
  });

  it("rejects invalid interaction inputs before launching a browser", async () => {
    const withBrowser = vi.mocked(puppeteerLib.withBrowser);
    const cases = [
      ["/click", { url: "https://example.com", selector: "   " }],
      ["/type", { url: "https://example.com", selector: "#x", text: "x", clear: "yes" }],
      ["/evaluate", { url: "https://example.com", script: "   " }],
      ["/submit-form", { url: "https://example.com", fields: { "": "value" } }],
    ] as const;

    for (const [path, request] of cases) {
      const res = await postJson(path, request, buildEnv());
      expect(res.status).toBe(400);
    }
    expect(withBrowser).not.toHaveBeenCalled();
  });

  it("rejects Cloudflare-only options that local interaction routes cannot honor", async () => {
    const withBrowser = vi.mocked(puppeteerLib.withBrowser);
    const res = await postJson(
      "/click",
      {
        url: "https://example.com",
        selector: "#button",
        waitForTimeout: 1_000,
      },
      buildEnv(),
    );

    expect(res.status).toBe(400);
    expect(await res.text()).toContain("not supported by interaction endpoints");
    expect(withBrowser).not.toHaveBeenCalled();
  });

  it("POST /evaluate returns the script result", async () => {
    const res = await postJson(
      "/evaluate",
      { url: "https://example.com", script: "document.title" },
      buildEnv(),
    );
    expect(res.status).toBe(200);
    const body = await res.json<{ result: string; type: string }>();
    expect(body.result).toBe("Updated");
    expect(body.type).toBe("string");
  });

  it("POST /evaluate fails closed before returning an oversized result", async () => {
    evaluateResult = "x".repeat(MAX_INTERACTION_OUTPUT_BYTES + 1);
    const res = await postJson(
      "/evaluate",
      { url: "https://example.com", script: "largeValue" },
      buildEnv(),
    );

    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({
      error: "Interaction output byte limit exceeded",
    });
  });

  it("POST /evaluate bounds attacker-controlled error serialization", async () => {
    evaluateError = new Error("\0".repeat(MAX_INTERACTION_ERROR_BYTES * 2));
    const res = await postJson(
      "/evaluate",
      { url: "https://example.com", script: "throwLargeError()" },
      buildEnv(),
    );

    expect(res.status).toBe(500);
    const body = await res.json<{ error: string }>();
    expect(serializedByteLength(body.error)).toBeLessThanOrEqual(MAX_INTERACTION_ERROR_BYTES);
    expect(body.error.length).toBeLessThan(evaluateError.message.length);
  });

  it("POST /click fails closed before returning oversized page content", async () => {
    contentResult = "x".repeat(MAX_INTERACTION_OUTPUT_BYTES + 1);
    const res = await postJson(
      "/click",
      { url: "https://example.com", selector: "a.next" },
      buildEnv(),
    );

    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({
      error: "Interaction output byte limit exceeded",
    });
  });

  it("POST /interact executes action chains", async () => {
    const res = await postJson(
      "/interact",
      {
        url: "https://example.com",
        actions: [
          { action: "type", selector: "#email", text: "user@example.com", clear: true },
          { action: "click", selector: "button[type='submit']" },
          { action: "evaluate", script: "document.title" },
        ],
      },
      buildEnv(),
    );
    expect(res.status).toBe(200);
    const body = await res.json<{ results: Array<{ action: string; ok: boolean }> }>();
    expect(body.results).toEqual([
      { action: "type", ok: true },
      { action: "click", ok: true },
      { action: "evaluate", ok: true, result: "Updated" },
    ]);
  });

  it("POST /interact stops before returning an oversized base64 screenshot", async () => {
    screenshotResult = "x".repeat(MAX_INTERACTION_OUTPUT_BYTES + 1);
    const res = await postJson(
      "/interact",
      {
        url: "https://example.com",
        actions: [
          { action: "screenshot" },
          { action: "click", selector: "#should-not-run" },
        ],
      },
      buildEnv(),
    );

    expect(res.status).toBe(200);
    const body = await res.json<{ results: Array<Record<string, unknown>> }>();
    expect(body.results).toEqual([{
      action: "screenshot",
      ok: false,
      error: "Interaction output byte limit exceeded",
    }]);
  });

  it("POST /interact applies the byte limit cumulatively to evaluate results", async () => {
    evaluateResult = "x".repeat(Math.floor(MAX_INTERACTION_OUTPUT_BYTES / 2));
    const res = await postJson(
      "/interact",
      {
        url: "https://example.com",
        actions: [
          { action: "evaluate", script: "largeValue" },
          { action: "evaluate", script: "largeValue" },
          { action: "click", selector: "#should-not-run" },
        ],
      },
      buildEnv(),
    );

    expect(res.status).toBe(200);
    const body = await res.json<{ results: Array<Record<string, unknown>> }>();
    expect(body.results).toHaveLength(2);
    expect(body.results[0]).toMatchObject({ action: "evaluate", ok: true });
    expect(body.results[1]).toEqual({
      action: "evaluate",
      ok: false,
      error: "Interaction output byte limit exceeded",
    });
  });

  it("POST /interact bounds errors before appending them to action results", async () => {
    evaluateError = new Error("x".repeat(MAX_INTERACTION_ERROR_BYTES * 2));
    const res = await postJson(
      "/interact",
      {
        url: "https://example.com",
        actions: [{ action: "evaluate", script: "throwLargeError()" }],
      },
      buildEnv(),
    );

    expect(res.status).toBe(200);
    const body = await res.json<{ results: Array<{ error?: string }> }>();
    expect(serializedByteLength(body.results[0]?.error)).toBeLessThanOrEqual(
      MAX_INTERACTION_ERROR_BYTES,
    );
  });

  it("POST /interact bounds the complete response envelope", async () => {
    titleResult = "x".repeat(MAX_INTERACTION_OUTPUT_BYTES + 1);
    const res = await postJson(
      "/interact",
      {
        url: "https://example.com",
        actions: [{ action: "click", selector: "#button" }],
      },
      buildEnv(),
    );

    expect(res.status).toBe(200);
    const raw = await res.text();
    expect(new TextEncoder().encode(raw).byteLength).toBeLessThanOrEqual(
      MAX_INTERACTION_OUTPUT_BYTES,
    );
  });

  it("POST /interact rejects malformed actions before launching a browser", async () => {
    const withBrowser = vi.mocked(puppeteerLib.withBrowser);
    const res = await postJson(
      "/interact",
      { url: "https://example.com", actions: [null, { action: "type", selector: "#x" }] },
      buildEnv(),
    );
    expect(res.status).toBe(400);
    expect(withBrowser).not.toHaveBeenCalled();
  });

  it("POST /submit-form uses requestSubmit-compatible fallback", async () => {
    const res = await postJson(
      "/submit-form",
      {
        url: "https://example.com/form",
        fields: {
          "#email": "user@example.com",
          "#password": "secret",
        },
      },
      buildEnv(),
    );
    expect(res.status).toBe(200);
    const body = await res.json<{ title: string }>();
    expect(body.title).toBe("Updated");
  });
});
