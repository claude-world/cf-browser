"""
Basic CF Browser SDK usage examples.

Prerequisites:
    pip install cf-browser

Usage:
    export CF_BROWSER_URL="https://cf-browser.YOUR-SUBDOMAIN.workers.dev"
    export CF_BROWSER_API_KEY="your-api-key"
    python examples/basic-usage.py
"""

import asyncio
import os

from cf_browser import CFBrowser


async def main():
    url = os.environ.get("CF_BROWSER_URL", "https://cf-browser.example.workers.dev")
    key = os.environ.get("CF_BROWSER_API_KEY", "your-api-key")

    async with CFBrowser(base_url=url, api_key=key) as browser:
        # 1. Read a page as Markdown (best for LLM consumption)
        print("--- Markdown ---")
        md = await browser.markdown("https://example.com")
        print(md[:500])
        print()

        # 2. Get rendered HTML (JavaScript executed)
        print("--- HTML ---")
        html = await browser.content("https://example.com")
        print(f"HTML length: {len(html)} chars")
        print()

        # 3. Take a screenshot
        print("--- Screenshot ---")
        png = await browser.screenshot("https://example.com", width=1280, height=720)
        with open("example-screenshot.png", "wb") as f:
            f.write(png)
        print(f"Saved screenshot: {len(png)} bytes → example-screenshot.png")
        print()

        # 4. Extract all links
        print("--- Links ---")
        links = await browser.links("https://example.com")
        for link in links[:5]:
            print(f"  {link.get('text', 'N/A')} → {link['href']}")
        print()

        # 5. AI-powered data extraction
        print("--- AI Extraction ---")
        data = await browser.json_extract(
            "https://news.ycombinator.com",
            prompt="Extract the top 3 stories with title, score, and comment count",
        )
        print(data)


if __name__ == "__main__":
    asyncio.run(main())
