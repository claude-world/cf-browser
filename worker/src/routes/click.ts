import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { validateUrl } from "../lib/validate-url.js";
import {
  withBrowser,
  BlockedNavigationError,
  BrowserBindingUnavailable,
  performActionAndWaitForNavigation,
  toBaseBody,
} from "../lib/puppeteer.js";
import {
  boundedInteractionErrorMessage,
  boundedPageState,
  InteractionOutputLimitError,
} from "../lib/output-limit.js";

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

  if (typeof body.selector !== "string" || body.selector.trim().length === 0) {
    return c.json({ error: "Missing required field: selector", status: 400 }, 400);
  }

  const selector = body.selector as string;
  if (selector.length > 500) {
    return c.json({ error: "Selector exceeds 500 character limit", status: 400 }, 400);
  }

  try {
    const result = await withBrowser(c.env, toBaseBody(body), async ({ page }) => {
      await performActionAndWaitForNavigation(page, () => page.click(selector), 5000);

      return boundedPageState(page);
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
    const message = boundedInteractionErrorMessage(err, "Click failed");
    return c.json({ error: message, status: 500 }, 500);
  }
});

export default app;
