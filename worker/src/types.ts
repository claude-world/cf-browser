export type Env = {
  CF_ACCOUNT_ID: string;
  CF_API_TOKEN: string;
  API_KEYS: string; // comma-separated valid API keys
  CACHE: KVNamespace;
  RATE_LIMIT: KVNamespace;
  STORAGE: R2Bucket;
};

export type Variables = {
  apiKey: string;
};

export type AppEnv = { Bindings: Env; Variables: Variables };

// Optional cookies for authenticated browsing
export type CookieParam = {
  name: string;
  value: string;
  domain?: string;
  path?: string;
  secure?: boolean;
  httpOnly?: boolean;
  sameSite?: "Strict" | "Lax" | "None";
};

// Base request body all POST routes accept.
//
// User-facing params use snake_case; mapToCfParams() translates them
// to the camelCase equivalents the CF Browser Rendering REST API expects:
//   wait_for   → waitForSelector
//   headers    → setExtraHTTPHeaders
//   timeout    → gotoOptions.timeout
//   wait_until → gotoOptions.waitUntil
//   user_agent → userAgent
export type BaseRequestBody = {
  url: string;
  no_cache?: boolean;
  cookies?: CookieParam[];              // inject cookies before page load
  headers?: Record<string, string>;     // → setExtraHTTPHeaders
  wait_for?: string;                    // → waitForSelector
  timeout?: number;                     // → gotoOptions.timeout
  wait_until?: string;                  // → gotoOptions.waitUntil
  user_agent?: string;                  // → userAgent
};

// Endpoint-specific option types

export type ContentRequestBody = BaseRequestBody;

export type ScreenshotRequestBody = BaseRequestBody & {
  width?: number;
  height?: number;
  full_page?: boolean;
};

export type PdfRequestBody = BaseRequestBody & {
  format?: "A4" | "Letter" | "A3" | "A5" | "Legal" | "Tabloid";
  landscape?: boolean;
};

export type MarkdownRequestBody = BaseRequestBody;

export type SnapshotRequestBody = BaseRequestBody;

export type ScrapeRequestBody = BaseRequestBody & {
  elements?: string[];  // CSS selectors to extract
};

export type JsonRequestBody = BaseRequestBody & {
  schema?: Record<string, unknown>;
  prompt?: string;
};

export type LinksRequestBody = BaseRequestBody & {
  include_external?: boolean;
};

export type CrawlRequestBody = BaseRequestBody & {
  limit?: number;       // max pages to crawl (CF API param)
  max_pages?: number;   // alias for limit (user-friendly)
};

export type A11yRequestBody = BaseRequestBody;

// Unified error response
export type ErrorResponse = {
  error: string;
  status: number;
};

// Cache metadata stored alongside KV entries
export type CacheMeta = {
  content_type: string;
  cached_at: number;
  ttl: number;
};
