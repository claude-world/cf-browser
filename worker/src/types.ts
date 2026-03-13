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

// Base request body all POST routes accept
export type BaseRequestBody = {
  url: string;
  no_cache?: boolean;
  cookies?: CookieParam[];       // inject cookies before page load
  headers?: Record<string, string>; // custom HTTP headers
};

// Endpoint-specific option types

export type ContentRequestBody = BaseRequestBody & {
  wait_for?: string;   // CSS selector to wait for
  timeout?: number;
};

export type ScreenshotRequestBody = BaseRequestBody & {
  width?: number;
  height?: number;
  full_page?: boolean;
  wait_for?: string;
  timeout?: number;
};

export type PdfRequestBody = BaseRequestBody & {
  format?: "A4" | "Letter" | "A3" | "A5" | "Legal" | "Tabloid";
  landscape?: boolean;
  wait_for?: string;
  timeout?: number;
};

export type MarkdownRequestBody = BaseRequestBody & {
  wait_for?: string;
  timeout?: number;
};

export type SnapshotRequestBody = BaseRequestBody & {
  wait_for?: string;
  timeout?: number;
};

export type ScrapeRequestBody = BaseRequestBody & {
  elements?: string[];  // CSS selectors to extract
  wait_for?: string;
  timeout?: number;
};

export type JsonRequestBody = BaseRequestBody & {
  schema?: Record<string, unknown>;
  prompt?: string;
  wait_for?: string;
  timeout?: number;
};

export type LinksRequestBody = BaseRequestBody & {
  wait_for?: string;
  timeout?: number;
  include_external?: boolean;
};

export type CrawlRequestBody = BaseRequestBody & {
  limit?: number;       // max pages to crawl (CF API param)
  max_pages?: number;   // alias for limit (user-friendly)
  timeout?: number;
};

export type A11yRequestBody = BaseRequestBody & {
  wait_for?: string;
  timeout?: number;
};

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
