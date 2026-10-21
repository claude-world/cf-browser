"""Normalize Worker/CF API response shapes into the SDK contract."""

from __future__ import annotations

from typing import Any

from .exceptions import CFBrowserError


def normalize_scrape_response(data: Any) -> dict[str, Any]:
    """Return a stable ``{"elements": [...]}`` envelope for scrape results."""
    if isinstance(data, dict) and isinstance(data.get("elements"), list):
        result = data
        elements = data["elements"]
    elif isinstance(data, list):
        result = {"elements": data}
        elements = data
    else:
        raise CFBrowserError("CF Browser returned malformed scrape response", status_code=502)

    if not all(isinstance(item, dict) for item in elements):
        raise CFBrowserError("CF Browser returned malformed scrape response", status_code=502)
    return result


def normalize_links_response(data: Any) -> list[dict[str, Any]]:
    """Return links as ``[{href, text}]`` objects."""
    links: list[Any]
    if isinstance(data, list):
        links = data
    elif isinstance(data, dict) and isinstance(data.get("links"), list):
        links = data["links"]
    else:
        raise CFBrowserError("CF Browser returned malformed links response", status_code=502)

    normalized: list[dict[str, Any]] = []
    for item in links:
        if isinstance(item, str):
            normalized.append({"href": item, "text": None})
        elif isinstance(item, dict) and isinstance(item.get("href"), str):
            text = item.get("text")
            if text is not None and not isinstance(text, str):
                raise CFBrowserError(
                    "CF Browser returned malformed links response",
                    status_code=502,
                )
            normalized.append(
                {
                    **item,
                    "href": item["href"],
                    "text": text,
                }
            )
        else:
            raise CFBrowserError("CF Browser returned malformed links response", status_code=502)
    return normalized
