---
name: content-extractor
description: Extract structured content from web pages using CF Browser MCP tools
user_invocable: true
---

# Content Extractor

Extract content from JavaScript-rendered web pages using CF Browser MCP tools.

## Prerequisites

CF Browser MCP server must be configured in `.mcp.json` (see [setup guide](../../README.md#setup)).

## Modes

Analyze the user's intent and select the appropriate mode:

### Mode 1: Read Page Content
**Trigger**: "read this page", "get content from", "what does X say"
**Tool**: `browser_markdown`
**Workflow**:
1. Call `browser_markdown` with the URL
2. Clean the markdown (remove navigation, footer boilerplate)
3. Return formatted content with source attribution

### Mode 2: Extract Structured Data
**Trigger**: "extract products", "get prices", "pull data from"
**Tool**: `browser_json`
**Workflow**:
1. Determine extraction prompt from user intent
2. Call `browser_json` with URL and extraction prompt
3. Format and return structured JSON

### Mode 3: Scrape Specific Elements
**Trigger**: "get the headlines", "extract article titles", "find all images"
**Tool**: `browser_scrape`
**Workflow**:
1. Determine CSS selectors from user intent
2. Call `browser_scrape` with URL and selectors array
3. Post-process and return results

### Mode 4: Discover Links
**Trigger**: "find all links", "list pages on", "discover URLs"
**Tool**: `browser_links`
**Workflow**:
1. Call `browser_links` with the URL
2. Filter/categorize links (internal, external, resource)
3. Return organized link list

### Mode 5: Visual Capture
**Trigger**: "screenshot", "show me what X looks like", "capture page"
**Tool**: `browser_screenshot`
**Workflow**:
1. Call `browser_screenshot` with URL and optional viewport dimensions
2. Return file path to saved PNG
3. Read the image to show the user

## Output Format

- For text: Clean markdown with source URL attribution
- For data: JSON with clear field names
- For images: File path + display
- Truncate if output exceeds 50K characters

## Examples

```
"Read the Hono documentation homepage"
→ browser_markdown("https://hono.dev")

"Extract all pricing tiers from Vercel"
→ browser_json("https://vercel.com/pricing", prompt="Extract all pricing tiers with name, price, and features")

"Get all h2 headings from this blog post"
→ browser_scrape("https://example.com/blog/post", selectors=["h2"])

"Screenshot the landing page at mobile width"
→ browser_screenshot("https://example.com", width=375, height=812)
```
