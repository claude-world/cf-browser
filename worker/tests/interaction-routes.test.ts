import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import app from "../src/index.js";
import type { Env } from "../src/types.js";
import * as puppeteerLib from "../src/lib/puppeteer.js";

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
    RATE_LIMIT: makeKv(),
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
    vi.spyOn(puppeteerLib, "withBrowser").mockImplementation(async (_env, _body, callback) => {
      const page = {
        click: vi.fn(async () => {}),
        type: vi.fn(async () => {}),
        title: vi.fn(async () => "Updated"),
        content: vi.fn(async () => "<html>updated</html>"),
        url: vi.fn(() => "https://example.com/next"),
        waitForNavigation: vi.fn(async () => null),
        waitForSelector: vi.fn(async () => null),
        select: vi.fn(async () => []),
        screenshot: vi.fn(async () => "base64-image"),
        keyboard: {
          press: vi.fn(async () => {}),
        },
        evaluate: vi.fn(async (script: string) => {
          if (script.includes("requestSubmit")) {
            return { ok: true, method: "requestSubmit" };
          }
          if (script.includes("document.title")) {
            return "Updated";
          }
          return null;
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
