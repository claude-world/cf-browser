import { Hono } from "hono";
import type { AppEnv } from "../types.js";
import { CfBrowserApi } from "../lib/cf-api.js";
import { validateUrl } from "../lib/validate-url.js";
import { mapToCfParams } from "../lib/param-map.js";

// /json is explicitly not cached — results are LLM-extracted and may vary
const app = new Hono<AppEnv>();

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

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

  if (body.prompt !== undefined && (
    typeof body.prompt !== "string" || body.prompt.trim().length === 0
  )) {
    return c.json({ error: "prompt must be a non-empty string", status: 400 }, 400);
  }
  if (body.schema !== undefined && (
    body.schema === null || typeof body.schema !== "object" || Array.isArray(body.schema)
  )) {
    return c.json({ error: "schema must be a JSON object", status: 400 }, 400);
  }
  if (body.response_format !== undefined) {
    if (!isRecord(body.response_format)) {
      return c.json({ error: "response_format must be a JSON object", status: 400 }, 400);
    }
    if (
      body.response_format.type !== "json_schema" ||
      !isRecord(body.response_format.json_schema)
    ) {
      return c.json({
        error: "response_format must contain type=json_schema and a json_schema object",
        status: 400,
      }, 400);
    }
  }
  if (body.schema !== undefined && body.response_format !== undefined) {
    return c.json({ error: "Use either schema or response_format, not both", status: 400 }, 400);
  }
  if (body.prompt === undefined && body.schema === undefined && body.response_format === undefined) {
    return c.json({ error: "One of prompt, schema, or response_format is required", status: 400 }, 400);
  }

  const api = new CfBrowserApi(c.env.CF_ACCOUNT_ID, c.env.CF_API_TOKEN);
  const { no_cache: _skip, ...cfBody } = body;
  if (cfBody.schema !== undefined) {
    cfBody.response_format = {
      type: "json_schema",
      json_schema: cfBody.schema,
    };
    delete cfBody.schema;
  }
  const cfPayload = mapToCfParams(cfBody);
  const result = await api.json(cfPayload);

  if (!result.ok) {
    return c.json({ error: result.message, status: result.status }, result.status as 502);
  }

  c.header("X-Cache", "BYPASS");
  return c.json(result.data);
});

export default app;
