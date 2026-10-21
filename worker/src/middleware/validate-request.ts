import type { Context, Next } from "hono";
import { bodyLimit } from "hono/body-limit";
import type { AppEnv } from "../types.js";

/**
 * Largest accepted request body. Requests carry a URL plus options; the
 * biggest legitimate fields are injected script/style tags and JSON schemas,
 * so 2 MiB leaves ample room while bounding parse memory per request.
 */
export const MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024;
/** Deeper JSON is rejected before recursive option handling or cache hashing. */
export const MAX_JSON_DEPTH = 64;

/** Enforced after authentication and before the body is read or parsed. */
export const requestBodyLimit = bodyLimit({
  maxSize: MAX_REQUEST_BODY_BYTES,
  onError: (c) => c.json({
    error: `Request body exceeds ${MAX_REQUEST_BODY_BYTES} bytes`,
    status: 413,
  }, 413),
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function stringRecord(value: unknown): boolean {
  return isRecord(value) && Object.values(value).every((item) => typeof item === "string");
}

const RESOURCE_TYPES = new Set([
  "document", "stylesheet", "image", "media", "font", "script", "texttrack", "xhr",
  "fetch", "prefetch", "eventsource", "websocket", "manifest", "signedexchange", "ping",
  "cspviolationreport", "preflight", "other",
]);

function boundedStringArray(
  value: unknown,
  maxItems: number,
  maxLength: number,
  allowed?: ReadonlySet<string>,
): boolean {
  return Array.isArray(value) && value.length <= maxItems && value.every((item) =>
    typeof item === "string" && item.trim().length > 0 && item.length <= maxLength &&
    (!allowed || allowed.has(item))
  );
}

function taggedResources(value: unknown): boolean {
  return Array.isArray(value) && value.length <= 50 && value.every((item) => {
    if (!isRecord(item)) return false;
    const contentValid = typeof item.content === "string" &&
      item.content.length > 0 && item.content.length <= 1024 * 1024;
    const urlValid = typeof item.url === "string" && item.url.length > 0 && item.url.length <= 8_192;
    if (item.content !== undefined && !contentValid) return false;
    if (item.url !== undefined && !urlValid) return false;
    if (item.id !== undefined && (
      typeof item.id !== "string" || item.id.length === 0 || item.id.length > 1_024
    )) return false;
    if (item.type !== undefined && (
      typeof item.type !== "string" || item.type.length === 0 || item.type.length > 256
    )) return false;
    return contentValid || urlValid;
  });
}

/** Reject prototype-mutating keys and pathological nesting anywhere in the body. */
export function validateJsonShape(value: unknown): string | null {
  const pending: Array<[unknown, number]> = [[value, 1]];
  for (let entry = pending.pop(); entry; entry = pending.pop()) {
    const [item, depth] = entry;
    if (item === null || typeof item !== "object") continue;
    if (depth > MAX_JSON_DEPTH) {
      return `JSON body must not be nested more than ${MAX_JSON_DEPTH} levels deep`;
    }
    if (Array.isArray(item)) {
      for (const child of item) pending.push([child, depth + 1]);
      continue;
    }
    for (const [key, child] of Object.entries(item)) {
      if (key === "__proto__") return "JSON body must not contain __proto__ keys";
      pending.push([child, depth + 1]);
    }
  }
  return null;
}

/** Validate options shared by Quick Actions and interaction routes. */
export function validateCommonOptions(body: Record<string, unknown>): string | null {
  for (const [friendly, canonical] of [
    ["wait_for", "waitForSelector"],
    ["headers", "setExtraHTTPHeaders"],
    ["user_agent", "userAgent"],
    ["add_script_tag", "addScriptTag"],
    ["add_style_tag", "addStyleTag"],
    ["reject_resource_types", "rejectResourceTypes"],
  ] as const) {
    if (body[friendly] !== undefined && body[canonical] !== undefined) {
      return `Use either ${friendly} or ${canonical}, not both`;
    }
  }
  if (body.no_cache !== undefined && typeof body.no_cache !== "boolean") {
    return "no_cache must be a boolean";
  }
  if (body.wait_for !== undefined && (
    typeof body.wait_for !== "string" || body.wait_for.trim().length === 0 || body.wait_for.length > 500
  )) {
    return "wait_for must be a non-empty string up to 500 characters";
  }
  if (body.timeout !== undefined && (
    typeof body.timeout !== "number" || !Number.isSafeInteger(body.timeout) ||
    body.timeout < 1 || body.timeout > 60_000
  )) {
    return "timeout must be an integer between 1 and 60000 milliseconds";
  }
  if (body.gotoOptions !== undefined && !isRecord(body.gotoOptions)) {
    return "gotoOptions must be an object";
  }
  if (body.waitForSelector !== undefined && !isRecord(body.waitForSelector)) {
    return "waitForSelector must be an object";
  }
  if (isRecord(body.waitForSelector)) {
    const selector = body.waitForSelector.selector;
    if (typeof selector !== "string" || selector.trim().length === 0 || selector.length > 500) {
      return "waitForSelector.selector must be a non-empty string up to 500 characters";
    }
    const selectorTimeout = body.waitForSelector.timeout;
    if (selectorTimeout !== undefined && (
      typeof selectorTimeout !== "number" || !Number.isSafeInteger(selectorTimeout) ||
      selectorTimeout < 1 || selectorTimeout > 120_000
    )) {
      return "waitForSelector.timeout must be an integer between 1 and 120000 milliseconds";
    }
    for (const field of ["hidden", "visible"] as const) {
      if (body.waitForSelector[field] !== undefined && typeof body.waitForSelector[field] !== "boolean") {
        return `waitForSelector.${field} must be a boolean`;
      }
    }
    if (body.waitForSelector.hidden === true && body.waitForSelector.visible === true) {
      return "waitForSelector.hidden and waitForSelector.visible cannot both be true";
    }
  }
  if (body.viewport !== undefined && !isRecord(body.viewport)) {
    return "viewport must be an object";
  }
  if (isRecord(body.viewport)) {
    for (const [field, maximum] of [["width", 7_680], ["height", 4_320]] as const) {
      const value = body.viewport[field];
      if (value !== undefined && (
        typeof value !== "number" || !Number.isSafeInteger(value) || value < 1 || value > maximum
      )) {
        return `viewport.${field} must be an integer between 1 and ${maximum}`;
      }
    }
    const scale = body.viewport.deviceScaleFactor;
    if (scale !== undefined && (
      typeof scale !== "number" || !Number.isFinite(scale) || scale <= 0 || scale > 10
    )) {
      return "viewport.deviceScaleFactor must be a number between 0 and 10";
    }
    for (const field of ["hasTouch", "isLandscape", "isMobile"] as const) {
      if (body.viewport[field] !== undefined && typeof body.viewport[field] !== "boolean") {
        return `viewport.${field} must be a boolean`;
      }
    }
  }
  if (isRecord(body.gotoOptions)) {
    if (body.timeout !== undefined && body.gotoOptions.timeout !== undefined) {
      return "Use either timeout or gotoOptions.timeout, not both";
    }
    if (body.wait_until !== undefined && body.gotoOptions.waitUntil !== undefined) {
      return "Use either wait_until or gotoOptions.waitUntil, not both";
    }
    const timeout = body.gotoOptions.timeout;
    if (timeout !== undefined && (
      typeof timeout !== "number" || !Number.isSafeInteger(timeout) || timeout < 1 || timeout > 60_000
    )) {
      return "gotoOptions.timeout must be an integer between 1 and 60000 milliseconds";
    }
    const waitUntil = body.gotoOptions.waitUntil;
    const allowed = new Set(["load", "domcontentloaded", "networkidle0", "networkidle2"]);
    const validWaitUntil =
      typeof waitUntil === "string" && allowed.has(waitUntil) ||
      Array.isArray(waitUntil) && waitUntil.length > 0 &&
        waitUntil.every((item) => typeof item === "string" && allowed.has(item));
    if (waitUntil !== undefined && !validWaitUntil) {
      return "gotoOptions.waitUntil contains an unsupported lifecycle event";
    }
    for (const [field, maximum] of [["referer", 8_192], ["referrerPolicy", 256]] as const) {
      const value = body.gotoOptions[field];
      if (value !== undefined && (
        typeof value !== "string" || value.trim().length === 0 || value.length > maximum
      )) {
        return `gotoOptions.${field} must be a non-empty string up to ${maximum} characters`;
      }
    }
  }
  for (const field of ["actionTimeout", "waitForTimeout"] as const) {
    const value = body[field];
    if (value !== undefined && (
      typeof value !== "number" || !Number.isSafeInteger(value) || value < 1 || value > 120_000
    )) {
      return `${field} must be an integer between 1 and 120000 milliseconds`;
    }
  }
  for (const field of ["bestAttempt", "setJavaScriptEnabled"] as const) {
    if (body[field] !== undefined && typeof body[field] !== "boolean") {
      return `${field} must be a boolean`;
    }
  }
  if (body.emulateMediaType !== undefined && (
    typeof body.emulateMediaType !== "string" || body.emulateMediaType.trim().length === 0 ||
    body.emulateMediaType.length > 1_024
  )) {
    return "emulateMediaType must be a non-empty string up to 1024 characters";
  }
  for (const field of ["rejectRequestPattern", "allowRequestPattern"] as const) {
    if (body[field] !== undefined && !boundedStringArray(body[field], 100, 2_048)) {
      return `${field} must be an array of up to 100 non-empty strings of at most 2048 characters`;
    }
  }
  if (body.allowResourceTypes !== undefined && (
    !boundedStringArray(body.allowResourceTypes, RESOURCE_TYPES.size, 64, RESOURCE_TYPES)
  )) {
    return "allowResourceTypes contains an unsupported resource type";
  }
  if (body.wait_until !== undefined) {
    const allowed = new Set(["load", "domcontentloaded", "networkidle0", "networkidle2"]);
    if (typeof body.wait_until !== "string" || !allowed.has(body.wait_until)) {
      return "wait_until must be load, domcontentloaded, networkidle0, or networkidle2";
    }
  }
  if (body.user_agent !== undefined && (
    typeof body.user_agent !== "string" || body.user_agent.trim().length === 0 || body.user_agent.length > 1_024
  )) {
    return "user_agent must be a non-empty string up to 1024 characters";
  }
  if (body.userAgent !== undefined && (
    typeof body.userAgent !== "string" || body.userAgent.trim().length === 0 ||
    body.userAgent.length > 1_024
  )) {
    return "userAgent must be a non-empty string up to 1024 characters";
  }
  if (body.headers !== undefined && !stringRecord(body.headers)) {
    return "headers must be an object with string values";
  }
  if (body.setExtraHTTPHeaders !== undefined && !stringRecord(body.setExtraHTTPHeaders)) {
    return "setExtraHTTPHeaders must be an object with string values";
  }
  if (body.cookies !== undefined && (
    !Array.isArray(body.cookies) || !body.cookies.every((cookie) =>
      isRecord(cookie) && typeof cookie.name === "string" && cookie.name.length > 0 &&
      typeof cookie.value === "string"
    )
  )) {
    return "cookies must be an array of objects with non-empty name and string value";
  }
  if (body.authenticate !== undefined && (
    !isRecord(body.authenticate) ||
    typeof body.authenticate.username !== "string" || body.authenticate.username.length === 0 ||
    typeof body.authenticate.password !== "string" || body.authenticate.password.length === 0
  )) {
    return "authenticate must contain non-empty username and password strings";
  }
  if (body.add_script_tag !== undefined && !taggedResources(body.add_script_tag)) {
    return "add_script_tag must be an array whose entries contain content or url";
  }
  if (body.add_style_tag !== undefined && !taggedResources(body.add_style_tag)) {
    return "add_style_tag must be an array whose entries contain content or url";
  }
  if (body.addScriptTag !== undefined && !taggedResources(body.addScriptTag)) {
    return "addScriptTag must be an array whose entries contain content or url";
  }
  if (body.addStyleTag !== undefined && !taggedResources(body.addStyleTag)) {
    return "addStyleTag must be an array whose entries contain content or url";
  }
  if (body.reject_resource_types !== undefined && (
    !boundedStringArray(body.reject_resource_types, RESOURCE_TYPES.size, 64, RESOURCE_TYPES)
  )) {
    return "reject_resource_types contains an unsupported resource type";
  }
  if (body.rejectResourceTypes !== undefined && (
    !boundedStringArray(body.rejectResourceTypes, RESOURCE_TYPES.size, 64, RESOURCE_TYPES)
  )) {
    return "rejectResourceTypes contains an unsupported resource type";
  }
  return null;
}

function validateInteractionOptions(path: string, body: Record<string, unknown>): string | null {
  if (!/^\/(?:click|type|evaluate|interact|submit-form)(?:\/|$)/.test(path)) return null;
  for (const field of [
    "actionTimeout",
    "waitForTimeout",
    "bestAttempt",
    "setJavaScriptEnabled",
    "emulateMediaType",
    "rejectRequestPattern",
    "allowRequestPattern",
    "allowResourceTypes",
  ]) {
    if (body[field] !== undefined) {
      return `${field} is not supported by interaction endpoints`;
    }
  }
  return null;
}

export async function validateRequestMiddleware(
  c: Context<AppEnv>,
  next: Next,
): Promise<Response | void> {
  if (c.req.method !== "POST") {
    await next();
    return;
  }

  let parsed: unknown;
  try {
    parsed = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON body", status: 400 }, 400);
  }
  if (!isRecord(parsed)) {
    return c.json({ error: "JSON body must be an object", status: 400 }, 400);
  }

  const shapeError = validateJsonShape(parsed);
  if (shapeError) return c.json({ error: shapeError, status: 400 }, 400);
  const error = validateCommonOptions(parsed);
  if (error) return c.json({ error, status: 400 }, 400);
  const interactionError = validateInteractionOptions(c.req.path, parsed);
  if (interactionError) return c.json({ error: interactionError, status: 400 }, 400);
  await next();
}
