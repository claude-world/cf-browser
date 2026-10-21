"""
CF Browser SDK - Python async client for Cloudflare Browser Run.

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

__version__ = "2.1.0"

from .client import CFBrowser
from .direct import CFBrowserDirect
from .exceptions import (
    AuthenticationError,
    BrowserUnavailableError,
    CFBrowserError,
    CrawlJobError,
    NotFoundError,
    RateLimitError,
    TransportError,
)
from .models import (
    ClickResult,
    CrawlJob,
    CrawlResult,
    EvaluateResult,
    FormField,
    InteractAction,
    InteractResult,
    LinkItem,
    ScrapeResult,
)

__all__ = [
    # Metadata
    "__version__",
    # Client
    "CFBrowser",
    "CFBrowserDirect",
    # Exceptions
    "CFBrowserError",
    "AuthenticationError",
    "BrowserUnavailableError",
    "CrawlJobError",
    "TransportError",
    "RateLimitError",
    "NotFoundError",
    # Models
    "ScrapeResult",
    "LinkItem",
    "CrawlJob",
    "CrawlResult",
    "ClickResult",
    "EvaluateResult",
    "InteractAction",
    "InteractResult",
    "FormField",
]
