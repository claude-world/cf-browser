# cf-browser-mcp

MCP Server with 15 browser tools for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — powered by [Cloudflare Browser Rendering](https://developers.cloudflare.com/browser-rendering/).

## Installation

```bash
pip install cf-browser-mcp
```

## Setup

Add to your `.mcp.json`. Two modes are supported:

| Mode | Available tools | Best for |
|------|-----------------|----------|
| Direct Mode | 10 read-only tools | Personal use, no Worker deployment |
| Worker Mode | All 15 tools | Teams, cached usage, browser interaction |

### Direct Mode (no Worker needed)

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_ACCOUNT_ID": "your-cloudflare-account-id",
        "CF_API_TOKEN": "your-cloudflare-api-token"
      }
    }
  }
}
```

### Worker Mode (via deployed Cloudflare Worker)

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_BROWSER_URL": "https://cf-browser.YOUR-SUBDOMAIN.workers.dev",
        "CF_BROWSER_API_KEY": "your-api-key"
      }
    }
  }
}
```

## Tools

### Read-Only Tools

| Tool | Description |
|------|-------------|
| `browser_markdown` | Convert page to clean Markdown |
| `browser_content` | Get fully rendered HTML |
| `browser_screenshot` | Take a PNG screenshot |
| `browser_pdf` | Generate PDF |
| `browser_scrape` | Extract elements by CSS selector as `{"elements":[...]}` |
| `browser_json` | AI-powered data extraction |
| `browser_links` | Extract normalized `{href, text}` link objects |
| `browser_a11y` | Accessibility-oriented snapshot with screenshot stripped |
| `browser_crawl` | Start async multi-page crawl and return `{job_id, status}` |
| `browser_crawl_status` | Check crawl progress |

### Interaction Tools (Worker Mode only)

| Tool | Description |
|------|-------------|
| `browser_click` | Click an element on a page |
| `browser_type` | Type text into an input field |
| `browser_evaluate` | Execute JavaScript and return result |
| `browser_interact` | Execute a chain of browser actions |
| `browser_submit_form` | Fill and submit a form |

All tools accept optional `cookies` and `headers` for authenticated scraping. Most read-only tools also accept `wait_for`, `wait_until`, and `user_agent`.

## Troubleshooting

- Interaction tools return `501`: your Worker is missing the `BROWSER` binding.
- Interaction tools return `404`: your Worker deployment is stale. Redeploy from the current repo and confirm `/health` reports `version: "2.0.1"`.
- `browser_scrape` or `browser_links` responses differ between environments: the MCP server normalizes legacy response shapes, but redeploying the Worker keeps every layer consistent.

## Requirements

- Python 3.10+
- **Direct Mode**: Cloudflare Account ID + API Token
- **Worker Mode**: A deployed [CF Browser Worker](https://github.com/claude-world/cf-browser)

## License

[MIT](https://github.com/claude-world/cf-browser/blob/main/LICENSE)
