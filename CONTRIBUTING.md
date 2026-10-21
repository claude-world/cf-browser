# Contributing

## Scope

This repo has three main contributor surfaces:

- `worker/`: Cloudflare Worker proxy built with TypeScript, Hono, Wrangler, and Vitest
- `sdk/`: Python SDK built with `httpx`, `pydantic`, `pytest`, and `respx`
- `mcp-server/`: MCP server (official `mcp` 2.x SDK) wrapping the SDK, with its own pytest suite

Keep changes focused, add or update tests for behavior changes, and avoid committing secrets or generated credentials.

## Prerequisites

- Node.js 22+ (CI also verifies Node 24 and 26)
- Python 3.10+
- Cloudflare account and `wrangler login` if you are working on deployed Worker behavior

## Worker Development

```bash
cd worker
npm ci
cp wrangler.toml.example wrangler.toml
```

`worker/wrangler.toml` is intentionally gitignored. Keep real namespace IDs, bucket bindings, and account-local config out of commits.

For local development:

```bash
npm run dev
```

Before opening a PR for Worker changes, run:

```bash
npm run type-check
npm test
npm audit --audit-level=high
```

## SDK Development

```bash
cd sdk
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run tests with:

```bash
ruff check src tests
mypy src
pytest tests/ -q
```

## MCP Server Development

```bash
cd mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ../sdk
pip install -e ".[dev]"
ruff check src tests
mypy src
pytest tests/ -q
```

## Code Style

- Match the existing layout and naming in the package you touch.
- Keep TypeScript imports explicit and consistent with the current ESM setup.
- Keep Python code typed; add docstrings for public SDK behavior when needed.
- Prefer small, targeted changes over broad refactors.
- Add or update Vitest tests for Worker changes and `pytest` tests for SDK changes.
- Update README / package README / CHANGELOG entries when public behavior, setup, or response shapes change.

## Pull Requests

1. Create a branch from `main`.
2. Make the smallest change that resolves the issue.
3. Run the relevant checks:
   - `cd worker && npm audit --audit-level=high && npm run type-check && npm test`
   - `ruff check sdk/src sdk/tests examples && mypy --config-file sdk/pyproject.toml sdk/src && pytest -q sdk/tests`
   - `ruff check mcp-server/src mcp-server/tests && mypy --config-file mcp-server/pyproject.toml mcp-server/src && pytest -q mcp-server/tests`
4. Update docs if setup, behavior, or API usage changed.
5. Open a PR with a clear summary, linked issue, and test notes.
