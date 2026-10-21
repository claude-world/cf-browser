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

  it.each([
    "http://198.18.0.1/", // benchmark network
    "http://224.0.0.1/", // multicast
    "http://240.0.0.1/", // reserved for future use
    "http://[ff02::1]/", // IPv6 multicast
    "http://[2001:db8::1]/", // IPv6 documentation range
  ])("blocks non-public IP literal %s", (url) => {
    expect(validateUrl(url)).toEqual({
      valid: false,
      error: "URL targets a private IP address",
    });
  });

  it.each([
    "https://93.184.216.34/",
    "https://[2606:4700:4700::1111]/",
  ])("allows globally routable IP literal %s", (url) => {
    expect(validateUrl(url)).toEqual({ valid: true });
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

  it.each(["::1", "0:0:0:0:0:0:0:1"])(
    "blocks hostnames that resolve to IPv6 loopback %s",
    async (loopback) => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        const type = new URL(url).searchParams.get("type");
        const answer = type === "AAAA" ? [{ data: loopback }] : [];
        return new Response(JSON.stringify({ Status: 0, Answer: answer }), {
          status: 200,
          headers: { "Content-Type": "application/dns-json" },
        });
      });
      vi.stubGlobal("fetch", fetchMock);

      await expect(validateUrlWithDns("https://loopback-v6.example")).resolves.toEqual({
        valid: false,
        error: "URL hostname resolves to a private IP address",
      });
    },
  );

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

  it("fails closed when DNS returns no A or AAAA address", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ Status: 0, Answer: [] }),
      { status: 200, headers: { "Content-Type": "application/dns-json" } },
    )));

    await expect(validateUrlWithDns("https://missing.example")).resolves.toEqual({
      valid: false,
      error: "Unable to validate URL hostname resolution",
    });
  });

  it("ignores CNAME records and requires a public address answer", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ Status: 0, Answer: [{ data: "alias.example." }] }),
      { status: 200, headers: { "Content-Type": "application/dns-json" } },
    )));

    await expect(validateUrlWithDns("https://cname-only.example")).resolves.toEqual({
      valid: false,
      error: "Unable to validate URL hostname resolution",
    });
  });

  it.each(["198.18.0.1", "239.255.255.250", "ff02::1"])(
    "blocks hostnames that resolve to non-public address %s",
    async (address) => {
      vi.stubGlobal("fetch", vi.fn(async () => new Response(
        JSON.stringify({ Status: 0, Answer: [{ data: address }] }),
        { status: 200, headers: { "Content-Type": "application/dns-json" } },
      )));

      await expect(validateUrlWithDns("https://non-public.example")).resolves.toEqual({
        valid: false,
        error: "URL hostname resolves to a private IP address",
      });
    },
  );
});
