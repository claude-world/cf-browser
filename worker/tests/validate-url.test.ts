import { afterEach, describe, expect, it, vi } from "vitest";
import { validateUrl, validateUrlWithDns } from "../src/lib/validate-url.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("validateUrl", () => {
  it("blocks obvious private hosts synchronously", () => {
    expect(validateUrl("http://127.0.0.1/admin")).toEqual({
      valid: false,
      error: "URL targets a blocked host",
    });
  });

  it("blocks the full IPv4 loopback range", () => {
    for (const url of [
      "http://127.0.0.2/admin",
      "http://127.1.2.3/admin",
    ]) {
      expect(validateUrl(url)).toEqual({
        valid: false,
        error: "URL targets a private IP address",
      });
    }
  });
});

describe("validateUrlWithDns", () => {
  it("blocks hostnames that resolve to private IPs", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      const type = new URL(url).searchParams.get("type");
      const answer = type === "A" ? [{ data: "127.0.0.1" }] : [];
      return new Response(JSON.stringify({ Status: 0, Answer: answer }), {
        status: 200,
        headers: { "Content-Type": "application/dns-json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(validateUrlWithDns("https://internal.example")).resolves.toEqual({
      valid: false,
      error: "URL hostname resolves to a private IP address",
    });
  });

  it("blocks hostnames that resolve to non-127.0.0.1 loopback IPs", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      const type = new URL(url).searchParams.get("type");
      const answer = type === "A" ? [{ data: "127.0.0.2" }] : [];
      return new Response(JSON.stringify({ Status: 0, Answer: answer }), {
        status: 200,
        headers: { "Content-Type": "application/dns-json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(validateUrlWithDns("https://loopback.example")).resolves.toEqual({
      valid: false,
      error: "URL hostname resolves to a private IP address",
    });
  });

  it("allows hostnames that resolve to public IPs", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({ Status: 0, Answer: [{ data: "93.184.216.34" }] }),
        {
          status: 200,
          headers: { "Content-Type": "application/dns-json" },
        },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(validateUrlWithDns("https://example.com")).resolves.toEqual({
      valid: true,
    });
  });
});
