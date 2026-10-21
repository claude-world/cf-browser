# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **Native rate limiting** — replaced the concurrency-unsafe KV counter with Cloudflare's native Rate Limiting binding, keyed by full SHA-256 API-key digests.
- **Crawl tenant isolation** — crawl jobs are bound to the API key that created them; missing owner metadata and cross-key GET/DELETE requests fail closed with 404, including cached results.
- **Crawl cancellation** — `DELETE /crawl/:id` now cancels the upstream Cloudflare job before removing local state; a KV owner fallback preserves a recovery path when both the primary owner write and compensating cancellation fail.
- **R2 retention enforcement** — screenshot, PDF, snapshot, crawl result, and crawl-owner metadata expire logically, and setup installs and verifies an enabled, all-prefix, exact eight-day bucket lifecycle rule so unread objects are deleted too; conflicting same-name rules fail closed and legacy cache objects without valid TTL metadata are invalidated.
- **SSRF hardening** — complete non-global IPv4/IPv6 classes, empty/CNAME-only DNS answers, injected script/style URLs, and intercepted interaction redirects/subrequests fail closed.
- **Private MCP artifacts** — screenshot/PDF filenames are unpredictable, omit URL userinfo, use `0600` inside a `0700` directory, enforce bounded disk quotas, and are cleaned up at process exit.
- **Secret-safe setup** — setup no longer prints generated keys, exposes application or official Wrangler credential variables to npm/pip lifecycle or package-import subprocesses, or places credentials in process arguments. It writes private MCP config with `0600`, injects Worker secrets from one mode-`0600` temporary file, and restores an existing Claude MCP registration if replacement fails.
- **Bounded interaction output** — every interaction route enforces an eight-MiB JSON response limit; multi-action results share an exact full-envelope quota, with bounded page state and an explicit truncation marker.
- **Hardened publishing** — build/test jobs have no OIDC permission; minimal publishing jobs download verified artifacts and use commit-pinned actions. MCP-only releases require the exact SDK version to exist on PyPI.
- **Dependency refresh** — Hono 4.12.30, Wrangler 4.112.0, Vitest 4.1.10, current Workers types, and refreshed transitive packages produce zero full or production `npm audit` findings.

### Fixed

- **Current Cloudflare contracts** — PDF options use `pdfOptions`; accessibility uses `/accessibilityTree`; links use `excludeExternalLinks`/`visibleLinksOnly`; JSON schemas use `response_format`; HTTP `authenticate` is preserved.
- **Snapshot cache parity** — cache hits now return the same complete JSON shape as misses instead of dropping the screenshot.
- **Crawl lifecycle** — supports string and numeric opaque cursors, bounded record filters, current completion/failure/cancellation statuses, wall-clock-bounded polling, all-page final fetches, orphan cancellation, and missing-job-ID validation without caching partial pages.
- **Current crawl contract** — Worker, Direct SDK, and MCP expose upstream `cacheTTL`, depth, formats, Content Signals purposes, freshness filters, URL patterns, JSON extraction, and rendered request/JavaScript/viewport controls. MCP also accepts the complete structured navigation, selector-wait, and viewport objects.
- **Interaction validation** — malformed/null actions and shared request options now return 400 instead of reaching Puppeteer or producing generic 500 errors.
- **Canonical option and response validation** — raw canonical navigation, selector, viewport, request/resource, JavaScript, and media fields are validated before forwarding and applied consistently to interaction pages; unsupported Cloudflare-only fields fail explicitly. Malformed crawl, text, JSON, screenshot, and PDF success responses—including binary MIME/magic mismatches—fail as typed 502 errors instead of becoming false-success output.
- **Timeout layering** — Worker and Python transport deadlines now accommodate the longest supported synchronous Browser Run action instead of aborting valid 120-second options early.
- **Transport classification** — SDK network failures use `TransportError`; terminal crawl states use `CrawlJobError`, so MCP no longer labels auth/network failures as failed jobs.
- **Setup correctness** — uses `npm ci`, atomically installs a real `.toml` config only after deployment, exact-name resource checks, recoverable backup and stable rate-limit namespace, native `RATE_LIMITER`, supported Wrangler flags, account-pinned resource/deploy operations, rollback regression tests, readiness plus authenticated smoke tests, and isolated Python installation.
- **PyPI release gate** — MCP-only publication now requires an exact SDK release with at least one non-yanked downloadable file; empty or yanked-only release keys no longer false-green.

### Added

- **17 MCP tools** — added `browser_snapshot` and `browser_delete_crawl`; structured actions/fields, `no_cache`, navigation timeout, JSON schemas, link filters, and crawl pagination are exposed.
- **Explicit MCP mode** — `CF_BROWSER_MODE=direct|worker`; ambiguous credential pairs fail closed.
- **Readiness health response** — `/health` returns `ready`, `degraded`/503 for missing core bindings, and the optional interaction capability.
- **Typed distribution** — SDK wheel now contains `py.typed`; source distributions exclude local `.pymon` state.
- **Release gates** — Python 3.10–3.13, Node 22/24, Ruff, Mypy, audit, tests, builds, Twine, archive inspection, all duplicate version sources, Actionlint, ShellCheck, mock setup end-to-end, and Wrangler dry-run are covered by CI.

### Changed

- Worker, SDK, and MCP Server versions prepared as 2.1.0.
- Minimum Node.js version is 22 to match current Wrangler; Python remains 3.10+.
- Root/localized/package READMEs, examples, contributing guide, setup flow, and Skills now use the Cloudflare Browser Run name and describe the current API and secret-handling model.

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
