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

export function normalizeScrapeResponse(data: unknown): ScrapeResponse {
  if (isRecord(data) && Array.isArray(data.elements)) {
    return { ...data, elements: data.elements } as ScrapeResponse;
  }

  if (Array.isArray(data)) {
    return { elements: data };
  }

  return { elements: [] };
}

export function normalizeLinksResponse(data: unknown): LinkResponse[] {
  const links = Array.isArray(data)
    ? data
    : isRecord(data) && Array.isArray(data.links)
      ? data.links
      : [];

  return links.flatMap((item) => {
    if (typeof item === "string") {
      return [{ href: item, text: null }];
    }

    if (isRecord(item) && typeof item.href === "string") {
      return [
        {
          ...item,
          href: item.href,
          text: typeof item.text === "string" ? item.text : null,
        } as LinkResponse,
      ];
    }

    return [];
  });
}
