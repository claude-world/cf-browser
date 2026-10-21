import type { Page } from "@cloudflare/puppeteer";

export const MAX_INTERACTION_OUTPUT_BYTES = 8 * 1024 * 1024;
export const MAX_INTERACTION_ERROR_BYTES = 8 * 1024;
export const INTERACTION_OUTPUT_LIMIT_ERROR = "Interaction output byte limit exceeded";

export class InteractionOutputLimitError extends Error {
  constructor() {
    super(INTERACTION_OUTPUT_LIMIT_ERROR);
    this.name = "InteractionOutputLimitError";
  }
}

export function serializedByteLength(value: unknown): number {
  try {
    const serialized = JSON.stringify(value);
    return serialized === undefined ? 0 : new TextEncoder().encode(serialized).byteLength;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

export function assertInteractionOutputSize<T>(value: T): T {
  if (serializedByteLength(value) > MAX_INTERACTION_OUTPUT_BYTES) {
    throw new InteractionOutputLimitError();
  }
  return value;
}

export async function boundedPageState(page: Page): Promise<{
  url: string;
  title: string;
  content: string;
}> {
  return assertInteractionOutputSize({
    url: page.url(),
    title: await page.title(),
    content: await page.content(),
  });
}

export function truncateUtf8(value: string, maxBytes: number): { value: string; truncated: boolean } {
  const encoder = new TextEncoder();
  if (encoder.encode(value).byteLength <= maxBytes) return { value, truncated: false };

  let low = 0;
  let high = value.length;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (encoder.encode(value.slice(0, middle)).byteLength <= maxBytes) low = middle;
    else high = middle - 1;
  }
  let end = low;
  if (end > 0 && /[\uD800-\uDBFF]/.test(value[end - 1]!)) end -= 1;
  return { value: value.slice(0, end), truncated: true };
}

/**
 * Browser errors can contain attacker-controlled page or script text. Keep all
 * interaction error responses bounded before they are serialized by Hono.
 */
export function boundedInteractionErrorMessage(error: unknown, fallback: string): string {
  const raw = error instanceof Error && error.message.length > 0 ? error.message : fallback;
  if (serializedByteLength(raw) <= MAX_INTERACTION_ERROR_BYTES) return raw;

  let low = 0;
  let high = raw.length;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (serializedByteLength(raw.slice(0, middle)) <= MAX_INTERACTION_ERROR_BYTES) low = middle;
    else high = middle - 1;
  }
  let end = low;
  if (end > 0 && /[\uD800-\uDBFF]/.test(raw[end - 1]!)) end -= 1;
  return raw.slice(0, end);
}
