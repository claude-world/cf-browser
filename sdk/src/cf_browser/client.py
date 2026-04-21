"""
CFBrowser async client.

Example usage::

    async with CFBrowser(base_url="https://...", api_key="...") as browser:
        html = await browser.content("https://example.com")
        md   = await browser.markdown("https://example.com")
        png  = await browser.screenshot("https://example.com", width=1280)
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


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP error codes to typed SDK exceptions."""
    if response.is_success:
        return

    # Try to extract a message from the response body.
    try:
        body = response.json()
        if isinstance(body, dict):
            message = body.get("error") or body.get("message") or str(body)
        else:
            message = str(body)
    except ValueError:
        message = response.text or f"HTTP {response.status_code}"

    status = response.status_code
    if status == 401:
        raise AuthenticationError(message, status_code=status)
    if status == 404:
        raise NotFoundError(message, status_code=status)
    if status == 429:
        raise RateLimitError(message, status_code=status)
    raise CFBrowserError(message, status_code=status)


def _build_payload(url: str, no_cache: bool | None, extras: dict[str, Any]) -> dict[str, Any]:
    """Assemble the JSON body sent to the Worker."""
    payload: dict[str, Any] = {"url": url, **extras}
    if no_cache:
        payload["no_cache"] = True
    return payload


class CFBrowser:
    """Async Python client for the CF Browser Worker API.

    Parameters
    ----------
    base_url:
        Root URL of the deployed Cloudflare Worker
        (e.g. ``"https://cf-browser.example.workers.dev"``).
    api_key:
        Secret key sent as ``Authorization: Bearer <api_key>``.
    timeout:
        Default request timeout in seconds (default 30).
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _post_text(self, path: str, payload: dict[str, Any]) -> str:
        response = await self._client.post(f"{self._base_url}{path}", json=payload)
        _raise_for_status(response)
        return response.text

    async def _post_bytes(self, path: str, payload: dict[str, Any]) -> bytes:
        response = await self._client.post(f"{self._base_url}{path}", json=payload)
        _raise_for_status(response)
        return response.content

    async def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        response = await self._client.post(f"{self._base_url}{path}", json=payload)
        _raise_for_status(response)
        return response.json()

    async def _get_json(self, path: str) -> Any:
        response = await self._client.get(f"{self._base_url}{path}")
        _raise_for_status(response)
        return response.json()

    async def _delete(self, path: str) -> None:
        response = await self._client.delete(f"{self._base_url}{path}")
        _raise_for_status(response)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def content(self, url: str, *, no_cache: bool = False, **opts: Any) -> str:
        """Fetch the raw HTML content of *url*.

        Returns
        -------
        str
            The full HTML source of the rendered page.
        """
        payload = _build_payload(url, no_cache, opts)
        return await self._post_text("/content", payload)

    async def screenshot(self, url: str, *, no_cache: bool = False, **opts: Any) -> bytes:
        """Capture a screenshot of *url*.

        Returns
        -------
        bytes
            Raw PNG image bytes.
        """
        payload = _build_payload(url, no_cache, opts)
        return await self._post_bytes("/screenshot", payload)

    async def pdf(self, url: str, *, no_cache: bool = False, **opts: Any) -> bytes:
        """Generate a PDF of *url*.

        Returns
        -------
        bytes
            Raw PDF bytes.
        """
        payload = _build_payload(url, no_cache, opts)
        return await self._post_bytes("/pdf", payload)

    async def markdown(self, url: str, *, no_cache: bool = False, **opts: Any) -> str:
        """Convert *url* to Markdown.

        Returns
        -------
        str
            Markdown-formatted page content.
        """
        payload = _build_payload(url, no_cache, opts)
        return await self._post_text("/markdown", payload)

    async def snapshot(self, url: str, *, no_cache: bool = False, **opts: Any) -> dict:
        """Take a full snapshot (HTML + screenshot) of *url*.

        Returns
        -------
        dict
            JSON snapshot payload from the Worker.
        """
        payload = _build_payload(url, no_cache, opts)
        return await self._post_json("/snapshot", payload)

    async def scrape(
        self,
        url: str,
        selectors: list[str],
        *,
        no_cache: bool = False,
        **opts: Any,
    ) -> dict[str, Any]:
        """Scrape specific CSS *selectors* from *url*.

        Parameters
        ----------
        selectors:
            List of CSS selectors to extract.

        Returns
        -------
        dict
            Normalized as ``{"elements": [...]}``.
        """
        payload = _build_payload(url, no_cache, {"elements": selectors, **opts})
        return normalize_scrape_response(await self._post_json("/scrape", payload))

    async def json_extract(
        self,
        url: str,
        prompt: str,
        *,
        no_cache: bool = False,
        **opts: Any,
    ) -> dict:
        """Use an AI prompt to extract structured JSON from *url*.

        Parameters
        ----------
        prompt:
            Natural-language description of what to extract.

        Returns
        -------
        dict
            Extracted data as a JSON object.
        """
        payload = _build_payload(url, no_cache, {"prompt": prompt, **opts})
        return await self._post_json("/json", payload)

    async def links(
        self,
        url: str,
        *,
        no_cache: bool = False,
        **opts: Any,
    ) -> list[dict[str, Any]]:
        """Extract all hyperlinks from *url*.

        Returns
        -------
        list[dict]
            Each item has at minimum ``href`` and optionally ``text``.
        """
        payload = _build_payload(url, no_cache, opts)
        return normalize_links_response(await self._post_json("/links", payload))

    async def a11y(self, url: str, *, no_cache: bool = False, **opts: Any) -> dict:
        """Get the accessibility tree of *url*.

        Returns a structured representation of the page's accessibility
        information — the same data assistive technologies use. Lower
        token cost than HTML for LLM consumption.

        Returns
        -------
        dict
            Accessibility tree data.
        """
        payload = _build_payload(url, no_cache, opts)
        return await self._post_json("/a11y", payload)

    async def crawl(self, url: str, *, no_cache: bool = False, **opts: Any) -> str:
        """Start an asynchronous crawl of *url*.

        Returns
        -------
        str
            The ``job_id`` for the crawl job (pass to :meth:`crawl_status`
            or :meth:`crawl_wait`).
        """
        payload = _build_payload(url, no_cache, opts)
        data = await self._post_json("/crawl", payload)
        job_id = data.get("job_id") if isinstance(data, dict) else None
        if not job_id:
            raise CFBrowserError(
                "Crawl response missing job_id",
                status_code=None,
            )
        return job_id

    async def crawl_status(self, job_id: str) -> dict:
        """Poll the status of a crawl job.

        Parameters
        ----------
        job_id:
            The job ID returned by :meth:`crawl`.

        Returns
        -------
        dict
            Status payload with at minimum ``job_id`` and ``status`` keys.
        """
        return await self._get_json(f"/crawl/{job_id}")

    async def crawl_wait(
        self,
        job_id: str,
        *,
        timeout: float = 300,
        poll_interval: float = 5,
    ) -> dict:
        """Block until a crawl job completes (or fails / times out).

        Parameters
        ----------
        job_id:
            The job ID returned by :meth:`crawl`.
        timeout:
            Maximum seconds to wait before raising :class:`TimeoutError`.
        poll_interval:
            Seconds between status polls.

        Returns
        -------
        dict
            The final status payload (``status == "complete"``).

        Raises
        ------
        TimeoutError
            If the job does not finish within *timeout* seconds.
        CFBrowserError
            If the job reaches ``status == "failed"``.
        """
        from ._shared import crawl_wait_poll
        return await crawl_wait_poll(
            job_id, self.crawl_status, timeout=timeout, poll_interval=poll_interval
        )

    # ------------------------------------------------------------------
    # Interaction API (requires Worker with BROWSER binding)
    # ------------------------------------------------------------------

    async def click(self, url: str, selector: str, **opts: Any) -> dict:
        """Click an element on *url*.

        Parameters
        ----------
        selector:
            CSS selector of the element to click.

        Returns
        -------
        dict
            Page state after click: ``{url, title, content}``.
        """
        payload = _build_payload(url, None, {"selector": selector, **opts})
        return await self._post_json("/click", payload)

    async def type_text(
        self, url: str, selector: str, text: str, *, clear: bool = False, **opts: Any
    ) -> dict:
        """Type text into an input element on *url*.

        Parameters
        ----------
        selector:
            CSS selector of the input element.
        text:
            Text to type.
        clear:
            When True, clear the field before typing.

        Returns
        -------
        dict
            Page state after typing: ``{url, title, content}``.
        """
        extras: dict[str, Any] = {"selector": selector, "text": text, **opts}
        if clear:
            extras["clear"] = True
        payload = _build_payload(url, None, extras)
        return await self._post_json("/type", payload)

    async def evaluate(self, url: str, script: str, **opts: Any) -> dict:
        """Execute JavaScript on *url* and return the result.

        Parameters
        ----------
        script:
            JavaScript code to execute in the page context.

        Returns
        -------
        dict
            ``{result, type}`` where *result* is the return value.
        """
        payload = _build_payload(url, None, {"script": script, **opts})
        return await self._post_json("/evaluate", payload)

    async def interact(self, url: str, actions: list[dict], **opts: Any) -> dict:
        """Execute a chain of browser actions on *url*.

        Parameters
        ----------
        actions:
            List of action objects. Each must have an ``action`` key
            (navigate, click, type, wait, screenshot, evaluate, select, scroll).

        Returns
        -------
        dict
            ``{url, title, results}`` where *results* is a list of per-action outcomes.
        """
        payload = _build_payload(url, None, {"actions": actions, **opts})
        return await self._post_json("/interact", payload)

    async def submit_form(
        self,
        url: str,
        fields: dict[str, str],
        *,
        submit_selector: str | None = None,
        **opts: Any,
    ) -> dict:
        """Fill and submit a form on *url*.

        Parameters
        ----------
        fields:
            Mapping of CSS selector → value for each form field.
        submit_selector:
            Optional CSS selector for the submit button. If omitted,
            submits the first ``<form>`` on the page.

        Returns
        -------
        dict
            Page state after submission: ``{url, title, content}``.
        """
        extras: dict[str, Any] = {"fields": fields, **opts}
        if submit_selector:
            extras["submit_selector"] = submit_selector
        payload = _build_payload(url, None, extras)
        return await self._post_json("/submit-form", payload)

    async def delete_crawl(self, job_id: str) -> None:
        """Delete a cached crawl result.

        Parameters
        ----------
        job_id:
            The crawl job ID to delete.
        """
        await self._delete(f"/crawl/{job_id}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        await self._client.aclose()

    async def __aenter__(self) -> "CFBrowser":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
