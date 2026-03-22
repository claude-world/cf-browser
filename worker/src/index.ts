import { Hono } from "hono";
import { cors } from "hono/cors";
import type { AppEnv } from "./types.js";
import { authMiddleware } from "./middleware/auth.js";
import { rateLimitMiddleware } from "./middleware/rate-limit.js";
import contentRoute from "./routes/content.js";
import screenshotRoute from "./routes/screenshot.js";
import pdfRoute from "./routes/pdf.js";
import markdownRoute from "./routes/markdown.js";
import snapshotRoute from "./routes/snapshot.js";
import scrapeRoute from "./routes/scrape.js";
import jsonRoute from "./routes/json.js";
import linksRoute from "./routes/links.js";
import crawlRoute from "./routes/crawl.js";
import a11yRoute from "./routes/a11y.js";
import clickRoute from "./routes/click.js";
import typeRoute from "./routes/type.js";
import evaluateRoute from "./routes/evaluate.js";
import interactRoute from "./routes/interact.js";
import submitFormRoute from "./routes/submit-form.js";

const app = new Hono<AppEnv>();

// ---------------------------------------------------------------------------
// Global middleware
// ---------------------------------------------------------------------------

// CORS: wildcard origin is intentional for this API-style Worker.
// All endpoints require Bearer token auth, so unauthenticated cross-origin
// requests are rejected regardless. Teams needing tighter CORS should
// replace "*" with their specific origin domain.
app.use(
  "*",
  cors({
    origin: "*",
    allowMethods: ["GET", "POST", "DELETE", "OPTIONS"],
    allowHeaders: ["Authorization", "Content-Type"],
    exposeHeaders: ["X-Cache", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
  })
);

// ---------------------------------------------------------------------------
// Health check (no auth)
// ---------------------------------------------------------------------------

app.get("/health", (c) => {
  return c.json({
    status: "ok",
    version: "2.0.1",
    capabilities: {
      interact: !!c.env.BROWSER,
    },
  });
});

// ---------------------------------------------------------------------------
// Authenticated + rate-limited routes
// ---------------------------------------------------------------------------

// Read-only routes
app.use("/content/*", authMiddleware, rateLimitMiddleware);
app.use("/screenshot/*", authMiddleware, rateLimitMiddleware);
app.use("/pdf/*", authMiddleware, rateLimitMiddleware);
app.use("/markdown/*", authMiddleware, rateLimitMiddleware);
app.use("/snapshot/*", authMiddleware, rateLimitMiddleware);
app.use("/scrape/*", authMiddleware, rateLimitMiddleware);
app.use("/json/*", authMiddleware, rateLimitMiddleware);
app.use("/links/*", authMiddleware, rateLimitMiddleware);
app.use("/crawl/*", authMiddleware, rateLimitMiddleware);
app.use("/a11y/*", authMiddleware, rateLimitMiddleware);

// Interaction routes (require BROWSER binding)
app.use("/click/*", authMiddleware, rateLimitMiddleware);
app.use("/type/*", authMiddleware, rateLimitMiddleware);
app.use("/evaluate/*", authMiddleware, rateLimitMiddleware);
app.use("/interact/*", authMiddleware, rateLimitMiddleware);
app.use("/submit-form/*", authMiddleware, rateLimitMiddleware);

// ---------------------------------------------------------------------------
// Route handlers
// ---------------------------------------------------------------------------

// Read-only
app.route("/content", contentRoute);
app.route("/screenshot", screenshotRoute);
app.route("/pdf", pdfRoute);
app.route("/markdown", markdownRoute);
app.route("/snapshot", snapshotRoute);
app.route("/scrape", scrapeRoute);
app.route("/json", jsonRoute);
app.route("/links", linksRoute);
app.route("/crawl", crawlRoute);
app.route("/a11y", a11yRoute);

// Interaction
app.route("/click", clickRoute);
app.route("/type", typeRoute);
app.route("/evaluate", evaluateRoute);
app.route("/interact", interactRoute);
app.route("/submit-form", submitFormRoute);

// ---------------------------------------------------------------------------
// 404 fallback
// ---------------------------------------------------------------------------

app.notFound((c) => {
  return c.json({ error: "Not found", status: 404 }, 404);
});

// ---------------------------------------------------------------------------
// Global error handler
// ---------------------------------------------------------------------------

app.onError((err, c) => {
  console.error("Unhandled error:", err);
  const message = err instanceof Error ? err.message : "Internal server error";
  return c.json({ error: message, status: 500 }, 500);
});

export default app;
