import { Hono } from "hono";
import type { AppEnv, InteractAction } from "../types.js";
import { validateUrl } from "../lib/validate-url.js";
import {
  withBrowser,
  BrowserBindingUnavailable,
  performActionAndWaitForNavigation,
  toBaseBody,
} from "../lib/puppeteer.js";
import {
  assertInteractionOutputSize,
  boundedInteractionErrorMessage,
  INTERACTION_OUTPUT_LIMIT_ERROR,
  MAX_INTERACTION_OUTPUT_BYTES,
  serializedByteLength,
  truncateUtf8,
} from "../lib/output-limit.js";

const MAX_ACTIONS = 20;
const TOTAL_TIMEOUT = 50_000; // 50 seconds
const MAX_SCRIPT_SIZE = 10 * 1024; // 10 KB
export { MAX_INTERACTION_OUTPUT_BYTES } from "../lib/output-limit.js";

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

  for (const [index, rawAction] of body.actions.entries()) {
    if (!rawAction || typeof rawAction !== "object" || Array.isArray(rawAction)) {
      return c.json({ error: `actions[${index}] must be an object`, status: 400 }, 400);
    }
    const action = rawAction as Record<string, unknown>;
    const name = action.action;
    if (typeof name !== "string") {
      return c.json({ error: `actions[${index}].action must be a string`, status: 400 }, 400);
    }

    const requireString = (field: string, maxLength: number): string | undefined => {
      const value = action[field];
      return typeof value === "string" && value.trim().length > 0 && value.length <= maxLength
        ? undefined
        : `actions[${index}].${field} must be a non-empty string up to ${maxLength} characters`;
    };

    let validationError: string | undefined;
    switch (name) {
      case "navigate":
        validationError = requireString("url", 8_192);
        break;
      case "click":
        validationError = requireString("selector", 500);
        break;
      case "type":
        validationError = requireString("selector", 500);
        if (!validationError && (typeof action.text !== "string" || action.text.length > 10_000)) {
          validationError = `actions[${index}].text must be a string up to 10000 characters`;
        }
        if (!validationError && action.clear !== undefined && typeof action.clear !== "boolean") {
          validationError = `actions[${index}].clear must be a boolean`;
        }
        break;
      case "wait":
        validationError = requireString("selector", 500);
        if (
          !validationError &&
          action.timeout !== undefined &&
          (typeof action.timeout !== "number" || !Number.isFinite(action.timeout) || action.timeout < 1)
        ) {
          validationError = `actions[${index}].timeout must be a positive number`;
        }
        break;
      case "evaluate":
        validationError = requireString("script", MAX_SCRIPT_SIZE);
        if (
          !validationError &&
          new TextEncoder().encode(action.script as string).byteLength > MAX_SCRIPT_SIZE
        ) {
          validationError = `actions[${index}].script exceeds ${MAX_SCRIPT_SIZE} bytes`;
        }
        break;
      case "select":
        validationError = requireString("selector", 500) ?? requireString("value", 10_000);
        break;
      case "scroll":
        if (
          (action.x !== undefined && (typeof action.x !== "number" || !Number.isFinite(action.x))) ||
          (action.y !== undefined && (typeof action.y !== "number" || !Number.isFinite(action.y)))
        ) {
          validationError = `actions[${index}] scroll coordinates must be finite numbers`;
        }
        break;
      case "screenshot":
        break;
      default:
        validationError = `Unknown action: ${name}`;
    }

    if (validationError) {
      return c.json({ error: validationError, status: 400 }, 400);
    }
  }

  const actions = body.actions as InteractAction[];

  try {
    const result = await withBrowser(c.env, toBaseBody(body), async ({ page }) => {
      const results: ActionResult[] = [];
      const deadline = Date.now() + TOTAL_TIMEOUT;
      let outputBytes = 0;

      const appendResult = (entry: ActionResult): boolean => {
        const entryBytes = serializedByteLength(entry);
        if (!Number.isFinite(entryBytes) || outputBytes + entryBytes > MAX_INTERACTION_OUTPUT_BYTES) {
          results.push({
            action: entry.action,
            ok: false,
            error: INTERACTION_OUTPUT_LIMIT_ERROR,
          });
          return false;
        }
        results.push(entry);
        outputBytes += entryBytes;
        return true;
      };

      actionLoop: for (const action of actions) {
        const remaining = deadline - Date.now();
        if (remaining <= 0) {
          appendResult({ action: action.action, ok: false, error: "Total execution timeout exceeded" });
          break;
        }
        page.setDefaultTimeout(Math.max(1, remaining));

        try {
          switch (action.action) {
            case "navigate": {
              const navCheck = validateUrl(action.url);
              if (!navCheck.valid) {
                if (!appendResult({ action: "navigate", ok: false, error: navCheck.error })) {
                  break actionLoop;
                }
                break;
              }
              await page.goto(action.url, {
                waitUntil: "load",
                timeout: Math.max(1, Math.min(15_000, remaining)),
              });
              if (!appendResult({ action: "navigate", ok: true, result: action.url })) {
                break actionLoop;
              }
              continue;
            }
            case "click": {
              await performActionAndWaitForNavigation(
                page,
                () => page.click(action.selector),
                Math.max(1, Math.min(3_000, remaining)),
              );
              if (!appendResult({ action: "click", ok: true })) break actionLoop;
              continue;
            }
            case "type": {
              if (action.clear) {
                await page.click(action.selector, { clickCount: 3 });
                await page.keyboard.press("Backspace");
              }
              await page.type(action.selector, action.text);
              if (!appendResult({ action: "type", ok: true })) break actionLoop;
              continue;
            }
            case "wait": {
              const remaining = Math.max(100, deadline - Date.now());
              const waitTimeout = Math.min(action.timeout ?? 10_000, remaining);
              await page.waitForSelector(action.selector, { timeout: waitTimeout });
              if (!appendResult({ action: "wait", ok: true })) break actionLoop;
              continue;
            }
            case "screenshot": {
              const buf = await page.screenshot({ encoding: "base64" });
              if (typeof buf !== "string") throw new Error("Screenshot did not return base64 data");
              if (!appendResult({ action: "screenshot", ok: true, data: buf })) break actionLoop;
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
                if (!appendResult({ action: "evaluate", ok: true, result: evalResult })) {
                  break actionLoop;
                }
              } finally {
                if (evalTimer) clearTimeout(evalTimer);
              }
              continue;
            }
            case "select": {
              await page.select(action.selector, action.value);
              if (!appendResult({ action: "select", ok: true })) break actionLoop;
              continue;
            }
            case "scroll": {
              const x = typeof action.x === "number" ? action.x : 0;
              const y = typeof action.y === "number" ? action.y : 0;
              await page.evaluate(
                `((dx,dy)=>window.scrollBy(dx,dy))(${JSON.stringify(x)},${JSON.stringify(y)})`
              );
              if (!appendResult({ action: "scroll", ok: true })) break actionLoop;
              continue;
            }
            default: {
              const name = String((action as any).action ?? "unknown");
              appendResult({ action: name, ok: false, error: `Unknown action: ${name}` });
              break actionLoop; // unknown action stops processing
            }
          }
        } catch (err) {
          const msg = boundedInteractionErrorMessage(err, "Action failed");
          appendResult({ action: action.action, ok: false, error: msg });
          break;
        }
      }

      const url = truncateUtf8(page.url(), 32 * 1024);
      const title = truncateUtf8(await page.title(), 64 * 1024);
      const envelopeMarker: ActionResult = {
        action: "response",
        ok: false,
        error: INTERACTION_OUTPUT_LIMIT_ERROR,
      };
      let markerNeeded = url.truncated || title.truncated;
      let response = { url: url.value, title: title.value, results };
      while (
        results.length > 0 &&
        serializedByteLength({
          ...response,
          results: [...results, ...(markerNeeded ? [envelopeMarker] : [])],
        }) > MAX_INTERACTION_OUTPUT_BYTES
      ) {
        results.pop();
        markerNeeded = true;
      }
      if (markerNeeded) results.push(envelopeMarker);
      response = { url: url.value, title: title.value, results };
      return assertInteractionOutputSize(response);
    });

    return c.json(result);
  } catch (err) {
    if (err instanceof BrowserBindingUnavailable) {
      return c.json({ error: boundedInteractionErrorMessage(err, "Browser unavailable"), status: 501 }, 501);
    }
    const message = boundedInteractionErrorMessage(err, "Interact failed");
    return c.json({ error: message, status: 500 }, 500);
  }
});

export default app;
