# cf-browser

Python SDK for [CF Browser](https://github.com/claude-world/cf-browser) — read any JavaScript-rendered web page from Python.

## Installation

```bash
pip install cf-browser
```

## Usage

```python
from cf_browser import CFBrowser

async with CFBrowser(
    base_url="https://cf-browser.YOUR-SUBDOMAIN.workers.dev",
    api_key="your-api-key",
) as browser:
    # Read a page as Markdown
    md = await browser.markdown("https://react.dev")

    # Take a screenshot
    png = await browser.screenshot("https://example.com", width=1280)

    # AI-powered data extraction
    data = await browser.json_extract(
        "https://news.ycombinator.com",
        prompt="Extract top 5 stories with title and score",
    )

    # Accessibility tree (low token cost)
    tree = await browser.a11y("https://example.com")

    # Authenticated scraping
    md = await browser.markdown(
        "https://app.example.com/dashboard",
        cookies=[{"name": "session", "value": "abc", "domain": ".example.com"}],
    )
```

## Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `content(url)` | `str` | Rendered HTML |
| `markdown(url)` | `str` | Clean Markdown |
| `screenshot(url)` | `bytes` | PNG image |
| `pdf(url)` | `bytes` | PDF document |
| `snapshot(url)` | `dict` | HTML + metadata |
| `scrape(url, selectors)` | `dict` | Elements by CSS selector |
| `json_extract(url, prompt)` | `dict` | AI-extracted data |
| `links(url)` | `list[dict]` | All hyperlinks |
| `a11y(url)` | `dict` | Accessibility tree |
| `crawl(url)` | `str` | Async crawl job ID |
| `crawl_status(job_id)` | `dict` | Job status |
| `crawl_wait(job_id)` | `dict` | Wait for completion |

All methods accept `no_cache=True`, `cookies`, and `headers` kwargs.

## Requirements

- Python 3.10+
- A deployed [CF Browser Worker](https://github.com/claude-world/cf-browser)

## License

[MIT](https://github.com/claude-world/cf-browser/blob/main/LICENSE)
