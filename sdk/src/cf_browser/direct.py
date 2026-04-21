"""
CFBrowserDirect — call Cloudflare Browser Rendering API without a Worker.

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

from typing import Any

import httpx

from ._normalizers import normalize_links_response, normalize_scrape_response
from .exceptions import (
    AuthenticationError,
    CFBrowserError,
    NotFoundError,
    RateLimitError,
)

_CF_API_BASE = "https://api.cloudflare.com/client/v4/accounts"


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP error codes to typed SDK exceptions."""
    if response.is_success:
        return

    try:
        body = response.json()
        # CF API nests errors in {"success": false, "errors": [{"message": "..."}]}
        if isinstance(body, dict):
            errors = body.get("errors")
            if isinstance(errors, list) and errors:
                message = errors[0].get("message", str(body))
            else:
                message = body.get("error") or body.get("message") or str(body)
        else:
            message = str(body)
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


def _transform_screenshot_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Map user-friendly screenshot params to CF API format."""
    out = dict(opts)
    width = out.pop("width", None)
    height = out.pop("height", None)
    full_page = out.pop("full_page", None)

    if width or height:
        out["viewport"] = {
            "width": width or 1920,
            "height": height or 1080,
        }
    if full_page:
        out["screenshotOptions"] = {"fullPage": True}
    return out


def _transform_pdf_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Strip PDF-specific params not supported by the CF REST API.

    The CF Browser Rendering REST API ``/pdf`` endpoint does not accept
    ``format`` or ``landscape`` options (unlike the Puppeteer-based Workers
    Binding API).  We strip them silently so callers can use the same kwargs
    across Worker and Direct modes without errors.
    """
    out = dict(opts)
    out.pop("format", None)
    out.pop("landscape", None)
    return out


def _transform_scrape_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Map string selectors to CF API's ``[{selector: "..."}]`` format."""
    out = dict(opts)
    elements = out.get("elements")
    if isinstance(elements, list):
        out["elements"] = [
            {"selector": el} if isinstance(el, str) else el for el in elements
        ]
    return out


def _transform_crawl_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Map ``max_pages`` to CF API's ``limit`` param."""
    out = dict(opts)
    max_pages = out.pop("max_pages", None)
    if max_pages and "limit" not in out:
        out["limit"] = max_pages
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
        goto_options: dict[str, Any] = out.get("gotoOptions", {})
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
    """Call Cloudflare Browser Rendering API directly (no Worker needed).

    Parameters
    ----------
    account_id:
        Cloudflare Account ID (from ``wrangler whoami`` or dashboard).
    api_token:
        Cloudflare API Token with Browser Rendering permissions.
    timeout:
        Default request timeout in seconds (default 60).
    """

    def __init__(self, account_id: str, api_token: str, timeout: float = 60.0) -> None:
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

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> httpx.Response:
        response = await self._client.post(
            f"{self._base_url}{endpoint}", json=payload
        )
        _raise_for_status(response)
        return response

    async def _post_text(self, endpoint: str, payload: dict[str, Any]) -> str:
        response = await self._post(endpoint, payload)
        ct = response.headers.get("content-type", "")
        if "application/json" in ct:
            return str(_unwrap_cf_envelope(response.json()))
        return response.text

    async def _post_bytes(self, endpoint: str, payload: dict[str, Any]) -> bytes:
        response = await self._post(endpoint, payload)
        return response.content

    async def _post_json(self, endpoint: str, payload: dict[str, Any]) -> Any:
        response = await self._post(endpoint, payload)
        return _unwrap_cf_envelope(response.json())

    async def _get_json(self, endpoint: str) -> Any:
        response = await self._client.get(f"{self._base_url}{endpoint}")
        _raise_for_status(response)
        return _unwrap_cf_envelope(response.json())

    @staticmethod
    def _strip_no_cache(opts: dict[str, Any]) -> dict[str, Any]:
        """Remove ``no_cache`` — CF API doesn't support it."""
        out = dict(opts)
        out.pop("no_cache", None)
        return out

    # ------------------------------------------------------------------
    # Public API (same interface as CFBrowser)
    # ------------------------------------------------------------------

    async def content(self, url: str, *, no_cache: bool = False, **opts: Any) -> str:
        payload = self._strip_no_cache({"url": url, **opts})
        payload = _transform_common_opts(payload)
        return await self._post_text("/content", payload)

    async def screenshot(self, url: str, *, no_cache: bool = False, **opts: Any) -> bytes:
        payload = self._strip_no_cache({"url": url, **opts})
        payload = _transform_common_opts(payload)
        payload = _transform_screenshot_opts(payload)
        return await self._post_bytes("/screenshot", payload)

    async def pdf(self, url: str, *, no_cache: bool = False, **opts: Any) -> bytes:
        payload = self._strip_no_cache({"url": url, **opts})
        payload = _transform_common_opts(payload)
        payload = _transform_pdf_opts(payload)
        return await self._post_bytes("/pdf", payload)

    async def markdown(self, url: str, *, no_cache: bool = False, **opts: Any) -> str:
        payload = self._strip_no_cache({"url": url, **opts})
        payload = _transform_common_opts(payload)
        return await self._post_text("/markdown", payload)

    async def snapshot(self, url: str, *, no_cache: bool = False, **opts: Any) -> dict:
        payload = self._strip_no_cache({"url": url, **opts})
        payload = _transform_common_opts(payload)
        return await self._post_json("/snapshot", payload)

    async def scrape(
        self,
        url: str,
        selectors: list[str],
        *,
        no_cache: bool = False,
        **opts: Any,
    ) -> dict[str, Any]:
        payload = self._strip_no_cache({"url": url, "elements": selectors, **opts})
        payload = _transform_common_opts(payload)
        payload = _transform_scrape_opts(payload)
        return normalize_scrape_response(await self._post_json("/scrape", payload))

    async def json_extract(
        self,
        url: str,
        prompt: str,
        *,
        no_cache: bool = False,
        **opts: Any,
    ) -> dict:
        payload = self._strip_no_cache({"url": url, "prompt": prompt, **opts})
        payload = _transform_common_opts(payload)
        return await self._post_json("/json", payload)

    async def links(
        self,
        url: str,
        *,
        no_cache: bool = False,
        **opts: Any,
    ) -> list[dict[str, Any]]:
        payload = self._strip_no_cache({"url": url, **opts})
        payload = _transform_common_opts(payload)
        return normalize_links_response(await self._post_json("/links", payload))

    async def a11y(self, url: str, *, no_cache: bool = False, **opts: Any) -> dict:
        """Accessibility tree via /snapshot with screenshot data stripped."""
        payload = self._strip_no_cache({"url": url, **opts})
        payload = _transform_common_opts(payload)
        snapshot = await self._post_json("/snapshot", payload)
        if isinstance(snapshot, dict):
            snapshot.pop("screenshot", None)
            return {"type": "accessibility_snapshot", **snapshot}
        return {"type": "accessibility_snapshot", "data": snapshot}

    async def crawl(self, url: str, *, no_cache: bool = False, **opts: Any) -> str:
        payload = self._strip_no_cache({"url": url, **opts})
        payload = _transform_common_opts(payload)
        payload = _transform_crawl_opts(payload)
        data = await self._post_json("/crawl", payload)
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            job_id = data.get("id") or data.get("job_id")
            if job_id:
                return str(job_id)
        raise CFBrowserError("Crawl response missing job_id", status_code=None)

    async def crawl_status(self, job_id: str) -> dict:
        data = await self._get_json(f"/crawl/{job_id}")
        if isinstance(data, dict):
            return {"job_id": data.get("id", job_id), "status": data.get("status", "unknown"), **data}
        return {"job_id": job_id, "status": "unknown", "data": data}

    async def crawl_wait(
        self,
        job_id: str,
        *,
        timeout: float = 300,
        poll_interval: float = 5,
    ) -> dict:
        from ._shared import crawl_wait_poll
        return await crawl_wait_poll(
            job_id, self.crawl_status, timeout=timeout, poll_interval=poll_interval
        )

    # ------------------------------------------------------------------
    # Interaction API stubs (not supported in Direct mode)
    # ------------------------------------------------------------------

    _INTERACT_MSG = (
        "Browser interaction requires Worker mode with BROWSER binding. "
        "Direct mode only supports read-only operations."
    )

    async def click(self, url: str, selector: str, **opts: Any) -> dict:
        raise NotImplementedError(self._INTERACT_MSG)

    async def type_text(
        self, url: str, selector: str, text: str, *, clear: bool = False, **opts: Any
    ) -> dict:
        raise NotImplementedError(self._INTERACT_MSG)

    async def evaluate(self, url: str, script: str, **opts: Any) -> dict:
        raise NotImplementedError(self._INTERACT_MSG)

    async def interact(self, url: str, actions: list[dict], **opts: Any) -> dict:
        raise NotImplementedError(self._INTERACT_MSG)

    async def submit_form(
        self,
        url: str,
        fields: dict[str, str],
        *,
        submit_selector: str | None = None,
        **opts: Any,
    ) -> dict:
        raise NotImplementedError(self._INTERACT_MSG)

    async def delete_crawl(self, job_id: str) -> None:
        raise NotImplementedError(
            "delete_crawl is not yet implemented in Direct mode. "
            "The CF REST API may not expose a crawl deletion endpoint. "
            "Use Worker mode if you need to manage cached crawl results."
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "CFBrowserDirect":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
