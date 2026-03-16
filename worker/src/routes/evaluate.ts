import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { validateUrl } from "../lib/validate-url.js";
import { withBrowser, BrowserBindingUnavailable } from "../lib/puppeteer.js";

const MAX_SCRIPT_SIZE = 10 * 1024; // 10 KB
const EVAL_TIMEOUT = 10_000; // 10 seconds

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

  if (!body.script || typeof body.script !== "string") {
    return c.json({ error: "Missing required field: script", status: 400 }, 400);
  }

  const script = body.script as string;
  if (script.length > MAX_SCRIPT_SIZE) {
    return c.json({ error: `Script exceeds ${MAX_SCRIPT_SIZE} byte limit`, status: 400 }, 400);
  }

  try {
    const result = await withBrowser(c.env, body as any, async ({ page }) => {
      // Execute with timeout — close the page to abort if it takes too long
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        const value = await Promise.race([
          page.evaluate(script),
          new Promise((_, reject) => {
            timer = setTimeout(async () => {
              try { await page.close(); } catch { /* already closing */ }
              reject(new Error("Script execution timed out"));
            }, EVAL_TIMEOUT);
          }),
        ]);
        const type = value === null ? "null" : typeof value;
        return { result: value, type };
      } finally {
        if (timer) clearTimeout(timer);
      }
    });

    return c.json(result);
  } catch (err) {
    if (err instanceof BrowserBindingUnavailable) {
      return c.json({ error: err.message, status: 501 }, 501);
    }
    const message = err instanceof Error ? err.message : "Evaluate failed";
    return c.json({ error: message, status: 500 }, 500);
  }
});

export default app;
