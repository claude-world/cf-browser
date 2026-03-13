# CF Browser

Open-source proxy service that gives [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 9 MCP tools for JavaScript-rendered web pages.

Claude Code's built-in `WebFetch` only returns raw HTML. Single-page apps, dynamic content, and JS-rendered pages come back empty. CF Browser solves this by wrapping [Cloudflare Browser Rendering](https://developers.cloudflare.com/browser-rendering/) behind a Worker proxy with auth, caching, and rate limiting, then exposing everything as MCP tools.

## Architecture

```
Claude Code
  └── MCP Server (9 tools)
         │ HTTP + Bearer token
         ▼
  Cloudflare Worker
  ├── Auth middleware (API key, timing-safe)
  ├── Rate limiting (KV, 60 req/min)
  └── Cache (KV for text, R2 for binary)
         │
         ▼
  CF Browser Rendering API (headless Chrome)
```

Three independent packages:

| Package | Language | Purpose |
|---------|----------|---------|
| `worker/` | TypeScript (Hono) | Edge proxy with auth, cache, rate limiting |
| `sdk/` | Python (httpx) | Async client library |
| `mcp-server/` | Python (FastMCP) | 9 MCP tools for Claude Code |

## Quick Start

### Prerequisites

- Node.js 18+, Python 3.10+
- Cloudflare account with [Browser Rendering](https://developers.cloudflare.com/browser-rendering/) enabled
- `wrangler` CLI authenticated (`npm i -g wrangler && wrangler login`)

### Step 1: Deploy the Worker

```bash
cd worker
cp wrangler.toml.example wrangler.toml
npm install
```

Create resources and paste the namespace IDs into `wrangler.toml`:

```bash
wrangler kv namespace create CACHE
wrangler kv namespace create RATE_LIMIT
wrangler r2 bucket create cf-browser-storage
```

Set secrets:

```bash
# Your Cloudflare account ID (shown by: wrangler whoami)
wrangler secret put CF_ACCOUNT_ID

# API token — create at https://dash.cloudflare.com/profile/api-tokens
# Required permission: "Workers Browser Rendering Edit" (瀏覽器轉譯)
wrangler secret put CF_API_TOKEN

# Client API key for authenticating requests to your Worker
echo "$(openssl rand -hex 32)" | wrangler secret put API_KEYS
```

Deploy:

```bash
wrangler deploy
# → https://cf-browser.<your-subdomain>.workers.dev
```

Verify:

```bash
curl https://cf-browser.<your-subdomain>.workers.dev/health
# {"status":"ok","version":"1.0.0"}
```

### Step 2: Install the SDK and MCP Server

```bash
cd ../sdk && pip install -e .
cd ../mcp-server && pip install -e .
```

### Step 3: Register MCP in Claude Code

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_BROWSER_URL": "https://cf-browser.<your-subdomain>.workers.dev",
        "CF_BROWSER_API_KEY": "<the-api-key-you-generated>"
      }
    }
  }
}
```

Restart Claude Code. You'll see 9 `browser_*` tools available.

## MCP Tools

| Tool | Input | Output | Use case |
|------|-------|--------|----------|
| `browser_markdown` | url | Markdown string | Read any web page as clean text |
| `browser_content` | url | HTML string | Get fully rendered HTML (JS executed) |
| `browser_screenshot` | url, width, height | PNG file path | Visual verification, multi-device testing |
| `browser_pdf` | url, format | PDF file path | Generate reports, archive pages |
| `browser_scrape` | url, selectors[] | JSON | Extract specific elements by CSS selector |
| `browser_json` | url, prompt | JSON | AI-powered structured data extraction |
| `browser_links` | url | JSON array | Discover all hyperlinks on a page |
| `browser_crawl` | url, limit | Job ID | Start async multi-page crawl |
| `browser_crawl_status` | job_id, wait | JSON | Poll or wait for crawl results |

### Examples in Claude Code

```
"Read the React 19 migration guide"
→ browser_markdown("https://react.dev/blog/2024/12/05/react-19")

"Show me what our homepage looks like on mobile"
→ browser_screenshot("https://example.com", width=375, height=667)

"Extract the top 5 products with name, price, and rating"
→ browser_json("https://example.com/products", prompt="Extract top 5 products...")

"Find all broken links on our site"
→ browser_crawl("https://example.com", limit=50) → browser_crawl_status(job_id, wait=True)
```

## Worker API Reference

All routes (except `/health`) require `Authorization: Bearer <api-key>` header.

### Endpoints

| Route | Method | Body | Cache | Response |
|-------|--------|------|-------|----------|
| `/health` | GET | — | — | `{"status":"ok"}` |
| `/content` | POST | `{url, wait_for?, no_cache?}` | KV 1hr | HTML |
| `/markdown` | POST | `{url, wait_for?, no_cache?}` | KV 1hr | Markdown |
| `/screenshot` | POST | `{url, width?, height?, full_page?, no_cache?}` | R2 24hr | PNG |
| `/pdf` | POST | `{url, format?, landscape?, no_cache?}` | R2 24hr | PDF |
| `/snapshot` | POST | `{url, wait_for?, no_cache?}` | KV 30min | JSON |
| `/scrape` | POST | `{url, elements[], wait_for?, no_cache?}` | KV 30min | JSON |
| `/json` | POST | `{url, prompt, schema?, no_cache?}` | None | JSON |
| `/links` | POST | `{url, wait_for?, no_cache?}` | KV 1hr | JSON |
| `/crawl` | POST | `{url, limit?, no_cache?}` | — | `{"job_id":"..."}` |
| `/crawl/:id` | GET | — | R2 | JSON |

### Request examples

```bash
# Get markdown
curl -X POST https://cf-browser.example.workers.dev/markdown \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://react.dev"}'

# Screenshot with viewport
curl -X POST https://cf-browser.example.workers.dev/screenshot \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "width": 1280, "height": 720}' \
  -o screenshot.png

# AI extraction
curl -X POST https://cf-browser.example.workers.dev/json \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://news.ycombinator.com", "prompt": "Extract top 5 stories with title and score"}'

# Scrape specific elements
curl -X POST https://cf-browser.example.workers.dev/scrape \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "elements": ["h1", ".price", "#main"]}'

# Start async crawl
curl -X POST https://cf-browser.example.workers.dev/crawl \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "limit": 10}'

# Poll crawl status
curl https://cf-browser.example.workers.dev/crawl/JOB_ID \
  -H "Authorization: Bearer YOUR_KEY"
```

### Cache behavior

- Set `"no_cache": true` in the request body to bypass cache
- Cached responses include `X-Cache: HIT` header
- Text content (HTML, Markdown, JSON) is stored in KV
- Binary content (PNG, PDF) is stored in R2
- Completed crawl results are persisted to R2

### Rate limiting

- Default: 60 requests per minute per API key
- Response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`
- Exceeded: HTTP 429 with `Retry-After` header

## Python SDK

```python
from cf_browser import CFBrowser

async with CFBrowser(
    base_url="https://cf-browser.example.workers.dev",
    api_key="your-key",
) as browser:
    # Read a page
    markdown = await browser.markdown("https://react.dev")

    # Take a screenshot
    png_bytes = await browser.screenshot("https://example.com", width=1280, height=720)

    # AI-powered extraction
    data = await browser.json_extract(
        "https://news.ycombinator.com",
        prompt="Extract the top 5 stories with title and score",
    )

    # Scrape by CSS selectors
    elements = await browser.scrape("https://example.com", selectors=["h1", ".price"])

    # Async crawl
    job_id = await browser.crawl("https://example.com", limit=10)
    result = await browser.crawl_wait(job_id, timeout=120)
```

### SDK methods

| Method | Returns | Description |
|--------|---------|-------------|
| `content(url, **opts)` | `str` | Rendered HTML |
| `markdown(url, **opts)` | `str` | Clean Markdown |
| `screenshot(url, **opts)` | `bytes` | PNG image |
| `pdf(url, **opts)` | `bytes` | PDF document |
| `snapshot(url, **opts)` | `dict` | HTML + metadata |
| `scrape(url, selectors, **opts)` | `dict` | Elements by selector |
| `json_extract(url, prompt, **opts)` | `dict` | AI-extracted data |
| `links(url, **opts)` | `list[dict]` | All hyperlinks |
| `crawl(url, **opts)` | `str` | Job ID |
| `crawl_status(job_id)` | `dict` | Job status |
| `crawl_wait(job_id, timeout, poll_interval)` | `dict` | Wait for completion |

All methods accept `no_cache=True` to bypass caching.

## Security

- **Auth**: Timing-safe Bearer token comparison using SHA-256 (prevents timing attacks)
- **Rate limiting**: Per-key tracking with hashed key material in KV (no raw keys stored)
- **SSRF prevention**: Only `http://` and `https://` URLs allowed
- **Secrets**: All credentials stored via `wrangler secret put`, never in code

## Cost

| Component | Free Tier | Paid ($5/mo Workers) |
|-----------|-----------|---------------------|
| Browser Rendering | 10 min/day, 5 crawl jobs | Higher limits |
| KV | 100K reads/day | 10M reads/mo |
| R2 | 10GB storage | 10GB included |
| Workers | 100K requests/day | 10M requests/mo |

For most Claude Code usage, the free tier is sufficient.

## Development

### Worker

```bash
cd worker
npm install
npm run dev          # Local dev server at :8787
npm run type-check   # TypeScript checks
npm test             # Run tests
```

### SDK

```bash
cd sdk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

### MCP Server

```bash
cd mcp-server
python -m venv .venv && source .venv/bin/activate
pip install -e ../sdk     # Install SDK first
pip install -e ".[dev]"
```

## Project Structure

```
cf-browser/
├── worker/                  Cloudflare Worker (TypeScript)
│   ├── src/
│   │   ├── index.ts         Hono app entry point
│   │   ├── types.ts         Env bindings & request types
│   │   ├── middleware/
│   │   │   ├── auth.ts      Bearer token validation
│   │   │   ├── cache.ts     KV/R2 cache layer
│   │   │   └── rate-limit.ts  Per-key rate limiting
│   │   ├── routes/
│   │   │   ├── content.ts   POST /content → HTML
│   │   │   ├── markdown.ts  POST /markdown → Markdown
│   │   │   ├── screenshot.ts POST /screenshot → PNG
│   │   │   ├── pdf.ts       POST /pdf → PDF
│   │   │   ├── snapshot.ts  POST /snapshot → JSON
│   │   │   ├── scrape.ts    POST /scrape → JSON
│   │   │   ├── json.ts      POST /json → JSON (AI)
│   │   │   ├── links.ts     POST /links → JSON
│   │   │   └── crawl.ts     POST/GET /crawl
│   │   └── lib/
│   │       ├── cf-api.ts    CF Browser Rendering client
│   │       ├── cache-key.ts SHA-256 cache keys
│   │       └── validate-url.ts  SSRF prevention
│   ├── tests/
│   ├── wrangler.toml.example
│   └── package.json
├── sdk/                     Python SDK
│   ├── src/cf_browser/
│   │   ├── client.py        Async CFBrowser client
│   │   ├── models.py        Pydantic response models
│   │   └── exceptions.py    Typed error hierarchy
│   ├── tests/
│   └── pyproject.toml
├── mcp-server/              MCP Server
│   ├── src/cf_browser_mcp/
│   │   └── server.py        9 MCP tool definitions
│   └── pyproject.toml
├── LICENSE
└── README.md
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run `npm test` (worker) and `pytest` (SDK) to verify
5. Submit a pull request

## License

[MIT](LICENSE)
