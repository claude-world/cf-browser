"""
Crawl a website and analyze the results.

Start an async crawl job, wait for completion,
then process the results.

Prerequisites:
    pip install cf-browser
"""

import asyncio
import os

from cf_browser import CFBrowser


async def main():
    try:
        url = os.environ["CF_BROWSER_URL"]
        key = os.environ["CF_BROWSER_API_KEY"]
    except KeyError as exc:
        raise SystemExit(
            f"Set the required environment variable: {exc.args[0]}"
        ) from exc

    async with CFBrowser(base_url=url, api_key=key) as browser:
        # Start a crawl (async — returns immediately)
        print("Starting crawl...")
        job_id = await browser.crawl(
            "https://example.com/docs/",
            limit=10,  # max pages to crawl
            depth=2,
            formats=["markdown"],
            crawl_purposes=["search"],
            include_patterns=["**/docs/**"],
            exclude_patterns=["**/private/**"],
        )
        print(f"Job ID: {job_id}")

        # Wait for completion (polls automatically)
        print("Waiting for crawl to complete...")
        result = await browser.crawl_wait(
            job_id,
            timeout=120,  # max 2 minutes
            poll_interval=3,  # check every 3 seconds
        )

        print(f"Status: {result.get('status')}")
        records = result.get("records", [])
        print(f"Records crawled: {len(records)}")

        for record in records[:5]:
            print(f"  - {record.get('url', 'N/A')}")


if __name__ == "__main__":
    asyncio.run(main())
