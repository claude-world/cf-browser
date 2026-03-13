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

### Step 2: Quick Analysis from Crawl Data

The crawl results already include per-page `metadata` with title, OG tags, and HTTP status.
Parse these first — this covers 80% of SEO checks with zero extra API calls:
- `metadata.title` → check for missing/duplicate titles
- `metadata.og:title`, `og:description`, `og:image` → check OG completeness
- `metadata.status` → identify 4xx/5xx error pages
- `metadata.url` → detect redirect chains (final URL != original)

### Step 3: Deep Scrape (only pages with issues)

For pages where crawl metadata is insufficient, use `browser_scrape` to extract:
- `h1`, `h2`, `h3` headings (hierarchy check)
- `img` tags (check alt attributes)
- `link[rel="canonical"]` canonical URL
- `meta[name="robots"]` directives
- `meta[name="description"]` (if not in crawl metadata)

Batch scrape in groups of 5 to respect rate limits.

### Step 4: Check Links

Using `browser_links` on 3-5 key pages (homepage, major sections):
- Categorize: internal, external, resource
- Cross-reference with crawl results to find orphan pages
- Identify links pointing to 4xx/5xx pages found in Step 2

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
