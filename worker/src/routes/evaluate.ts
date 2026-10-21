import { Hono } from "hono";
import type { AppEnv, BaseRequestBody } from "../types.js";
import { validateUrl } from "../lib/validate-url.js";
import {
  withBrowser,
  BlockedNavigationError,
  BrowserBindingUnavailable,
  toBaseBody,
} from "../lib/puppeteer.js";
import {
  assertInteractionOutputSize,
  boundedInteractionErrorMessage,
  InteractionOutputLimitError,
} from "../lib/output-limit.js";

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

  if (typeof body.script !== "string" || body.script.trim().length === 0) {
    return c.json({ error: "Missing required field: script", status: 400 }, 400);
  }

  const script = body.script as string;
  if (new TextEncoder().encode(script).byteLength > MAX_SCRIPT_SIZE) {
    return c.json({ error: `Script exceeds ${MAX_SCRIPT_SIZE} byte limit`, status: 400 }, 400);
  }

  try {
    const result = await withBrowser(c.env, toBaseBody(body), async ({ page }) => {
      // Execute with timeout — browser.close() in withBrowser's finally handles cleanup
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        const value = await Promise.race([
          page.evaluate(script),
          new Promise((_, reject) => {
            timer = setTimeout(() => {
              reject(new Error("Script execution timed out"));
            }, EVAL_TIMEOUT);
          }),
        ]);
        const type = value === null ? "null" : typeof value;
        return assertInteractionOutputSize({ result: value, type });
      } finally {
        if (timer) clearTimeout(timer);
      }
    });

    return c.json(result);
  } catch (err) {
    if (err instanceof BrowserBindingUnavailable) {
      return c.json({ error: boundedInteractionErrorMessage(err, "Browser unavailable"), status: 501 }, 501);
    }
    if (err instanceof BlockedNavigationError) {
      return c.json({ error: boundedInteractionErrorMessage(err, "Navigation blocked"), status: 400 }, 400);
    }
    if (err instanceof InteractionOutputLimitError) {
      return c.json({ error: boundedInteractionErrorMessage(err, "Interaction output failed"), status: 502 }, 502);
    }
    const message = boundedInteractionErrorMessage(err, "Evaluate failed");
    return c.json({ error: message, status: 500 }, 500);
  }
});

export default app;
