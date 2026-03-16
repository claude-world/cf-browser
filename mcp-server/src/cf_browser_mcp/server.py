"""MCP Server wrapping the CF Browser Python SDK as 15 tools."""

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
    """Return a compact timestamp string with millisecond precision to avoid collisions."""
    return str(int(time.time() * 1000))


def _build_kwargs(
    cookies: str = "",
    headers: str = "",
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    add_script_tag: str = "",
    add_style_tag: str = "",
    reject_resource_types: str = "",
) -> dict[str, Any]:
    """Parse tool params into SDK kwargs.

    Handles JSON parsing for cookies/headers/script/style strings and
    passes through browser-control params (wait_for, wait_until, user_agent)
    which the SDK translates to CF API equivalents.
    """
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
    if wait_for:
        kwargs["wait_for"] = wait_for
    if wait_until:
        kwargs["wait_until"] = wait_until
    if user_agent:
        kwargs["user_agent"] = user_agent
    if add_script_tag:
        try:
            kwargs["add_script_tag"] = json.loads(add_script_tag)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid add_script_tag JSON: {e}") from e
    if add_style_tag:
        try:
            kwargs["add_style_tag"] = json.loads(add_style_tag)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid add_style_tag JSON: {e}") from e
    if reject_resource_types:
        try:
            kwargs["reject_resource_types"] = json.loads(reject_resource_types)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid reject_resource_types JSON: {e}") from e
    return kwargs


# ---------------------------------------------------------------------------
# Tool 1: browser_content
# ---------------------------------------------------------------------------


@mcp.tool(description="Fetch rendered HTML content of a web page (JavaScript executed)")
async def browser_content(
    url: str,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
    add_script_tag: str = "",
    add_style_tag: str = "",
    reject_resource_types: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent, add_script_tag, add_style_tag, reject_resource_types)
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
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
    add_script_tag: str = "",
    add_style_tag: str = "",
    reject_resource_types: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent, add_script_tag, add_style_tag, reject_resource_types)
    data: bytes = await client.screenshot(
        url, width=width, height=height, full_page=full_page, **kwargs
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
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
    add_script_tag: str = "",
    add_style_tag: str = "",
    reject_resource_types: str = "",
) -> str:
    """Render *url* as a PDF and return the local file path.

    Args:
        url: The page URL to render.
        format: Paper format – A4 | Letter | A3 | A5 | Legal | Tabloid (default A4).
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent, add_script_tag, add_style_tag, reject_resource_types)
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
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
    add_script_tag: str = "",
    add_style_tag: str = "",
    reject_resource_types: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent, add_script_tag, add_style_tag, reject_resource_types)
    return await client.markdown(url, **kwargs)


# ---------------------------------------------------------------------------
# Tool 5: browser_scrape
# ---------------------------------------------------------------------------


@mcp.tool(description="Scrape specific elements from a web page using CSS selectors")
async def browser_scrape(
    url: str,
    selectors: list[str],
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
    add_script_tag: str = "",
    add_style_tag: str = "",
    reject_resource_types: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent, add_script_tag, add_style_tag, reject_resource_types)
    result = await client.scrape(url, selectors, **kwargs)
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
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
    add_script_tag: str = "",
    add_style_tag: str = "",
    reject_resource_types: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent, add_script_tag, add_style_tag, reject_resource_types)
    result = await client.json_extract(url, prompt, **kwargs)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 7: browser_links
# ---------------------------------------------------------------------------


@mcp.tool(description="Extract all links from a web page")
async def browser_links(
    url: str,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
    add_script_tag: str = "",
    add_style_tag: str = "",
    reject_resource_types: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent, add_script_tag, add_style_tag, reject_resource_types)
    result = await client.links(url, **kwargs)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 8: browser_crawl
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Start crawling a website (async – use browser_crawl_status to check progress)"
    )
)
async def browser_crawl(
    url: str,
    limit: int = 10,
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
) -> str:
    """Kick off an async website crawl and return the job ID plus initial status.

    Args:
        url: Seed URL for the crawl.
        limit: Maximum number of pages to crawl (default 10).
        user_agent: Custom User-Agent string for the browser.
        cookies: Optional JSON array of cookie objects for authenticated crawling.
        headers: Optional JSON object of custom HTTP headers.
    """
    client = get_client()
    kwargs = _build_kwargs(cookies=cookies, headers=headers, user_agent=user_agent)
    job_id = await client.crawl(url, limit=limit, **kwargs)
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
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
    add_script_tag: str = "",
    add_style_tag: str = "",
    reject_resource_types: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent, add_script_tag, add_style_tag, reject_resource_types)
    result = await client.a11y(url, **kwargs)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 11: browser_click
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Click an element on a web page (requires Worker mode with BROWSER binding)"
    )
)
async def browser_click(
    url: str,
    selector: str,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent)
    try:
        result = await client.click(url, selector, **kwargs)
        return json.dumps(result, ensure_ascii=False)
    except NotImplementedError as e:
        return json.dumps({"error": str(e), "hint": "Use Worker mode with BROWSER binding"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 12: browser_type
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
    cookies: str = "",
    headers: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent)
    try:
        result = await client.type_text(url, selector, text, clear=clear, **kwargs)
        return json.dumps(result, ensure_ascii=False)
    except NotImplementedError as e:
        return json.dumps({"error": str(e), "hint": "Use Worker mode with BROWSER binding"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 13: browser_evaluate
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
    cookies: str = "",
    headers: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent)
    try:
        result = await client.evaluate(url, script, **kwargs)
        return json.dumps(result, ensure_ascii=False)
    except NotImplementedError as e:
        return json.dumps({"error": str(e), "hint": "Use Worker mode with BROWSER binding"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 14: browser_interact
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Execute a chain of browser actions (click, type, wait, screenshot, JS eval) — "
        "the most powerful interaction tool (requires Worker mode with BROWSER binding)"
    )
)
async def browser_interact(
    url: str,
    actions: str,
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent)

    try:
        parsed_actions = json.loads(actions)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid actions JSON: {e}"}, ensure_ascii=False)

    if not isinstance(parsed_actions, list):
        return json.dumps({"error": "actions must be a JSON array"}, ensure_ascii=False)

    try:
        result = await client.interact(url, parsed_actions, **kwargs)
        return json.dumps(result, ensure_ascii=False)
    except NotImplementedError as e:
        return json.dumps({"error": str(e), "hint": "Use Worker mode with BROWSER binding"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 15: browser_submit_form
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Fill and submit a form on a web page "
        "(requires Worker mode with BROWSER binding)"
    )
)
async def browser_submit_form(
    url: str,
    fields: str,
    submit_selector: str = "",
    wait_for: str = "",
    wait_until: str = "",
    user_agent: str = "",
    cookies: str = "",
    headers: str = "",
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
    kwargs = _build_kwargs(cookies, headers, wait_for, wait_until, user_agent)

    try:
        parsed_fields = json.loads(fields)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid fields JSON: {e}"}, ensure_ascii=False)

    if not isinstance(parsed_fields, dict):
        return json.dumps({"error": "fields must be a JSON object"}, ensure_ascii=False)

    try:
        result = await client.submit_form(
            url,
            parsed_fields,
            submit_selector=submit_selector or None,
            **kwargs,
        )
        return json.dumps(result, ensure_ascii=False)
    except NotImplementedError as e:
        return json.dumps({"error": str(e), "hint": "Use Worker mode with BROWSER binding"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Entry point for ``uvx cf-browser-mcp`` / ``pipx run cf-browser-mcp``."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
