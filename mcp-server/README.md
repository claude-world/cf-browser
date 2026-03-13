# cf-browser-mcp

MCP Server with 10 browser tools for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — powered by [Cloudflare Browser Rendering](https://developers.cloudflare.com/browser-rendering/).

## Installation

```bash
pip install cf-browser-mcp
```

## Setup

Add to your `.mcp.json`:

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

| Tool | Description |
|------|-------------|
| `browser_markdown` | Convert page to clean Markdown |
| `browser_content` | Get fully rendered HTML |
| `browser_screenshot` | Take a PNG screenshot |
| `browser_pdf` | Generate PDF |
| `browser_scrape` | Extract elements by CSS selector |
| `browser_json` | AI-powered data extraction |
| `browser_links` | Extract all hyperlinks |
| `browser_a11y` | Accessibility tree (low token cost) |
| `browser_crawl` | Start async multi-page crawl |
| `browser_crawl_status` | Check crawl progress |

All tools accept optional `cookies` and `headers` for authenticated scraping.

## Requirements

- Python 3.10+
- A deployed [CF Browser Worker](https://github.com/claude-world/cf-browser)

## License

[MIT](https://github.com/claude-world/cf-browser/blob/main/LICENSE)
