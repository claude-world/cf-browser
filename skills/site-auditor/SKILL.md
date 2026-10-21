---
name: site-auditor
description: Audit website SEO, links, and accessibility using Cloudflare Browser Run
user-invocable: true
---

# Site Auditor

Comprehensive website audit for SEO, broken links, and accessibility.

## Prerequisites

CF Browser MCP server must be configured (see the [CF Browser quick start](https://github.com/claude-world/cf-browser#quick-start)).

## Workflow

### Step 1: Crawl Site

```
browser_crawl(url, limit=50)
→ browser_crawl_status(job_id, wait=True)
→ Get list of all discovered pages
```

### Step 2: Quick Analysis from Crawl Data

The crawl records include URL, record status, and page metadata such as final URL, title, and HTTP status. Parse only fields actually present before making extra calls:
- `metadata.title` → check for missing/duplicate titles
- `metadata.status` → identify 4xx/5xx error pages
- `metadata.url` versus record URL → identify a final-URL change; do not claim a full redirect chain without separate evidence

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
- Identify links pointing to 4xx/5xx pages already evidenced by crawl records
- Treat external links as unverified until each destination is separately fetched or checked

### Step 5: Generate Report

Output a markdown report with sections:

#### SEO Issues
- Missing or duplicate `<title>` tags
- Missing or duplicate meta descriptions
- Missing h1 or multiple h1 tags
- Missing canonical URLs
- Missing OpenGraph tags

#### Link Health
- Broken internal links (404s)
- Broken external links (only when separately verified)
- Redirect chains (only when hop-by-hop evidence is available)
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
