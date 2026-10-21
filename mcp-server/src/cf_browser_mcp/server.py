"""MCP Server wrapping the CF Browser Python SDK as 17 tools."""

from __future__ import annotations

import atexit
import asyncio
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cf_browser import CFBrowser, CFBrowserDirect
from cf_browser.exceptions import BrowserUnavailableError, CrawlJobError, NotFoundError
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cf-browser")

# ---------------------------------------------------------------------------
# Shared client singleton (avoids leaking httpx.AsyncClient per tool call)
# ---------------------------------------------------------------------------

_client: CFBrowser | CFBrowserDirect | None = None
_artifact_dir: Path | None = None
_MAX_ARTIFACT_COUNT = 32
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_ARTIFACT_TOTAL_BYTES = 128 * 1024 * 1024


def get_client() -> CFBrowser | CFBrowserDirect:
    """Return a singleton browser client (lazy-initialized).

    Supports two modes based on environment variables:

    **Worker mode** (via deployed Cloudflare Worker):
        CF_BROWSER_URL + CF_BROWSER_API_KEY

    **Direct mode** (call CF API directly, no Worker needed):
        CF_ACCOUNT_ID + CF_API_TOKEN
    """
    global _client
    if _client is None:
        mode = os.environ.get("CF_BROWSER_MODE", "").strip().lower()
        account_id = os.environ.get("CF_ACCOUNT_ID")
        api_token = os.environ.get("CF_API_TOKEN")
        worker_url = os.environ.get("CF_BROWSER_URL")
        worker_key = os.environ.get("CF_BROWSER_API_KEY")

        direct_ready = bool(account_id and api_token)
        worker_ready = bool(worker_url and worker_key)
        if mode not in {"", "direct", "worker"}:
            raise RuntimeError("CF_BROWSER_MODE must be 'direct' or 'worker'.")
        if not mode and direct_ready and worker_ready:
            raise RuntimeError(
                "Both Direct and Worker credentials are configured. Set "
                "CF_BROWSER_MODE=direct or CF_BROWSER_MODE=worker explicitly."
            )
        if mode == "direct" and not direct_ready:
            raise RuntimeError("Direct mode requires CF_ACCOUNT_ID and CF_API_TOKEN.")
        if mode == "worker" and not worker_ready:
            raise RuntimeError("Worker mode requires CF_BROWSER_URL and CF_BROWSER_API_KEY.")

        selected_mode = mode or ("direct" if direct_ready else "worker" if worker_ready else "")
        if selected_mode == "direct":
            assert account_id is not None and api_token is not None
            _client = CFBrowserDirect(
                account_id=account_id,
                api_token=api_token,
            )
        elif selected_mode == "worker":
            assert worker_url is not None and worker_key is not None
            _client = CFBrowser(
                base_url=worker_url,
                api_key=worker_key,
            )
        else:
            raise RuntimeError(
                "CF Browser: set either (CF_ACCOUNT_ID + CF_API_TOKEN) for Direct mode "
                "or (CF_BROWSER_URL + CF_BROWSER_API_KEY) for Worker mode."
            )
    return _client


def _cleanup_client() -> None:
    """Close the browser client on process exit.

    Uses asyncio.run() for a clean shutdown and suppresses teardown errors.
    Cleanup is best effort because atexit can run while an event loop is active.
    """
    global _client
    if _client is None:
        return
    client, _client = _client, None
    try:
        asyncio.run(client.close())
    except RuntimeError:
        # asyncio.run() raised because a loop is already running (e.g. framework
        # teardown calling atexit while still inside an async context).
        # run_until_complete() on a running loop would also raise, so cleanup is
        # not possible here — accept the connection pool leak rather than crashing.
        pass
    except Exception:
        pass


atexit.register(_cleanup_client)


def _domain_from_url(url: str) -> str:
    """Extract a filesystem-safe domain string from a URL."""
    try:
        hostname = urlparse(url).hostname or ""
        # Strip anything that isn't alphanumeric, dot, or hyphen
        safe = re.sub(r"[^\w.\-]", "_", hostname) or "unknown"
        encoded = safe.encode("utf-8")[:180]
        while encoded:
            try:
                return encoded.decode("utf-8").rstrip("._-") or "unknown"
            except UnicodeDecodeError:
                encoded = encoded[:-1]
        return "unknown"
    except Exception:
        return "unknown"


def _get_artifact_dir() -> Path:
    """Return a process-private temporary directory for generated artifacts."""
    global _artifact_dir
    if _artifact_dir is None:
        _artifact_dir = Path(tempfile.mkdtemp(prefix="cf-browser-artifacts-"))
        _artifact_dir.chmod(0o700)
    return _artifact_dir


def _write_artifact(url: str, data: bytes, suffix: str) -> str:
    """Write an artifact using an unpredictable 0600 filename and bounded storage."""
    if len(data) > _MAX_ARTIFACT_BYTES:
        raise ValueError(
            f"Artifact exceeds the maximum artifact size of {_MAX_ARTIFACT_BYTES} bytes"
        )
    directory = _get_artifact_dir()
    files = sorted(
        (path for path in directory.iterdir() if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    total_bytes = sum(path.stat().st_size for path in files)
    while files and (
        len(files) >= _MAX_ARTIFACT_COUNT or total_bytes + len(data) > _MAX_ARTIFACT_TOTAL_BYTES
    ):
        oldest = files.pop(0)
        try:
            total_bytes -= oldest.stat().st_size
            oldest.unlink()
        except FileNotFoundError:
            pass
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f"{_domain_from_url(url)}_",
        suffix=suffix,
        dir=directory,
        delete=False,
    ) as output:
        output.write(data)
        path = Path(output.name)
    path.chmod(0o600)
    return str(path)


def _cleanup_artifacts() -> None:
    """Remove generated screenshots and PDFs when the MCP process exits."""
    global _artifact_dir
    directory, _artifact_dir = _artifact_dir, None
    if directory is not None:
        shutil.rmtree(directory, ignore_errors=True)


atexit.register(_cleanup_artifacts)


def _parse_json_value(name: str, value: Any, expected_type: type) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid {name} JSON: {exc}") from exc
    if not isinstance(value, expected_type):
        raise ValueError(f"{name} must be a JSON {expected_type.__name__}")
    return value


def _build_kwargs(
    *,
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
    timeout: int = 0,
) -> dict[str, Any]:
    """Parse tool params into SDK kwargs.

    Handles JSON parsing for cookies/headers/script/style strings and
    passes through browser-control params (wait_for, wait_until, user_agent)
    which the SDK translates to CF API equivalents.
    """
    kwargs: dict[str, Any] = {}
    parsed_cookies = _parse_json_value("cookies", cookies, list)
    if parsed_cookies is not None:
        if not all(
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("value"), str)
            for item in parsed_cookies
        ):
            raise ValueError("cookies entries must contain string name and value")
        kwargs["cookies"] = parsed_cookies
    parsed_headers = _parse_json_value("headers", headers, dict)
    if parsed_headers is not None:
        if not all(
            isinstance(key, str) and isinstance(value, str) for key, value in parsed_headers.items()
        ):
            raise ValueError("headers keys and values must be strings")
        kwargs["headers"] = parsed_headers
    parsed_authenticate = _parse_json_value("authenticate", authenticate, dict)
    if parsed_authenticate is not None:
        if (
            not isinstance(parsed_authenticate.get("username"), str)
            or not parsed_authenticate["username"]
            or not isinstance(parsed_authenticate.get("password"), str)
            or not parsed_authenticate["password"]
        ):
            raise ValueError("authenticate must contain non-empty username and password strings")
        kwargs["authenticate"] = parsed_authenticate
    if wait_for:
        if not wait_for.strip() or len(wait_for) > 500:
            raise ValueError("wait_for must be a non-empty string up to 500 characters")
        kwargs["wait_for"] = wait_for
    if wait_until:
        if wait_until not in {"load", "domcontentloaded", "networkidle0", "networkidle2"}:
            raise ValueError(
                "wait_until must be load, domcontentloaded, networkidle0, or networkidle2"
            )
        kwargs["wait_until"] = wait_until
    if user_agent:
        if not user_agent.strip() or len(user_agent) > 1_024:
            raise ValueError("user_agent must be a non-empty string up to 1024 characters")
        kwargs["user_agent"] = user_agent
    for name, value in (
        ("add_script_tag", add_script_tag),
        ("add_style_tag", add_style_tag),
    ):
        parsed = _parse_json_value(name, value, list)
        if parsed is not None:
            if not all(
                isinstance(item, dict)
                and (
                    isinstance(item.get("content"), str)
                    and bool(item["content"])
                    or isinstance(item.get("url"), str)
                    and bool(item["url"])
                )
                for item in parsed
            ):
                raise ValueError(f"{name} entries must contain non-empty content or url")
            kwargs[name] = parsed
    parsed_resources = _parse_json_value("reject_resource_types", reject_resource_types, list)
    if parsed_resources is not None:
        if not all(isinstance(item, str) and bool(item) for item in parsed_resources):
            raise ValueError("reject_resource_types entries must be non-empty strings")
        kwargs["reject_resource_types"] = parsed_resources
    if timeout:
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 60_000:
            raise ValueError("timeout must be an integer between 1 and 60000 milliseconds")
        kwargs["timeout"] = timeout
    return kwargs


def _interaction_error_payload(err: Exception) -> str:
    """Return a user-facing JSON error for interaction-only tools."""
    if isinstance(err, NotImplementedError):
        return json.dumps(
            {
                "error": str(err),
                "hint": "Use Worker mode with BROWSER binding",
            },
            ensure_ascii=False,
        )

    if isinstance(err, NotFoundError):
        return json.dumps(
            {
                "error": str(err),
                "hint": (
                    "The deployed Worker is missing interaction routes. "
                    "Redeploy the Worker from this repo and ensure the BROWSER binding is enabled."
                ),
            },
            ensure_ascii=False,
        )

    if isinstance(err, BrowserUnavailableError):
        return json.dumps(
            {
                "error": str(err),
                "hint": "Enable the Worker BROWSER binding",
            },
            ensure_ascii=False,
        )

    raise err


# ---------------------------------------------------------------------------
# Tool 1: browser_content
# ---------------------------------------------------------------------------


@mcp.tool(description="Fetch rendered HTML content of a web page (JavaScript executed)")
async def browser_content(
    url: str,
    no_cache: bool = False,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
) -> str:
    """Return the fully-rendered HTML of *url*.

    Args:
        url: The page URL to fetch.
        wait_for: Optional CSS selector to wait for before capturing.
        wait_until: When to consider navigation done — "load" | "domcontentloaded"
                    | "networkidle0" | "networkidle2" (default: "load").
        user_agent: Custom User-Agent string for the browser.
        cookies: Optional JSON array of cookie objects for authenticated pages.
                 Example: [{"name":"session","value":"abc","domain":".example.com"}]
        headers: Optional JSON object of custom HTTP headers.
                 Example: {"X-Auth":"token123"}
        add_script_tag: Optional JSON array of scripts to inject before capture.
                        Example: [{"content":"document.title='Modified'"}]
        add_style_tag: Optional JSON array of styles to inject before capture.
                       Example: [{"content":"body{background:red}"}]
        reject_resource_types: Optional JSON array of resource types to block.
                               Example: ["image","stylesheet"]
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    return await client.content(url, no_cache=no_cache, **kwargs)


# ---------------------------------------------------------------------------
# Tool 2: browser_screenshot
# ---------------------------------------------------------------------------


@mcp.tool(description="Take a screenshot of a web page")
async def browser_screenshot(
    url: str,
    width: int = 1280,
    height: int = 720,
    full_page: bool = False,
    no_cache: bool = False,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
) -> str:
    """Capture a PNG screenshot of *url* and return the local file path.

    Args:
        url: The page URL to screenshot.
        width: Viewport width in pixels (default 1280).
        height: Viewport height in pixels (default 720).
        full_page: When True, capture the full scrollable page.
        wait_for: Optional CSS selector to wait for before capturing.
        wait_until: Navigation strategy — "load" | "domcontentloaded" | "networkidle0" | "networkidle2".
        user_agent: Custom User-Agent string for the browser.
        cookies: Optional JSON array of cookie objects.
        headers: Optional JSON object of custom HTTP headers.
        add_script_tag: Optional JSON array of scripts to inject. Example: [{"content":"document.title='X'"}]
        add_style_tag: Optional JSON array of styles to inject. Example: [{"content":"body{background:red}"}]
        reject_resource_types: Optional JSON array of resource types to block. Example: ["image"]
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    data: bytes = await client.screenshot(
        url, width=width, height=height, full_page=full_page, no_cache=no_cache, **kwargs
    )
    return _write_artifact(url, data, ".png")


# ---------------------------------------------------------------------------
# Tool 3: browser_pdf
# ---------------------------------------------------------------------------


@mcp.tool(description="Generate PDF of a web page")
async def browser_pdf(
    url: str,
    format: str = "A4",
    landscape: bool = False,
    no_cache: bool = False,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
) -> str:
    """Render *url* as a PDF and return the local file path.

    Args:
        url: The page URL to render.
        format: Paper format – Letter, Legal, Tabloid, Ledger, or A0–A6 (default A4).
        landscape: When True, render in landscape orientation (default False).
        wait_for: Optional CSS selector to wait for before capturing.
        wait_until: When to consider navigation done — "load" | "domcontentloaded"
                    | "networkidle0" | "networkidle2" (default: "load").
        user_agent: Custom User-Agent string for the browser.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
        add_script_tag: Optional JSON array of scripts to inject before capture.
                        Example: [{"content":"document.title='Modified'"}]
        add_style_tag: Optional JSON array of styles to inject before capture.
                       Example: [{"content":"body{background:red}"}]
        reject_resource_types: Optional JSON array of resource types to block.
                               Example: ["image","stylesheet"]
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    data: bytes = await client.pdf(
        url, format=format, landscape=landscape, no_cache=no_cache, **kwargs
    )
    return _write_artifact(url, data, ".pdf")


# ---------------------------------------------------------------------------
# Tool 4: browser_markdown
# ---------------------------------------------------------------------------


@mcp.tool(description="Convert web page to clean Markdown (best for reading content)")
async def browser_markdown(
    url: str,
    no_cache: bool = False,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
) -> str:
    """Return the Markdown representation of *url*.

    Args:
        url: The page URL to convert.
        wait_for: Optional CSS selector to wait for before capturing.
        wait_until: When to consider navigation done — "load" | "domcontentloaded"
                    | "networkidle0" | "networkidle2" (default: "load").
        user_agent: Custom User-Agent string for the browser.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
        add_script_tag: Optional JSON array of scripts to inject before capture.
                        Example: [{"content":"document.title='Modified'"}]
        add_style_tag: Optional JSON array of styles to inject before capture.
                       Example: [{"content":"body{background:red}"}]
        reject_resource_types: Optional JSON array of resource types to block.
                               Example: ["image","stylesheet"]
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    return await client.markdown(url, no_cache=no_cache, **kwargs)


# ---------------------------------------------------------------------------
# Tool 5: browser_snapshot
# ---------------------------------------------------------------------------


@mcp.tool(description="Capture page content, Markdown, screenshot, and accessibility data")
async def browser_snapshot(
    url: str,
    no_cache: bool = False,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
) -> str:
    """Return Cloudflare's multi-format snapshot response as JSON."""
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    result = await client.snapshot(url, no_cache=no_cache, **kwargs)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 6: browser_scrape
# ---------------------------------------------------------------------------


@mcp.tool(description="Scrape specific elements from a web page using CSS selectors")
async def browser_scrape(
    url: str,
    selectors: list[str],
    no_cache: bool = False,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
) -> str:
    """Extract DOM elements matching each CSS selector and return as JSON.

    Args:
        url: The page URL to scrape.
        selectors: List of CSS selectors to extract (e.g. ["h1", ".price", "#main"]).
        wait_for: Optional CSS selector to wait for before capturing.
        wait_until: When to consider navigation done — "load" | "domcontentloaded"
                    | "networkidle0" | "networkidle2" (default: "load").
        user_agent: Custom User-Agent string for the browser.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
        add_script_tag: Optional JSON array of scripts to inject before capture.
                        Example: [{"content":"document.title='Modified'"}]
        add_style_tag: Optional JSON array of styles to inject before capture.
                       Example: [{"content":"body{background:red}"}]
        reject_resource_types: Optional JSON array of resource types to block.
                               Example: ["image","stylesheet"]
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    result = await client.scrape(url, selectors, no_cache=no_cache, **kwargs)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 7: browser_json
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Extract structured data from a web page using AI "
        "(provide a prompt describing what to extract)"
    )
)
async def browser_json(
    url: str,
    prompt: str = "",
    response_format: dict[str, Any] | str | None = None,
    schema: dict[str, Any] | str | None = None,
    no_cache: bool = False,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
) -> str:
    """Use AI to extract structured data from *url* and return as JSON.

    Args:
        url: The page URL to analyse.
        prompt: Natural-language description of the data to extract
                (e.g. "extract product name, price, and availability").
        wait_for: Optional CSS selector to wait for before capturing.
        wait_until: When to consider navigation done — "load" | "domcontentloaded"
                    | "networkidle0" | "networkidle2" (default: "load").
        user_agent: Custom User-Agent string for the browser.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
        add_script_tag: Optional JSON array of scripts to inject before capture.
                        Example: [{"content":"document.title='Modified'"}]
        add_style_tag: Optional JSON array of styles to inject before capture.
                       Example: [{"content":"body{background:red}"}]
        reject_resource_types: Optional JSON array of resource types to block.
                               Example: ["image","stylesheet"]
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    parsed_format = _parse_json_value("response_format", response_format, dict)
    parsed_schema = _parse_json_value("schema", schema, dict)
    result = await client.json_extract(
        url,
        prompt or None,
        response_format=parsed_format,
        schema=parsed_schema,
        no_cache=no_cache,
        **kwargs,
    )
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 8: browser_links
# ---------------------------------------------------------------------------


@mcp.tool(description="Extract all links from a web page")
async def browser_links(
    url: str,
    include_external: bool = True,
    visible_only: bool = False,
    no_cache: bool = False,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
) -> str:
    """Return all hyperlinks found on *url* as a JSON array of {href, text} objects.

    Args:
        url: The page URL to inspect.
        wait_for: Optional CSS selector to wait for before capturing.
        wait_until: When to consider navigation done — "load" | "domcontentloaded"
                    | "networkidle0" | "networkidle2" (default: "load").
        user_agent: Custom User-Agent string for the browser.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
        add_script_tag: Optional JSON array of scripts to inject before capture.
                        Example: [{"content":"document.title='Modified'"}]
        add_style_tag: Optional JSON array of styles to inject before capture.
                       Example: [{"content":"body{background:red}"}]
        reject_resource_types: Optional JSON array of resource types to block.
                               Example: ["image","stylesheet"]
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    result = await client.links(
        url,
        include_external=include_external,
        visible_only=visible_only,
        no_cache=no_cache,
        **kwargs,
    )
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 9: browser_crawl
# ---------------------------------------------------------------------------


@mcp.tool(
    description=("Start crawling a website (async – use browser_crawl_status to check progress)")
)
async def browser_crawl(
    url: str,
    limit: int = 10,
    no_cache: bool = False,
    cache_ttl: int = -1,
    include_external: bool = False,
    include_subdomains: bool = False,
    render: bool = True,
    source: str = "all",
    depth: int = 0,
    formats: list[str] | str | None = None,
    crawl_purposes: list[str] | str | None = None,
    max_age: int = -1,
    modified_since: int = 0,
    include_patterns: list[str] | str | None = None,
    exclude_patterns: list[str] | str | None = None,
    json_options: dict[str, Any] | str | None = None,
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    goto_options: dict[str, Any] | str | None = None,
    wait_for_selector: dict[str, Any] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
    reject_request_patterns: list[str] | str | None = None,
    allow_request_patterns: list[str] | str | None = None,
    allow_resource_types: list[str] | str | None = None,
    javascript_enabled: bool | None = None,
    action_timeout: int = 0,
    wait_for_timeout: int = 0,
    best_attempt: bool | None = None,
    emulate_media_type: str = "",
    viewport_width: int = 0,
    viewport_height: int = 0,
    viewport: dict[str, Any] | str | None = None,
) -> str:
    """Kick off an async website crawl and return the job ID plus initial status.

    Args:
        url: Seed URL for the crawl.
        limit: Maximum number of pages to crawl (default 10).
        no_cache: Disable Cloudflare's crawl cache by sending ``cacheTTL=0``.
        cache_ttl: Cloudflare crawl cache TTL in seconds (0-86400; -1 uses the default).
        render: Render JavaScript pages (default True). Set False for static fetches.
        source: Discover URLs from "all", "links", or "sitemaps".
        cookies: Optional JSON array of cookie objects for authenticated crawling.
        headers: Optional JSON object of custom HTTP headers.
        authenticate: Optional HTTP Basic Auth object with username and password.
        timeout: Page-navigation timeout in milliseconds for rendered crawls.
        goto_options: Full Cloudflare ``gotoOptions`` object; mutually exclusive with
            ``timeout`` and ``wait_until``.
        wait_for_selector: Full Cloudflare ``waitForSelector`` object; mutually
            exclusive with ``wait_for``.
        depth: Maximum link depth (1-100000; 0 uses Cloudflare's default).
        formats: JSON array containing html, markdown, and/or json.
        crawl_purposes: Content Signals purposes: search, ai-input, and/or ai-train.
        max_age: Cached-resource age in seconds (0-604800; -1 uses the default).
        modified_since: Unix timestamp in seconds; 0 disables this filter.
        include_patterns: Wildcard URL patterns to include.
        exclude_patterns: Wildcard URL patterns to exclude.
    """
    client = get_client()
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100_000:
        raise ValueError("limit must be an integer between 1 and 100000")
    if not isinstance(no_cache, bool):
        raise ValueError("no_cache must be a boolean")
    if (
        isinstance(cache_ttl, bool)
        or not isinstance(cache_ttl, int)
        or not -1 <= cache_ttl <= 86_400
    ):
        raise ValueError("cache_ttl must be -1 or an integer between 0 and 86400")
    if no_cache and cache_ttl not in {-1, 0}:
        raise ValueError("no_cache=True conflicts with a non-zero cache_ttl")
    if not isinstance(render, bool):
        raise ValueError("render must be a boolean")
    if source not in {"all", "links", "sitemaps"}:
        raise ValueError("source must be all, links, or sitemaps")
    if depth != 0 and (
        isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 100_000
    ):
        raise ValueError("depth must be an integer between 1 and 100000")
    parsed_formats = _parse_json_value("formats", formats, list)
    if parsed_formats is not None and (
        not parsed_formats
        or not all(
            isinstance(item, str) and item in {"html", "markdown", "json"}
            for item in parsed_formats
        )
    ):
        raise ValueError("formats entries must be html, markdown, or json")
    parsed_purposes = _parse_json_value("crawl_purposes", crawl_purposes, list)
    if parsed_purposes is not None and (
        not parsed_purposes
        or not all(
            isinstance(item, str) and item in {"search", "ai-input", "ai-train"}
            for item in parsed_purposes
        )
    ):
        raise ValueError("crawl_purposes entries must be search, ai-input, or ai-train")
    if isinstance(max_age, bool) or not isinstance(max_age, int) or not -1 <= max_age <= 604_800:
        raise ValueError("max_age must be -1 or an integer between 0 and 604800")
    if (
        isinstance(modified_since, bool)
        or not isinstance(modified_since, int)
        or modified_since < 0
    ):
        raise ValueError("modified_since must be a non-negative Unix timestamp")
    parsed_include_patterns = _parse_json_value("include_patterns", include_patterns, list)
    parsed_exclude_patterns = _parse_json_value("exclude_patterns", exclude_patterns, list)
    for name, patterns in (
        ("include_patterns", parsed_include_patterns),
        ("exclude_patterns", parsed_exclude_patterns),
    ):
        if patterns is not None and (
            not patterns
            or not all(isinstance(item, str) and bool(item.strip()) for item in patterns)
        ):
            raise ValueError(f"{name} entries must be non-empty strings")
    parsed_json_options = _parse_json_value("json_options", json_options, dict)
    if parsed_formats is not None and "json" in parsed_formats and parsed_json_options is None:
        raise ValueError("json_options is required when formats includes json")
    if parsed_json_options is not None and (parsed_formats is None or "json" not in parsed_formats):
        raise ValueError("json_options requires formats to include json")

    parsed_goto_options = _parse_json_value("goto_options", goto_options, dict)
    if parsed_goto_options is not None:
        if timeout or wait_until:
            raise ValueError("goto_options is mutually exclusive with timeout and wait_until")
        raw_timeout = parsed_goto_options.get("timeout")
        if raw_timeout is not None and (
            isinstance(raw_timeout, bool)
            or not isinstance(raw_timeout, int)
            or not 1 <= raw_timeout <= 60_000
        ):
            raise ValueError("goto_options.timeout must be an integer between 1 and 60000")
        raw_wait_until = parsed_goto_options.get("waitUntil")
        allowed_wait_until = {"load", "domcontentloaded", "networkidle0", "networkidle2"}
        valid_wait_until = (
            isinstance(raw_wait_until, str)
            and raw_wait_until in allowed_wait_until
            or isinstance(raw_wait_until, list)
            and bool(raw_wait_until)
            and all(isinstance(item, str) and item in allowed_wait_until for item in raw_wait_until)
        )
        if raw_wait_until is not None and not valid_wait_until:
            raise ValueError("goto_options.waitUntil contains an unsupported lifecycle event")
        for field in ("referer", "referrerPolicy"):
            value = parsed_goto_options.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"goto_options.{field} must be a non-empty string")

    parsed_wait_for_selector = _parse_json_value("wait_for_selector", wait_for_selector, dict)
    if parsed_wait_for_selector is not None:
        if wait_for:
            raise ValueError("wait_for_selector is mutually exclusive with wait_for")
        selector = parsed_wait_for_selector.get("selector")
        if not isinstance(selector, str) or not selector.strip() or len(selector) > 500:
            raise ValueError(
                "wait_for_selector.selector must be a non-empty string up to 500 characters"
            )
        selector_timeout = parsed_wait_for_selector.get("timeout")
        if selector_timeout is not None and (
            isinstance(selector_timeout, bool)
            or not isinstance(selector_timeout, int)
            or not 1 <= selector_timeout <= 120_000
        ):
            raise ValueError("wait_for_selector.timeout must be an integer between 1 and 120000")
        for field in ("hidden", "visible"):
            value = parsed_wait_for_selector.get(field)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"wait_for_selector.{field} must be a boolean")

    parsed_reject_patterns = _parse_json_value(
        "reject_request_patterns", reject_request_patterns, list
    )
    parsed_allow_patterns = _parse_json_value(
        "allow_request_patterns", allow_request_patterns, list
    )
    parsed_allow_resources = _parse_json_value("allow_resource_types", allow_resource_types, list)
    for name, values in (
        ("reject_request_patterns", parsed_reject_patterns),
        ("allow_request_patterns", parsed_allow_patterns),
        ("allow_resource_types", parsed_allow_resources),
    ):
        if values is not None and (
            not values or not all(isinstance(item, str) and bool(item.strip()) for item in values)
        ):
            raise ValueError(f"{name} entries must be non-empty strings")
    for name, boolean_value in (
        ("javascript_enabled", javascript_enabled),
        ("best_attempt", best_attempt),
    ):
        if boolean_value is not None and not isinstance(boolean_value, bool):
            raise ValueError(f"{name} must be a boolean")
    for name, timeout_value in (
        ("action_timeout", action_timeout),
        ("wait_for_timeout", wait_for_timeout),
    ):
        if timeout_value and (
            isinstance(timeout_value, bool)
            or not isinstance(timeout_value, int)
            or not 1 <= timeout_value <= 120_000
        ):
            raise ValueError(f"{name} must be an integer between 1 and 120000")
    if emulate_media_type and (
        not isinstance(emulate_media_type, str) or not emulate_media_type.strip()
    ):
        raise ValueError("emulate_media_type must be a non-empty string")
    if bool(viewport_width) != bool(viewport_height):
        raise ValueError("viewport_width and viewport_height must be provided together")
    parsed_viewport = _parse_json_value("viewport", viewport, dict)
    if parsed_viewport is not None and (viewport_width or viewport_height):
        raise ValueError("viewport is mutually exclusive with viewport_width and viewport_height")
    if viewport_width and (
        isinstance(viewport_width, bool)
        or isinstance(viewport_height, bool)
        or not isinstance(viewport_width, int)
        or not isinstance(viewport_height, int)
        or not 1 <= viewport_width <= 7_680
        or not 1 <= viewport_height <= 4_320
    ):
        raise ValueError("crawl viewport must be between 1x1 and 7680x4320")
    if parsed_viewport is not None:
        for field, maximum in (("width", 7_680), ("height", 4_320)):
            value = parsed_viewport.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"viewport.{field} must be an integer between 1 and {maximum}")
        scale = parsed_viewport.get("deviceScaleFactor")
        if scale is not None and (
            isinstance(scale, bool)
            or not isinstance(scale, (int, float))
            or not math.isfinite(scale)
            or not 0 < scale <= 10
        ):
            raise ValueError("viewport.deviceScaleFactor must be a number between 0 and 10")
        for field in ("hasTouch", "isLandscape", "isMobile"):
            value = parsed_viewport.get(field)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"viewport.{field} must be a boolean")
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        timeout=timeout,
        wait_for=wait_for,
        wait_until=wait_until,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
    )
    if not render and kwargs:
        raise ValueError("browser options require render=True for crawl requests")
    rendered_options = {
        "reject_request_patterns": parsed_reject_patterns,
        "allow_request_patterns": parsed_allow_patterns,
        "allow_resource_types": parsed_allow_resources,
        "javascript_enabled": javascript_enabled,
        "action_timeout": action_timeout or None,
        "wait_for_timeout": wait_for_timeout or None,
        "best_attempt": best_attempt,
        "emulate_media_type": emulate_media_type or None,
        "gotoOptions": parsed_goto_options,
        "waitForSelector": parsed_wait_for_selector,
        "viewport": parsed_viewport
        or ({"width": viewport_width, "height": viewport_height} if viewport_width else None),
    }
    if not render and any(value is not None for value in rendered_options.values()):
        raise ValueError("browser options require render=True for crawl requests")
    crawl_options: dict[str, Any] = {
        "limit": limit,
        "render": render,
        "source": source,
        "options": {
            "includeExternalLinks": include_external,
            "includeSubdomains": include_subdomains,
        },
        **kwargs,
    }
    for name, value in (
        ("depth", depth or None),
        ("formats", parsed_formats),
        ("crawl_purposes", parsed_purposes),
        ("max_age", max_age if max_age >= 0 else None),
        ("modified_since", modified_since or None),
        ("include_patterns", parsed_include_patterns),
        ("exclude_patterns", parsed_exclude_patterns),
        ("json_options", parsed_json_options),
        *rendered_options.items(),
    ):
        if value is not None:
            crawl_options[name] = value
    transport_options: dict[str, Any] = {}
    if no_cache:
        transport_options["no_cache"] = True
    if no_cache or cache_ttl >= 0:
        transport_options["cache_ttl"] = 0 if no_cache else cache_ttl
    job_id = await client.crawl(url, **transport_options, **crawl_options)
    return json.dumps({"job_id": job_id, "status": "started"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 10: browser_crawl_status
# ---------------------------------------------------------------------------


@mcp.tool(description="Check crawl job status. Set wait=True to block until complete.")
async def browser_crawl_status(
    job_id: str,
    wait: bool = False,
    timeout: int = 60,
    cursor: str | int | None = None,
    limit: int = 0,
    status: str = "",
) -> str:
    """Poll or block on the status of a crawl job and return as JSON.

    Args:
        job_id: The crawl job ID returned by browser_crawl.
        wait: When True, poll until the job completes or timeout is reached.
        timeout: Maximum seconds to wait when wait=True (default 60).
    """
    client = get_client()

    if not wait:
        if limit < 0:
            raise ValueError("limit must be a positive integer")
        result = await client.crawl_status(
            job_id,
            cursor=cursor,
            limit=limit or None,
            status=status or None,
        )
        return json.dumps(result, ensure_ascii=False)

    if cursor is not None or limit or status:
        raise ValueError("cursor, limit, and status are only available when wait=False")

    # Delegate to SDK's crawl_wait which handles polling and error states
    try:
        result = await client.crawl_wait(
            job_id,
            timeout=float(timeout),
            poll_interval=2.0,
        )
        return json.dumps(result, ensure_ascii=False)
    except TimeoutError:
        return json.dumps(
            {"job_id": job_id, "status": "running", "_timeout": True},
            ensure_ascii=False,
        )
    except CrawlJobError as e:
        return json.dumps(
            {"job_id": job_id, "status": "failed", "error": str(e)},
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Tool 11: browser_delete_crawl
# ---------------------------------------------------------------------------


@mcp.tool(description="Cancel a crawl job and remove cached Worker state")
async def browser_delete_crawl(job_id: str) -> str:
    """Cancel the crawl identified by *job_id*."""
    client = get_client()
    await client.delete_crawl(job_id)
    return json.dumps({"job_id": job_id, "status": "cancelled"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 12: browser_a11y
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Get the accessibility tree of a web page — structured data for LLM "
        "consumption with lower token cost than HTML"
    )
)
async def browser_a11y(
    url: str,
    no_cache: bool = False,
    timeout: int = 0,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
) -> str:
    """Return the accessibility tree of *url* as JSON.

    The accessibility tree contains the same structured data that screen
    readers and assistive technologies use: headings, landmarks, links,
    buttons, form elements, and text content.

    Args:
        url: The page URL to inspect.
        wait_for: Optional CSS selector to wait for before capturing.
        wait_until: When to consider navigation done — "load" | "domcontentloaded"
                    | "networkidle0" | "networkidle2" (default: "load").
        user_agent: Custom User-Agent string for the browser.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
        add_script_tag: Optional JSON array of scripts to inject before capture.
                        Example: [{"content":"document.title='Modified'"}]
        add_style_tag: Optional JSON array of styles to inject before capture.
                       Example: [{"content":"body{background:red}"}]
        reject_resource_types: Optional JSON array of resource types to block.
                               Example: ["image","stylesheet"]
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    result = await client.a11y(url, no_cache=no_cache, **kwargs)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 13: browser_click
# ---------------------------------------------------------------------------


@mcp.tool(
    description=("Click an element on a web page (requires Worker mode with BROWSER binding)")
)
async def browser_click(
    url: str,
    selector: str,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
    timeout: int = 0,
) -> str:
    """Navigate to *url*, click the element matching *selector*, and return page state.

    Args:
        url: The page URL.
        selector: CSS selector of the element to click (e.g. "button#submit", "a.nav-link").
        wait_for: Optional CSS selector to wait for before clicking.
        wait_until: Navigation strategy — "load" | "domcontentloaded" | "networkidle0" | "networkidle2".
        user_agent: Custom User-Agent string.
        cookies: Optional JSON array of cookie objects.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    try:
        result = await client.click(url, selector, **kwargs)
        return json.dumps(result, ensure_ascii=False)
    except (NotImplementedError, NotFoundError, BrowserUnavailableError) as e:
        return _interaction_error_payload(e)


# ---------------------------------------------------------------------------
# Tool 14: browser_type
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Type text into an input field on a web page (requires Worker mode with BROWSER binding)"
    )
)
async def browser_type(
    url: str,
    selector: str,
    text: str,
    clear: bool = False,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
    timeout: int = 0,
) -> str:
    """Navigate to *url*, type *text* into the input matching *selector*.

    Args:
        url: The page URL.
        selector: CSS selector of the input element (e.g. "input#username", "textarea.comment").
        text: The text to type.
        clear: When True, clear the field before typing (default False).
        wait_for: Optional CSS selector to wait for before typing.
        wait_until: Navigation strategy — "load" | "domcontentloaded" | "networkidle0" | "networkidle2".
        user_agent: Custom User-Agent string.
        cookies: Optional JSON array of cookie objects.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    try:
        result = await client.type_text(url, selector, text, clear=clear, **kwargs)
        return json.dumps(result, ensure_ascii=False)
    except (NotImplementedError, NotFoundError, BrowserUnavailableError) as e:
        return _interaction_error_payload(e)


# ---------------------------------------------------------------------------
# Tool 15: browser_evaluate
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Execute JavaScript on a web page and return the result "
        "(requires Worker mode with BROWSER binding)"
    )
)
async def browser_evaluate(
    url: str,
    script: str,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
    timeout: int = 0,
) -> str:
    """Navigate to *url* and execute *script* in the page context.

    Args:
        url: The page URL.
        script: JavaScript code to execute (max 10KB). Example: "document.title"
                or "document.querySelectorAll('a').length".
        wait_for: Optional CSS selector to wait for before executing.
        wait_until: Navigation strategy — "load" | "domcontentloaded" | "networkidle0" | "networkidle2".
        user_agent: Custom User-Agent string.
        cookies: Optional JSON array of cookie objects.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )
    try:
        result = await client.evaluate(url, script, **kwargs)
        return json.dumps(result, ensure_ascii=False)
    except (NotImplementedError, NotFoundError, BrowserUnavailableError) as e:
        return _interaction_error_payload(e)


# ---------------------------------------------------------------------------
# Tool 16: browser_interact
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Execute a chain of browser actions (click, type, wait, screenshot, JS eval) — "
        "the most powerful interaction tool (requires Worker mode with BROWSER binding)"
    )
)
async def browser_interact(
    url: str,
    actions: list[dict[str, Any]] | str,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
    timeout: int = 0,
) -> str:
    """Navigate to *url* and execute a sequence of actions.

    Args:
        url: The starting page URL.
        actions: JSON array of action objects. Max 20 actions, 50s total timeout.
                 Each action has an "action" key plus action-specific params.
                 Supported actions:
                 - {"action":"click", "selector":"#btn"}
                 - {"action":"type", "selector":"#input", "text":"hello", "clear":true}
                 - {"action":"wait", "selector":".loaded", "timeout":5000}
                 - {"action":"navigate", "url":"https://..."}
                 - {"action":"screenshot"}
                 - {"action":"evaluate", "script":"document.title"}
                 - {"action":"select", "selector":"select#country", "value":"US"}
                 - {"action":"scroll", "x":0, "y":500}
                 Example: [{"action":"type","selector":"#user","text":"admin"},
                           {"action":"click","selector":"#login"},
                           {"action":"wait","selector":".dashboard"}]
        wait_for: Optional CSS selector to wait for before starting actions.
        wait_until: Navigation strategy — "load" | "domcontentloaded" | "networkidle0" | "networkidle2".
        user_agent: Custom User-Agent string.
        cookies: Optional JSON array of cookie objects.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )

    try:
        parsed_actions = _parse_json_value("actions", actions, list)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    if not parsed_actions or not all(isinstance(action, dict) for action in parsed_actions):
        return json.dumps({"error": "actions entries must be JSON objects"}, ensure_ascii=False)

    try:
        result = await client.interact(url, parsed_actions, **kwargs)
        return json.dumps(result, ensure_ascii=False)
    except (NotImplementedError, NotFoundError, BrowserUnavailableError) as e:
        return _interaction_error_payload(e)


# ---------------------------------------------------------------------------
# Tool 17: browser_submit_form
# ---------------------------------------------------------------------------


@mcp.tool(
    description=("Fill and submit a form on a web page (requires Worker mode with BROWSER binding)")
)
async def browser_submit_form(
    url: str,
    fields: dict[str, str] | str,
    submit_selector: str = "",
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: list[dict[str, Any]] | str | None = None,
    headers: dict[str, str] | str | None = None,
    authenticate: dict[str, str] | str | None = None,
    add_script_tag: list[dict[str, Any]] | str | None = None,
    add_style_tag: list[dict[str, Any]] | str | None = None,
    reject_resource_types: list[str] | str | None = None,
    timeout: int = 0,
) -> str:
    """Navigate to *url*, fill form fields, and submit.

    Args:
        url: The page URL containing the form.
        fields: JSON object mapping CSS selector → value for each field.
                Example: {"#username":"admin", "#password":"secret", "#email":"a@b.com"}
        submit_selector: Optional CSS selector for the submit button.
                         If empty, submits the first <form> on the page.
        wait_for: Optional CSS selector to wait for before filling.
        wait_until: Navigation strategy — "load" | "domcontentloaded" | "networkidle0" | "networkidle2".
        user_agent: Custom User-Agent string.
        cookies: Optional JSON array of cookie objects.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    kwargs = _build_kwargs(
        cookies=cookies,
        headers=headers,
        authenticate=authenticate,
        wait_for=wait_for,
        wait_until=wait_until,
        user_agent=user_agent,
        add_script_tag=add_script_tag,
        add_style_tag=add_style_tag,
        reject_resource_types=reject_resource_types,
        timeout=timeout,
    )

    try:
        parsed_fields = _parse_json_value("fields", fields, dict)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    if not parsed_fields or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in parsed_fields.items()
    ):
        return json.dumps({"error": "fields keys and values must be strings"}, ensure_ascii=False)

    try:
        result = await client.submit_form(
            url,
            parsed_fields,
            submit_selector=submit_selector or None,
            **kwargs,
        )
        return json.dumps(result, ensure_ascii=False)
    except (NotImplementedError, NotFoundError, BrowserUnavailableError) as e:
        return _interaction_error_payload(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for ``uvx cf-browser-mcp`` / ``pipx run cf-browser-mcp``."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
