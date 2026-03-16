"""
Pydantic models for the CF Browser SDK.

These models are provided as convenience types for users who want
structured access to API responses. SDK methods return raw dicts/lists
for flexibility — use these models to parse responses when type safety
is desired::

    from cf_browser.models import CrawlResult
    result = CrawlResult(**await browser.crawl_status("job-id"))
"""
from __future__ import annotations

from pydantic import BaseModel


class ScrapeResult(BaseModel):
    """Result from a scrape operation."""

    elements: list[dict]


class LinkItem(BaseModel):
    """A single link extracted from a page."""

    href: str
    text: str | None = None


class CrawlJob(BaseModel):
    """Represents a crawl job returned from the Worker API."""

    job_id: str
    status: str  # "pending" | "running" | "complete" | "failed"


class CrawlResult(BaseModel):
    """Full result of a completed (or failed) crawl job."""

    job_id: str
    status: str  # "pending" | "running" | "complete" | "failed"
    pages: list[dict] | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Interaction models (require Worker mode with BROWSER binding)
# ---------------------------------------------------------------------------


class ClickResult(BaseModel):
    """Result from a click operation."""

    url: str
    title: str
    content: str


class EvaluateResult(BaseModel):
    """Result from a JavaScript evaluation."""

    result: object | None = None
    type: str


class InteractAction(BaseModel):
    """A single action in an interaction chain."""

    action: str  # navigate | click | type | wait | screenshot | evaluate | select | scroll
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    clear: bool | None = None
    script: str | None = None
    value: str | None = None
    x: int | None = None
    y: int | None = None
    timeout: int | None = None


class InteractResult(BaseModel):
    """Result from a single action in an interaction chain."""

    action: str
    ok: bool
    error: str | None = None
    result: object | None = None
    data: str | None = None  # base64 screenshot data


class FormField(BaseModel):
    """A form field mapping: CSS selector → value."""

    selector: str
    value: str
