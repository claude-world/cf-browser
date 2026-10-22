# CF Browser

Use [Cloudflare Browser Run](https://developers.cloudflare.com/browser-run/) (formerly Browser Rendering) from Python or Claude Code. CF Browser provides a typed async SDK, a deployable Worker proxy, **17 MCP tools**, and six reusable Skills for rendered content, screenshots, PDFs, structured extraction, crawling, accessibility trees, and browser interaction.

[![PyPI - cf-browser](https://img.shields.io/pypi/v/cf-browser?label=cf-browser)](https://pypi.org/project/cf-browser/)
[![PyPI - cf-browser-mcp](https://img.shields.io/pypi/v/cf-browser-mcp?label=cf-browser-mcp)](https://pypi.org/project/cf-browser-mcp/)
[![Tests](https://github.com/claude-world/cf-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/claude-world/cf-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<img src="assets/demo.gif" alt="Claude Code calling the cf-browser browser_markdown MCP tool on example.com and answering from the rendered page" width="809" />

## Choose a mode

| | Direct mode | Worker mode |
|---|---|---|
| Calls | Cloudflare REST API | Your authenticated Worker proxy |
| Setup | Two Cloudflare credentials | Worker, KV, R2, native rate limiter |
| MCP tools | 12 read/crawl tools | All 17 tools |
| Cache | None | KV + R2, with enforced TTLs |
| Rate limit | Cloudflare account limits | 60 requests/minute/key/location |
| Interaction | No | Click, type, evaluate, action chains, forms |
| Best fit | Personal use | Teams and browser automation |

Both modes use the same `cf-browser` Python interface. Set `CF_BROWSER_MODE` explicitly if both credential sets exist.

## Quick start

### Direct mode

Create an API token with **Account → Browser Run (Browser Rendering) → Edit**, then install:

```bash
python -m pip install cf-browser cf-browser-mcp
export CF_BROWSER_MODE=direct
export CF_ACCOUNT_ID="your-account-id"
export CF_API_TOKEN="your-browser-rendering-token"
```

For Claude Code, keep secrets in environment variables and reference them from a private `.mcp.json`:

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_BROWSER_MODE": "direct",
        "CF_ACCOUNT_ID": "${CF_ACCOUNT_ID}",
        "CF_API_TOKEN": "${CF_API_TOKEN}"
      }
    }
  }
}
```

Direct mode supports all read-only Quick Actions plus crawl status, pagination, cancellation, and waiting. Interaction tools return a mode-specific hint.

### Worker mode

Requirements: Node.js 22+, Python 3.10+, an authenticated Wrangler session, and a Cloudflare account with Browser Run. The setup script creates/reuses storage, installs physical R2 expiration, pins every resource operation to the selected account, configures the native rate limiter and secrets, deploys, performs authenticated live verification, installs an isolated MCP environment, and registers a user-scoped Claude Code server when the `claude` CLI is present.

```bash
git clone https://github.com/claude-world/cf-browser.git
cd cf-browser
cd worker && npx wrangler login && cd ..
bash setup.sh
```

The script does not print API keys. It backs up an existing `worker/wrangler.toml`, preserves its native rate-limit namespace ID, sends all Worker secrets in one private temporary file during deployment (deleted right after), and stores the MCP configuration in a private generation directory under `~/.config/cf-browser/` (or `$XDG_CONFIG_HOME/cf-browser/`) with mode `0600`; the final summary prints its path. If Claude Code registration fails, the new configuration is kept and the summary prints the exact `claude mcp add` command, because each run installs a new Worker API key.

To run read-only endpoints without the paid browser binding:

```bash
CF_BROWSER_ENABLE_INTERACTIONS=0 bash setup.sh
```

#### Manual Worker deployment

```bash
cd worker
cp wrangler.toml.example wrangler.toml
npm ci

npx wrangler kv namespace create cf-browser-CACHE
# Paste the returned ID into wrangler.toml.
npx wrangler r2 bucket create cf-browser-storage
# The Worker keeps every R2 object under cf-browser/; expire that prefix after 8 days.
npx wrangler r2 bucket lifecycle add cf-browser-storage cf-browser-prefix-expire-after-8-days cf-browser/ --expire-days 8
# Choose an account-unique positive ratelimits.namespace_id in wrangler.toml.

npx wrangler secret put CF_ACCOUNT_ID
npx wrangler secret put CF_API_TOKEN
CF_BROWSER_API_KEY="$(openssl rand -hex 32)"
printf '%s' "$CF_BROWSER_API_KEY" | npx wrangler secret put API_KEYS

npm audit --audit-level=high
npm run type-check
npm test
npx wrangler deploy
```

`CF_API_TOKEN` needs Browser Run access (the API permission may still appear as Browser Rendering). R2 lifecycle management needs Workers R2 Storage Write permission. Save `CF_BROWSER_API_KEY` in your password manager or client configuration before closing the shell; Cloudflare cannot reveal the stored secret later. Wrangler login authorizes resource creation and deployment. Remove the `[browser]` block only if you intentionally do not need interaction tools.

## MCP tools

### Read and crawl tools

| Tool | Main arguments | Result |
|---|---|---|
| `browser_content` | `url` | Rendered HTML |
| `browser_markdown` | `url` | Markdown |
| `browser_screenshot` | `url`, `width`, `height`, `full_page` | Private temporary PNG path |
| `browser_pdf` | `url`, `format`, `landscape` | Private temporary PDF path |
| `browser_snapshot` | `url` | Content, Markdown, screenshot, and optional a11y tree |
| `browser_scrape` | `url`, `selectors[]` | Normalized selector results |
| `browser_json` | `url`, `prompt?`, `response_format?` | AI-extracted JSON |
| `browser_links` | `url`, `include_external`, `visible_only` | Normalized links |
| `browser_a11y` | `url` | Native accessibility tree |
| `browser_crawl` | `url`, `limit`, crawl options | Job ID |
| `browser_crawl_status` | `job_id`, `wait`, pagination filters | Status or records |
| `browser_delete_crawl` | `job_id` | Cancellation confirmation |

Read tools accept structured `cookies`, `headers`, HTTP Basic `authenticate`, script/style tags, `wait_for`, `wait_until`, `user_agent`, `timeout` (page-navigation milliseconds), and `no_cache`. Crawls render by default and additionally expose `depth`, `formats`, `crawl_purposes`, upstream `cache_ttl`, freshness filters, include/exclude patterns, JSON extraction options, request/resource filters, JavaScript control, action timeouts, and viewport controls. MCP callers can use either flattened conveniences or full `goto_options`, `wait_for_selector`, and `viewport` objects. `render=false` selects static fetching and rejects browser-only options. Interaction tools also forward authentication, injection, and resource-blocking controls.

### Interaction tools (Worker mode)

| Tool | Main arguments | Result |
|---|---|---|
| `browser_click` | `url`, `selector` | Resulting page state |
| `browser_type` | `url`, `selector`, `text`, `clear` | Resulting page state |
| `browser_evaluate` | `url`, `script` | JSON-serializable value |
| `browser_interact` | `url`, `actions[]` | Per-action results |
| `browser_submit_form` | `url`, `fields`, `submit_selector?` | Resulting page state |

Interaction routes require the `BROWSER` binding. A missing binding returns HTTP 501 and maps to `BrowserUnavailableError`; Direct mode uses `NotImplementedError`. A target (or main-frame redirect) that resolves to a blocked address returns HTTP 400 before any page content is returned.

## Worker API

Every route except `/health` requires `Authorization: Bearer <API_KEY>`. Authentication and rate limiting run before any request body is read; bodies must be JSON objects of at most 2 MiB (larger bodies get HTTP 413), without `__proto__` keys or nesting deeper than 64 levels.

| Route | Method | Important request fields | Cache/result |
|---|---|---|---|
| `/health` | GET | — | Readiness, version, capabilities |
| `/content` | POST | `url`, common options | KV, 1 hour |
| `/markdown` | POST | `url`, common options | KV, 1 hour |
| `/screenshot` | POST | `url`, `width?`, `height?`, `full_page?` | R2, 24 hours |
| `/pdf` | POST | `url`, `format?`, `landscape?` | R2, 24 hours |
| `/snapshot` | POST | `url`, common options | R2 JSON, 30 minutes |
| `/scrape` | POST | `url`, non-empty `elements[]` | KV, 30 minutes |
| `/json` | POST | `url` and `prompt` or `response_format` | Never locally cached |
| `/links` | POST | `url`, `include_external?`, `visible_only?` | KV, 1 hour |
| `/a11y` | POST | `url`, common options | KV, 5 minutes |
| `/crawl` | POST | `url`, `limit?`, `cache_ttl?`, `depth?`, formats/purposes/patterns, render options | Starts a job |
| `/crawl/:id` | GET | `cursor?`, `limit?`, record `status?` | Full completed result in R2 |
| `/crawl/:id` | DELETE | — | Cancels upstream and clears local state |
| `/click`, `/type`, `/evaluate`, `/interact`, `/submit-form` | POST | Route-specific fields | Not cached |

Health is a readiness check: missing core bindings produce HTTP 503 with `status: "degraded"`. `capabilities.interact` reports whether `BROWSER` is configured.

### Structured JSON extraction

Cloudflare's current schema field is `response_format`. The Worker and SDK retain `schema` as a compatibility alias and translate it before sending the request.

```json
{
  "url": "https://example.com/products",
  "prompt": "Extract the products",
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "type": "object",
      "properties": {
        "products": {"type": "array", "items": {"type": "object"}}
      },
      "required": ["products"]
    }
  }
}
```

### Crawl behavior

- Current success statuses `complete`, `completed`, and `done` are accepted for compatibility.
- Current failure/cancellation statuses are surfaced as `CrawlJobError`.
- Polling uses `limit=1`, then follows every result cursor and combines all records once finished.
- Cursor values are opaque strings or non-negative integers; partial pages bypass the full-result cache.
- A crawl is bound to the API key that created it. Other valid keys receive 404, and if Cloudflare ever returns a job ID that another key already owns, creation fails with 409 instead of sharing it.
- Owner metadata and completed results expire logically after seven days. The Worker stores every R2 object under `cf-browser/`, and setup installs an eight-day lifecycle rule for that prefix so unread objects are physically deleted.
- `DELETE` cancels the Cloudflare job; it is not merely a cache delete.

### Cache and rate limiting

Set `no_cache: true` to skip local cache reads/writes; for crawl creation it also sends Cloudflare `cacheTTL=0`. Use `cache_ttl` (0-86400 seconds) to control the upstream crawl cache independently. Text is stored in KV; binary and large JSON snapshots are stored in R2. R2 TTL metadata is enforced on reads, and the setup-installed bucket lifecycle physically removes otherwise-unread objects.

The native Cloudflare Rate Limiting binding enforces 60 requests per 60 seconds for each hashed API key at each Cloudflare location. A rejected request returns 429 with `Retry-After`, `X-RateLimit-Limit`, and `X-RateLimit-Remaining: 0`. Native counters are intentionally not presented as a globally exact remaining count.

## Python SDK

```python
from cf_browser import CFBrowser, CFBrowserDirect

# Direct mode
async with CFBrowserDirect(account_id="...", api_token="...") as browser:
    markdown = await browser.markdown("https://example.com")

# Worker mode
async with CFBrowser(base_url="https://...workers.dev", api_key="...") as browser:
    tree = await browser.a11y("https://example.com", no_cache=True)
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
    job_id = await browser.crawl("https://example.com", limit=20, cache_ttl=3600)
    result = await browser.crawl_wait(job_id, timeout=300, poll_interval=2)
    await browser.delete_crawl(job_id)
```

The SDK includes `py.typed`, typed HTTP/status exceptions, separate `TransportError` and `CrawlJobError`, `CrawlResultsTimeoutError` for crawls that finished but whose results could not be fetched in time, URL-quoted crawl IDs, and normalized link/scrape responses. Keys and tokens must be visible ASCII and never appear in error messages. See [sdk/README.md](sdk/README.md).

## Security model

- Bearer keys are compared using SHA-256 digests and a constant-time loop.
- Raw keys are not used as rate-limit or crawl-owner identifiers.
- URL validation blocks private, loopback, link-local, CGNAT, multicast, reserved, and other non-public literals. Top-level and injected resource URLs require public DNS answers before REST calls. Worker-mode interaction resolves the target before launching a browser, then intercepts the page's requests, including redirects and iframes, bypasses service workers, and closes popups; WebSocket and worker-initiated connections are not intercepted, and DNS can change between the check and the browser's own lookup. REST Quick Actions execute in Cloudflare's remote browser, so redirects, page subresources, and crawl-discovered URLs are outside this Worker's interception boundary and depend on Cloudflare's egress isolation. Do not expose API keys to untrusted tenants; use the interaction routes when application-enforced per-request interception is required.
- Multi-key crawl reads/cancellations enforce creator ownership.
- Shared request options and interaction actions are validated with size/type limits.
- MCP artifacts use unpredictable names in a process-private directory, mode `0600`, omit URL userinfo, enforce per-file/count/total-size quotas, and are deleted when the server exits normally. A server killed by a signal leaves its private (`0700`) directory in the system temp folder.
- Secrets are never hardcoded by setup or examples. Keep `.dev.vars`, `wrangler.toml`, and `.mcp.json` private.

Review Cloudflare's current Browser Run [limits](https://developers.cloudflare.com/browser-run/limits/) and [pricing](https://developers.cloudflare.com/browser-run/pricing/) before production use.

## Skills

Six skills are included under `skills/`: content extraction, site auditing, documentation fetching, visual QA, changelog monitoring, and competitor comparison.

```bash
cp -R skills/content-extractor .claude/skills/
# or
cp -R skills/* .claude/skills/
```

## Development

```bash
# Worker (Node 22, 24 or 26)
cd worker
npm ci
npm audit --audit-level=high
npm run type-check
npm test

# SDK
python -m pip install -e './sdk[dev]'
python -m ruff check sdk/src sdk/tests examples scripts
python -m mypy --config-file sdk/pyproject.toml sdk/src
python -m pytest -q sdk/tests

# MCP server
python -m pip install -e './sdk' -e './mcp-server[dev]'
python -m ruff check mcp-server/src mcp-server/tests
python -m mypy --config-file mcp-server/pyproject.toml mcp-server/src
python -m pytest -q mcp-server/tests

# Distribution checks
python -m build sdk
python scripts/verify_python_dist.py sdk --require-py-typed
python -m build mcp-server
python scripts/verify_python_dist.py mcp-server

# Setup script (hermetic mock run; touches nothing outside a temp directory)
bash scripts/test_setup.sh
```

CI runs Python 3.10–3.15, Node 22/24/26, audits, type checks, tests, builds, archive inspection, Actionlint, ShellCheck plus a mock setup end-to-end test, and a Wrangler deployment dry-run.

## Troubleshooting

- Interaction returns 501: enable the `BROWSER` binding and use Worker mode.
- Interaction returns 404: redeploy the current Worker; `/health` should report version `2.1.0`.
- MCP has both credential pairs: set `CF_BROWSER_MODE=direct` or `worker`.
- Crawl pagination appears incomplete: follow the returned opaque `cursor` until absent.
- Crawl creation returns 409: Cloudflare reused a job owned by another key; retry with `cache_ttl=0`.
- A request returns 413: the JSON body exceeds 2 MiB.
- Setup stops instead of printing success: read the failing Wrangler/curl step; the script intentionally does not swallow configuration errors.

## License

[MIT](LICENSE)
