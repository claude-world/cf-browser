/**
 * Validate that a URL is safe to forward to the CF Browser Rendering API.
 * Only allows http: and https: schemes to prevent SSRF via file:/data:/etc.
 */

// Block private/internal targets to prevent SSRF
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

    // Block private IP ranges (10.x, 172.16-31.x, 192.168.x, 169.254.x)
    const ip = parsed.hostname;
    if (/^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.)/.test(ip)) {
      return { valid: false, error: "URL targets a private IP address" };
    }

    return { valid: true };
  } catch {
    return { valid: false, error: "Invalid URL format" };
  }
}
