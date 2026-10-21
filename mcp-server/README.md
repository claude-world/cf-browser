# cf-browser-mcp

FastMCP server exposing **17 Cloudflare Browser Run tools** (formerly Browser Rendering) to Claude Code and other MCP clients.

## Install

```bash
python -m pip install cf-browser-mcp
```

## Configure

Set `CF_BROWSER_MODE` explicitly when both credential pairs might exist.

| Mode | Credentials | Tools |
|---|---|---|
| `direct` | `CF_ACCOUNT_ID`, `CF_API_TOKEN` | 12 read/crawl tools |
| `worker` | `CF_BROWSER_URL`, `CF_BROWSER_API_KEY` | All 17 tools |

Use environment expansion so secrets do not live in a project file:

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_BROWSER_MODE": "${CF_BROWSER_MODE}",
        "CF_BROWSER_URL": "${CF_BROWSER_URL}",
        "CF_BROWSER_API_KEY": "${CF_BROWSER_API_KEY}"
      }
    }
  }
}
```

For Direct mode, replace the two Worker variables with `CF_ACCOUNT_ID` and `CF_API_TOKEN`. If both complete credential pairs exist and no mode is selected, startup fails instead of silently choosing one.

## Tools

Read/crawl tools:

- `browser_content`, `browser_markdown`, `browser_screenshot`, `browser_pdf`
- `browser_snapshot`, `browser_scrape`, `browser_json`, `browser_links`, `browser_a11y`
- `browser_crawl`, `browser_crawl_status`, `browser_delete_crawl`

Worker interaction tools:

- `browser_click`, `browser_type`, `browser_evaluate`
- `browser_interact`, `browser_submit_form`

MCP input schemas accept real arrays/objects for cookies, headers, HTTP Basic authentication, actions, fields, script/style tags, and JSON response schemas. JSON-encoded strings remain accepted for compatibility. Read and interaction tools expose page controls consistently; crawls include `cache_ttl`, depth, formats, Content Signals purposes, freshness filters, URL patterns, JSON options, and rendered controls. Full `goto_options`, `wait_for_selector`, and `viewport` objects are available alongside flattened conveniences, with ambiguous combinations rejected. Static mode rejects browser-only options; crawl status accepts string or non-negative integer cursors and current record filters.

Screenshot and PDF results are written with unpredictable names into a process-private directory. Paths exclude URL credentials, files use mode `0600`, quotas prevent unbounded accumulation, and the directory is removed when the MCP process exits.

## Troubleshooting

- Interaction returns 501: enable the Worker `BROWSER` binding.
- Interaction returns 404: redeploy the current Worker; `/health` should report `2.1.0`.
- Startup reports ambiguous credentials: set `CF_BROWSER_MODE=direct` or `worker`.
- Crawl wait returns a failed JSON status only for terminal crawl states; transport/auth errors remain typed errors instead of being mislabeled as job failures.

See the [project README](https://github.com/claude-world/cf-browser#readme) for setup and the complete API contract.

## License

[MIT](https://github.com/claude-world/cf-browser/blob/main/LICENSE)
