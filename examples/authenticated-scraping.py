"""
Authenticated scraping with cookies and custom headers.

Use cookies to access logged-in pages, paywalled content,
or any page that requires authentication.

Prerequisites:
    pip install cf-browser
"""

import asyncio
import os

from cf_browser import CFBrowser


async def main():
    url = os.environ.get("CF_BROWSER_URL", "https://cf-browser.example.workers.dev")
    key = os.environ.get("CF_BROWSER_API_KEY", "your-api-key")

    async with CFBrowser(base_url=url, api_key=key) as browser:
        # Example: Scrape a page that requires authentication cookies
        cookies = [
            {
                "name": "session_id",
                "value": "your-session-cookie-value",
                "domain": ".example.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            },
            {
                "name": "auth_token",
                "value": "your-auth-token",
                "domain": ".example.com",
            },
        ]

        # Custom headers (e.g., for API-based auth)
        headers = {
            "X-Custom-Auth": "bearer some-token",
            "Accept-Language": "en-US,en;q=0.9",
        }

        # Fetch authenticated page as markdown
        md = await browser.markdown(
            "https://example.com/dashboard",
            cookies=cookies,
            headers=headers,
        )
        print(md[:1000])

        # Take screenshot of authenticated page
        png = await browser.screenshot(
            "https://example.com/dashboard",
            cookies=cookies,
            width=1440,
            height=900,
        )
        with open("dashboard-screenshot.png", "wb") as f:
            f.write(png)
        print(f"Saved: dashboard-screenshot.png ({len(png)} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
