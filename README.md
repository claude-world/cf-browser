# CF Browser

[![GitHub Stars](https://img.shields.io/github/stars/claude-world/cf-browser)](https://github.com/claude-world/cf-browser/stargazers)
[![License](https://img.shields.io/github/license/claude-world/cf-browser)](https://github.com/claude-world/cf-browser/blob/main/LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](sdk/pyproject.toml)

> Open-source proxy service that gives [Claude Code](https://docs.anthropic.com/en/docs/claude-code) **9 MCP tools + 6 ready-made Skills** for JavaScript-rendered web pages.

**[繁體中文版 README](README.zh-TW.md)**

Claude Code's built-in `WebFetch` only returns raw HTML — single-page apps, dynamic content, and JS-rendered pages come back empty. CF Browser wraps [Cloudflare Browser Rendering](https://developers.cloudflare.com/browser-rendering/) behind a Worker proxy with auth, caching, and rate limiting, then exposes everything as MCP tools.

## Why cf-browser?

| Feature | WebFetch | cf-browser |
|---------|----------|------------|
| JS rendering | ❌ | ✅ |
| Screenshots | ❌ | ✅ |
| PDF generation | ❌ | ✅ |
| Multi-page crawl | ❌ | ✅ |
| Cookie/auth support | ❌ | ✅ |
| JSON extraction | ❌ | ✅ |

## Architecture

```
Claude Code
  └── MCP Server (9 tools)
         │ HTTP + Bearer token
         ▼
  Cloudflare Worker (Edge)
  ├── Auth middleware (API key, timing-safe)
  ├── Rate limiting (KV, 60 req/min)
  └── Cache (KV for text, R2 for binary)
         │
         ▼
  CF Browser Rendering API (headless Chrome)
```

| Package | Language | Purpose |
|---------|----------|---------|
| `worker/` | TypeScript (Hono) | Edge proxy with auth, cache, rate limiting |
| `sdk/` | Python (httpx) | Async client library |
| `mcp-server/` | Python (FastMCP) | 9 MCP tools for Claude Code |

## MCP Tools

| Tool | Input | Output | Use case |
|------|-------|--------|----------|
| `browser_markdown` | url | Markdown | Read any web page as clean text |
| `browser_content` | url | HTML | Get fully rendered HTML (JS executed) |
| `browser_screenshot` | url, width, height | PNG file | Visual verification, multi-device testing |
| `browser_pdf` | url, format | PDF file | Generate reports, archive pages |
| `browser_scrape` | url, selectors[] | JSON | Extract specific elements by CSS selector |
| `browser_json` | url, prompt | JSON | AI-powered structured data extraction |
| `browser_links` | url | JSON array | Discover all hyperlinks on a page |
| `browser_crawl` | url, limit | Job ID | Start async multi-page crawl |
| `browser_crawl_status` | job_id, wait | JSON | Poll or wait for crawl results |

### What you can ask Claude Code

```
"Read the React 19 migration guide"
→ browser_markdown("https://react.dev/blog/2024/12/05/react-19")

"Show me what our homepage looks like on mobile"
→ browser_screenshot("https://example.com", width=375, height=667)

"Extract the top 5 products with name, price, and rating"
→ browser_json("https://example.com/products", prompt="Extract top 5 products...")

"Find all broken links on our site"
→ browser_crawl("https://example.com", limit=50) + browser_crawl_status(job_id, wait=True)
```

## Setup

### Option A: Connect to an existing Worker (2 minutes)

If someone has already deployed the Worker (e.g. a teammate), you only need the URL and API key:

```bash
# Install into a dedicated venv
python3 -m venv ~/.cf-browser-venv
~/.cf-browser-venv/bin/pip install \
  "cf-browser @ git+https://github.com/claude-world/cf-browser.git#subdirectory=sdk" \
  "cf-browser-mcp @ git+https://github.com/claude-world/cf-browser.git#subdirectory=mcp-server"
```

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "~/.cf-browser-venv/bin/python",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_BROWSER_URL": "https://cf-browser.<subdomain>.workers.dev",
        "CF_BROWSER_API_KEY": "<your-api-key>"
      }
    }
  }
}
```

Restart Claude Code — 9 `browser_*` tools ready.

### Option B: Deploy your own Worker (5 minutes)

#### Prerequisites

- Node.js 18+, Python 3.10+
- Cloudflare account with [Browser Rendering](https://developers.cloudflare.com/browser-rendering/) enabled
- `wrangler` CLI (`npm i -g wrangler && wrangler login`)

#### Step 1: Deploy the Worker

```bash
git clone https://github.com/claude-world/cf-browser.git
cd cf-browser/worker
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
# Account ID (shown by: wrangler whoami)
wrangler secret put CF_ACCOUNT_ID

# API token — create at https://dash.cloudflare.com/profile/api-tokens
# Required permission: Account → Workers Browser Rendering → Edit
wrangler secret put CF_API_TOKEN

# Generate a client API key (save this — you'll need it for .mcp.json)
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

#### Step 2: Install SDK + MCP Server

```bash
cd ../sdk && pip install -e .
cd ../mcp-server && pip install -e .
```

#### Step 3: Register MCP

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

Restart Claude Code — 9 `browser_*` tools available.

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

# Screenshot with custom viewport
curl -X POST https://cf-browser.example.workers.dev/screenshot \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "width": 1280, "height": 720}' \
  -o screenshot.png

# AI-powered structured extraction
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
- Text content (HTML, Markdown, JSON) → KV storage
- Binary content (PNG, PDF) → R2 storage
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

## Skills (Bonus)

CF Browser ships with 6 ready-made [Claude Code Skills](https://docs.anthropic.com/en/docs/claude-code/skills) in `skills/`. Copy any skill folder into your project's `.claude/skills/` to enable it.

| Skill | Command | What it does |
|-------|---------|--------------|
| **content-extractor** | `/content-extractor` | Read pages, extract structured data, scrape elements, discover links |
| **site-auditor** | `/site-auditor` | Crawl a site and generate SEO/links/accessibility audit report |
| **doc-fetcher** | `/doc-fetcher` | Fetch an entire documentation site as local markdown for RAG |
| **visual-qa** | `/visual-qa` | Multi-viewport screenshots (mobile/tablet/laptop/desktop) with visual review |
| **changelog-monitor** | `/changelog-monitor` | Track releases and breaking changes from any project's web page |
| **competitor-watch** | `/competitor-watch` | Extract and compare pricing/features across competitor websites |

### Install a skill

```bash
# Copy one skill
cp -r skills/content-extractor .claude/skills/

# Or copy all
cp -r skills/* .claude/skills/
```

Restart Claude Code — skills available as slash commands.

### Example workflows

```
"Read the Hono docs and summarize the routing section"
→ /content-extractor → browser_markdown → clean summary

"Audit claude-world.com for SEO issues"
→ /site-auditor → crawl 50 pages → scrape meta tags → markdown report

"Download the Astro docs for offline reference"
→ /doc-fetcher → discover 20 pages → browser_markdown each → save as docs/

"QA check our site on mobile, tablet, and desktop"
→ /visual-qa → 4 viewport screenshots per page → visual review report

"What's new in Claude Code?"
→ /changelog-monitor → browser_json on GitHub releases → structured summary

"Compare Vercel vs Netlify vs Cloudflare Pages pricing"
→ /competitor-watch → extract each pricing page → normalized comparison table
```

## Security

- **Auth**: Timing-safe Bearer token comparison using SHA-256
- **Rate limiting**: Per-key tracking with hashed key material in KV
- **SSRF prevention**: Only `http://` and `https://` URLs allowed
- **Secrets**: All credentials stored via `wrangler secret put`, never in code

## Cost

| Component | Free Tier | Paid ($5/mo Workers) |
|-----------|-----------|---------------------|
| Browser Rendering | 10 min/day, 5 crawl jobs | Higher limits |
| KV | 100K reads/day | 10M reads/mo |
| R2 | 10GB storage | 10GB included |
| Workers | 100K requests/day | 10M requests/mo |

## Development

```bash
# Worker
cd worker && npm install && npm test

# SDK (28 tests)
cd sdk && pip install -e ".[dev]" && pytest tests/ -v

# MCP Server
cd mcp-server && pip install -e ../sdk && pip install -e ".[dev]"
```

## Project Structure

```
cf-browser/
├── worker/                  Cloudflare Worker (TypeScript/Hono)
│   ├── src/
│   │   ├── index.ts         App entry point
│   │   ├── types.ts         Env bindings & request types
│   │   ├── middleware/      auth, cache, rate-limit
│   │   ├── routes/          9 endpoint handlers
│   │   └── lib/             CF API client, cache keys, URL validation
│   ├── tests/
│   └── wrangler.toml.example
├── sdk/                     Python SDK (httpx + Pydantic)
│   ├── src/cf_browser/      client, models, exceptions
│   └── tests/test_client.py
├── mcp-server/              MCP Server (FastMCP)
│   └── src/cf_browser_mcp/server.py
├── skills/                  Claude Code Skills (copy to .claude/skills/)
│   ├── content-extractor/   Read & extract web content
│   ├── site-auditor/        SEO & link health audit
│   ├── doc-fetcher/         Fetch docs for RAG
│   ├── visual-qa/           Multi-viewport screenshot QA
│   ├── changelog-monitor/   Track releases & breaking changes
│   └── competitor-watch/    Compare pricing & features
├── LICENSE                  MIT
├── README.md
└── README.zh-TW.md
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run `npm test` (worker) and `pytest` (SDK)
5. Submit a pull request

## License

[MIT](LICENSE)
