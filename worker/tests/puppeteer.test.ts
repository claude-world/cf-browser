import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Env } from "../src/types.js";

const puppeteerMock = vi.hoisted(() => ({
  launch: vi.fn(),
}));

vi.mock("@cloudflare/puppeteer", () => ({
  default: { launch: puppeteerMock.launch },
}));

import {
  BlockedNavigationError,
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
  const mainFrame = {};
  const page = {
    mainFrame: vi.fn(() => mainFrame),
    setBypassServiceWorker: vi.fn(async () => undefined),
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
    on: vi.fn(),
  };
  puppeteerMock.launch.mockResolvedValue(browser);
  return { page, browser, mainFrame };
}

let dnsAnswer = "93.184.216.34";

beforeEach(() => {
  vi.clearAllMocks();
  dnsAnswer = "93.184.216.34";
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === "string" ? input : input.toString());
    const host = url.searchParams.get("name") ?? "";
    const type = url.searchParams.get("type");
    const data = host.startsWith("internal.") ? "10.0.0.7" : dnsAnswer;
    return new Response(JSON.stringify({
      Status: 0,
      Answer: type === "A" ? [{ data }] : [],
    }), { headers: { "Content-Type": "application/dns-json" } });
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
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

  it("rejects targets that resolve to private addresses before launching a browser", async () => {
    buildBrowser();
    dnsAnswer = "10.1.2.3";

    await expect(
      withBrowser(buildEnv(), { url: "https://example.com" }, async () => undefined),
    ).rejects.toBeInstanceOf(BlockedNavigationError);
    expect(puppeteerMock.launch).not.toHaveBeenCalled();
  });

  it("reports a main-frame redirect to a blocked destination as a blocked navigation", async () => {
    const { page, browser, mainFrame } = buildBrowser();
    let requestHandler: ((request: unknown) => void) | undefined;
    page.on.mockImplementation((_event: string, handler: (request: unknown) => void) => {
      requestHandler = handler;
    });
    const redirect = {
      resourceType: vi.fn(() => "document"),
      url: vi.fn(() => "https://internal.example.com/admin"),
      isNavigationRequest: vi.fn(() => true),
      frame: vi.fn(() => mainFrame),
      abort: vi.fn(async () => undefined),
      continue: vi.fn(async () => undefined),
    };
    page.goto.mockImplementation(async () => {
      requestHandler?.(redirect);
      await vi.waitFor(() => expect(redirect.abort).toHaveBeenCalledWith("blockedbyclient"));
      throw new Error("net::ERR_BLOCKED_BY_CLIENT at https://example.com");
    });

    await expect(
      withBrowser(buildEnv(), { url: "https://example.com" }, async () => undefined),
    ).rejects.toBeInstanceOf(BlockedNavigationError);
    expect(redirect.continue).not.toHaveBeenCalled();
    expect(browser.close).toHaveBeenCalledOnce();
  });

  it("bypasses service workers and closes popups opened by the page", async () => {
    const { page, browser } = buildBrowser();
    let targetHandler: ((target: unknown) => void) | undefined;
    browser.on.mockImplementation((event: string, handler: (target: unknown) => void) => {
      if (event === "targetcreated") targetHandler = handler;
    });
    const popup = { close: vi.fn(async () => undefined) };

    await withBrowser(buildEnv(), { url: "https://example.com" }, async () => {
      targetHandler?.({ type: () => "page", page: async () => popup });
      targetHandler?.({ type: () => "page", page: async () => page });
      targetHandler?.({ type: () => "service_worker", page: async () => null });
    });

    expect(page.setBypassServiceWorker).toHaveBeenCalledWith(true);
    await vi.waitFor(() => expect(popup.close).toHaveBeenCalledOnce());
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
