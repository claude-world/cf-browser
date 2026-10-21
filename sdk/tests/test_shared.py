"""Tests for helpers shared by Worker mode and Direct mode."""

import asyncio

import pytest

from cf_browser._shared import collect_crawl_pages, crawl_job_path, crawl_wait_poll
from cf_browser.exceptions import CFBrowserError, CrawlJobError


@pytest.mark.parametrize("job_id", [".", ".."])
def test_crawl_job_path_rejects_relative_segments(job_id):
    with pytest.raises(ValueError, match="relative path segment"):
        crawl_job_path(job_id)


def test_crawl_job_path_encodes_one_segment():
    assert crawl_job_path("a/b?c") == "/crawl/a%2Fb%3Fc"


@pytest.mark.asyncio
async def test_repeated_cursor_is_an_upstream_error_not_a_failed_job():
    async def fetch_page(_job_id, _cursor):
        return {"job_id": "abc", "status": "completed", "records": [], "cursor": "same"}

    with pytest.raises(CFBrowserError, match="invalid cursor") as exc_info:
        await collect_crawl_pages("abc", fetch_page)
    assert exc_info.value.status_code == 502
    assert not isinstance(exc_info.value, CrawlJobError)


@pytest.mark.asyncio
async def test_completed_job_gets_a_fresh_window_to_fetch_results():
    async def fetch_status(_job_id):
        await asyncio.sleep(0.3)
        return {"job_id": "abc", "status": "completed"}

    async def fetch_final(_job_id):
        # Longer than what remains of the polling deadline, shorter than a fresh window.
        await asyncio.sleep(0.35)
        return {"job_id": "abc", "status": "completed", "records": []}

    result = await crawl_wait_poll(
        "abc", fetch_status, fetch_final=fetch_final, timeout=0.5, poll_interval=0.01
    )
    assert result["records"] == []


@pytest.mark.asyncio
async def test_result_fetch_timeout_reports_the_completed_job():
    async def fetch_status(_job_id):
        return {"job_id": "abc", "status": "completed"}

    async def fetch_final(_job_id):
        await asyncio.sleep(1)
        return {}

    with pytest.raises(TimeoutError, match="completed, but its results could not be fetched"):
        await crawl_wait_poll(
            "abc", fetch_status, fetch_final=fetch_final, timeout=0.05, poll_interval=0.01
        )
