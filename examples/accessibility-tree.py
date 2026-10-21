"""
Accessibility tree extraction.

Get a structured representation of a page's accessibility tree —
the same data screen readers and assistive technologies use.
Great for LLM consumption: lower token cost than full HTML.

Prerequisites:
    pip install cf-browser
"""

import asyncio
import json
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
        # Get accessibility tree
        tree = await browser.a11y("https://example.com")
        print(json.dumps(tree, indent=2, ensure_ascii=False)[:2000])

        # Use with wait_for for dynamic pages
        tree = await browser.a11y(
            "https://react.dev",
            wait_for="main",
        )
        print(f"\nReact.dev a11y tree keys: {list(tree.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
