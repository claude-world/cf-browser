/**
 * Cloudflare Browser Rendering REST API client.
 *
 * Uses the high-level REST endpoints which provide AI extraction,
 * async crawl, and server-side rendering without Worker CPU cost.
 *
 * Docs: https://developers.cloudflare.com/browser-rendering/rest-api/
 */

export type CfApiResponse<T> =
  | { ok: true; data: T; contentType: string }
  | { ok: false; status: number; message: string };

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
    body?: Record<string, unknown>
  ): Promise<CfApiResponse<T>> {
    try {
      const res = await fetch(`${this.baseUrl}${endpoint}`, {
        method,
        headers: this.headers(),
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(55_000),
      });

      if (!res.ok) {
        const rawText = await res.text().catch(() => res.statusText);
        // Try to extract nested error from CF API response
        let message = rawText;
        try {
          const parsed = JSON.parse(rawText);
          message = parsed.errors?.[0]?.message ?? parsed.error ?? rawText;
        } catch { /* keep raw text */ }
        return { ok: false, status: res.status, message };
      }

      const contentType = res.headers.get("content-type") ?? "application/octet-stream";

      // Binary responses: screenshot (PNG), PDF
      if (contentType.includes("image/") || contentType.includes("application/pdf")) {
        const data = await res.arrayBuffer();
        return { ok: true, data: data as T, contentType };
      }

      // JSON responses — CF API often wraps results in { success, result }
      if (contentType.includes("application/json")) {
        const json = (await res.json()) as Record<string, unknown>;
        // Unwrap CF API envelope if present
        const data = (json.success !== undefined && json.result !== undefined)
          ? json.result as T
          : json as T;
        return { ok: true, data, contentType };
      }

      // Plain text / HTML / Markdown
      const data = (await res.text()) as T;
      return { ok: true, data, contentType };
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown fetch error";
      return { ok: false, status: 502, message };
    }
  }

  async content(body: Record<string, unknown>): Promise<CfApiResponse<string>> {
    return this.request<string>("POST", "/content", body);
  }

  async screenshot(body: Record<string, unknown>): Promise<CfApiResponse<ArrayBuffer>> {
    return this.request<ArrayBuffer>("POST", "/screenshot", body);
  }

  async pdf(body: Record<string, unknown>): Promise<CfApiResponse<ArrayBuffer>> {
    return this.request<ArrayBuffer>("POST", "/pdf", body);
  }

  async markdown(body: Record<string, unknown>): Promise<CfApiResponse<string>> {
    return this.request<string>("POST", "/markdown", body);
  }

  async snapshot(body: Record<string, unknown>): Promise<CfApiResponse<unknown>> {
    return this.request<unknown>("POST", "/snapshot", body);
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

  async crawl(body: Record<string, unknown>): Promise<CfApiResponse<unknown>> {
    return this.request<unknown>("POST", "/crawl", body);
  }

  async getCrawlStatus(jobId: string): Promise<CfApiResponse<unknown>> {
    return this.request<unknown>("GET", `/crawl/${jobId}`);
  }
}
