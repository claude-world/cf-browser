"""
CFBrowser async client.

Example usage::

    async with CFBrowser(base_url="https://...", api_key="...") as browser:
        html = await browser.content("https://example.com")
        md   = await browser.markdown("https://example.com")
        png  = await browser.screenshot("https://example.com", width=1280)
"""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ._normalizers import normalize_links_response, normalize_scrape_response
from .exceptions import (
    AuthenticationError,
    BrowserUnavailableError,
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

DEFAULT_WORKER_TIMEOUT = 320.0
_WORKER_ERROR_MESSAGE_MAX = 2_048


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
    if status == 501:
        raise BrowserUnavailableError(message, status_code=status)
    raise CFBrowserError(message, status_code=status)


def _build_payload(url: str, no_cache: bool | None, extras: dict[str, Any]) -> dict[str, Any]:
    """Assemble the JSON body sent to the Worker."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    if no_cache is not None and not isinstance(no_cache, bool):
        raise ValueError("no_cache must be a boolean")
    payload: dict[str, Any] = {"url": url, **extras}
    validate_common_canonical_options(payload)
    if no_cache:
        payload["no_cache"] = True
    return payload


def _decode_json(response: httpx.Response) -> Any:
    """Decode a successful response without leaking a raw JSON parser error."""
    try:
        data = response.json()
    except ValueError as exc:
        raise CFBrowserError(
            "CF Browser returned an invalid JSON response",
            status_code=response.status_code,
        ) from exc
    if isinstance(data, dict) and data.get("success") is False:
        errors = data.get("errors")
        nested_message = (
            errors[0].get("message")
            if isinstance(errors, list) and errors and isinstance(errors[0], dict)
            else None
        )
        message = next(
            (
                candidate.strip()
                for candidate in (nested_message, data.get("error"), data.get("message"))
                if isinstance(candidate, str) and candidate.strip()
            ),
            "CF Browser reported an unsuccessful response",
        )
        raise CFBrowserError(message[:_WORKER_ERROR_MESSAGE_MAX], status_code=502)
    return data


def _require_json_object(value: Any, operation: str) -> dict[str, Any]:
    """Require an object response for endpoints with an object contract."""
    if not isinstance(value, dict):
        raise CFBrowserError(
            f"CF Browser returned malformed {operation}",
            status_code=502,
        )
    return value


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
        Default request timeout in seconds (default 320). This includes the
        Worker proxy and Cloudflare's longest supported synchronous action.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = DEFAULT_WORKER_TIMEOUT,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("api_key must be a non-empty string")
        normalized_base_url = base_url.strip().rstrip("/")
        parsed_base_url = urlsplit(normalized_base_url)
        if (
            parsed_base_url.scheme not in {"http", "https"}
            or not parsed_base_url.netloc
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ValueError(
                "base_url must be an absolute HTTP(S) URL without credentials or query"
            )
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be greater than zero")
        self._base_url = normalized_base_url
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, f"{self._base_url}{path}", **kwargs)
        except httpx.TimeoutException as exc:
            raise TransportError("CF Browser request timed out") from exc
        except httpx.HTTPError as exc:
            raise TransportError(f"CF Browser request failed: {exc}") from exc
        _raise_for_status(response)
        return response

    async def _post_text(self, path: str, payload: dict[str, Any]) -> str:
        response = await self._request("POST", path, json=payload)
        if "application/json" in response.headers.get("content-type", "").lower():
            _decode_json(response)
        return response.text

    async def _post_bytes(self, path: str, payload: dict[str, Any]) -> bytes:
        response = await self._request("POST", path, json=payload)
        data = response.content
        valid = (
            data.startswith((b"\x89PNG", b"\xff\xd8\xff"))
            or len(data) >= 12
            and data.startswith(b"RIFF")
            and data[8:12] == b"WEBP"
            if path == "/screenshot"
            else data.startswith(b"%PDF-")
        )
        if not valid:
            operation = "screenshot" if path == "/screenshot" else "PDF"
            raise CFBrowserError(
                f"CF Browser returned malformed {operation} bytes",
                status_code=502,
            )
        return data

    async def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        response = await self._request("POST", path, json=payload)
        return _decode_json(response)

    async def _get_json(self, path: str, *, params: dict[str, str | int] | None = None) -> Any:
        response = await self._request("GET", path, params=params)
        return _decode_json(response)

    async def _delete(self, path: str) -> None:
        await self._request("DELETE", path)

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

    async def snapshot(self, url: str, *, no_cache: bool = False, **opts: Any) -> dict[str, Any]:
        """Take a full snapshot (HTML + screenshot) of *url*.

        Returns
        -------
        dict
            JSON snapshot payload from the Worker.
        """
        payload = _build_payload(url, no_cache, opts)
        return _require_json_object(await self._post_json("/snapshot", payload), "snapshot")

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
        prompt: str | None = None,
        *,
        response_format: dict[str, Any] | None = None,
        schema: dict[str, Any] | None = None,
        no_cache: bool = False,
        **opts: Any,
    ) -> Any:
        """Extract JSON using a prompt and/or a JSON response schema.

        Parameters
        ----------
        prompt:
            Natural-language description of what to extract.

        Returns
        -------
        dict
            Extracted data as a JSON object.
        """
        extraction = build_json_extraction_options(prompt, response_format, schema, opts)
        payload = _build_payload(url, no_cache, extraction)
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

    async def a11y(self, url: str, *, no_cache: bool = False, **opts: Any) -> dict[str, Any]:
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
        return _require_json_object(await self._post_json("/a11y", payload), "accessibility tree")

    async def crawl(
        self,
        url: str,
        *,
        no_cache: bool = False,
        cache_ttl: int | None = None,
        **opts: Any,
    ) -> str:
        """Start an asynchronous crawl of *url*.

        Returns
        -------
        str
            The ``job_id`` for the crawl job (pass to :meth:`crawl_status`
            or :meth:`crawl_wait`).
        """
        validate_crawl_cache_controls(no_cache, cache_ttl)
        crawl_options = dict(opts)
        if cache_ttl is not None:
            crawl_options["cache_ttl"] = cache_ttl
        crawl_options.setdefault("render", True)
        crawl_options.setdefault("source", "all")
        options = crawl_options.get("options")
        if options is None and not any(
            name in crawl_options
            for name in (
                "include_external",
                "include_subdomains",
                "include_patterns",
                "exclude_patterns",
            )
        ):
            crawl_options["options"] = {
                "includeExternalLinks": False,
                "includeSubdomains": False,
            }
        payload = _build_payload(url, no_cache, crawl_options)
        data = await self._post_json("/crawl", payload)
        job_id = data.get("job_id") if isinstance(data, dict) else None
        if not isinstance(job_id, str) or not job_id:
            raise CFBrowserError(
                "Crawl response missing job_id",
                status_code=None,
            )
        return job_id

    async def crawl_status(
        self,
        job_id: str,
        *,
        cursor: CrawlCursor | None = None,
        limit: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
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
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id must be a non-empty string")
        params = build_crawl_status_params(cursor, limit, status)
        encoded_job_id = quote(job_id, safe="")
        return normalize_crawl_status_response(
            await self._get_json(f"/crawl/{encoded_job_id}", params=params or None),
            job_id,
            source="CF Browser",
        )

    async def crawl_wait(
        self,
        job_id: str,
        *,
        timeout: float = 300,
        poll_interval: float = 5,
    ) -> dict[str, Any]:
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
            The final status payload (normally ``status == "completed"``).

        Raises
        ------
        TimeoutError
            If the job does not finish within *timeout* seconds.
        CrawlJobError
            If the job reaches a terminal failure or cancellation status.
        """
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
    # Interaction API (requires Worker with BROWSER binding)
    # ------------------------------------------------------------------

    async def click(self, url: str, selector: str, **opts: Any) -> dict[str, Any]:
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
        return _require_json_object(await self._post_json("/click", payload), "click result")

    async def type_text(
        self, url: str, selector: str, text: str, *, clear: bool = False, **opts: Any
    ) -> dict[str, Any]:
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
        return _require_json_object(await self._post_json("/type", payload), "type result")

    async def evaluate(self, url: str, script: str, **opts: Any) -> dict[str, Any]:
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
        return _require_json_object(
            await self._post_json("/evaluate", payload), "evaluation result"
        )

    async def interact(
        self, url: str, actions: list[dict[str, Any]], **opts: Any
    ) -> dict[str, Any]:
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
        return _require_json_object(
            await self._post_json("/interact", payload), "interaction result"
        )

    async def submit_form(
        self,
        url: str,
        fields: dict[str, str],
        *,
        submit_selector: str | None = None,
        **opts: Any,
    ) -> dict[str, Any]:
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
        return _require_json_object(
            await self._post_json("/submit-form", payload), "form submission result"
        )

    async def delete_crawl(self, job_id: str) -> None:
        """Cancel a crawl job and remove its cached Worker state.

        Parameters
        ----------
        job_id:
            The crawl job ID to delete.
        """
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id must be a non-empty string")
        await self._delete(f"/crawl/{quote(job_id, safe='')}")

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
