/**
 * Map user-friendly snake_case params to Cloudflare Browser Rendering
 * REST API camelCase equivalents.
 *
 * CF API silently ignores unrecognized keys, so incorrect names cause
 * silent failures.  This function is called by every route handler after
 * stripping `no_cache` and endpoint-specific params (e.g. width/height).
 *
 * Mappings:
 *   wait_for              → waitForSelector
 *   headers               → setExtraHTTPHeaders
 *   timeout               → gotoOptions.timeout
 *   wait_until            → gotoOptions.waitUntil
 *   user_agent            → userAgent
 *   add_script_tag        → addScriptTag
 *   add_style_tag         → addStyleTag
 *   reject_resource_types → rejectResourceTypes
 */
export function mapToCfParams(
  body: Record<string, unknown>,
): Record<string, unknown> {
  const out = { ...body };

  // wait_for → waitForSelector (CF API expects an object, not a plain string)
  if (out.wait_for !== undefined) {
    out.waitForSelector = { selector: out.wait_for };
    delete out.wait_for;
  }

  // headers → setExtraHTTPHeaders
  if (out.headers !== undefined) {
    out.setExtraHTTPHeaders = out.headers;
    delete out.headers;
  }

  // timeout → gotoOptions.timeout
  // wait_until → gotoOptions.waitUntil
  const timeout = out.timeout;
  const waitUntil = out.wait_until;
  delete out.timeout;
  delete out.wait_until;

  if (timeout !== undefined || waitUntil !== undefined) {
    const gotoOptions: Record<string, unknown> =
      (out.gotoOptions as Record<string, unknown>) ?? {};
    if (timeout !== undefined) gotoOptions.timeout = timeout;
    if (waitUntil !== undefined) gotoOptions.waitUntil = waitUntil;
    out.gotoOptions = gotoOptions;
  }

  // user_agent → userAgent
  if (out.user_agent !== undefined) {
    out.userAgent = out.user_agent;
    delete out.user_agent;
  }

  // add_script_tag → addScriptTag
  if (out.add_script_tag !== undefined) {
    out.addScriptTag = out.add_script_tag;
    delete out.add_script_tag;
  }

  // add_style_tag → addStyleTag
  if (out.add_style_tag !== undefined) {
    out.addStyleTag = out.add_style_tag;
    delete out.add_style_tag;
  }

  // reject_resource_types → rejectResourceTypes
  if (out.reject_resource_types !== undefined) {
    out.rejectResourceTypes = out.reject_resource_types;
    delete out.reject_resource_types;
  }

  return out;
}
