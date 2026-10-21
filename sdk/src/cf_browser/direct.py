"""
CFBrowserDirect — call Cloudflare Browser Run API without a Worker.

Skips the Worker proxy and calls the CF REST API directly using your
account ID and API token. No caching, rate limiting, or auth proxy —
ideal for personal use and quick setup.

Example usage::

    async with CFBrowserDirect(
        account_id="abc123",
        api_token="your-cf-api-token",
    ) as browser:
        md = await browser.markdown("https://example.com")
"""

from __future__ import annotations

import math
import time
from typing import Any
from urllib.parse import quote

import httpx

from ._normalizers import normalize_links_response, normalize_scrape_response
from .exceptions import (
    AuthenticationError,
    CFBrowserError,
    NotFoundError,
    RateLimitError,
    TransportError,
)
from ._shared import (
    CrawlCursor,
    build_crawl_status_params,
    build_json_extraction_options,
    normalize_crawl_status_response,
    validate_crawl_cache_controls,
    validate_common_canonical_options,
)

_CF_API_BASE = "https://api.cloudflare.com/client/v4/accounts"
DEFAULT_DIRECT_TIMEOUT = 310.0


def _cf_error_message(body: Any, fallback: str) -> str:
    if not isinstance(body, dict):
        return fallback
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        message = errors[0].get("message")
        if isinstance(message, str):
            return message
    for key in ("error", "message"):
        message = body.get(key)
        if isinstance(message, str):
            return message
    return fallback


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP error codes to typed SDK exceptions."""
    if response.is_success:
        return

    try:
        body = response.json()
        message = _cf_error_message(body, str(body))
    except Exception:
        message = response.text or f"HTTP {response.status_code}"

    status = response.status_code
    if status == 401:
        raise AuthenticationError(message, status_code=status)
    if status == 404:
        raise NotFoundError(message, status_code=status)
    if status == 429:
        raise RateLimitError(message, status_code=status)
    raise CFBrowserError(message, status_code=status)


def _unwrap_cf_envelope(data: Any) -> Any:
    """Unwrap CF API's ``{success, result}`` envelope if present."""
    if isinstance(data, dict) and "success" in data and "result" in data:
        return data["result"]
    return data


def _decode_json(response: httpx.Response) -> Any:
    """Decode a successful Cloudflare response as a typed SDK error on failure."""
    try:
        data = response.json()
    except ValueError as exc:
        raise CFBrowserError(
            "Cloudflare Browser Run returned an invalid JSON response",
            status_code=response.status_code,
        ) from exc
    if isinstance(data, dict) and data.get("success") is False:
        raise CFBrowserError(
            _cf_error_message(data, "Cloudflare API reported an unsuccessful response"),
            status_code=502 if response.status_code < 400 else response.status_code,
        )
    return data


def _require_json_object(value: Any, operation: str) -> dict[str, Any]:
    """Require an object response for endpoints with an object contract."""
    if not isinstance(value, dict):
        raise CFBrowserError(
            f"Cloudflare Browser Run returned malformed {operation}",
            status_code=502,
        )
    return value


def _valid_screenshot_bytes(data: bytes) -> bool:
    return (
        data.startswith(b"\x89PNG")
        or data.startswith(b"\xff\xd8\xff")
        or (len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )


def _crawl_cache_params(no_cache: bool, cache_ttl: int | None) -> dict[str, str | int]:
    effective_ttl = validate_crawl_cache_controls(no_cache, cache_ttl)
    return {"cacheTTL": effective_ttl} if effective_ttl is not None else {}


def _require_crawl_job_id(data: Any) -> str:
    if isinstance(data, str):
        candidates: list[Any] = [data]
    elif isinstance(data, dict):
        candidates = [data[field] for field in ("id", "job_id") if field in data]
    else:
        candidates = []

    job_ids: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            raise CFBrowserError(
                "Cloudflare Browser Run returned malformed crawl job ID",
                status_code=502,
            )
        job_ids.append(candidate)
    if not job_ids or len(set(job_ids)) != 1:
        raise CFBrowserError(
            "Cloudflare Browser Run returned malformed crawl job ID",
            status_code=502,
        )
    return job_ids[0]


def _transform_screenshot_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Map user-friendly screenshot params to CF API format."""
    out = dict(opts)
    width = out.pop("width", None)
    height = out.pop("height", None)
    full_page = out.pop("full_page", None)

    existing_viewport = out.get("viewport")
    if existing_viewport is not None and not isinstance(existing_viewport, dict):
        raise ValueError("viewport must be a dictionary")
    existing_screenshot_options = out.get("screenshotOptions")
    if existing_screenshot_options is not None and not isinstance(
        existing_screenshot_options, dict
    ):
        raise ValueError("screenshotOptions must be a dictionary")
    if isinstance(existing_screenshot_options, dict) and existing_screenshot_options.get(
        "encoding"
    ) not in {None, "binary"}:
        raise ValueError("screenshotOptions.encoding must be binary")
    if isinstance(existing_screenshot_options, dict) and not isinstance(
        existing_screenshot_options.get("fullPage", False), bool
    ):
        raise ValueError("screenshotOptions.fullPage must be a boolean")

    for name, value, maximum in (("width", width, 7680), ("height", height, 4320)):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum
        ):
            raise ValueError(f"{name} must be an integer between 1 and {maximum}")
    if full_page is not None and not isinstance(full_page, bool):
        raise ValueError("full_page must be a boolean")

    if width is not None or height is not None:
        out["viewport"] = {
            **(existing_viewport or {}),
            "width": width if width is not None else (existing_viewport or {}).get("width", 1920),
            "height": height
            if height is not None
            else (existing_viewport or {}).get("height", 1080),
        }
    if full_page is not None:
        out["screenshotOptions"] = {
            **(existing_screenshot_options or {}),
            "fullPage": full_page,
        }
    return out


def _transform_pdf_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Map user-friendly PDF params to Cloudflare's ``pdfOptions`` object."""
    out = dict(opts)
    format_name = out.pop("format", None)
    landscape = out.pop("landscape", None)
    existing = out.get("pdfOptions")
    if existing is not None and not isinstance(existing, dict):
        raise ValueError("pdfOptions must be a dictionary")
    pdf_options = dict(existing) if isinstance(existing, dict) else {}
    raw_format = pdf_options.get("format")
    allowed = {"letter", "legal", "tabloid", "ledger", "a0", "a1", "a2", "a3", "a4", "a5", "a6"}
    if raw_format is not None and (
        not isinstance(raw_format, str) or raw_format.lower() not in allowed
    ):
        raise ValueError("Unsupported pdfOptions.format")
    if pdf_options.get("landscape") is not None and not isinstance(pdf_options["landscape"], bool):
        raise ValueError("pdfOptions.landscape must be a boolean")
    if format_name is not None:
        if not isinstance(format_name, str):
            raise ValueError("format must be a string")
        normalized = format_name.lower()
        if normalized not in allowed:
            raise ValueError("Unsupported PDF format")
        pdf_options["format"] = normalized
    if landscape is not None:
        if not isinstance(landscape, bool):
            raise ValueError("landscape must be a boolean")
        pdf_options["landscape"] = landscape
    if pdf_options:
        out["pdfOptions"] = pdf_options
    return out


def _transform_scrape_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Map string selectors to CF API's ``[{selector: "..."}]`` format."""
    out = dict(opts)
    elements = out.get("elements")
    if (
        not isinstance(elements, list)
        or not elements
        or not all(isinstance(element, str) and bool(element.strip()) for element in elements)
    ):
        raise ValueError("selectors must be a non-empty list of strings")
    if isinstance(elements, list):
        out["elements"] = [{"selector": el} if isinstance(el, str) else el for el in elements]
    return out


def _transform_crawl_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate Cloudflare's current crawl request contract."""
    out = dict(opts)

    def alias(snake: str, camel: str) -> None:
        if snake not in out:
            return
        if camel in out:
            raise ValueError(f"Use either {snake} or {camel}, not both")
        out[camel] = out.pop(snake)

    for snake, camel in (
        ("crawl_purposes", "crawlPurposes"),
        ("max_age", "maxAge"),
        ("modified_since", "modifiedSince"),
        ("json_options", "jsonOptions"),
        ("reject_request_patterns", "rejectRequestPattern"),
        ("allow_request_patterns", "allowRequestPattern"),
        ("allow_resource_types", "allowResourceTypes"),
        ("javascript_enabled", "setJavaScriptEnabled"),
        ("action_timeout", "actionTimeout"),
        ("wait_for_timeout", "waitForTimeout"),
        ("best_attempt", "bestAttempt"),
        ("emulate_media_type", "emulateMediaType"),
    ):
        alias(snake, camel)

    max_pages = out.pop("max_pages", None)
    if max_pages is not None and "limit" in out:
        raise ValueError("Use either max_pages or limit, not both")
    if max_pages is not None and (
        isinstance(max_pages, bool)
        or not isinstance(max_pages, int)
        or max_pages < 1
        or max_pages > 100_000
    ):
        raise ValueError("max_pages must be an integer between 1 and 100000")
    if max_pages is not None and "limit" not in out:
        out["limit"] = max_pages
    out.setdefault("render", True)
    out.setdefault("source", "all")
    render = out["render"]
    if not isinstance(render, bool):
        raise ValueError("render must be a boolean")
    if "userAgent" in out:
        raise ValueError("user_agent is not supported by the crawl endpoint")
    if out.get("render") is False:
        rendered_only = {
            "cookies",
            "setExtraHTTPHeaders",
            "authenticate",
            "waitForSelector",
            "gotoOptions",
            "addScriptTag",
            "addStyleTag",
            "rejectResourceTypes",
            "rejectRequestPattern",
            "allowRequestPattern",
            "allowResourceTypes",
            "setJavaScriptEnabled",
            "actionTimeout",
            "waitForTimeout",
            "bestAttempt",
            "emulateMediaType",
            "viewport",
        }
        if rendered_only.intersection(out):
            raise ValueError("Browser options require render=True for crawl requests")
    limit = out.get("limit")
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 100_000
    ):
        raise ValueError("limit must be an integer between 1 and 100000")
    options = out.get("options")
    if "options" in out and not isinstance(options, dict):
        raise ValueError("options must be a dictionary")
    normalized_options = dict(options or {})
    for snake, camel in (
        ("include_external", "includeExternalLinks"),
        ("include_subdomains", "includeSubdomains"),
        ("include_patterns", "includePatterns"),
        ("exclude_patterns", "excludePatterns"),
    ):
        if snake in out:
            if camel in normalized_options:
                raise ValueError(f"Use either {snake} or options.{camel}, not both")
            normalized_options[camel] = out.pop(snake)
    normalized_options.setdefault("includeExternalLinks", False)
    normalized_options.setdefault("includeSubdomains", False)
    for field in ("includeExternalLinks", "includeSubdomains"):
        value = normalized_options.get(field)
        if not isinstance(value, bool):
            raise ValueError(f"options.{field} must be a boolean")
    for field in ("includePatterns", "excludePatterns"):
        value = normalized_options.get(field)
        if value is not None and (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and bool(item.strip()) for item in value)
        ):
            raise ValueError(f"options.{field} must be a non-empty list of strings")
    out["options"] = normalized_options

    source = out.get("source")
    if source not in {"all", "links", "sitemaps"}:
        raise ValueError("source must be all, links, or sitemaps")

    depth = out.get("depth")
    if depth is not None and (
        isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 100_000
    ):
        raise ValueError("depth must be an integer between 1 and 100000")
    formats = out.get("formats")
    if formats is not None and (
        not isinstance(formats, list)
        or not formats
        or not all(
            isinstance(item, str) and item in {"html", "markdown", "json"} for item in formats
        )
    ):
        raise ValueError("formats must be a non-empty list of html, markdown, or json")
    purposes = out.get("crawlPurposes")
    if purposes is not None and (
        not isinstance(purposes, list)
        or not purposes
        or not all(
            isinstance(item, str) and item in {"search", "ai-input", "ai-train"}
            for item in purposes
        )
    ):
        raise ValueError("crawl_purposes must be a non-empty list of search, ai-input, or ai-train")
    max_age = out.get("maxAge")
    if max_age is not None and (
        isinstance(max_age, bool) or not isinstance(max_age, int) or not 0 <= max_age <= 604_800
    ):
        raise ValueError("max_age must be an integer between 0 and 604800")
    modified_since = out.get("modifiedSince")
    now = int(time.time())
    if modified_since is not None and (
        isinstance(modified_since, bool)
        or not isinstance(modified_since, int)
        or modified_since < now - 365 * 24 * 60 * 60
        or modified_since > now
    ):
        raise ValueError("modified_since must be a Unix timestamp within the past year")
    json_options = out.get("jsonOptions")
    if json_options is not None and not isinstance(json_options, dict):
        raise ValueError("json_options must be a dictionary")
    if isinstance(formats, list) and "json" in formats and json_options is None:
        raise ValueError("json_options is required when formats includes json")
    if json_options is not None and (not isinstance(formats, list) or "json" not in formats):
        raise ValueError("json_options requires formats to include json")

    for field in ("rejectRequestPattern", "allowRequestPattern", "allowResourceTypes"):
        value = out.get(field)
        if value is not None and (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and bool(item.strip()) for item in value)
        ):
            raise ValueError(f"{field} must be a non-empty list of strings")
    for field in ("setJavaScriptEnabled", "bestAttempt"):
        value = out.get(field)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{field} must be a boolean")
    for field in ("actionTimeout", "waitForTimeout"):
        value = out.get(field)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 120_000
        ):
            raise ValueError(f"{field} must be an integer between 1 and 120000")
    if out.get("emulateMediaType") is not None and (
        not isinstance(out["emulateMediaType"], str) or not out["emulateMediaType"].strip()
    ):
        raise ValueError("emulateMediaType must be a non-empty string")
    return out


def _transform_links_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Map friendly link filters to Cloudflare's current option names."""
    out = dict(opts)
    include_external = out.pop("include_external", None)
    visible_only = out.pop("visible_only", None)
    if include_external is not None:
        if not isinstance(include_external, bool):
            raise ValueError("include_external must be a boolean")
        out["excludeExternalLinks"] = not include_external
    if visible_only is not None:
        if not isinstance(visible_only, bool):
            raise ValueError("visible_only must be a boolean")
        out["visibleLinksOnly"] = visible_only
    return out


def _transform_common_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Map common user-friendly snake_case params to CF API camelCase.

    Mappings::

        wait_for              → waitForSelector
        headers               → setExtraHTTPHeaders
        timeout               → gotoOptions.timeout
        wait_until            → gotoOptions.waitUntil
        user_agent            → userAgent
        add_script_tag        → addScriptTag
        add_style_tag         → addStyleTag
        reject_resource_types → rejectResourceTypes
    """
    out = dict(opts)

    for friendly, canonical in (
        ("wait_for", "waitForSelector"),
        ("headers", "setExtraHTTPHeaders"),
        ("user_agent", "userAgent"),
        ("add_script_tag", "addScriptTag"),
        ("add_style_tag", "addStyleTag"),
        ("reject_resource_types", "rejectResourceTypes"),
    ):
        if friendly in out and canonical in out:
            raise ValueError(f"Use either {friendly} or {canonical}, not both")

    url_value = out.get("url")
    if not isinstance(url_value, str) or not url_value.strip():
        raise ValueError("url must be a non-empty string")

    validate_common_canonical_options(out)

    raw_goto_options = out.get("gotoOptions")
    if raw_goto_options is not None and not isinstance(raw_goto_options, dict):
        raise ValueError("gotoOptions must be a dictionary")
    if isinstance(raw_goto_options, dict):
        if "timeout" in out and "timeout" in raw_goto_options:
            raise ValueError("Use either timeout or gotoOptions.timeout, not both")
        if "wait_until" in out and "waitUntil" in raw_goto_options:
            raise ValueError("Use either wait_until or gotoOptions.waitUntil, not both")
        raw_timeout = raw_goto_options.get("timeout")
        if raw_timeout is not None and (
            isinstance(raw_timeout, bool)
            or not isinstance(raw_timeout, int)
            or not 1 <= raw_timeout <= 60_000
        ):
            raise ValueError("gotoOptions.timeout must be an integer between 1 and 60000")
        raw_wait_until = raw_goto_options.get("waitUntil")
        allowed_wait_until = {"load", "domcontentloaded", "networkidle0", "networkidle2"}
        valid_wait_until = (
            isinstance(raw_wait_until, str)
            and raw_wait_until in allowed_wait_until
            or isinstance(raw_wait_until, list)
            and bool(raw_wait_until)
            and all(isinstance(item, str) and item in allowed_wait_until for item in raw_wait_until)
        )
        if raw_wait_until is not None and not valid_wait_until:
            raise ValueError("gotoOptions.waitUntil contains an unsupported lifecycle event")

    viewport = out.get("viewport")
    if viewport is not None and not isinstance(viewport, dict):
        raise ValueError("viewport must be a dictionary")
    if isinstance(viewport, dict):
        for field, maximum in (("width", 7_680), ("height", 4_320)):
            value = viewport.get(field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum
            ):
                raise ValueError(f"viewport.{field} must be an integer between 1 and {maximum}")
        scale = viewport.get("deviceScaleFactor")
        if scale is not None and (
            isinstance(scale, bool)
            or not isinstance(scale, (int, float))
            or not math.isfinite(scale)
            or not 0 < scale <= 10
        ):
            raise ValueError("viewport.deviceScaleFactor must be a number between 0 and 10")
        for field in ("hasTouch", "isLandscape", "isMobile"):
            if viewport.get(field) is not None and not isinstance(viewport[field], bool):
                raise ValueError(f"viewport.{field} must be a boolean")

    wait_for_value = out.get("wait_for")
    if wait_for_value is not None and (
        not isinstance(wait_for_value, str)
        or not wait_for_value.strip()
        or len(wait_for_value) > 500
    ):
        raise ValueError("wait_for must be a non-empty string up to 500 characters")

    timeout_value = out.get("timeout")
    if timeout_value is not None and (
        isinstance(timeout_value, bool)
        or not isinstance(timeout_value, int)
        or timeout_value < 1
        or timeout_value > 60_000
    ):
        raise ValueError("timeout must be an integer between 1 and 60000 milliseconds")

    wait_until_value = out.get("wait_until")
    allowed_wait_until = {"load", "domcontentloaded", "networkidle0", "networkidle2"}
    if wait_until_value is not None and (
        not isinstance(wait_until_value, str) or wait_until_value not in allowed_wait_until
    ):
        raise ValueError("wait_until must be load, domcontentloaded, networkidle0, or networkidle2")

    user_agent_value = out.get("user_agent")
    if user_agent_value is not None and (
        not isinstance(user_agent_value, str)
        or not user_agent_value.strip()
        or len(user_agent_value) > 1_024
    ):
        raise ValueError("user_agent must be a non-empty string up to 1024 characters")
    canonical_user_agent = out.get("userAgent")
    if canonical_user_agent is not None and (
        not isinstance(canonical_user_agent, str)
        or not canonical_user_agent.strip()
        or len(canonical_user_agent) > 1_024
    ):
        raise ValueError("userAgent must be a non-empty string up to 1024 characters")

    headers_value = out.get("headers")
    if headers_value is not None and (
        not isinstance(headers_value, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in headers_value.items()
        )
    ):
        raise ValueError("headers must be a dictionary with string keys and values")
    canonical_headers = out.get("setExtraHTTPHeaders")
    if canonical_headers is not None and (
        not isinstance(canonical_headers, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in canonical_headers.items()
        )
    ):
        raise ValueError("setExtraHTTPHeaders must be a dictionary with string keys and values")

    cookies_value = out.get("cookies")
    if cookies_value is not None and (
        not isinstance(cookies_value, list)
        or not all(
            isinstance(cookie, dict)
            and isinstance(cookie.get("name"), str)
            and bool(cookie["name"])
            and isinstance(cookie.get("value"), str)
            for cookie in cookies_value
        )
    ):
        raise ValueError(
            "cookies must be a list of dictionaries with non-empty name and string value"
        )

    authenticate_value = out.get("authenticate")
    if authenticate_value is not None and (
        not isinstance(authenticate_value, dict)
        or not isinstance(authenticate_value.get("username"), str)
        or not authenticate_value["username"]
        or not isinstance(authenticate_value.get("password"), str)
        or not authenticate_value["password"]
    ):
        raise ValueError("authenticate must contain non-empty username and password strings")

    for option_name in ("add_script_tag", "add_style_tag"):
        resources = out.get(option_name)
        if resources is not None and (
            not isinstance(resources, list)
            or not all(
                isinstance(resource, dict)
                and (
                    isinstance(resource.get("content"), str)
                    and bool(resource["content"])
                    or isinstance(resource.get("url"), str)
                    and bool(resource["url"])
                )
                for resource in resources
            )
        ):
            raise ValueError(f"{option_name} must be a list whose entries contain content or url")

    for option_name in ("addScriptTag", "addStyleTag"):
        resources = out.get(option_name)
        if resources is not None and (
            not isinstance(resources, list)
            or not all(
                isinstance(resource, dict)
                and (
                    isinstance(resource.get("content"), str)
                    and bool(resource["content"])
                    or isinstance(resource.get("url"), str)
                    and bool(resource["url"])
                )
                for resource in resources
            )
        ):
            raise ValueError(f"{option_name} must be a list whose entries contain content or url")

    rejected_types = out.get("reject_resource_types")
    if rejected_types is not None and (
        not isinstance(rejected_types, list)
        or not all(isinstance(item, str) and bool(item) for item in rejected_types)
    ):
        raise ValueError("reject_resource_types must be a list of non-empty strings")
    canonical_rejected_types = out.get("rejectResourceTypes")
    if canonical_rejected_types is not None and (
        not isinstance(canonical_rejected_types, list)
        or not all(isinstance(item, str) and bool(item) for item in canonical_rejected_types)
    ):
        raise ValueError("rejectResourceTypes must be a list of non-empty strings")

    # wait_for → waitForSelector (CF API expects an object, not a plain string)
    wait_for = out.pop("wait_for", None)
    if wait_for is not None:
        out["waitForSelector"] = {"selector": wait_for}

    # headers → setExtraHTTPHeaders
    headers = out.pop("headers", None)
    if headers is not None:
        out["setExtraHTTPHeaders"] = headers

    # timeout + wait_until → gotoOptions
    timeout = out.pop("timeout", None)
    wait_until = out.pop("wait_until", None)
    if timeout is not None or wait_until is not None:
        existing_goto_options = out.get("gotoOptions")
        if existing_goto_options is not None and not isinstance(existing_goto_options, dict):
            raise ValueError("gotoOptions must be a dictionary")
        goto_options: dict[str, Any] = dict(existing_goto_options or {})
        if timeout is not None:
            goto_options["timeout"] = timeout
        if wait_until is not None:
            goto_options["waitUntil"] = wait_until
        out["gotoOptions"] = goto_options

    # user_agent → userAgent
    user_agent = out.pop("user_agent", None)
    if user_agent is not None:
        out["userAgent"] = user_agent

    # add_script_tag → addScriptTag
    add_script_tag = out.pop("add_script_tag", None)
    if add_script_tag is not None:
        out["addScriptTag"] = add_script_tag

    # add_style_tag → addStyleTag
    add_style_tag = out.pop("add_style_tag", None)
    if add_style_tag is not None:
        out["addStyleTag"] = add_style_tag

    # reject_resource_types → rejectResourceTypes
    reject_resource_types = out.pop("reject_resource_types", None)
    if reject_resource_types is not None:
        out["rejectResourceTypes"] = reject_resource_types

    return out


class CFBrowserDirect:
    """Call Cloudflare Browser Run API directly (no Worker needed).

    Parameters
    ----------
    account_id:
        Cloudflare Account ID (from ``wrangler whoami`` or dashboard).
    api_token:
        Cloudflare API Token with Browser Run (Browser Rendering) permissions.
    timeout:
        Default request timeout in seconds (default 310), leaving transport
        overhead beyond Cloudflare's longest supported synchronous action.
    """

    def __init__(
        self,
        account_id: str,
        api_token: str,
        timeout: float = DEFAULT_DIRECT_TIMEOUT,
    ) -> None:
        if (
            not isinstance(account_id, str)
            or not account_id.strip()
            or any(character.isspace() or character in "/?#" for character in account_id)
        ):
            raise ValueError("account_id must be a non-empty string")
        if not isinstance(api_token, str) or not api_token:
            raise ValueError("api_token must be a non-empty string")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be greater than zero")
        self._base_url = f"{_CF_API_BASE}/{account_id}/browser-rendering"
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, f"{self._base_url}{endpoint}", **kwargs)
        except httpx.TimeoutException as exc:
            raise TransportError("Cloudflare Browser Run request timed out") from exc
        except httpx.HTTPError as exc:
            raise TransportError(f"Cloudflare Browser Run request failed: {exc}") from exc
        _raise_for_status(response)
        return response

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        params: dict[str, str | int] | None = None,
    ) -> httpx.Response:
        return await self._request("POST", endpoint, json=payload, params=params)

    async def _post_text(self, endpoint: str, payload: dict[str, Any]) -> str:
        response = await self._post(endpoint, payload)
        ct = response.headers.get("content-type", "")
        if "application/json" in ct:
            value = _unwrap_cf_envelope(_decode_json(response))
            if not isinstance(value, str):
                raise CFBrowserError(
                    "Cloudflare returned malformed content",
                    status_code=response.status_code,
                )
            return value
        return response.text

    async def _post_bytes(self, endpoint: str, payload: dict[str, Any]) -> bytes:
        response = await self._post(endpoint, payload)
        content_type = response.headers.get("content-type", "").lower()
        data = response.content
        if "application/json" in content_type or data.lstrip().startswith((b"{", b"[")):
            _decode_json(response)
            raise CFBrowserError(
                "Cloudflare Browser Run returned JSON for a binary endpoint",
                status_code=502,
            )
        valid_magic = (
            _valid_screenshot_bytes(data) if endpoint == "/screenshot" else data.startswith(b"%PDF")
        )
        if not valid_magic:
            operation = "screenshot" if endpoint == "/screenshot" else "PDF"
            raise CFBrowserError(
                f"Cloudflare Browser Run returned malformed {operation} bytes",
                status_code=502,
            )
        return data

    async def _post_json(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        params: dict[str, str | int] | None = None,
    ) -> Any:
        response = await self._post(endpoint, payload, params=params)
        return _unwrap_cf_envelope(_decode_json(response))

    async def _get_json(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> Any:
        response = await self._request("GET", endpoint, params=params)
        return _unwrap_cf_envelope(_decode_json(response))

    async def _delete(self, endpoint: str) -> None:
        response = await self._request("DELETE", endpoint)
        if response.content and "application/json" in response.headers.get("content-type", ""):
            _decode_json(response)

    @staticmethod
    def _strip_no_cache(opts: dict[str, Any]) -> dict[str, Any]:
        """Remove ``no_cache`` — CF API doesn't support it."""
        out = dict(opts)
        no_cache = out.pop("no_cache", None)
        if no_cache is not None and not isinstance(no_cache, bool):
            raise ValueError("no_cache must be a boolean")
        return out

    # ------------------------------------------------------------------
    # Public API (same interface as CFBrowser)
    # ------------------------------------------------------------------

    async def content(self, url: str, *, no_cache: bool = False, **opts: Any) -> str:
        payload = self._strip_no_cache({"url": url, "no_cache": no_cache, **opts})
        payload = _transform_common_opts(payload)
        return await self._post_text("/content", payload)

    async def screenshot(self, url: str, *, no_cache: bool = False, **opts: Any) -> bytes:
        payload = self._strip_no_cache({"url": url, "no_cache": no_cache, **opts})
        payload = _transform_common_opts(payload)
        payload = _transform_screenshot_opts(payload)
        return await self._post_bytes("/screenshot", payload)

    async def pdf(self, url: str, *, no_cache: bool = False, **opts: Any) -> bytes:
        payload = self._strip_no_cache({"url": url, "no_cache": no_cache, **opts})
        payload = _transform_common_opts(payload)
        payload = _transform_pdf_opts(payload)
        return await self._post_bytes("/pdf", payload)

    async def markdown(self, url: str, *, no_cache: bool = False, **opts: Any) -> str:
        payload = self._strip_no_cache({"url": url, "no_cache": no_cache, **opts})
        payload = _transform_common_opts(payload)
        return await self._post_text("/markdown", payload)

    async def snapshot(self, url: str, *, no_cache: bool = False, **opts: Any) -> dict[str, Any]:
        payload = self._strip_no_cache({"url": url, "no_cache": no_cache, **opts})
        payload = _transform_common_opts(payload)
        return _require_json_object(await self._post_json("/snapshot", payload), "snapshot")

    async def scrape(
        self,
        url: str,
        selectors: list[str],
        *,
        no_cache: bool = False,
        **opts: Any,
    ) -> dict[str, Any]:
        payload = self._strip_no_cache(
            {"url": url, "no_cache": no_cache, "elements": selectors, **opts}
        )
        payload = _transform_common_opts(payload)
        payload = _transform_scrape_opts(payload)
        return normalize_scrape_response(await self._post_json("/scrape", payload))

    async def json_extract(
        self,
        url: str,
        prompt: str | None = None,
        *,
        response_format: dict[str, Any] | None = None,
        schema: dict[str, Any] | None = None,
        no_cache: bool = False,
        **opts: Any,
    ) -> Any:
        extraction = build_json_extraction_options(prompt, response_format, schema, opts)
        payload = self._strip_no_cache({"url": url, "no_cache": no_cache, **extraction})
        payload = _transform_common_opts(payload)
        return await self._post_json("/json", payload)

    async def links(
        self,
        url: str,
        *,
        no_cache: bool = False,
        **opts: Any,
    ) -> list[dict[str, Any]]:
        payload = self._strip_no_cache({"url": url, "no_cache": no_cache, **opts})
        payload = _transform_common_opts(payload)
        payload = _transform_links_opts(payload)
        return normalize_links_response(await self._post_json("/links", payload))

    async def a11y(self, url: str, *, no_cache: bool = False, **opts: Any) -> dict[str, Any]:
        """Return Cloudflare's native accessibility tree response."""
        payload = self._strip_no_cache({"url": url, "no_cache": no_cache, **opts})
        payload = _transform_common_opts(payload)
        tree = _require_json_object(
            await self._post_json("/accessibilityTree", payload),
            "accessibility tree",
        )
        return {**tree, "type": "accessibility_tree"}

    async def crawl(
        self,
        url: str,
        *,
        no_cache: bool = False,
        cache_ttl: int | None = None,
        **opts: Any,
    ) -> str:
        cache_params = _crawl_cache_params(no_cache, cache_ttl)
        payload = {"url": url, **opts}
        payload = _transform_common_opts(payload)
        payload = _transform_crawl_opts(payload)
        data = await self._post_json("/crawl", payload, params=cache_params or None)
        return _require_crawl_job_id(data)

    async def crawl_status(
        self,
        job_id: str,
        *,
        cursor: CrawlCursor | None = None,
        limit: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id must be a non-empty string")
        params = build_crawl_status_params(cursor, limit, status)
        data = await self._get_json(f"/crawl/{quote(job_id, safe='')}", params=params or None)
        return normalize_crawl_status_response(
            data,
            job_id,
            source="Cloudflare Browser Run",
        )

    async def crawl_wait(
        self,
        job_id: str,
        *,
        timeout: float = 300,
        poll_interval: float = 5,
    ) -> dict[str, Any]:
        from ._shared import collect_crawl_pages, crawl_wait_poll

        async def poll_status(current_job_id: str) -> dict[str, Any]:
            return await self.crawl_status(current_job_id, limit=1)

        async def fetch_final(current_job_id: str) -> dict[str, Any]:
            async def fetch_page(page_job_id: str, cursor: CrawlCursor | None) -> dict[str, Any]:
                return await self.crawl_status(page_job_id, cursor=cursor)

            return await collect_crawl_pages(current_job_id, fetch_page)

        return await crawl_wait_poll(
            job_id,
            poll_status,
            fetch_final=fetch_final,
            timeout=timeout,
            poll_interval=poll_interval,
        )

    # ------------------------------------------------------------------
    # Interaction API stubs (not supported in Direct mode)
    # ------------------------------------------------------------------

    _INTERACT_MSG = (
        "Browser interaction requires Worker mode with BROWSER binding. "
        "Direct mode only supports read-only operations."
    )

    async def click(self, url: str, selector: str, **opts: Any) -> dict[str, Any]:
        raise NotImplementedError(self._INTERACT_MSG)

    async def type_text(
        self, url: str, selector: str, text: str, *, clear: bool = False, **opts: Any
    ) -> dict[str, Any]:
        raise NotImplementedError(self._INTERACT_MSG)

    async def evaluate(self, url: str, script: str, **opts: Any) -> dict[str, Any]:
        raise NotImplementedError(self._INTERACT_MSG)

    async def interact(
        self, url: str, actions: list[dict[str, Any]], **opts: Any
    ) -> dict[str, Any]:
        raise NotImplementedError(self._INTERACT_MSG)

    async def submit_form(
        self,
        url: str,
        fields: dict[str, str],
        *,
        submit_selector: str | None = None,
        **opts: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError(self._INTERACT_MSG)

    async def delete_crawl(self, job_id: str) -> None:
        """Cancel a crawl job through Cloudflare's REST API."""
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id must be a non-empty string")
        await self._delete(f"/crawl/{quote(job_id, safe='')}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "CFBrowserDirect":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
