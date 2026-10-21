"""Shared helpers used by both CFBrowser (Worker mode) and CFBrowserDirect."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Awaitable, Callable, TypeGuard

from .exceptions import CFBrowserError, CrawlJobError

CRAWL_PAGE_LIMIT_MAX = 100_000
CRAWL_CURSOR_INT_MAX = 9_007_199_254_740_991
CRAWL_CACHE_TTL_MAX = 86_400
COMMON_ACTION_TIMEOUT_MAX = 120_000
RESOURCE_TYPES = {
    "document",
    "stylesheet",
    "image",
    "media",
    "font",
    "script",
    "texttrack",
    "xhr",
    "fetch",
    "prefetch",
    "eventsource",
    "websocket",
    "manifest",
    "signedexchange",
    "ping",
    "cspviolationreport",
    "preflight",
    "other",
}
CrawlCursor = str | int
CRAWL_RECORD_STATUSES = {
    "queued",
    "errored",
    "completed",
    "disallowed",
    "skipped",
    "cancelled",
}


def _is_valid_crawl_cursor(value: object) -> TypeGuard[CrawlCursor]:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= CRAWL_CURSOR_INT_MAX
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 2_048
        and "\r" not in value
        and "\n" not in value
    )


def _is_valid_crawl_records(value: object) -> TypeGuard[list[dict[str, Any]]]:
    return isinstance(value, list) and all(isinstance(record, dict) for record in value)


def build_crawl_status_params(
    cursor: CrawlCursor | None,
    limit: int | None,
    status: str | None,
) -> dict[str, str | int]:
    """Validate crawl result filters and return transport-ready query params."""
    if cursor is not None and not _is_valid_crawl_cursor(cursor):
        raise ValueError("cursor must be a valid opaque cursor")
    if limit is not None and (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
        or limit > CRAWL_PAGE_LIMIT_MAX
    ):
        raise ValueError(f"limit must be an integer between 1 and {CRAWL_PAGE_LIMIT_MAX}")
    if status is not None and status not in CRAWL_RECORD_STATUSES:
        raise ValueError("Invalid crawl record status")
    return {
        **({"cursor": cursor} if cursor is not None else {}),
        **({"limit": limit} if limit is not None else {}),
        **({"status": status} if status is not None else {}),
    }


def validate_crawl_cache_controls(no_cache: bool, cache_ttl: int | None) -> int | None:
    """Validate crawl cache controls and return the effective upstream TTL."""
    if not isinstance(no_cache, bool):
        raise ValueError("no_cache must be a boolean")
    if cache_ttl is not None and (
        isinstance(cache_ttl, bool)
        or not isinstance(cache_ttl, int)
        or not 0 <= cache_ttl <= CRAWL_CACHE_TTL_MAX
    ):
        raise ValueError(f"cache_ttl must be an integer between 0 and {CRAWL_CACHE_TTL_MAX}")
    if no_cache and cache_ttl not in (None, 0):
        raise ValueError("Use either no_cache=True or cache_ttl, not both")
    return 0 if no_cache else cache_ttl


def normalize_crawl_status_response(
    data: Any,
    job_id: str,
    *,
    source: str,
) -> dict[str, Any]:
    """Fail closed on malformed crawl status envelopes from either transport."""
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("status"), str)
        or not data["status"].strip()
        or len(data["status"]) > 128
        or ("id" in data and data["id"] != job_id)
        or ("job_id" in data and data["job_id"] != job_id)
        or ("records" in data and not _is_valid_crawl_records(data["records"]))
        or (
            "cursor" in data
            and data["cursor"] not in (None, "")
            and not _is_valid_crawl_cursor(data["cursor"])
        )
    ):
        raise CFBrowserError(f"{source} returned malformed crawl status", status_code=502)
    return {**data, "job_id": job_id, "status": data["status"]}


async def collect_crawl_pages(
    job_id: str,
    fetch_page: Callable[[str, CrawlCursor | None], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Fetch every cursor page for a completed crawl and combine its records."""
    first = await fetch_page(job_id, None)
    result = dict(first)
    records = result.get("records", [])
    if not _is_valid_crawl_records(records):
        raise CrawlJobError("Crawl result records must be a list of objects", status_code=None)
    combined = list(records)
    seen: set[str] = set()
    cursor = result.get("cursor")

    while cursor not in (None, ""):
        if not _is_valid_crawl_cursor(cursor):
            raise CrawlJobError("Crawl result contained an invalid cursor", status_code=None)
        cursor_key = str(cursor)
        if cursor_key in seen:
            raise CrawlJobError("Crawl result contained an invalid cursor", status_code=None)
        seen.add(cursor_key)
        page = await fetch_page(job_id, cursor)
        page_records = page.get("records", [])
        if not _is_valid_crawl_records(page_records):
            raise CrawlJobError("Crawl result records must be a list of objects", status_code=None)
        combined.extend(page_records)
        cursor = page.get("cursor")

    result["records"] = combined
    result.pop("cursor", None)
    return result


def validate_common_canonical_options(options: dict[str, Any]) -> None:
    """Validate raw Cloudflare common options before either transport sends them."""
    if "gotoOptions" in options:
        goto_options = options["gotoOptions"]
        if not isinstance(goto_options, dict):
            raise ValueError("gotoOptions must be a dictionary")
        if "timeout" in goto_options:
            timeout = goto_options["timeout"]
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, int)
                or not 1 <= timeout <= 60_000
            ):
                raise ValueError("gotoOptions.timeout must be an integer between 1 and 60000")
        if "waitUntil" in goto_options:
            wait_until = goto_options["waitUntil"]
            allowed = {"load", "domcontentloaded", "networkidle0", "networkidle2"}
            valid = (isinstance(wait_until, str) and wait_until in allowed) or (
                isinstance(wait_until, list)
                and bool(wait_until)
                and all(isinstance(item, str) and item in allowed for item in wait_until)
            )
            if not valid:
                raise ValueError("gotoOptions.waitUntil contains an unsupported lifecycle event")
        for field, maximum in (("referer", 8_192), ("referrerPolicy", 256)):
            if field in goto_options:
                value = goto_options[field]
                if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                    raise ValueError(
                        f"gotoOptions.{field} must be a non-empty string up to {maximum} characters"
                    )

    if "waitForSelector" in options:
        wait_for_selector = options["waitForSelector"]
        if not isinstance(wait_for_selector, dict):
            raise ValueError("waitForSelector must be a dictionary")
        selector = wait_for_selector.get("selector")
        if not isinstance(selector, str) or not selector.strip() or len(selector) > 500:
            raise ValueError(
                "waitForSelector.selector must be a non-empty string up to 500 characters"
            )
        if "timeout" in wait_for_selector:
            selector_timeout = wait_for_selector["timeout"]
            if (
                isinstance(selector_timeout, bool)
                or not isinstance(selector_timeout, int)
                or not 1 <= selector_timeout <= COMMON_ACTION_TIMEOUT_MAX
            ):
                raise ValueError("waitForSelector.timeout must be an integer between 1 and 120000")
        for field in ("hidden", "visible"):
            if field in wait_for_selector and not isinstance(wait_for_selector[field], bool):
                raise ValueError(f"waitForSelector.{field} must be a boolean")
        if wait_for_selector.get("hidden") is True and wait_for_selector.get("visible") is True:
            raise ValueError("waitForSelector.hidden and visible cannot both be true")

    if "viewport" in options:
        viewport = options["viewport"]
        if not isinstance(viewport, dict):
            raise ValueError("viewport must be a dictionary")
        for field, maximum in (("width", 7_680), ("height", 4_320)):
            if field in viewport:
                value = viewport[field]
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not 1 <= value <= maximum
                ):
                    raise ValueError(f"viewport.{field} must be an integer between 1 and {maximum}")
        if "deviceScaleFactor" in viewport:
            scale = viewport["deviceScaleFactor"]
            if (
                isinstance(scale, bool)
                or not isinstance(scale, (int, float))
                or not math.isfinite(scale)
                or not 0 < scale <= 10
            ):
                raise ValueError("viewport.deviceScaleFactor must be a number between 0 and 10")
        for field in ("hasTouch", "isLandscape", "isMobile"):
            if field in viewport and not isinstance(viewport[field], bool):
                raise ValueError(f"viewport.{field} must be a boolean")

    for field in ("actionTimeout", "waitForTimeout"):
        if field not in options:
            continue
        value = options[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= COMMON_ACTION_TIMEOUT_MAX
        ):
            raise ValueError(f"{field} must be an integer between 1 and 120000")

    for field in ("bestAttempt", "setJavaScriptEnabled"):
        if field in options and not isinstance(options[field], bool):
            raise ValueError(f"{field} must be a boolean")

    if "emulateMediaType" in options:
        media_type = options["emulateMediaType"]
        if not isinstance(media_type, str) or not media_type.strip() or len(media_type) > 1_024:
            raise ValueError("emulateMediaType must be a non-empty string up to 1024 characters")

    for field in ("rejectRequestPattern", "allowRequestPattern"):
        if field in options:
            patterns = options[field]
            if (
                not isinstance(patterns, list)
                or len(patterns) > 100
                or not all(
                    isinstance(item, str) and bool(item.strip()) and len(item) <= 2_048
                    for item in patterns
                )
            ):
                raise ValueError(
                    f"{field} must be an array of up to 100 non-empty strings of at most 2048 characters"
                )

    if "allowResourceTypes" in options:
        resource_types = options["allowResourceTypes"]
        if (
            not isinstance(resource_types, list)
            or len(resource_types) > len(RESOURCE_TYPES)
            or not all(isinstance(item, str) and item in RESOURCE_TYPES for item in resource_types)
        ):
            raise ValueError("allowResourceTypes contains an unsupported resource type")


def build_json_extraction_options(
    prompt: str | None,
    response_format: dict[str, Any] | None,
    schema: dict[str, Any] | None,
    opts: dict[str, Any],
) -> dict[str, Any]:
    """Build the current Cloudflare JSON extraction payload.

    ``schema`` is retained as a compatibility alias and translated to
    ``response_format`` before any request leaves the SDK.
    """
    if response_format is not None and schema is not None:
        raise ValueError("Use either response_format or schema, not both")
    if prompt is not None and (not isinstance(prompt, str) or not prompt.strip()):
        raise ValueError("prompt must be a non-empty string")
    if response_format is not None:
        if not isinstance(response_format, dict):
            raise ValueError("response_format must be a dictionary")
        if response_format.get("type") != "json_schema" or not isinstance(
            response_format.get("json_schema"), dict
        ):
            raise ValueError(
                "response_format must contain type=json_schema and a json_schema dictionary"
            )
    if schema is not None and not isinstance(schema, dict):
        raise ValueError("schema must be a dictionary")
    if prompt is None and response_format is None and schema is None:
        raise ValueError("One of prompt, response_format, or schema is required")

    result = dict(opts)
    if prompt is not None:
        result["prompt"] = prompt
    if schema is not None:
        result["response_format"] = {
            "type": "json_schema",
            "json_schema": schema,
        }
    elif response_format is not None:
        result["response_format"] = response_format
    return result


async def crawl_wait_poll(
    job_id: str,
    fetch_status: Callable[[str], Awaitable[dict[str, Any]]],
    *,
    fetch_final: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    timeout: float = 300,
    poll_interval: float = 5,
) -> dict[str, Any]:
    """Shared polling logic for crawl_wait.

    Parameters
    ----------
    job_id:
        The crawl job ID.
    fetch_status:
        Async callable that takes job_id and returns status dict.
    timeout:
        Maximum seconds to wait.
    poll_interval:
        Seconds between polls.
    """
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("timeout must be greater than zero")
    if (
        isinstance(poll_interval, bool)
        or not isinstance(poll_interval, (int, float))
        or not math.isfinite(poll_interval)
        or poll_interval <= 0
    ):
        raise ValueError("poll_interval must be greater than zero")
    if not isinstance(job_id, str) or not job_id:
        raise ValueError("job_id must be a non-empty string")

    deadline = time.monotonic() + timeout

    async def before_deadline(
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Crawl job {job_id!r} did not complete within {timeout}s")
        try:
            return await asyncio.wait_for(operation(), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Crawl job {job_id!r} did not complete within {timeout}s") from exc

    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Crawl job {job_id!r} did not complete within {timeout}s")

        status_data = await before_deadline(lambda: fetch_status(job_id))
        status = status_data.get("status", "")

        if status in ("complete", "completed", "done"):
            return (
                await before_deadline(lambda: fetch_final(job_id)) if fetch_final else status_data
            )
        if status in (
            "failed",
            "error",
            "errored",
            "cancelled",
            "canceled",
            "cancelled_due_to_timeout",
            "cancelled_due_to_limits",
            "cancelled_by_user",
        ):
            error_msg = status_data.get("error") or status
            raise CrawlJobError(
                f"Crawl job failed ({status}): {error_msg}",
                status_code=None,
            )

        await asyncio.sleep(max(0, min(poll_interval, deadline - time.monotonic())))
