"""
Crawl a website and analyze the results.

Start an async crawl job, wait for completion,
then process the results.

Prerequisites:
    pip install cf-browser
"""

import asyncio
import json
import os

from cf_browser import CFBrowser


async def main():
    url = os.environ.get("CF_BROWSER_URL", "https://cf-browser.example.workers.dev")
    key = os.environ.get("CF_BROWSER_API_KEY", "your-api-key")

    async with CFBrowser(base_url=url, api_key=key) as browser:
        # Start a crawl (async — returns immediately)
        print("Starting crawl...")
        job_id = await browser.crawl(
            "https://example.com",
            limit=10,  # max pages to crawl
        )
        print(f"Job ID: {job_id}")

        # Wait for completion (polls automatically)
        print("Waiting for crawl to complete...")
        result = await browser.crawl_wait(
            job_id,
            timeout=120,       # max 2 minutes
            poll_interval=3,   # check every 3 seconds
        )

        print(f"Status: {result.get('status')}")
        pages = result.get("pages", [])
        print(f"Pages crawled: {len(pages)}")

        for page in pages[:5]:
            print(f"  - {page.get('url', 'N/A')}")


if __name__ == "__main__":
    asyncio.run(main())
