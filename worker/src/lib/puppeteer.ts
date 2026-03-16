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
import type { Env, BaseRequestBody, CookieParam } from "../types.js";
import { validateUrl } from "./validate-url.js";

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
