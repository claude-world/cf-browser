# cf-browser

Typed async Python SDK for [Cloudflare Browser Run](https://developers.cloudflare.com/browser-run/) (formerly Browser Rendering). Use `CFBrowserDirect` against Cloudflare's REST API or `CFBrowser` through the authenticated Worker proxy.

## Install

```bash
python -m pip install cf-browser
```

Python 3.10–3.14 is supported (CI also exercises 3.15). The wheel includes a PEP 561 `py.typed` marker.

## Direct mode

```python
from cf_browser import CFBrowserDirect

async with CFBrowserDirect(account_id="...", api_token="...") as browser:
    markdown = await browser.markdown("https://example.com")
    links = await browser.links(
        "https://example.com",
        include_external=False,
        visible_only=True,
    )
    tree = await browser.a11y("https://example.com")
```

Direct mode has no local cache or proxy rate limit. Browser interaction methods raise `NotImplementedError`.

## Worker mode

```python
from cf_browser import CFBrowser

async with CFBrowser(base_url="https://...workers.dev", api_key="...") as browser:
    png = await browser.screenshot(
        "https://example.com",
        width=1280,
        height=720,
        no_cache=True,
    )
    data = await browser.json_extract(
        "https://example.com/products",
        response_format={
            "type": "json_schema",
            "json_schema": {
                "type": "object",
                "properties": {"products": {"type": "array"}},
            },
        },
    )
    job_id = await browser.crawl("https://example.com", limit=20)
    result = await browser.crawl_wait(job_id, timeout=300, poll_interval=2)
    await browser.delete_crawl(job_id)
```

`schema=` remains a compatibility alias for structured extraction and is translated to Cloudflare's current `response_format` shape.

## API

| Method | Returns | Notes |
|---|---|---|
| `content(url)` | `str` | Rendered HTML |
| `markdown(url)` | `str` | Markdown |
| `screenshot(url)` | `bytes` | PNG; validates viewport bounds |
| `pdf(url)` | `bytes` | Supported paper format and landscape options |
| `snapshot(url)` | `dict` | Content, Markdown, screenshot, and optional accessibility tree |
| `scrape(url, selectors)` | `dict` | `{"elements": [...]}` |
| `json_extract(url, prompt?, response_format?)` | `Any` | Prompt and/or JSON schema |
| `links(url)` | `list[dict]` | Normalized `{href, text}` items |
| `a11y(url)` | `dict` | Native accessibility tree |
| `crawl(url)` | `str` | Job ID |
| `crawl_status(job_id, cursor?, limit?, status?)` | `dict` | String or integer opaque cursor pagination |
| `crawl_wait(job_id)` | `dict` | Lightweight polling, then complete records |
| `delete_crawl(job_id)` | `None` | Cancels the Cloudflare crawl |
| `click`, `type_text`, `evaluate`, `interact`, `submit_form` | `dict` | Worker mode and `BROWSER` binding only |

Common page options include `cookies`, `headers`, `authenticate`, `wait_for`, `wait_until`, `timeout`, `user_agent`, injected tags, and rejected resource types. `no_cache` controls local Worker caching; for crawls in either mode it maps to upstream `cacheTTL=0`. Crawls default to `render=True` and support `cache_ttl` (0-86400), `depth`, `formats`, `crawl_purposes`, `max_age`, `modified_since`, include/exclude patterns, `json_options`, and rendered request/JavaScript/viewport controls. Static crawls (`render=False`) reject browser-only options. Cloudflare does not support `user_agent` for crawl requests.

Typed exceptions include `AuthenticationError`, `RateLimitError`, `NotFoundError`, `BrowserUnavailableError`, `TransportError`, and `CrawlJobError`, all deriving from `CFBrowserError`. `crawl_wait()` raises the built-in `TimeoutError` while a job is still running at the deadline, and its subclass `CrawlResultsTimeoutError` when the job completed but its result pages could not be fetched in time; malformed upstream pagination raises `CFBrowserError` with status 502.

API keys and tokens must be visible ASCII (no whitespace or line breaks) and are never included in error messages. The default `timeout` (320 s Worker, 310 s Direct) covers Cloudflare's longest synchronous action, while connecting is capped at 10 s so unreachable hosts fail fast.

See the [project README](https://github.com/claude-world/cf-browser#readme) for deployment and security details.

## License

[MIT](https://github.com/claude-world/cf-browser/blob/main/LICENSE)
