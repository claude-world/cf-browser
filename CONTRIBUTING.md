# Contributing

## Scope

This repo has two main contributor surfaces:

- `worker/`: Cloudflare Worker proxy built with TypeScript, Hono, Wrangler, and Vitest
- `sdk/`: Python SDK built with `httpx`, `pydantic`, `pytest`, and `respx`
- `mcp-server/`: FastMCP wrapper around the SDK with its own pytest suite

Keep changes focused, add or update tests for behavior changes, and avoid committing secrets or generated credentials.

## Prerequisites

- Node.js 18+
- Python 3.10+
- Cloudflare account and `wrangler login` if you are working on deployed Worker behavior

## Worker Development

```bash
cd worker
npm install
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
pytest tests/ -v
```

## MCP Server Development

```bash
cd mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ../sdk
pip install -e ".[dev]"
pytest tests/ -v
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
   - `cd worker && npm run type-check && npm test`
   - `cd sdk && pytest tests/ -v`
   - `cd mcp-server && pytest tests/ -v`
4. Update docs if setup, behavior, or API usage changed.
5. Open a PR with a clear summary, linked issue, and test notes.
