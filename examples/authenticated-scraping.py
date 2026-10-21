"""
Authenticated scraping with cookies and custom headers.

Use cookies to access logged-in pages, paywalled content,
or any page that requires authentication.

Prerequisites:
    pip install cf-browser
"""

import asyncio
import os
from urllib.parse import urlsplit

from cf_browser import CFBrowser


async def main():
    required = [
        "CF_BROWSER_URL",
        "CF_BROWSER_API_KEY",
        "CF_BROWSER_AUTH_URL",
        "CF_BROWSER_SESSION_COOKIE",
    ]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(
            f"Set the required environment variables: {', '.join(missing)}"
        )
    url = os.environ["CF_BROWSER_URL"]
    key = os.environ["CF_BROWSER_API_KEY"]
    target_url = os.environ["CF_BROWSER_AUTH_URL"]
    parsed_target = urlsplit(target_url)
    if parsed_target.scheme not in {"http", "https"} or not parsed_target.hostname:
        raise SystemExit("CF_BROWSER_AUTH_URL must be an absolute HTTP(S) URL")
    target_host = parsed_target.hostname

    async with CFBrowser(base_url=url, api_key=key) as browser:
        # Example: Scrape a page that requires authentication cookies
        cookies = [
            {
                "name": "session_id",
                "value": os.environ["CF_BROWSER_SESSION_COOKIE"],
                "domain": target_host,
                "path": "/",
                "secure": True,
                "httpOnly": True,
            },
        ]

        # Custom headers (e.g., for API-based auth)
        headers = {"Accept-Language": "en-US,en;q=0.9"}

        # Fetch authenticated page as markdown
        md = await browser.markdown(
            target_url,
            cookies=cookies,
            headers=headers,
        )
        print(md[:1000])

        # Take screenshot of authenticated page
        png = await browser.screenshot(
            target_url,
            cookies=cookies,
            width=1440,
            height=900,
        )
        with open("dashboard-screenshot.png", "wb") as f:
            f.write(png)
        print(f"Saved: dashboard-screenshot.png ({len(png)} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
