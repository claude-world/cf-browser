# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-03-15

### Added

- **`wait_until` parameter** — control navigation completion strategy (`networkidle0`, `networkidle2`, `load`, `domcontentloaded`). Critical for SPA sites like X/Twitter that need full JS hydration before content extraction
- **`user_agent` parameter** — set custom User-Agent string per request across all 10 MCP tools
- **`wait_for` now works correctly** — previously silently ignored by CF API due to wrong parameter name; now properly mapped to `waitForSelector` object format
- **`headers` now works correctly** — previously silently ignored; now properly mapped to `setExtraHTTPHeaders`
- **Shared `mapToCfParams()` utility** (Worker) — single-source parameter translation from user-friendly snake_case to CF API camelCase, used by all 10 route handlers
- **Shared `_transform_common_opts()` function** (SDK Direct mode) — equivalent parameter mapping for Direct API calls
- **`browser_crawl` now supports `cookies`/`headers`** — enables crawling authenticated sites

### Fixed

- **Critical: `wait_for` was silently broken** — CF REST API expects `waitForSelector: {selector: "..."}` (object), not `waitForSelector: "..."` (string) or `wait_for: "..."`. All prior versions sent the wrong format, causing the parameter to be silently ignored
- **Critical: `headers` was silently broken** — CF REST API expects `setExtraHTTPHeaders`, not `headers`. Custom HTTP headers were never actually applied
- **Critical: `timeout` was silently broken** — CF REST API expects `gotoOptions.timeout`, not top-level `timeout`. Request timeouts were never enforced
- **Worker types consolidated** — moved `wait_for`, `timeout` from every endpoint-specific type into `BaseRequestBody` (DRY)
- **MCP Server refactored** — replaced `_auth_kwargs()` with `_build_kwargs()` to handle all browser-control params in one place
- **Existing test fixed** — `test_pdf_transforms_options` was asserting `pdfOptions` existence (incorrect), now correctly asserts `format`/`landscape` are stripped

### Changed

- Worker, SDK, and MCP Server versions synced to 1.2.0

## [1.1.0] - 2026-03-14

### Added

- **Direct Mode** — call CF Browser Rendering API directly without deploying a Worker. New `CFBrowserDirect` class in SDK with same API as `CFBrowser`. MCP Server auto-detects mode from env vars: `CF_ACCOUNT_ID` + `CF_API_TOKEN` for Direct, `CF_BROWSER_URL` + `CF_BROWSER_API_KEY` for Worker
- **`landscape` parameter** for `browser_pdf` MCP tool

### Changed

- SDK `crawl_wait` polling logic extracted to shared `_shared.py` module (DRY between Worker and Direct clients)
- MCP Server `get_client()` now raises descriptive `RuntimeError` when neither credential pair is configured
- MCP Server adds `atexit` cleanup to close the HTTP client on process exit

### Fixed

- **Worker PDF endpoint** — strip `format`/`landscape` params that CF REST API does not accept (was returning 400)
- **Worker auth timing leak** — removed `break` in multi-key loop to prevent positional timing side-channel
- **Worker snapshot cache** — strip base64 screenshot before KV storage to avoid 25MB value limit
- **Worker SSRF** — block localhost, `0.0.0.0/8`, and RFC 1918 private IP ranges in URL validation
- **Worker rate limiter** — capture `Date.now()` once to prevent TOCTOU race at minute boundaries
- **Worker cache hit** — avoid redundant `JSON.parse` + `JSON.stringify` round-trip on cached JSON responses (snapshot, scrape, links, a11y routes)
- **MCP `browser_crawl_status`** — catch `CFBrowserError` from failed crawl jobs instead of surfacing raw exception
- **CORS** — documented `origin: "*"` as intentional design choice for API-style Worker

### Security

- Added `wrangler.local.toml` to root `.gitignore` to prevent KV namespace ID leaks

## [1.0.0] - 2026-03-14

### Added

- **`browser_a11y` tool** — accessibility tree extraction for LLM-friendly structured data (10th MCP tool), with 5-minute KV cache and screenshot stripping to reduce token cost
- **Cookie & header auth support** — all 10 tools now accept optional `cookies` (JSON array) and `headers` (JSON object) for scraping authenticated/paywalled pages
- **PyPI publishing workflow** — `pip install cf-browser` and `pip install cf-browser-mcp` via trusted OIDC publishing
- **One-command setup** — `bash setup.sh` creates KV namespaces, R2 bucket, generates API key, deploys Worker, and outputs `.mcp.json` config
- **CI: Worker tests** — added Node.js worker test job to CI pipeline
- **Examples directory** — 4 usage guides: `basic-usage.py`, `authenticated-scraping.py`, `accessibility-tree.py`, `crawl-and-analyze.py`

### Changed

- SDK and MCP Server version bumped to 1.0.0 with full PyPI metadata (authors, classifiers, URLs)
- SDK `crawl()` now raises `CFBrowserError` with clear message when API response is missing `job_id`
- MCP Server `browser_crawl_status` with `wait=True` now delegates to SDK's `crawl_wait()` instead of duplicating poll logic
- MCP Server `_auth_kwargs()` now raises `ValueError` on malformed JSON instead of silently ignoring
- README fully rewritten with PyPI badges, setup instructions, 10-tool endpoint table, and auth examples
- Package-specific `sdk/README.md` and `mcp-server/README.md` for PyPI display

### Fixed

- **Timing-safe auth** — removed `safeEqual` length short-circuit that partially defeated constant-time comparison (SHA-256 digest comparison is inherently constant-length)
- **Rate limit test** — fixed pre-seeded KV key to match SHA-256 hash prefix format
- **Wrangler config** — replaced real KV namespace IDs with placeholders for safe open-source distribution

### Security

- All endpoints now validate cookie/header JSON input, rejecting malformed payloads with descriptive errors
- Added `.dev.vars` to `.gitignore` to prevent accidental Wrangler secret leaks

## [0.1.0] - 2026-03-13

### Added

- Initial release
- Cloudflare Worker proxy with Bearer token auth, KV caching, and R2 binary storage
- Python SDK (`cf-browser`) — async httpx client with context manager support
- MCP Server (`cf-browser-mcp`) — FastMCP wrapper exposing 9 browser tools
- 9 browser tools: content, screenshot, pdf, markdown, snapshot, scrape, json, links, crawl + crawl_status
- KV caching (1hr text, 30min dynamic, 24hr binary via R2)
- SSRF prevention via URL validation
- Timing-safe Bearer token auth with SHA-256 + constant-time XOR
- Per-key rate limiting (60 req/min, KV-based with hashed keys)
