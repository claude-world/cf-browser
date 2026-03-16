"""Shared helpers used by both CFBrowser (Worker mode) and CFBrowserDirect."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from .exceptions import CFBrowserError


async def crawl_wait_poll(
    job_id: str,
    fetch_status: Callable[[str], Awaitable[dict[str, Any]]],
    *,
    timeout: float = 300,
    poll_interval: float = 5,
) -> dict:
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
    deadline = time.monotonic() + timeout

    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Crawl job {job_id!r} did not complete within {timeout}s"
            )

        status_data = await fetch_status(job_id)
        status = status_data.get("status", "")

        if status in ("complete", "completed"):
            return status_data
        if status in ("failed", "error"):
            error_msg = status_data.get("error", "unknown error")
            raise CFBrowserError(
                f"Crawl job failed: {error_msg}",
                status_code=None,
            )

        await asyncio.sleep(max(0, min(poll_interval, deadline - time.monotonic())))
