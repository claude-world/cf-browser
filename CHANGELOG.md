# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
