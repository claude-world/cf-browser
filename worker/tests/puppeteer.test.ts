import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Env } from "../src/types.js";

const puppeteerMock = vi.hoisted(() => ({
  launch: vi.fn(),
}));

vi.mock("@cloudflare/puppeteer", () => ({
  default: { launch: puppeteerMock.launch },
}));

import {
  BrowserBindingUnavailable,
  toBaseBody,
  withBrowser,
} from "../src/lib/puppeteer.js";

function buildEnv(): Env {
  return {
    CF_ACCOUNT_ID: "test-account",
    CF_API_TOKEN: "test-token",
    API_KEYS: "valid-key",
    CACHE: {} as KVNamespace,
    RATE_LIMITER: {} as RateLimit,
    STORAGE: {} as R2Bucket,
    BROWSER: {} as Fetcher,
  };
}

function buildBrowser() {
  const page = {
    setViewport: vi.fn(async () => undefined),
    setUserAgent: vi.fn(async () => undefined),
    setExtraHTTPHeaders: vi.fn(async () => undefined),
    authenticate: vi.fn(async () => undefined),
    setCookie: vi.fn(async () => undefined),
    setRequestInterception: vi.fn(async () => undefined),
    on: vi.fn(),
    goto: vi.fn(async () => null),
    addScriptTag: vi.fn(async () => null),
    addStyleTag: vi.fn(async () => null),
    waitForSelector: vi.fn(async () => null),
  };
  const browser = {
    newPage: vi.fn(async () => page),
    close: vi.fn(async () => undefined),
  };
  puppeteerMock.launch.mockResolvedValue(browser);
  return { page, browser };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("withBrowser", () => {
  it("normalizes supported canonical options for interaction routes", () => {
    expect(toBaseBody({
      url: "https://example.com",
      gotoOptions: {
        timeout: 9_000,
        waitUntil: ["domcontentloaded", "networkidle0"],
        referer: "https://referrer.example/",
      },
      waitForSelector: { selector: "main", visible: true, timeout: 8_000 },
      viewport: { width: 1280, height: 720, deviceScaleFactor: 2 },
      userAgent: "CanonicalBot/1.0",
      setExtraHTTPHeaders: { "X-Test": "canonical" },
      addScriptTag: [{ content: "window.ready = true" }],
      addStyleTag: [{ content: "body { color: red }" }],
      rejectResourceTypes: ["image"],
    })).toMatchObject({
      url: "https://example.com",
      goto_options: {
        timeout: 9_000,
        waitUntil: ["domcontentloaded", "networkidle0"],
        referer: "https://referrer.example/",
      },
      wait_for_selector: { selector: "main", visible: true, timeout: 8_000 },
      viewport: { width: 1280, height: 720, deviceScaleFactor: 2 },
      user_agent: "CanonicalBot/1.0",
      headers: { "X-Test": "canonical" },
      add_script_tag: [{ content: "window.ready = true" }],
      add_style_tag: [{ content: "body { color: red }" }],
      reject_resource_types: ["image"],
    });
  });

  it("applies canonical navigation, selector, and viewport options", async () => {
    const { page } = buildBrowser();
    const body = toBaseBody({
      url: "https://example.com",
      gotoOptions: {
        timeout: 9_000,
        waitUntil: ["domcontentloaded", "networkidle0"],
        referer: "https://referrer.example/",
      },
      waitForSelector: { selector: "main", visible: true, timeout: 8_000 },
      viewport: { width: 1280, height: 720, deviceScaleFactor: 2 },
    });

    await withBrowser(buildEnv(), body, async () => undefined);

    expect(page.setViewport).toHaveBeenCalledWith({
      width: 1280,
      height: 720,
      deviceScaleFactor: 2,
    });
    expect(page.goto).toHaveBeenCalledWith("https://example.com", {
      timeout: 9_000,
      waitUntil: ["domcontentloaded", "networkidle0"],
      referer: "https://referrer.example/",
    });
    expect(page.waitForSelector).toHaveBeenCalledWith("main", {
      visible: true,
      timeout: 8_000,
    });
  });

  it("applies every supported common interaction option", async () => {
    const { page, browser } = buildBrowser();
    const callback = vi.fn(async () => "done");

    const result = await withBrowser(
      buildEnv(),
      {
        url: "https://example.com",
        user_agent: "TestBot/1.0",
        headers: { "X-Test": "value" },
        authenticate: { username: "user", password: "pass" },
        cookies: [{ name: "session", value: "abc" }],
        add_script_tag: [{ content: "window.ready = true" }],
        add_style_tag: [{ content: "body { color: red }" }],
        reject_resource_types: ["image"],
        wait_for: "main",
        wait_until: "networkidle0",
        timeout: 12_000,
      },
      callback,
    );

    expect(result).toBe("done");
    expect(page.setUserAgent).toHaveBeenCalledWith("TestBot/1.0");
    expect(page.setExtraHTTPHeaders).toHaveBeenCalledWith({ "X-Test": "value" });
    expect(page.authenticate).toHaveBeenCalledWith({ username: "user", password: "pass" });
    expect(page.setCookie).toHaveBeenCalledWith(expect.objectContaining({
      name: "session",
      value: "abc",
      domain: "example.com",
    }));
    expect(page.goto).toHaveBeenCalledWith("https://example.com", {
      waitUntil: "networkidle0",
      timeout: 12_000,
    });
    expect(page.addScriptTag).toHaveBeenCalledWith({ content: "window.ready = true" });
    expect(page.addStyleTag).toHaveBeenCalledWith({ content: "body { color: red }" });
    expect(page.waitForSelector).toHaveBeenCalledWith("main", { timeout: 12_000 });
    expect(callback).toHaveBeenCalledWith({ page, browser });
    expect(browser.close).toHaveBeenCalledOnce();
  });

  it("aborts rejected resource types before DNS resolution", async () => {
    const { page } = buildBrowser();
    let requestHandler: ((request: unknown) => void) | undefined;
    page.on.mockImplementation((_event: string, handler: (request: unknown) => void) => {
      requestHandler = handler;
    });
    const request = {
      resourceType: vi.fn(() => "image"),
      url: vi.fn(() => "https://example.com/image.png"),
      abort: vi.fn(async () => undefined),
      continue: vi.fn(async () => undefined),
    };

    await withBrowser(
      buildEnv(),
      { url: "https://example.com", reject_resource_types: ["image"] },
      async () => {
        requestHandler?.(request);
      },
    );

    await vi.waitFor(() => expect(request.abort).toHaveBeenCalledWith("blockedbyclient"));
    expect(request.continue).not.toHaveBeenCalled();
  });

  it("fails clearly without a browser binding", async () => {
    const env = buildEnv();
    delete env.BROWSER;
    await expect(
      withBrowser(env, { url: "https://example.com" }, async () => undefined),
    ).rejects.toBeInstanceOf(BrowserBindingUnavailable);
    expect(puppeteerMock.launch).not.toHaveBeenCalled();
  });
});
