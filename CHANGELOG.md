# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **DNS-based SSRF validation** — Worker URL validation now blocks hostnames that resolve to private IPs, not just literal localhost / RFC1918-style addresses.
- **Production dependency refresh** — Worker dependencies upgraded to `@cloudflare/puppeteer@1.1.0` and `hono@4.12.14`, clearing published `npm audit --omit=dev` vulnerabilities.

### Fixed

- **`submit-form` fallback behavior** — Worker now prefers `requestSubmit()` or a real submit control instead of raw `form.submit()`, preserving validation and submit handlers.
- **Interaction navigation races** — `click`, `interact`, and `submit-form` now start navigation waits before the action, eliminating missed navigations on fast pages.
- **`scrape` / `links` contract drift** — Worker, SDK, and MCP now normalize upstream response shapes to the documented `{"elements":[...]}` and `[{href, text}]` formats.
- **Stale Worker interaction errors** — MCP interaction tools now distinguish "Direct mode unsupported" from "deployed Worker is missing routes" and return a redeploy hint for 404s.

### Added

- **Worker regression tests** — new coverage for interaction routes and DNS-based URL validation.

### Documentation

- Root README, localized README, package READMEs, contributing guide, and skills links updated to match the current 2.0.1 behavior and setup flow.

## [2.0.1] - 2026-03-22

### Security

- **SSRF filter hardened** — block CGNAT range (`100.64.0.0/10`, RFC 6598), NAT64 prefixes (`64:ff9b::/96`, `64:ff9b:1::/48`), IPv6 site-local (`fec0::/10`), and all zero-address variants (`::`, `0:0:0:0:0:0:0:0`, etc.)
- **`authenticate` field stripped from REST API payloads** — previously passed through silently to CF REST API which ignores it, misleading callers into thinking HTTP Basic Auth was active
- **Type-safe request body parsing** — new `toBaseBody()` helper eliminates all `body as any` casts in Puppeteer route handlers, preventing untyped field leakage

### Fixed

- **`interact` action loop stop logic** — unknown actions now correctly halt the loop via labeled `break`; previously fell through to next action due to switch/loop `break` ambiguity
- **`evaluate`/`interact` timeout race** — removed `page.close()` from timeout handlers that raced with `browser.close()` in the `withBrowser` finally block
- **`screenshot` viewport validation** — added numeric bounds checking for `width` (1–7680) and `height` (1–4320)
- **MCP Server `_build_kwargs` made keyword-only** — prevents positional argument ordering bugs across 13 call sites
- **MCP Server atexit cleanup** — simplified to honest single-path `asyncio.run()` with clear documentation that cleanup is best-effort
- **SDK `_raise_for_status` exception narrowing** — replaced bare `except Exception` with `except ValueError` and added `isinstance(body, dict)` guard to prevent `AttributeError` masking on non-dict JSON responses
- **SDK `delete_crawl` error message** — Direct mode now correctly states "not yet implemented" instead of incorrectly claiming it requires browser interaction
- **Removed stale `a11y` comment** from `cf-api.ts`

### Changed

- Worker, SDK, and MCP Server versions synced to 2.0.1

## [2.0.0] - 2026-03-17

### Added

- **Browser interaction tools** — 5 new MCP tools for clicking, typing, form submission, JavaScript execution, and multi-step action chains. Requires Worker mode with `BROWSER` binding (Workers Paid plan)
  - `browser_click` — click an element and return resulting page state
  - `browser_type` — type text into an input field, with optional clear-before-type
  - `browser_evaluate` — execute JavaScript in page context (10KB limit, 10s timeout)
  - `browser_interact` — chain up to 20 actions (click, type, wait, screenshot, evaluate, select, scroll, navigate) with 50s total execution budget
  - `browser_submit_form` — fill form fields and submit (sugar over interact)
- **`@cloudflare/puppeteer` integration** — new `withBrowser()` lifecycle helper manages browser launch, page setup (viewport, user agent, headers, cookies), navigation, and cleanup
- **`DELETE /crawl/:id`** — delete cached crawl results from R2 storage
- **SDK interaction methods** — `click()`, `type_text()`, `evaluate()`, `interact()`, `submit_form()`, `delete_crawl()` on `CFBrowser` class
- **Direct mode stubs** — all 6 interaction methods raise `NotImplementedError` with clear guidance on `CFBrowserDirect`
- **SDK models** — `ClickResult`, `EvaluateResult`, `InteractAction`, `InteractResult`, `FormField` Pydantic models
- **Health endpoint** — now reports `capabilities.interact: boolean` based on BROWSER binding availability
- **CORS** — `DELETE` method added to allowed methods

### Changed

- Worker, SDK, and MCP Server versions bumped to 2.0.0
- MCP Server description updated to 15 tools (was 10)

### Security

- **Selector injection**: 500-character limit on all CSS selectors
- **Script injection**: 10KB limit and 10s execution timeout on evaluate scripts
- **Action chain abuse**: Max 20 actions per interact call, 50s total timeout
- **SSRF in navigate actions**: `validateUrl()` applied to navigate action URLs within interact chains
- **No BROWSER binding**: Routes return 501; SDK raises `NotImplementedError`; MCP returns helpful error JSON

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
