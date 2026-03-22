/**
 * Puppeteer lifecycle helper for interaction routes.
 *
 * Launches a browser via the Workers Browser Rendering binding,
 * applies common page settings (viewport, user agent, headers, cookies),
 * navigates to the target URL, and hands the page to a callback.
 *
 * Requires `env.BROWSER` — returns 501 if the binding is missing.
 */
import puppeteer, {
  type Browser,
  type Page,
  type PuppeteerLifeCycleEvent,
} from "@cloudflare/puppeteer";
import type { Env, BaseRequestBody, CookieParam, ScriptTag, StyleTag } from "../types.js";
import { validateUrl } from "./validate-url.js";

/**
 * Safely extract known BaseRequestBody fields from a raw JSON object,
 * eliminating `body as any` casts in route handlers.
 */
export function toBaseBody(raw: Record<string, unknown>): BaseRequestBody {
  if (typeof raw.url !== "string" || !raw.url) {
    throw new Error("toBaseBody: missing or invalid url field");
  }
  const body: BaseRequestBody = { url: raw.url };
  if (typeof raw.wait_for === "string") body.wait_for = raw.wait_for;
  if (typeof raw.wait_until === "string") body.wait_until = raw.wait_until;
  if (typeof raw.user_agent === "string") body.user_agent = raw.user_agent;
  if (typeof raw.timeout === "number") body.timeout = raw.timeout;
  if (raw.no_cache === true) body.no_cache = true;
  if (Array.isArray(raw.cookies)) body.cookies = raw.cookies as CookieParam[];
  if (raw.headers && typeof raw.headers === "object" && !Array.isArray(raw.headers))
    body.headers = raw.headers as Record<string, string>;
  if (raw.authenticate && typeof raw.authenticate === "object")
    body.authenticate = raw.authenticate as { username: string; password: string };
  if (Array.isArray(raw.add_script_tag)) body.add_script_tag = raw.add_script_tag as ScriptTag[];
  if (Array.isArray(raw.add_style_tag)) body.add_style_tag = raw.add_style_tag as StyleTag[];
  if (Array.isArray(raw.reject_resource_types)) body.reject_resource_types = raw.reject_resource_types as string[];
  return body;
}

export class BrowserBindingUnavailable extends Error {
  constructor() {
    super(
      "Browser interaction requires the BROWSER binding (Workers Paid plan). " +
        "Read-only endpoints work without it."
    );
    this.name = "BrowserBindingUnavailable";
  }
}

type BrowserContext = {
  page: Page;
  browser: Browser;
};

/**
 * Open a browser, navigate to `body.url`, and execute `callback`.
 * The browser is always closed in the `finally` block.
 */
export async function withBrowser<T>(
  env: Env,
  body: BaseRequestBody,
  callback: (ctx: BrowserContext) => Promise<T>,
): Promise<T> {
  if (!env.BROWSER) {
    throw new BrowserBindingUnavailable();
  }

  const browser = await puppeteer.launch(env.BROWSER);
  try {
    const page = await browser.newPage();

    // Viewport
    await page.setViewport({ width: 1920, height: 1080 });

    // User agent
    if (body.user_agent) {
      await page.setUserAgent(body.user_agent);
    }

    // Extra HTTP headers
    if (body.headers) {
      await page.setExtraHTTPHeaders(body.headers);
    }

    // HTTP Basic Auth
    if (body.authenticate) {
      await page.authenticate(body.authenticate);
    }

    // Cookies
    if (body.cookies && body.cookies.length > 0) {
      const parsed = new URL(body.url);
      const puppeteerCookies = body.cookies.map((c: CookieParam) => ({
        name: c.name,
        value: c.value,
        domain: c.domain ?? parsed.hostname,
        path: c.path ?? "/",
        secure: c.secure ?? parsed.protocol === "https:",
        httpOnly: c.httpOnly ?? false,
        sameSite: c.sameSite as "Strict" | "Lax" | "None" | undefined,
      }));
      await page.setCookie(...puppeteerCookies);
    }

    // SSRF protection: intercept requests to block redirects to private IPs
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      const check = validateUrl(req.url());
      if (!check.valid) {
        req.abort("blockedbyclient");
      } else {
        req.continue();
      }
    });

    // Navigate
    const waitUntil = (body.wait_until as PuppeteerLifeCycleEvent) ?? "load";
    const timeout = body.timeout ?? 30_000;
    await page.goto(body.url, { waitUntil, timeout });

    // Wait for optional selector
    if (body.wait_for) {
      await page.waitForSelector(body.wait_for, { timeout });
    }

    return await callback({ page, browser });
  } finally {
    await browser.close();
  }
}
