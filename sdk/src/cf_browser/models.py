"""
Pydantic models for the CF Browser SDK.
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
