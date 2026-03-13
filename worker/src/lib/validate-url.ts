/**
 * Validate that a URL is safe to forward to the CF Browser Rendering API.
 * Only allows http: and https: schemes to prevent SSRF via file:/data:/etc.
 */
export function validateUrl(url: string): { valid: true } | { valid: false; error: string } {
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return { valid: false, error: "Only http and https URLs are supported" };
    }
    return { valid: true };
  } catch {
    return { valid: false, error: "Invalid URL format" };
  }
}
