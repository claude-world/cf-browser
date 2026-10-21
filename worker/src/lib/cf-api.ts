/**
 * Cloudflare Browser Run REST API client (API namespace: browser-rendering).
 *
 * Uses the high-level REST endpoints which provide AI extraction,
 * async crawl, and server-side rendering without Worker CPU cost.
 *
 * Docs: https://developers.cloudflare.com/browser-run/
 */

import { validateUrlWithDns } from "./validate-url.js";

export type CfApiResponse<T> =
  | { ok: true; data: T; contentType: string }
  | { ok: false; status: number; message: string };

export type CrawlStatusQuery = {
  cursor?: string | number;
  limit?: number;
  status?: "queued" | "errored" | "completed" | "disallowed" | "skipped" | "cancelled";
};

export type CrawlCreateQuery = {
  cacheTTL?: number;
};

const QUICK_ACTION_TIMEOUT_MS = 130_000;
const PDF_TIMEOUT_MS = 310_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function apiErrorMessage(value: unknown, fallback: string): string {
  if (!isRecord(value)) return fallback;
  const errors = value.errors;
  if (Array.isArray(errors) && isRecord(errors[0]) && typeof errors[0].message === "string") {
    return errors[0].message;
  }
  if (typeof value.error === "string") return value.error;
  if (typeof value.message === "string") return value.message;
  return fallback;
}

function nestedResourceUrls(body: Record<string, unknown>): string[] {
  const urls: string[] = [];
  for (const field of ["addScriptTag", "addStyleTag"]) {
    const resources = body[field];
    if (!Array.isArray(resources)) continue;
    for (const resource of resources) {
      if (isRecord(resource) && typeof resource.url === "string") urls.push(resource.url);
    }
  }
  return urls;
}

function startsWithBytes(data: ArrayBuffer, prefix: readonly number[]): boolean {
  const bytes = new Uint8Array(data);
  return bytes.length >= prefix.length && prefix.every((value, index) => bytes[index] === value);
}

function isScreenshotBytes(data: ArrayBuffer): boolean {
  const bytes = new Uint8Array(data);
  return startsWithBytes(data, [0x89, 0x50, 0x4e, 0x47]) ||
    startsWithBytes(data, [0xff, 0xd8, 0xff]) ||
    bytes.length >= 12 &&
      startsWithBytes(data, [0x52, 0x49, 0x46, 0x46]) &&
      bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50;
}

function isPdfBytes(data: ArrayBuffer): boolean {
  return startsWithBytes(data, [0x25, 0x50, 0x44, 0x46, 0x2d]);
}

export class CfBrowserApi {
  private readonly baseUrl: string;
  private readonly apiToken: string;

  constructor(accountId: string, apiToken: string) {
    this.baseUrl = `https://api.cloudflare.com/client/v4/accounts/${accountId}/browser-rendering`;
    this.apiToken = apiToken;
  }

  private headers(): HeadersInit {
    return {
      Authorization: `Bearer ${this.apiToken}`,
      "Content-Type": "application/json",
    };
  }

  private async request<T>(
    method: string,
    endpoint: string,
    body?: Record<string, unknown>,
    timeoutMs = QUICK_ACTION_TIMEOUT_MS,
  ): Promise<CfApiResponse<T>> {
    try {
      if (body) {
        const urls = [
          ...(typeof body.url === "string" ? [body.url] : []),
          ...nestedResourceUrls(body),
        ];
        const dnsCache = new Map<string, Promise<string[]>>();
        for (const url of urls) {
          const urlCheck = await validateUrlWithDns(url, dnsCache);
          if (!urlCheck.valid) {
            return { ok: false, status: 400, message: urlCheck.error };
          }
        }
      }

      const res = await fetch(`${this.baseUrl}${endpoint}`, {
        method,
        headers: this.headers(),
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(timeoutMs),
      });

      if (!res.ok) {
        const rawText = await res.text().catch(() => res.statusText);
        // Try to extract nested error from CF API response
        let message = rawText;
        try {
          message = apiErrorMessage(JSON.parse(rawText), rawText);
        } catch { /* keep raw text */ }
        return { ok: false, status: res.status, message: String(message).slice(0, 2_000) };
      }

      const contentType = res.headers.get("content-type") ?? "application/octet-stream";

      // Binary responses: screenshot (PNG), PDF
      if (contentType.includes("image/") || contentType.includes("application/pdf")) {
        const data = await res.arrayBuffer();
        return { ok: true, data: data as T, contentType };
      }

      // JSON responses — CF API often wraps results in { success, result }
      if (contentType.includes("application/json")) {
        const json = await res.json() as unknown;
        if (isRecord(json) && json.success === false) {
          return {
            ok: false,
            status: 502,
            message: apiErrorMessage(json, "Cloudflare API reported an unsuccessful response")
              .slice(0, 2_000),
          };
        }
        // Unwrap CF API envelope if present
        const data = (isRecord(json) && json.success !== undefined && json.result !== undefined)
          ? json.result as T
          : json as T;
        return { ok: true, data, contentType };
      }

      // Plain text / HTML / Markdown
      const data = (await res.text()) as T;
      return { ok: true, data, contentType };
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown fetch error";
      const status = err instanceof DOMException && err.name === "TimeoutError" ? 504 : 502;
      return { ok: false, status, message: String(message).slice(0, 2_000) };
    }
  }

  private async requestText(
    endpoint: string,
    body: Record<string, unknown>,
    label: string,
  ): Promise<CfApiResponse<string>> {
    const result = await this.request<unknown>("POST", endpoint, body);
    if (!result.ok) return result;
    if (typeof result.data !== "string") {
      return { ok: false, status: 502, message: `Cloudflare returned malformed ${label}` };
    }
    return { ...result, data: result.data };
  }

  private async requestBinary(
    endpoint: string,
    body: Record<string, unknown>,
    label: string,
    expectedContentType: (contentType: string) => boolean,
    expectedBytes: (data: ArrayBuffer) => boolean,
    timeoutMs = QUICK_ACTION_TIMEOUT_MS,
  ): Promise<CfApiResponse<ArrayBuffer>> {
    const result = await this.request<unknown>("POST", endpoint, body, timeoutMs);
    if (!result.ok) return result;
    if (
      !(result.data instanceof ArrayBuffer) ||
      !expectedContentType(result.contentType) ||
      !expectedBytes(result.data)
    ) {
      return { ok: false, status: 502, message: `Cloudflare returned malformed ${label}` };
    }
    return { ...result, data: result.data };
  }

  async content(body: Record<string, unknown>): Promise<CfApiResponse<string>> {
    return this.requestText("/content", body, "content");
  }

  async screenshot(body: Record<string, unknown>): Promise<CfApiResponse<ArrayBuffer>> {
    return this.requestBinary(
      "/screenshot",
      body,
      "screenshot",
      (contentType) => contentType.toLowerCase().startsWith("image/"),
      isScreenshotBytes,
    );
  }

  async pdf(body: Record<string, unknown>): Promise<CfApiResponse<ArrayBuffer>> {
    return this.requestBinary(
      "/pdf",
      body,
      "PDF",
      (contentType) => contentType.toLowerCase().includes("application/pdf"),
      isPdfBytes,
      PDF_TIMEOUT_MS,
    );
  }

  async markdown(body: Record<string, unknown>): Promise<CfApiResponse<string>> {
    return this.requestText("/markdown", body, "markdown");
  }

  async snapshot(body: Record<string, unknown>): Promise<CfApiResponse<unknown>> {
    return this.request<unknown>("POST", "/snapshot", body);
  }

  async accessibilityTree(body: Record<string, unknown>): Promise<CfApiResponse<unknown>> {
    return this.request<unknown>("POST", "/accessibilityTree", body);
  }

  async scrape(body: Record<string, unknown>): Promise<CfApiResponse<unknown>> {
    return this.request<unknown>("POST", "/scrape", body);
  }

  async json(body: Record<string, unknown>): Promise<CfApiResponse<unknown>> {
    return this.request<unknown>("POST", "/json", body);
  }

  async links(body: Record<string, unknown>): Promise<CfApiResponse<unknown>> {
    return this.request<unknown>("POST", "/links", body);
  }

  async crawl(
    body: Record<string, unknown>,
    query: CrawlCreateQuery = {},
  ): Promise<CfApiResponse<unknown>> {
    const params = new URLSearchParams();
    if (query.cacheTTL !== undefined) params.set("cacheTTL", String(query.cacheTTL));
    const suffix = params.size > 0 ? `?${params.toString()}` : "";
    return this.request<unknown>("POST", `/crawl${suffix}`, body);
  }

  async getCrawlStatus(
    jobId: string,
    query: CrawlStatusQuery = {},
  ): Promise<CfApiResponse<unknown>> {
    const params = new URLSearchParams();
    if (query.cursor !== undefined) params.set("cursor", String(query.cursor));
    if (query.limit !== undefined) params.set("limit", String(query.limit));
    if (query.status !== undefined) params.set("status", query.status);
    const suffix = params.size > 0 ? `?${params.toString()}` : "";
    return this.request<unknown>("GET", `/crawl/${jobId}${suffix}`);
  }

  async deleteCrawl(jobId: string): Promise<CfApiResponse<unknown>> {
    return this.request<unknown>("DELETE", `/crawl/${jobId}`);
  }

}
