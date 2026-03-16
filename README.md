# CF Browser

The fastest way to read any website from [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Open-source tool that gives Claude Code **15 MCP tools + 6 ready-to-use Skills** for JavaScript-rendered web pages — content extraction, screenshots, PDFs, accessibility trees, AI-powered data extraction, multi-page crawling, and **browser interaction** (click, type, form submit, JS eval, action chains). Powered by [Cloudflare Browser Rendering](https://developers.cloudflare.com/browser-rendering/) with zero-cost free tier. Supports **Direct Mode** (no Worker needed) and **Worker Mode** (with caching, rate limiting, and interaction).

[![PyPI - cf-browser](https://img.shields.io/pypi/v/cf-browser?label=cf-browser)](https://pypi.org/project/cf-browser/)
[![PyPI - cf-browser-mcp](https://img.shields.io/pypi/v/cf-browser-mcp?label=cf-browser-mcp)](https://pypi.org/project/cf-browser-mcp/)
[![Tests](https://github.com/claude-world/cf-browser/actions/workflows/test.yml/badge.svg)](https://github.com/claude-world/cf-browser/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Why CF Browser?

Claude Code's built-in `WebFetch` only returns raw HTML. Single-page apps, dynamic content, and JS-rendered pages come back empty. CF Browser solves this:

- **JS execution** — full headless Chrome renders the page before extraction
- **15 purpose-built tools** — markdown, screenshots, PDFs, a11y trees, AI extraction, crawling, plus click/type/evaluate/interact/form-submit
- **Browser interaction** — click buttons, fill forms, execute JS, chain multi-step actions (Worker mode)
- **Authenticated scraping** — inject cookies and custom headers for logged-in pages
- **Zero cost** — read-only tools run on Cloudflare's free tier; interaction tools require Workers Paid ($5/mo)
- **Edge-based** — global low latency from 300+ Cloudflare locations

## Quick Start

Two ways to use CF Browser — pick the one that fits:

| | Direct Mode | Worker Mode |
|---|---|---|
| **Setup** | `pip install` + 2 env vars | Deploy Worker + `pip install` |
| **Time to start** | 2 minutes | 10 minutes |
| **Requirements** | CF Account ID + API Token | Worker + KV + R2 |
| **Caching** | None | KV + R2 (saves ~70% API quota) |
| **Rate limiting** | None | 60 req/min per key |
| **Multi-user** | No (shares your CF credentials) | Yes (each user gets own API key) |
| **Best for** | Personal use, quick start | Teams, production, high volume |

### Option A: Direct Mode (No Worker)

Calls Cloudflare Browser Rendering API directly — no Worker deployment needed.

```bash
pip install cf-browser cf-browser-mcp
```

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_ACCOUNT_ID": "<your-account-id>",
        "CF_API_TOKEN": "<your-api-token>"
      }
    }
  }
}
```

Get your credentials:
- **Account ID**: `wrangler whoami` or [Cloudflare Dashboard](https://dash.cloudflare.com) → any domain → Overview → right sidebar
- **API Token**: [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens) → Create Token → use "Edit Cloudflare Workers" template

Restart Claude Code. Done.

### Option B: Worker Mode (with caching & rate limiting)

Deploy a Cloudflare Worker as an edge proxy with built-in caching and auth.

**One-Command Setup:**

```bash
git clone https://github.com/claude-world/cf-browser.git
cd cf-browser
bash setup.sh
```

The setup script creates all Cloudflare resources, deploys the Worker, installs Python packages, and outputs a ready-to-paste `.mcp.json` config.

<details>
<summary>Click to expand manual Worker setup</summary>

#### Prerequisites

- Node.js 18+, Python 3.10+
- Cloudflare account with [Browser Rendering](https://developers.cloudflare.com/browser-rendering/) enabled
- `wrangler` CLI authenticated (`npm i -g wrangler && wrangler login`)

#### Step 1: Deploy the Worker

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
wrangler secret put CF_ACCOUNT_ID      # from: wrangler whoami
wrangler secret put CF_API_TOKEN       # from: https://dash.cloudflare.com/profile/api-tokens
echo "$(openssl rand -hex 32)" | wrangler secret put API_KEYS
```

Deploy:

```bash
wrangler deploy
# → https://cf-browser.<your-subdomain>.workers.dev
```

#### Step 2: Install SDK + MCP Server

```bash
pip install cf-browser cf-browser-mcp
```

Or install from source:

```bash
cd sdk && pip install -e .
cd ../mcp-server && pip install -e .
```

#### Step 3: Register MCP in Claude Code

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
        "CF_BROWSER_API_KEY": "<your-api-key>"
      }
    }
  }
}
```

Restart Claude Code. You'll see 15 `browser_*` tools available.

</details>

## Architecture

```
                          ┌─────────────────────┐
                          │     Claude Code      │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │  MCP Server (15 tools)│
                          └──────────┬───────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                  │
            Direct Mode                        Worker Mode
            (CF_ACCOUNT_ID                     (CF_BROWSER_URL
             + CF_API_TOKEN)                    + CF_BROWSER_API_KEY)
                    │                                  │
                    │                    ┌─────────────▼──────────────┐
                    │                    │   Cloudflare Worker        │
                    │                    │  ├── Auth (timing-safe)    │
                    │                    │  ├── Rate limit (KV)       │
                    │                    │  └── Cache (KV + R2)       │
                    │                    └─────────────┬──────────────┘
                    │                                  │
                    └────────────────┬─────────────────┘
                                     │
                          ┌──────────▼───────────┐
                          │ CF Browser Rendering │
                          │   API (Chrome)       │
                          └──────────────────────┘
```

Three independent packages:

| Package | Language | Purpose |
|---------|----------|---------|
| `worker/` | TypeScript (Hono + Puppeteer) | Edge proxy with auth, cache, rate limiting, browser interaction |
| `sdk/` (`cf-browser` on PyPI) | Python (httpx) | Async client library |
| `mcp-server/` (`cf-browser-mcp` on PyPI) | Python (FastMCP) | 15 MCP tools for Claude Code |

## MCP Tools

### Read-only tools (Direct + Worker mode)

| Tool | Input | Output | Use case |
|------|-------|--------|----------|
| `browser_markdown` | url | Markdown string | Read any web page as clean text |
| `browser_content` | url | HTML string | Get fully rendered HTML (JS executed) |
| `browser_screenshot` | url, width, height | PNG file path | Visual verification, multi-device testing |
| `browser_pdf` | url, format | PDF file path | Generate reports, archive pages |
| `browser_scrape` | url, selectors[] | JSON | Extract specific elements by CSS selector |
| `browser_json` | url, prompt | JSON | AI-powered structured data extraction |
| `browser_links` | url | JSON array | Discover all hyperlinks on a page |
| `browser_a11y` | url | JSON | Accessibility tree — LLM-friendly structured data |
| `browser_crawl` | url, limit | Job ID | Start async multi-page crawl |
| `browser_crawl_status` | job_id, wait | JSON | Poll or wait for crawl results |

### Interaction tools (Worker mode only — requires BROWSER binding)

| Tool | Input | Output | Use case |
|------|-------|--------|----------|
| `browser_click` | url, selector | JSON | Click a button/link and get resulting page |
| `browser_type` | url, selector, text | JSON | Type into input fields |
| `browser_evaluate` | url, script | JSON | Execute JavaScript and get return value |
| `browser_interact` | url, actions[] | JSON | Chain multiple actions (click, type, wait, screenshot, etc.) |
| `browser_submit_form` | url, fields | JSON | Fill and submit forms in one call |

All tools accept optional `cookies`, `headers`, `wait_for`, `wait_until`, and `user_agent` parameters. Use `wait_until="networkidle0"` for SPA sites (React, Next.js, X/Twitter).

### Examples in Claude Code

```
"Read the React 19 migration guide"
→ browser_markdown("https://react.dev/blog/2024/12/05/react-19")

"Show me what our homepage looks like on mobile"
→ browser_screenshot("https://example.com", width=375, height=667)

"Extract the top 5 products with name, price, and rating"
→ browser_json("https://example.com/products", prompt="Extract top 5 products...")

"Get the page structure for accessibility analysis"
→ browser_a11y("https://example.com")

"Scrape our dashboard (requires login)"
→ browser_markdown("https://app.example.com/dashboard", cookies='[{"name":"session","value":"abc"}]')

"Find all broken links on our site"
→ browser_crawl("https://example.com", limit=50) → browser_crawl_status(job_id, wait=True)

"Log into our staging site and check the dashboard"
→ browser_interact("https://staging.example.com/login", actions=[
    {"action":"type", "selector":"#email", "text":"admin@example.com"},
    {"action":"type", "selector":"#password", "text":"secret"},
    {"action":"click", "selector":"button[type=submit]"},
    {"action":"wait", "selector":".dashboard"},
    {"action":"screenshot"}
  ])

"Fill out the contact form"
→ browser_submit_form("https://example.com/contact",
    fields={"#name":"Claude", "#email":"claude@example.com", "#message":"Hello!"},
    submit_selector="button.submit")
```

## Worker API Reference

All routes (except `/health`) require `Authorization: Bearer <api-key>` header.

### Endpoints

| Route | Method | Body | Cache | Response |
|-------|--------|------|-------|----------|
| `/health` | GET | — | — | `{"status":"ok","version":"2.0.0","capabilities":{...}}` |
| `/content` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 1hr | HTML |
| `/markdown` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 1hr | Markdown |
| `/screenshot` | POST | `{url, width?, height?, full_page?, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | R2 24hr | PNG |
| `/pdf` | POST | `{url, format?, landscape?, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | R2 24hr | PDF |
| `/snapshot` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 30min | JSON |
| `/scrape` | POST | `{url, elements[], wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 30min | JSON |
| `/json` | POST | `{url, prompt, schema?, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | None | JSON |
| `/links` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 1hr | JSON |
| `/a11y` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 5min | JSON |
| `/crawl` | POST | `{url, limit?, user_agent?, cookies?, headers?, no_cache?}` | — | `{"job_id":"..."}` |
| `/crawl/:id` | GET | — | R2 | JSON |
| `/crawl/:id` | DELETE | — | — | 204 No Content |
| `/click` | POST | `{url, selector, wait_for?, ...}` | None | JSON |
| `/type` | POST | `{url, selector, text, clear?, wait_for?, ...}` | None | JSON |
| `/evaluate` | POST | `{url, script, wait_for?, ...}` | None | JSON |
| `/interact` | POST | `{url, actions[], wait_for?, ...}` | None | JSON |
| `/submit-form` | POST | `{url, fields, submit_selector?, wait_for?, ...}` | None | JSON |

Interaction routes (`/click`, `/type`, `/evaluate`, `/interact`, `/submit-form`) require the `BROWSER` binding. They return 501 if the binding is not configured.

### Authenticated requests

All endpoints accept optional `cookies` and `headers` fields for accessing authenticated pages:

```bash
curl -X POST https://cf-browser.example.workers.dev/markdown \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://app.example.com/dashboard",
    "cookies": [{"name": "session_id", "value": "abc123", "domain": ".example.com"}],
    "headers": {"X-Custom-Auth": "token"}
  }'
```

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

# Accessibility tree
curl -X POST https://cf-browser.example.workers.dev/a11y \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# AI extraction
curl -X POST https://cf-browser.example.workers.dev/json \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://news.ycombinator.com", "prompt": "Extract top 5 stories with title and score"}'
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

```bash
pip install cf-browser
```

```python
# Direct mode — no Worker needed
from cf_browser import CFBrowserDirect

async with CFBrowserDirect(
    account_id="your-cf-account-id",
    api_token="your-cf-api-token",
) as browser:
    md = await browser.markdown("https://example.com")

# Worker mode — via deployed Worker
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

    # Accessibility tree (LLM-friendly, lower token cost)
    tree = await browser.a11y("https://example.com")

    # Scrape by CSS selectors
    elements = await browser.scrape("https://example.com", selectors=["h1", ".price"])

    # Authenticated scraping with cookies
    md = await browser.markdown(
        "https://app.example.com/dashboard",
        cookies=[{"name": "session", "value": "abc", "domain": ".example.com"}],
    )

    # Async crawl
    job_id = await browser.crawl("https://example.com", limit=10)
    result = await browser.crawl_wait(job_id, timeout=120)
```

### SDK methods

**Read-only (Direct + Worker mode):**

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
| `a11y(url, **opts)` | `dict` | Accessibility tree |
| `crawl(url, **opts)` | `str` | Job ID |
| `crawl_status(job_id)` | `dict` | Job status |
| `crawl_wait(job_id, timeout, poll_interval)` | `dict` | Wait for completion |

**Interaction (Worker mode only):**

| Method | Returns | Description |
|--------|---------|-------------|
| `click(url, selector, **opts)` | `dict` | Click element, return page state |
| `type_text(url, selector, text, clear?, **opts)` | `dict` | Type into input field |
| `evaluate(url, script, **opts)` | `dict` | Execute JS, return result |
| `interact(url, actions, **opts)` | `dict` | Chain multiple actions |
| `submit_form(url, fields, submit_selector?, **opts)` | `dict` | Fill and submit form |
| `delete_crawl(job_id)` | `None` | Delete cached crawl result |

All methods accept `no_cache=True` to bypass caching, `cookies`/`headers` for authenticated access, `wait_for` to wait for a CSS selector, `wait_until` for navigation strategy (`networkidle0` for SPAs), and `user_agent` for custom User-Agent. Interaction methods raise `NotImplementedError` in Direct mode.

## Security

- **Auth**: Timing-safe Bearer token comparison using SHA-256 (prevents timing attacks)
- **Rate limiting**: Per-key tracking with hashed key material in KV (no raw keys stored)
- **SSRF prevention**: Only `http://` and `https://` URLs allowed; localhost and private IP ranges blocked
- **Secrets**: All credentials stored via `wrangler secret put`, never in code
- **Cookie isolation**: Cookies are injected per-request, never persisted

## Skills (Bonus)

CF Browser includes 6 ready-to-use [Claude Code Skills](https://docs.anthropic.com/en/docs/claude-code/skills) in the `skills/` directory. Copy a skill folder to your project's `.claude/skills/` to activate.

| Skill | Command | What it does |
|-------|---------|--------------|
| **content-extractor** | `/content-extractor` | Read pages, extract structured data, scrape elements, discover links |
| **site-auditor** | `/site-auditor` | Crawl a site and generate SEO / link / accessibility audit report |
| **doc-fetcher** | `/doc-fetcher` | Crawl an entire docs site to local Markdown for RAG |
| **visual-qa** | `/visual-qa` | Multi-device viewport screenshots (mobile/tablet/laptop/desktop) + visual checks |
| **changelog-monitor** | `/changelog-monitor` | Track version updates and breaking changes for any project |
| **competitor-watch** | `/competitor-watch` | Extract and compare competitor pricing / features |

```bash
# Copy a single skill
cp -r skills/content-extractor .claude/skills/

# Or copy all
cp -r skills/* .claude/skills/
```

## Cost

| Component | Free Tier | Paid ($5/mo Workers) |
|-----------|-----------|---------------------|
| Browser Rendering | 10 min/day, 5 crawl jobs | Higher limits |
| KV | 100K reads/day | 10M reads/mo |
| R2 | 10GB storage | 10GB included |
| Workers | 100K requests/day | 10M requests/mo |

For most Claude Code usage, the free tier is sufficient. Interaction tools (click, type, evaluate, interact, submit-form) require the Workers Paid plan ($5/mo) for the BROWSER binding.

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
│   │   │   ├── a11y.ts      POST /a11y → JSON (accessibility tree)
│   │   │   ├── crawl.ts     POST/GET/DELETE /crawl
│   │   │   ├── click.ts     POST /click (interaction)
│   │   │   ├── type.ts      POST /type (interaction)
│   │   │   ├── evaluate.ts  POST /evaluate (interaction)
│   │   │   ├── interact.ts  POST /interact (action chains)
│   │   │   └── submit-form.ts POST /submit-form (interaction)
│   │   └── lib/
│   │       ├── cf-api.ts    CF Browser Rendering client
│   │       ├── puppeteer.ts Puppeteer lifecycle helper (interaction)
│   │       ├── param-map.ts snake_case → CF API camelCase mapping
│   │       ├── cache-key.ts SHA-256 cache keys
│   │       └── validate-url.ts  SSRF prevention
│   ├── tests/
│   ├── wrangler.toml.example
│   └── package.json
├── sdk/                     Python SDK (cf-browser on PyPI)
│   ├── src/cf_browser/
│   │   ├── client.py        CFBrowser client (Worker mode)
│   │   ├── direct.py        CFBrowserDirect client (Direct mode)
│   │   ├── _shared.py       Shared helpers (crawl polling)
│   │   ├── models.py        Pydantic response models
│   │   └── exceptions.py    Typed error hierarchy
│   ├── tests/
│   └── pyproject.toml
├── mcp-server/              MCP Server (cf-browser-mcp on PyPI)
│   ├── src/cf_browser_mcp/
│   │   └── server.py        15 MCP tool definitions
│   └── pyproject.toml
├── examples/                Usage examples
├── setup.sh                 One-command setup script
├── CHANGELOG.md
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
