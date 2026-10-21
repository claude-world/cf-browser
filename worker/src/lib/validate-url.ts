/**
 * Validate that a URL is safe to forward to the Cloudflare Browser Run API.
 * Only allows http: and https: schemes to prevent SSRF via file:/data:/etc.
 *
 * Note on DNS rebinding: for REST API routes the actual fetch is performed by
 * Cloudflare's infrastructure, not by this Worker.  We validate the URL
 * statically here; Puppeteer routes additionally intercept every sub-request
 * via `page.setRequestInterception` for runtime SSRF protection.
 */

export type UrlValidationResult = { valid: true } | { valid: false; error: string };

// Block private/internal targets to prevent SSRF.
// URL.hostname keeps brackets for IPv6: http://[::1]/ → "[::1]"
const BLOCKED_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "[::1]",
  "0.0.0.0",
]);

const PRIVATE_IP_ERROR = "URL targets a private IP address";
const PRIVATE_HOST_ERROR = "URL targets a blocked host";
const PRIVATE_DNS_ERROR = "URL hostname resolves to a private IP address";
const DNS_LOOKUP_ERROR = "Unable to validate URL hostname resolution";
const DNS_ENDPOINT = "https://cloudflare-dns.com/dns-query";
const DNS_TIMEOUT_MS = 3_000;

function parseIpv4(host: string): number[] | null {
  if (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(host)) return null;
  const octets = host.split(".").map(Number);
  return octets.every((octet) => octet >= 0 && octet <= 255) ? octets : null;
}

function parseIpv6(host: string): number[] | null {
  let bare = host.replace(/^\[|\]$/g, "").toLowerCase();
  if (!bare.includes(":") || bare.includes("%")) return null;

  // Convert an embedded IPv4 tail (for example ::ffff:192.0.2.1) into two
  // hexadecimal groups before expanding the IPv6 address.
  if (bare.includes(".")) {
    const lastColon = bare.lastIndexOf(":");
    const ipv4 = parseIpv4(bare.slice(lastColon + 1));
    if (lastColon < 0 || ipv4 === null) return null;
    bare = `${bare.slice(0, lastColon)}:${((ipv4[0]! << 8) | ipv4[1]!).toString(16)}:${(
      (ipv4[2]! << 8) | ipv4[3]!
    ).toString(16)}`;
  }

  if ((bare.match(/::/g) ?? []).length > 1) return null;
  const [leftRaw, rightRaw] = bare.split("::");
  const left = leftRaw ? leftRaw.split(":") : [];
  const right = rightRaw ? rightRaw.split(":") : [];
  if ([...left, ...right].some((group) => !/^[0-9a-f]{1,4}$/.test(group))) return null;

  const compressed = bare.includes("::");
  const missing = 8 - left.length - right.length;
  if ((compressed && missing < 1) || (!compressed && missing !== 0)) return null;
  return [...left, ...Array(compressed ? missing : 0).fill("0"), ...right].map((group) =>
    Number.parseInt(group, 16)
  );
}

function isIpLiteral(host: string): boolean {
  return parseIpv4(host) !== null || parseIpv6(host) !== null;
}

function isPrivateIpLiteral(host: string): boolean {
  if (BLOCKED_HOSTS.has(host)) {
    return true;
  }

  const ipv4 = parseIpv4(host);
  if (ipv4 !== null) {
    const a = ipv4[0]!;
    const b = ipv4[1]!;
    const c = ipv4[2]!;
    // Reject every commonly allocated non-global IPv4 range from the IANA
    // special-purpose registry, including benchmark, documentation,
    // multicast, and reserved networks. Public unicast addresses pass.
    return (
      a === 0 ||
      a === 10 ||
      a === 127 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 0 && c === 0 && ipv4[3]! !== 9 && ipv4[3]! !== 10) ||
      (a === 192 && b === 0 && c === 2) ||
      (a === 192 && b === 88 && c === 99) ||
      (a === 192 && b === 168) ||
      (a === 198 && (b === 18 || b === 19)) ||
      (a === 198 && b === 51 && c === 100) ||
      (a === 203 && b === 0 && c === 113) ||
      a >= 224
    );
  }

  const ipv6 = parseIpv6(host);
  if (ipv6 === null) return false;
  const first = ipv6[0]!;
  const second = ipv6[1]!;

  // Fail closed to IPv6 global unicast (2000::/3), then exclude special-use
  // sub-ranges inside it. This also rejects multicast, ULA, link-local,
  // unspecified, mapped IPv4, NAT64, and deprecated site-local addresses.
  if ((first & 0xe000) !== 0x2000) return true;
  return (
    (first === 0x2001 && second === 0) || // Teredo
    (first === 0x2001 && second === 2 && ipv6[2]! === 0) || // benchmarking
    (first === 0x2001 && ((second & 0xfff0) === 0x0010 || (second & 0xfff0) === 0x0020)) ||
    (first === 0x2001 && second === 0x0db8) || // documentation
    first === 0x2002 || // 6to4 (embeds an IPv4 target)
    (first === 0x3fff && (second & 0xf000) === 0) // 3fff::/20 documentation
  );
}

function validateParsedUrl(parsed: URL): UrlValidationResult {
  if (!["http:", "https:"].includes(parsed.protocol)) {
    return { valid: false, error: "Only http and https URLs are supported" };
  }

  if (BLOCKED_HOSTS.has(parsed.hostname)) {
    return { valid: false, error: PRIVATE_HOST_ERROR };
  }

  if (isPrivateIpLiteral(parsed.hostname)) {
    return { valid: false, error: PRIVATE_IP_ERROR };
  }

  return { valid: true };
}

async function resolveHostname(
  hostname: string,
  cache: Map<string, Promise<string[]>> = new Map(),
): Promise<string[]> {
  const cacheKey = hostname.toLowerCase();
  const cached = cache.get(cacheKey);
  if (cached) {
    return cached;
  }

  const lookup = (async () => {
    const recordTypes = ["A", "AAAA"];
    const settled = await Promise.all(
      recordTypes.map(async (type) => {
        const params = new URLSearchParams({ name: hostname, type });
        const response = await fetch(`${DNS_ENDPOINT}?${params.toString()}`, {
          headers: { Accept: "application/dns-json" },
          signal: AbortSignal.timeout(DNS_TIMEOUT_MS),
        });

        if (!response.ok) {
          throw new Error(`DNS lookup failed with HTTP ${response.status}`);
        }

        const payload = await response.json<{
          Answer?: Array<{ data?: unknown }>;
        }>();

        return (payload.Answer ?? [])
          .map((answer) => answer.data)
          .filter((answer): answer is string => typeof answer === "string");
      }),
    );

    return settled.flat();
  })();

  cache.set(cacheKey, lookup);
  return lookup;
}

export function validateUrl(url: string): UrlValidationResult {
  try {
    const parsed = new URL(url);
    return validateParsedUrl(parsed);
  } catch {
    return { valid: false, error: "Invalid URL format" };
  }
}

export async function validateUrlWithDns(
  url: string,
  cache?: Map<string, Promise<string[]>>,
): Promise<UrlValidationResult> {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { valid: false, error: "Invalid URL format" };
  }

  const staticCheck = validateParsedUrl(parsed);
  if (!staticCheck.valid) {
    return staticCheck;
  }

  if (isIpLiteral(parsed.hostname)) {
    return staticCheck;
  }

  try {
    const answers = await resolveHostname(parsed.hostname, cache);
    const addressAnswers = answers.filter((answer) => isIpLiteral(answer));
    if (addressAnswers.length === 0) {
      return { valid: false, error: DNS_LOOKUP_ERROR };
    }
    if (addressAnswers.some((answer) => isPrivateIpLiteral(answer))) {
      return { valid: false, error: PRIVATE_DNS_ERROR };
    }
    return { valid: true };
  } catch {
    return { valid: false, error: DNS_LOOKUP_ERROR };
  }
}
