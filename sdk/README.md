# cf-browser

Python SDK for [CF Browser](https://github.com/claude-world/cf-browser) — read any JavaScript-rendered web page from Python, either through a deployed Worker or by calling Cloudflare Browser Rendering directly.

## Installation

```bash
pip install cf-browser
```

## Usage

### Worker Mode

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

    # Accessibility snapshot (screenshot stripped, low token cost)
    tree = await browser.a11y("https://example.com")

    # Authenticated scraping
    md = await browser.markdown(
        "https://app.example.com/dashboard",
        cookies=[{"name": "session", "value": "abc", "domain": ".example.com"}],
    )
```

### Direct Mode

```python
from cf_browser import CFBrowserDirect

async with CFBrowserDirect(
    account_id="your-cloudflare-account-id",
    api_token="your-cloudflare-api-token",
) as browser:
    html = await browser.content("https://example.com")
    links = await browser.links("https://example.com")
```

## Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `content(url)` | `str` | Rendered HTML |
| `markdown(url)` | `str` | Clean Markdown |
| `screenshot(url)` | `bytes` | PNG image |
| `pdf(url)` | `bytes` | PDF document |
| `snapshot(url)` | `dict` | HTML + metadata |
| `scrape(url, selectors)` | `dict` | Normalized as `{"elements": [...]}` |
| `json_extract(url, prompt)` | `dict` | AI-extracted data |
| `links(url)` | `list[dict]` | Normalized list of `{href, text}` objects |
| `a11y(url)` | `dict` | Accessibility-oriented snapshot with screenshot stripped |
| `crawl(url)` | `str` | Async crawl job ID |
| `crawl_status(job_id)` | `dict` | Job status |
| `crawl_wait(job_id)` | `dict` | Wait for completion |

All methods accept `no_cache=True`, `cookies`, and `headers` kwargs. Read-only methods also support `wait_for`, `wait_until`, and `user_agent`.

Interaction methods (`click`, `type_text`, `evaluate`, `interact`, `submit_form`) are available on `CFBrowser` only. `CFBrowserDirect` raises `NotImplementedError` for them. If `CFBrowser` raises `NotFoundError` for an interaction route, your Worker deployment is stale and should be redeployed.

## Requirements

- Python 3.10+
- Either:
  - A deployed [CF Browser Worker](https://github.com/claude-world/cf-browser), or
  - Cloudflare Account ID + API Token for Direct Mode

## License

[MIT](https://github.com/claude-world/cf-browser/blob/main/LICENSE)
