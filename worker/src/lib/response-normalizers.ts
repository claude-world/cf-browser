type ScrapeResponse = {
  elements: unknown[];
};

type LinkResponse = {
  href: string;
  text: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function normalizeScrapeResponse(data: unknown): ScrapeResponse | null {
  if (
    isRecord(data) && Array.isArray(data.elements) &&
    data.elements.every((item) => isRecord(item))
  ) {
    return { ...data, elements: data.elements } as ScrapeResponse;
  }

  if (Array.isArray(data) && data.every((item) => isRecord(item))) {
    return { elements: data };
  }

  return null;
}

export function normalizeLinksResponse(data: unknown): LinkResponse[] | null {
  const links: unknown[] | null = Array.isArray(data)
    ? data
    : isRecord(data) && Array.isArray(data.links)
      ? data.links
      : null;

  if (links === null) return null;

  const normalized: LinkResponse[] = [];
  for (const item of links) {
    if (typeof item === "string") {
      normalized.push({ href: item, text: null });
      continue;
    }

    if (isRecord(item) && typeof item.href === "string") {
      if (item.text !== undefined && item.text !== null && typeof item.text !== "string") {
        return null;
      }
      normalized.push({
        ...item,
        href: item.href,
        text: typeof item.text === "string" ? item.text : null,
      } as LinkResponse);
      continue;
    }

    return null;
  }
  return normalized;
}
