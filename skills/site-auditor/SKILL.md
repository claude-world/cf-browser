---
name: site-auditor
description: Audit website SEO, links, and accessibility using CF Browser Rendering
user_invocable: true
---

# Site Auditor

Comprehensive website audit for SEO, broken links, and accessibility.

## Prerequisites

CF Browser MCP server must be configured in `.mcp.json` (see [setup guide](../../README.md#setup)).

## Workflow

### Step 1: Crawl Site

```
browser_crawl(url, limit=50)
→ browser_crawl_status(job_id, wait=True)
→ Get list of all discovered pages
```

### Step 2: Analyze Each Page

For each page (batch in groups of 5), use `browser_scrape` to extract:
- `title` tag
- `meta[name="description"]` content
- `h1`, `h2`, `h3` headings
- `img` tags (check alt attributes)
- `meta[property^="og:"]` OpenGraph tags
- `link[rel="canonical"]` canonical URL
- `meta[name="robots"]` directives

### Step 3: Check Links

Using `browser_links` on key pages:
- Categorize: internal, external, resource
- Identify potential broken links (relative URLs with no target)
- Detect redirect chains
- Find orphan pages (not linked from any other page)

### Step 4: Generate Report

Output a markdown report with sections:

#### SEO Issues
- Missing or duplicate `<title>` tags
- Missing or duplicate meta descriptions
- Missing h1 or multiple h1 tags
- Missing canonical URLs
- Missing OpenGraph tags

#### Link Health
- Broken internal links (404s)
- Broken external links
- Redirect chains (>2 hops)
- Orphan pages

#### Accessibility
- Images without alt text
- Missing form labels
- Missing lang attribute

#### Structure
- Sitemap coverage
- Page depth analysis
- URL structure issues

Each issue includes:
- **Severity**: Critical / Warning / Info
- **Page**: URL where issue was found
- **Fix**: Specific action to take

## Output

Markdown report saved to `audit-report-{domain}-{date}.md` in the current directory.

## Examples

```
"Audit my website for SEO issues"
→ Crawl + analyze + generate full report

"Check for broken links on docs.example.com"
→ Crawl + link check only

"Review OpenGraph tags across the site"
→ Crawl + extract OG tags + report missing ones
```
