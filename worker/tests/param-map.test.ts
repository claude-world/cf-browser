import { describe, it, expect } from "vitest";
import { mapToCfParams } from "../src/lib/param-map.js";

describe("mapToCfParams", () => {
  // -----------------------------------------------------------------------
  // wait_for → waitForSelector
  // -----------------------------------------------------------------------

  it("maps wait_for to waitForSelector", () => {
    const result = mapToCfParams({ url: "https://example.com", wait_for: ".main" });
    expect(result.waitForSelector).toEqual({ selector: ".main" });
    expect(result.wait_for).toBeUndefined();
  });

  it("preserves native waitForSelector object if present", () => {
    const result = mapToCfParams({ url: "https://example.com", waitForSelector: { selector: ".x" } });
    expect(result.waitForSelector).toEqual({ selector: ".x" });
  });

  // -----------------------------------------------------------------------
  // headers → setExtraHTTPHeaders
  // -----------------------------------------------------------------------

  it("maps headers to setExtraHTTPHeaders", () => {
    const h = { "X-Auth": "token" };
    const result = mapToCfParams({ url: "https://example.com", headers: h });
    expect(result.setExtraHTTPHeaders).toEqual(h);
    expect(result.headers).toBeUndefined();
  });

  // -----------------------------------------------------------------------
  // timeout → gotoOptions.timeout
  // -----------------------------------------------------------------------

  it("maps timeout to gotoOptions.timeout", () => {
    const result = mapToCfParams({ url: "https://example.com", timeout: 5000 });
    expect(result.gotoOptions).toEqual({ timeout: 5000 });
    expect(result.timeout).toBeUndefined();
  });

  // -----------------------------------------------------------------------
  // wait_until → gotoOptions.waitUntil
  // -----------------------------------------------------------------------

  it("maps wait_until to gotoOptions.waitUntil", () => {
    const result = mapToCfParams({ url: "https://example.com", wait_until: "networkidle0" });
    expect(result.gotoOptions).toEqual({ waitUntil: "networkidle0" });
    expect(result.wait_until).toBeUndefined();
  });

  it("merges timeout and wait_until into gotoOptions", () => {
    const result = mapToCfParams({
      url: "https://example.com",
      timeout: 3000,
      wait_until: "networkidle2",
    });
    expect(result.gotoOptions).toEqual({ timeout: 3000, waitUntil: "networkidle2" });
    expect(result.timeout).toBeUndefined();
    expect(result.wait_until).toBeUndefined();
  });

  it("merges into existing gotoOptions", () => {
    const result = mapToCfParams({
      url: "https://example.com",
      gotoOptions: { referer: "https://google.com" },
      timeout: 5000,
    });
    expect(result.gotoOptions).toEqual({
      referer: "https://google.com",
      timeout: 5000,
    });
  });

  // -----------------------------------------------------------------------
  // user_agent → userAgent
  // -----------------------------------------------------------------------

  it("maps user_agent to userAgent", () => {
    const result = mapToCfParams({ url: "https://example.com", user_agent: "MyBot/1.0" });
    expect(result.userAgent).toBe("MyBot/1.0");
    expect(result.user_agent).toBeUndefined();
  });

  // -----------------------------------------------------------------------
  // No-op / passthrough
  // -----------------------------------------------------------------------

  it("passes through unrelated params unchanged", () => {
    const result = mapToCfParams({ url: "https://example.com", cookies: [{ name: "a", value: "b" }] });
    expect(result.url).toBe("https://example.com");
    expect(result.cookies).toEqual([{ name: "a", value: "b" }]);
  });

  it("handles empty body with only url", () => {
    const result = mapToCfParams({ url: "https://example.com" });
    expect(result).toEqual({ url: "https://example.com" });
  });

  // -----------------------------------------------------------------------
  // All params together
  // -----------------------------------------------------------------------

  it("maps all params correctly when combined", () => {
    const result = mapToCfParams({
      url: "https://example.com",
      wait_for: ".loaded",
      headers: { "X-Token": "abc" },
      timeout: 10000,
      wait_until: "networkidle0",
      user_agent: "Bot/2.0",
      cookies: [{ name: "s", value: "v" }],
    });

    expect(result.waitForSelector).toEqual({ selector: ".loaded" });
    expect(result.setExtraHTTPHeaders).toEqual({ "X-Token": "abc" });
    expect(result.gotoOptions).toEqual({ timeout: 10000, waitUntil: "networkidle0" });
    expect(result.userAgent).toBe("Bot/2.0");
    expect(result.cookies).toEqual([{ name: "s", value: "v" }]);
    expect(result.url).toBe("https://example.com");

    // No snake_case originals remain
    expect(result.wait_for).toBeUndefined();
    expect(result.headers).toBeUndefined();
    expect(result.timeout).toBeUndefined();
    expect(result.wait_until).toBeUndefined();
    expect(result.user_agent).toBeUndefined();
  });

  it("does not mutate the input object", () => {
    const input = { url: "https://example.com", wait_for: ".x" };
    mapToCfParams(input);
    expect(input.wait_for).toBe(".x");
  });
});
