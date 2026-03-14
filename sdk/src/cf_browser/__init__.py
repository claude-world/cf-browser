"""
CF Browser SDK - Python async client for Cloudflare Browser Rendering.

Two modes of operation:

**Direct mode** (no Worker needed)::

    from cf_browser import CFBrowserDirect

    async with CFBrowserDirect(
        account_id="your-cf-account-id",
        api_token="your-cf-api-token",
    ) as browser:
        md = await browser.markdown("https://example.com")

**Worker mode** (via deployed Cloudflare Worker)::

    from cf_browser import CFBrowser

    async with CFBrowser(
        base_url="https://cf-browser.example.workers.dev",
        api_key="your-secret-key",
    ) as browser:
        md = await browser.markdown("https://example.com")
"""

from .client import CFBrowser
from .direct import CFBrowserDirect
from .exceptions import (
    AuthenticationError,
    CFBrowserError,
    NotFoundError,
    RateLimitError,
)
from .models import (
    CrawlJob,
    CrawlResult,
    LinkItem,
    ScrapeResult,
)

__all__ = [
    # Client
    "CFBrowser",
    "CFBrowserDirect",
    # Exceptions
    "CFBrowserError",
    "AuthenticationError",
    "RateLimitError",
    "NotFoundError",
    # Models
    "ScrapeResult",
    "LinkItem",
    "CrawlJob",
    "CrawlResult",
]
