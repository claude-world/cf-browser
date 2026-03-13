"""
CF Browser SDK - Python async client for the CF Browser Worker API.

Example
-------

    import asyncio
    from cf_browser import CFBrowser

    async def main():
        async with CFBrowser(
            base_url="https://cf-browser.example.workers.dev",
            api_key="your-secret-key",
        ) as browser:
            md = await browser.markdown("https://example.com")
            print(md)

    asyncio.run(main())
"""

from .client import CFBrowser
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
