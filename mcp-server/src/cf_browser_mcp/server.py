"""MCP Server wrapping the CF Browser Python SDK as 9 tools."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("cf-browser")

# ---------------------------------------------------------------------------
# Shared client singleton (avoids leaking httpx.AsyncClient per tool call)
# ---------------------------------------------------------------------------

_client = None


def get_client():
    """Return a singleton CFBrowser client (lazy-initialized)."""
    global _client
    if _client is None:
        from cf_browser import CFBrowser

        _client = CFBrowser(
            base_url=os.environ["CF_BROWSER_URL"],
            api_key=os.environ["CF_BROWSER_API_KEY"],
        )
    return _client


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


# ---------------------------------------------------------------------------
# Tool 1: browser_content
# ---------------------------------------------------------------------------


@mcp.tool(description="Fetch rendered HTML content of a web page (JavaScript executed)")
async def browser_content(url: str, wait_for: str = "") -> str:
    """Return the fully-rendered HTML of *url*.

    Args:
        url: The page URL to fetch.
        wait_for: Optional CSS selector to wait for before capturing.
    """
    client = get_client()
    kwargs: dict = {}
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
) -> str:
    """Capture a PNG screenshot of *url* and return the local file path.

    Args:
        url: The page URL to screenshot.
        width: Viewport width in pixels (default 1280).
        height: Viewport height in pixels (default 720).
        full_page: When True, capture the full scrollable page.
    """
    client = get_client()
    data: bytes = await client.screenshot(
        url, width=width, height=height, full_page=full_page
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
async def browser_pdf(url: str, format: str = "A4") -> str:
    """Render *url* as a PDF and return the local file path.

    Args:
        url: The page URL to render.
        format: Paper format – A4 | Letter | A3 | A5 | Legal | Tabloid (default A4).
    """
    client = get_client()
    data: bytes = await client.pdf(url, format=format)

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
async def browser_markdown(url: str) -> str:
    """Return the Markdown representation of *url*.

    Args:
        url: The page URL to convert.
    """
    client = get_client()
    return await client.markdown(url)


# ---------------------------------------------------------------------------
# Tool 5: browser_scrape
# ---------------------------------------------------------------------------


@mcp.tool(description="Scrape specific elements from a web page using CSS selectors")
async def browser_scrape(url: str, selectors: list[str]) -> str:
    """Extract DOM elements matching each CSS selector and return as JSON.

    Args:
        url: The page URL to scrape.
        selectors: List of CSS selectors to extract (e.g. ["h1", ".price", "#main"]).
    """
    client = get_client()
    result = await client.scrape(url, selectors)
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
async def browser_json(url: str, prompt: str) -> str:
    """Use AI to extract structured data from *url* and return as JSON.

    Args:
        url: The page URL to analyse.
        prompt: Natural-language description of the data to extract
                (e.g. "extract product name, price, and availability").
    """
    client = get_client()
    result = await client.json_extract(url, prompt)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 7: browser_links
# ---------------------------------------------------------------------------


@mcp.tool(description="Extract all links from a web page")
async def browser_links(url: str) -> str:
    """Return all hyperlinks found on *url* as a JSON array of {href, text} objects.

    Args:
        url: The page URL to inspect.
    """
    client = get_client()
    result = await client.links(url)
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

    # Blocking poll loop
    poll_interval = 2
    deadline = time.monotonic() + timeout

    while True:
        result = await client.crawl_status(job_id)
        status_value = (
            result.get("status") if isinstance(result, dict) else None
        )

        if status_value in ("complete", "completed", "failed", "error"):
            return json.dumps(result, ensure_ascii=False)

        if time.monotonic() >= deadline:
            result_with_timeout = dict(result) if isinstance(result, dict) else {"raw": result}
            result_with_timeout["_timeout"] = True
            return json.dumps(result_with_timeout, ensure_ascii=False)

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
