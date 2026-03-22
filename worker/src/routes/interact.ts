import { Hono } from "hono";
import type { AppEnv, InteractAction } from "../types.js";
import { validateUrl } from "../lib/validate-url.js";
import { withBrowser, BrowserBindingUnavailable, toBaseBody } from "../lib/puppeteer.js";

const MAX_ACTIONS = 20;
const TOTAL_TIMEOUT = 50_000; // 50 seconds
const MAX_SCRIPT_SIZE = 10 * 1024; // 10 KB

type ActionResult = {
  action: string;
  ok: boolean;
  error?: string;
  result?: unknown;
  data?: string; // base64 screenshot data
};

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

  if (!Array.isArray(body.actions) || body.actions.length === 0) {
    return c.json({ error: "Missing required field: actions (non-empty array)", status: 400 }, 400);
  }

  if (body.actions.length > MAX_ACTIONS) {
    return c.json({ error: `Actions array exceeds ${MAX_ACTIONS} item limit`, status: 400 }, 400);
  }

  const actions = body.actions as InteractAction[];

  // Validate selectors length
  for (const a of actions) {
    if ("selector" in a && typeof a.selector === "string" && a.selector.length > 500) {
      return c.json({ error: "Selector exceeds 500 character limit", status: 400 }, 400);
    }
    if ("script" in a && typeof a.script === "string" && a.script.length > MAX_SCRIPT_SIZE) {
      return c.json({ error: `Script exceeds ${MAX_SCRIPT_SIZE} byte limit`, status: 400 }, 400);
    }
  }

  try {
    const result = await withBrowser(c.env, toBaseBody(body), async ({ page }) => {
      const results: ActionResult[] = [];
      const deadline = Date.now() + TOTAL_TIMEOUT;

      actionLoop: for (const action of actions) {
        if (Date.now() > deadline) {
          results.push({ action: action.action, ok: false, error: "Total execution timeout exceeded" });
          break;
        }

        try {
          switch (action.action) {
            case "navigate": {
              const navCheck = validateUrl(action.url);
              if (!navCheck.valid) {
                results.push({ action: "navigate", ok: false, error: navCheck.error });
                break;
              }
              await page.goto(action.url, { waitUntil: "load", timeout: 15_000 });
              results.push({ action: "navigate", ok: true, result: action.url });
              continue;
            }
            case "click": {
              await page.click(action.selector);
              // Best-effort wait for navigation
              try {
                await page.waitForNavigation({ timeout: 3000 });
              } catch {
                // No navigation — fine
              }
              results.push({ action: "click", ok: true });
              continue;
            }
            case "type": {
              if (action.clear) {
                await page.click(action.selector, { clickCount: 3 });
                await page.keyboard.press("Backspace");
              }
              await page.type(action.selector, action.text);
              results.push({ action: "type", ok: true });
              continue;
            }
            case "wait": {
              const remaining = Math.max(100, deadline - Date.now());
              const waitTimeout = Math.min(action.timeout ?? 10_000, remaining);
              await page.waitForSelector(action.selector, { timeout: waitTimeout });
              results.push({ action: "wait", ok: true });
              continue;
            }
            case "screenshot": {
              const buf = await page.screenshot({ encoding: "base64" });
              results.push({ action: "screenshot", ok: true, data: buf as string });
              continue;
            }
            case "evaluate": {
              const remaining = Math.max(1000, deadline - Date.now());
              const evalTimeout = Math.min(remaining, 10_000);
              let evalTimer: ReturnType<typeof setTimeout> | undefined;
              try {
                const evalResult = await Promise.race([
                  page.evaluate(action.script),
                  new Promise((_, reject) => {
                    evalTimer = setTimeout(() => {
                      reject(new Error("Script execution timed out"));
                    }, evalTimeout);
                  }),
                ]);
                results.push({ action: "evaluate", ok: true, result: evalResult });
              } finally {
                if (evalTimer) clearTimeout(evalTimer);
              }
              continue;
            }
            case "select": {
              await page.select(action.selector, action.value);
              results.push({ action: "select", ok: true });
              continue;
            }
            case "scroll": {
              const x = typeof action.x === "number" ? action.x : 0;
              const y = typeof action.y === "number" ? action.y : 0;
              await page.evaluate(
                `((dx,dy)=>window.scrollBy(dx,dy))(${JSON.stringify(x)},${JSON.stringify(y)})`
              );
              results.push({ action: "scroll", ok: true });
              continue;
            }
            default: {
              const name = String((action as any).action ?? "unknown");
              results.push({ action: name, ok: false, error: `Unknown action: ${name}` });
              break actionLoop; // unknown action stops processing
            }
          }
        } catch (err) {
          const msg = err instanceof Error ? err.message : "Action failed";
          results.push({ action: action.action, ok: false, error: msg });
          break;
        }
      }

      return {
        url: page.url(),
        title: await page.title(),
        results,
      };
    });

    return c.json(result);
  } catch (err) {
    if (err instanceof BrowserBindingUnavailable) {
      return c.json({ error: err.message, status: 501 }, 501);
    }
    const message = err instanceof Error ? err.message : "Interact failed";
    return c.json({ error: message, status: 500 }, 500);
  }
});

export default app;
