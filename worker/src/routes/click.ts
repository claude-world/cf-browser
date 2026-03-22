import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { validateUrl } from "../lib/validate-url.js";
import { withBrowser, BrowserBindingUnavailable, toBaseBody } from "../lib/puppeteer.js";

const app = new Hono<AppEnv>();

app.post("/", async (c) => {
  let body: Record<string, unknown>;
  try {
    body = await c.req.json<Record<string, unknown>>();
  } catch {
    return c.json({ error: "Invalid JSON body", status: 400 }, 400);
  }

  if (!body.url || typeof body.url !== "string") {
    return c.json({ error: "Missing required field: url", status: 400 }, 400);
  }

  const urlCheck = validateUrl(body.url as string);
  if (!urlCheck.valid) {
    return c.json({ error: urlCheck.error, status: 400 }, 400);
  }

  if (!body.selector || typeof body.selector !== "string") {
    return c.json({ error: "Missing required field: selector", status: 400 }, 400);
  }

  const selector = body.selector as string;
  if (selector.length > 500) {
    return c.json({ error: "Selector exceeds 500 character limit", status: 400 }, 400);
  }

  try {
    const result = await withBrowser(c.env, toBaseBody(body), async ({ page }) => {
      await page.click(selector);

      // Wait for potential navigation after click (best-effort)
      try {
        await page.waitForNavigation({ timeout: 5000 });
      } catch {
        // Navigation may not happen — that's fine
      }

      const url = page.url();
      const title = await page.title();
      const content = await page.content();

      return { url, title, content };
    });

    return c.json(result);
  } catch (err) {
    if (err instanceof BrowserBindingUnavailable) {
      return c.json({ error: err.message, status: 501 }, 501);
    }
    const message = err instanceof Error ? err.message : "Click failed";
    return c.json({ error: message, status: 500 }, 500);
  }
});

export default app;
