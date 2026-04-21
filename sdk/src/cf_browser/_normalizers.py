"""Normalize Worker/CF API response shapes into the SDK contract."""
from __future__ import annotations

from typing import Any


def normalize_scrape_response(data: Any) -> dict[str, Any]:
    """Return a stable ``{"elements": [...]}`` envelope for scrape results."""
    if isinstance(data, dict) and isinstance(data.get("elements"), list):
        return data
    if isinstance(data, list):
        return {"elements": data}
    return {"elements": []}


def normalize_links_response(data: Any) -> list[dict[str, Any]]:
    """Return links as ``[{href, text}]`` objects."""
    links: list[Any]
    if isinstance(data, list):
        links = data
    elif isinstance(data, dict) and isinstance(data.get("links"), list):
        links = data["links"]
    else:
        return []

    normalized: list[dict[str, Any]] = []
    for item in links:
        if isinstance(item, str):
            normalized.append({"href": item, "text": None})
        elif isinstance(item, dict) and isinstance(item.get("href"), str):
            normalized.append({
                **item,
                "href": item["href"],
                "text": item.get("text") if isinstance(item.get("text"), str) else None,
            })
    return normalized
