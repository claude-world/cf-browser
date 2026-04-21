---
name: doc-fetcher
description: Fetch external documentation sites and convert to local markdown for context
user_invocable: true
---

# Doc Fetcher

Fetch and convert external documentation to local markdown files for use as context (RAG, reference, etc.).

## Prerequisites

CF Browser MCP server must be configured in `.mcp.json` (see [quick start](../../README.md#quick-start)).

## Workflow

### Step 1: Discover Pages

```
browser_links(base_url) → list of all linked pages
```
- Filter to same-domain URLs only
- Filter by documentation patterns (e.g., /docs/, /guide/, /api/, /reference/)
- Cap at `max_pages` (default 20)

### Step 2: Fetch Content

For each discovered page:
```
browser_markdown(page_url) → markdown content
```
Process pages in parallel where possible (batch of 5).

### Step 3: Clean Content

For each page:
- Strip navigation headers/sidebars
- Remove footer boilerplate
- Remove cookie banners and ads
- Preserve code blocks and tables

### Step 4: Save to Disk

Save to `docs/{source_domain}/`:
```
docs/
└── docs.astro.build/
    ├── index.md          ← Table of contents
    ├── getting-started.md
    ├── routing.md
    └── components.md
```

### Step 5: Generate Index

Create `index.md` with:
- Source URL and fetch timestamp
- Table of contents with links to each file
- Total page count and approximate token count

### Step 6: Report

Output summary:
- Pages fetched successfully
- Total approximate token count
- Key topics covered
- Any failed pages

## Parameters

- `url` (required): Base URL of documentation site
- `max_pages` (optional, default=20): Maximum pages to fetch
- `output_dir` (optional, default="docs/{domain}"): Where to save files
- `patterns` (optional): URL patterns to include (e.g., "/docs/", "/api/")

## Examples

```
"Fetch the Hono documentation"
→ browser_links("https://hono.dev") → filter /docs/ → browser_markdown each → save

"Download Cloudflare Workers docs for reference"
→ browser_links("https://developers.cloudflare.com/workers/") → fetch up to 20 pages

"Index the Astro guide for RAG"
→ browser_links("https://docs.astro.build/") → fetch + clean + save with index
```
