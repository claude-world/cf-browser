---
name: visual-qa
description: Multi-viewport visual QA — screenshot pages at multiple device sizes and compare
user_invocable: true
---

# Visual QA

Automated visual quality assurance using multi-viewport screenshots.

## Prerequisites

CF Browser MCP server must be configured in `.mcp.json` (see [quick start](../../README.md#quick-start)).

## Workflow

### Step 1: Determine Target Pages

From user input, determine which pages to check:
- Single URL: screenshot that page
- Site URL: use `browser_links` to discover key pages (homepage, about, pricing, etc.), cap at 10
- URL list: use provided list directly

### Step 2: Define Viewports

Default viewports (user can override):

| Name | Width | Height | Device |
|------|-------|--------|--------|
| mobile | 375 | 812 | iPhone 14 |
| tablet | 768 | 1024 | iPad |
| laptop | 1280 | 800 | 13" laptop |
| desktop | 1920 | 1080 | Full HD monitor |

### Step 3: Capture Screenshots

For each page + viewport combination:
```
browser_screenshot(url, width=W, height=H)
→ Save PNG to screenshots/{page-slug}/{viewport-name}.png
```

Process in batches to respect rate limits (4 viewports per page, pause between pages).

### Step 4: Visual Review

For each screenshot:
1. Read the saved PNG image
2. Check for visual issues:
   - Layout broken or overlapping elements
   - Text overflow or truncation
   - Missing images or icons
   - Horizontal scrollbar on mobile
   - Navigation menu issues
   - Footer alignment

### Step 5: Generate Report

Output a markdown report:

```markdown
## Visual QA Report — {domain}
**Date**: {timestamp}
**Pages checked**: N
**Viewports**: mobile (375), tablet (768), laptop (1280), desktop (1920)

### Page: /
- mobile: OK
- tablet: WARNING — hero image overflows container
- laptop: OK
- desktop: OK

### Page: /pricing
- mobile: ISSUE — pricing table requires horizontal scroll
- tablet: OK
- laptop: OK
- desktop: OK

### Summary
- Total screenshots: N
- Issues found: M
- Warnings: W
```

## Parameters

- `url` (required): Page URL or site base URL
- `viewports` (optional): Custom viewport list, default is mobile/tablet/laptop/desktop
- `pages` (optional): Specific page paths to check
- `full_page` (optional, default=false): Capture full scrollable page

## Examples

```
"QA check our homepage on all devices"
→ 4 viewport screenshots of homepage + visual review

"Check the pricing page on mobile and desktop"
→ 2 viewport screenshots + review

"Visual QA the entire site after deploy"
→ Discover pages via browser_links → screenshot each at 4 viewports → report

"Full-page screenshot of the docs"
→ browser_screenshot(url, full_page=True) at each viewport
```
