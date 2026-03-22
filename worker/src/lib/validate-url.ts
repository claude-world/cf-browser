/**
 * Validate that a URL is safe to forward to the CF Browser Rendering API.
 * Only allows http: and https: schemes to prevent SSRF via file:/data:/etc.
 *
 * Note on DNS rebinding: for REST API routes the actual fetch is performed by
 * Cloudflare's infrastructure, not by this Worker.  We validate the URL
 * statically here; Puppeteer routes additionally intercept every sub-request
 * via `page.setRequestInterception` for runtime SSRF protection.
 */

// Block private/internal targets to prevent SSRF
// URL.hostname keeps brackets for IPv6: http://[::1]/ → "[::1]"
const BLOCKED_HOSTS = new Set([
  'localhost',
  '127.0.0.1',
  '[::1]',
  '0.0.0.0',
]);

export function validateUrl(url: string): { valid: true } | { valid: false; error: string } {
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return { valid: false, error: "Only http and https URLs are supported" };
    }

    // Check for blocked hostnames
    if (BLOCKED_HOSTS.has(parsed.hostname)) {
      return { valid: false, error: "URL targets a blocked host" };
    }

    // Block private IP ranges:
    //   0.x, 10.x, 172.16-31.x, 192.168.x, 169.254.x (link-local)
    //   100.64-127.x (CGNAT / RFC 6598)
    const ip = parsed.hostname;
    if (/^(0\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)/.test(ip)) {
      return { valid: false, error: "URL targets a private IP address" };
    }

    // Block IPv6 private/link-local/site-local ranges, IPv4-mapped, and NAT64
    // URL.hostname keeps brackets: [fc00::1], [fe80::1], [::ffff:7f00:1]
    const bare = ip.replace(/^\[|\]$/g, ""); // strip brackets for regex matching
    if (
      /^(fc|fd|fe[89a-f])/i.test(bare) ||   // ULA (fc00::/7) + link-local (fe80::/10) + site-local (fec0::/10)
      /^::ffff:/i.test(bare) ||              // IPv4-mapped IPv6 (::ffff:0:0/96)
      /^64:ff9b:/i.test(bare) ||             // NAT64 prefixes (64:ff9b::/96 + 64:ff9b:1::/48)
      /^[0:]+$/.test(bare)                   // unspecified address (::, ::0, 0:0:0:0:0:0:0:0, etc.)
    ) {
      return { valid: false, error: "URL targets a private IP address" };
    }

    return { valid: true };
  } catch {
    return { valid: false, error: "Invalid URL format" };
  }
}
