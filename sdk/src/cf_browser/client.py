"""
CFBrowser async client.

Example usage::

    async with CFBrowser(base_url="https://...", api_key="...") as browser:
        html = await browser.content("https://example.com")
        md   = await browser.markdown("https://example.com")
        png  = await browser.screenshot("https://example.com", width=1280)
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

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
        message = body.get("error") or body.get("message") or str(body)
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
    ) -> dict:
        """Scrape specific CSS *selectors* from *url*.

        Parameters
        ----------
        selectors:
            List of CSS selectors to extract.

        Returns
        -------
        dict
            Parsed elements keyed by selector.
        """
        payload = _build_payload(url, no_cache, {"elements": selectors, **opts})
        return await self._post_json("/scrape", payload)

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

    async def links(self, url: str, *, no_cache: bool = False, **opts: Any) -> list[dict]:
        """Extract all hyperlinks from *url*.

        Returns
        -------
        list[dict]
            Each item has at minimum ``href`` and optionally ``text``.
        """
        payload = _build_payload(url, no_cache, opts)
        return await self._post_json("/links", payload)

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
        return data["job_id"]

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
        deadline = time.monotonic() + timeout

        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Crawl job {job_id!r} did not complete within {timeout}s"
                )

            status_data = await self.crawl_status(job_id)
            status = status_data.get("status", "")

            if status in ("complete", "completed"):
                return status_data
            if status in ("failed", "error"):
                error_msg = status_data.get("error", "unknown error")
                raise CFBrowserError(
                    f"Crawl job failed: {error_msg}",
                    status_code=None,
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Crawl job {job_id!r} did not complete within {timeout}s"
                )
            await asyncio.sleep(min(poll_interval, remaining))

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
