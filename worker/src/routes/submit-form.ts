import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { validateUrl } from "../lib/validate-url.js";
import { withBrowser, BrowserBindingUnavailable } from "../lib/puppeteer.js";

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

  if (!body.fields || typeof body.fields !== "object" || Array.isArray(body.fields)) {
    return c.json({ error: "Missing required field: fields (object mapping selector → value)", status: 400 }, 400);
  }

  const fields = body.fields as Record<string, unknown>;
  const submitSelector = body.submit_selector;
  if (submitSelector !== undefined && typeof submitSelector !== "string") {
    return c.json({ error: "submit_selector must be a string", status: 400 }, 400);
  }

  // Validate fields count
  const fieldEntries = Object.entries(fields);
  if (fieldEntries.length > 50) {
    return c.json({ error: "fields exceeds 50 entry limit", status: 400 }, 400);
  }

  // Validate selector lengths and value types
  for (const [selector, value] of fieldEntries) {
    if (selector.length > 500) {
      return c.json({ error: "Field selector exceeds 500 character limit", status: 400 }, 400);
    }
    if (typeof value !== "string") {
      return c.json({ error: `Field value for "${selector}" must be a string`, status: 400 }, 400);
    }
    if ((value as string).length > 10_000) {
      return c.json({ error: `Field value for "${selector}" exceeds 10000 character limit`, status: 400 }, 400);
    }
  }
  if (submitSelector && submitSelector.length > 500) {
    return c.json({ error: "Submit selector exceeds 500 character limit", status: 400 }, 400);
  }

  try {
    const result = await withBrowser(c.env, body as any, async ({ page }) => {
      // Fill each field: clear then type
      for (const [selector, value] of fieldEntries) {
        await page.click(selector, { clickCount: 3 });
        await page.keyboard.press("Backspace");
        await page.type(selector, value as string);
      }

      // Submit
      if (submitSelector) {
        await page.click(submitSelector);
      } else {
        // Try to submit the first form on the page
        await page.evaluate(
          `(() => { const form = document.querySelector("form"); if (form) form.submit(); })()`
        );
      }

      // Wait for navigation after submit
      try {
        await page.waitForNavigation({ timeout: 10_000 });
      } catch {
        // May not navigate — that's fine
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
    const message = err instanceof Error ? err.message : "Form submission failed";
    return c.json({ error: message, status: 500 }, 500);
  }
});

export default app;
