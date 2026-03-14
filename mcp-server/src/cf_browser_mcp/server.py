"""MCP Server wrapping the CF Browser Python SDK as 10 tools."""

from __future__ import annotations

import atexit
import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cf_browser.exceptions import CFBrowserError
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cf-browser")

# ---------------------------------------------------------------------------
# Shared client singleton (avoids leaking httpx.AsyncClient per tool call)
# ---------------------------------------------------------------------------

_client = None


def get_client():
    """Return a singleton browser client (lazy-initialized).

    Supports two modes based on environment variables:

    **Worker mode** (via deployed Cloudflare Worker):
        CF_BROWSER_URL + CF_BROWSER_API_KEY

    **Direct mode** (call CF API directly, no Worker needed):
        CF_ACCOUNT_ID + CF_API_TOKEN
    """
    global _client
    if _client is None:
        account_id = os.environ.get("CF_ACCOUNT_ID")
        api_token = os.environ.get("CF_API_TOKEN")
        worker_url = os.environ.get("CF_BROWSER_URL")
        worker_key = os.environ.get("CF_BROWSER_API_KEY")

        if account_id and api_token:
            from cf_browser import CFBrowserDirect

            _client = CFBrowserDirect(
                account_id=account_id,
                api_token=api_token,
            )
        elif worker_url and worker_key:
            from cf_browser import CFBrowser

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


def _cleanup_client():
    """Close the browser client on process exit."""
    global _client
    if _client is not None:
        try:
            asyncio.run(_client.close())
        except Exception:
            pass


atexit.register(_cleanup_client)


def _domain_from_url(url: str) -> str:
    """Extract a filesystem-safe domain string from a URL."""
    try:
        netloc = urlparse(url).netloc
        # Strip anything that isn't alphanumeric, dot, or hyphen
        return re.sub(r"[^\w.\-]", "_", netloc) or "unknown"
    except Exception:
        return "unknown"


def _timestamp() -> str:
    """Return a compact integer timestamp string."""
    return str(int(time.time()))


def _auth_kwargs(
    cookies: str = "",
    headers: str = "",
) -> dict[str, Any]:
    """Parse optional cookies/headers JSON strings into SDK kwargs."""
    kwargs: dict[str, Any] = {}
    if cookies:
        try:
            kwargs["cookies"] = json.loads(cookies)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid cookies JSON: {e}") from e
    if headers:
        try:
            kwargs["headers"] = json.loads(headers)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid headers JSON: {e}") from e
    return kwargs


# ---------------------------------------------------------------------------
# Tool 1: browser_content
# ---------------------------------------------------------------------------


@mcp.tool(description="Fetch rendered HTML content of a web page (JavaScript executed)")
async def browser_content(
    url: str,
    wait_for: str = "",
    cookies: str = "",
    headers: str = "",
) -> str:
    """Return the fully-rendered HTML of *url*.

    Args:
        url: The page URL to fetch.
        wait_for: Optional CSS selector to wait for before capturing.
        cookies: Optional JSON array of cookie objects for authenticated pages.
                 Example: [{"name":"session","value":"abc","domain":".example.com"}]
        headers: Optional JSON object of custom HTTP headers.
                 Example: {"X-Auth":"token123"}
    """
    client = get_client()
    kwargs = _auth_kwargs(cookies, headers)
    if wait_for:
        kwargs["wait_for"] = wait_for
    return await client.content(url, **kwargs)


# ---------------------------------------------------------------------------
# Tool 2: browser_screenshot
# ---------------------------------------------------------------------------


@mcp.tool(description="Take a screenshot of a web page")
async def browser_screenshot(
    url: str,
    width: int = 1280,
    height: int = 720,
    full_page: bool = False,
    cookies: str = "",
    headers: str = "",
) -> str:
    """Capture a PNG screenshot of *url* and return the local file path.

    Args:
        url: The page URL to screenshot.
        width: Viewport width in pixels (default 1280).
        height: Viewport height in pixels (default 720).
        full_page: When True, capture the full scrollable page.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    auth = _auth_kwargs(cookies, headers)
    data: bytes = await client.screenshot(
        url, width=width, height=height, full_page=full_page, **auth
    )

    out_dir = Path(tempfile.gettempdir()) / "cf-browser-screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    domain = _domain_from_url(url)
    file_path = out_dir / f"{domain}_{_timestamp()}.png"
    file_path.write_bytes(data)

    return str(file_path)


# ---------------------------------------------------------------------------
# Tool 3: browser_pdf
# ---------------------------------------------------------------------------


@mcp.tool(description="Generate PDF of a web page")
async def browser_pdf(
    url: str,
    format: str = "A4",
    landscape: bool = False,
    cookies: str = "",
    headers: str = "",
) -> str:
    """Render *url* as a PDF and return the local file path.

    Args:
        url: The page URL to render.
        format: Paper format – A4 | Letter | A3 | A5 | Legal | Tabloid (default A4).
        landscape: When True, render in landscape orientation (default False).
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    auth = _auth_kwargs(cookies, headers)
    kwargs = auth
    if landscape:
        kwargs["landscape"] = True
    data: bytes = await client.pdf(url, format=format, **kwargs)

    out_dir = Path(tempfile.gettempdir()) / "cf-browser-pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)

    domain = _domain_from_url(url)
    file_path = out_dir / f"{domain}_{_timestamp()}.pdf"
    file_path.write_bytes(data)

    return str(file_path)


# ---------------------------------------------------------------------------
# Tool 4: browser_markdown
# ---------------------------------------------------------------------------


@mcp.tool(description="Convert web page to clean Markdown (best for reading content)")
async def browser_markdown(
    url: str,
    cookies: str = "",
    headers: str = "",
) -> str:
    """Return the Markdown representation of *url*.

    Args:
        url: The page URL to convert.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    auth = _auth_kwargs(cookies, headers)
    return await client.markdown(url, **auth)


# ---------------------------------------------------------------------------
# Tool 5: browser_scrape
# ---------------------------------------------------------------------------


@mcp.tool(description="Scrape specific elements from a web page using CSS selectors")
async def browser_scrape(
    url: str,
    selectors: list[str],
    cookies: str = "",
    headers: str = "",
) -> str:
    """Extract DOM elements matching each CSS selector and return as JSON.

    Args:
        url: The page URL to scrape.
        selectors: List of CSS selectors to extract (e.g. ["h1", ".price", "#main"]).
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    auth = _auth_kwargs(cookies, headers)
    result = await client.scrape(url, selectors, **auth)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 6: browser_json
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Extract structured data from a web page using AI "
        "(provide a prompt describing what to extract)"
    )
)
async def browser_json(
    url: str,
    prompt: str,
    cookies: str = "",
    headers: str = "",
) -> str:
    """Use AI to extract structured data from *url* and return as JSON.

    Args:
        url: The page URL to analyse.
        prompt: Natural-language description of the data to extract
                (e.g. "extract product name, price, and availability").
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    auth = _auth_kwargs(cookies, headers)
    result = await client.json_extract(url, prompt, **auth)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 7: browser_links
# ---------------------------------------------------------------------------


@mcp.tool(description="Extract all links from a web page")
async def browser_links(
    url: str,
    cookies: str = "",
    headers: str = "",
) -> str:
    """Return all hyperlinks found on *url* as a JSON array of {href, text} objects.

    Args:
        url: The page URL to inspect.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    auth = _auth_kwargs(cookies, headers)
    result = await client.links(url, **auth)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 8: browser_crawl
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Start crawling a website (async – use browser_crawl_status to check progress)"
    )
)
async def browser_crawl(url: str, limit: int = 10) -> str:
    """Kick off an async website crawl and return the job ID plus initial status.

    Args:
        url: Seed URL for the crawl.
        limit: Maximum number of pages to crawl (default 10).
    """
    client = get_client()
    job_id = await client.crawl(url, limit=limit)
    return json.dumps({"job_id": job_id, "status": "started"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 9: browser_crawl_status
# ---------------------------------------------------------------------------


@mcp.tool(description="Check crawl job status. Set wait=True to block until complete.")
async def browser_crawl_status(
    job_id: str,
    wait: bool = False,
    timeout: int = 60,
) -> str:
    """Poll or block on the status of a crawl job and return as JSON.

    Args:
        job_id: The crawl job ID returned by browser_crawl.
        wait: When True, poll until the job completes or timeout is reached.
        timeout: Maximum seconds to wait when wait=True (default 60).
    """
    client = get_client()

    if not wait:
        result = await client.crawl_status(job_id)
        return json.dumps(result, ensure_ascii=False)

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
    except CFBrowserError as e:
        return json.dumps(
            {"job_id": job_id, "status": "failed", "error": str(e)},
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Tool 10: browser_a11y
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Get the accessibility tree of a web page — structured data for LLM "
        "consumption with lower token cost than HTML"
    )
)
async def browser_a11y(
    url: str,
    wait_for: str = "",
    cookies: str = "",
    headers: str = "",
) -> str:
    """Return the accessibility tree of *url* as JSON.

    The accessibility tree contains the same structured data that screen
    readers and assistive technologies use: headings, landmarks, links,
    buttons, form elements, and text content.

    Args:
        url: The page URL to inspect.
        wait_for: Optional CSS selector to wait for before capturing.
        cookies: Optional JSON array of cookie objects for authenticated pages.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    kwargs = _auth_kwargs(cookies, headers)
    if wait_for:
        kwargs["wait_for"] = wait_for
    result = await client.a11y(url, **kwargs)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
