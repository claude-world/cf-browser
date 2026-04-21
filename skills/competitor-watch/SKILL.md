---
name: competitor-watch
description: Extract and compare structured data from competitor or benchmark websites
user_invocable: true
---

# Competitor Watch

Extract and compare structured data from multiple websites side-by-side.

## Prerequisites

CF Browser MCP server must be configured in `.mcp.json` (see [quick start](../../README.md#quick-start)).

## Why This Skill?

Pricing pages, feature matrices, and product comparisons are almost always JS-rendered. This skill uses `browser_json` and `browser_scrape` to extract structured data from multiple competitor pages, then generates a comparison.

## Workflow

### Step 1: Identify Pages

From user input, determine:
- Which competitors/products to compare
- What data points to extract (pricing, features, limits, etc.)
- Resolve URLs (homepage, pricing page, docs, etc.)

### Step 2: Extract Data (Parallel)

For each competitor page, use the most appropriate tool:

**Pricing data:**
```
browser_json(url, prompt="Extract all pricing tiers with: plan name, monthly price, annual price, key features, and limits")
```

**Feature comparison:**
```
browser_json(url, prompt="Extract all features with: feature name, availability (yes/no/limited), and any limits or quotas")
```

**General product info:**
```
browser_scrape(url, selectors=["h1", ".pricing-card", ".feature-list", "[class*=plan]"])
```

### Step 3: Normalize

Align extracted data into a consistent schema:
- Standardize plan names (Free/Pro/Enterprise)
- Convert currencies if needed
- Unify feature naming across competitors
- Handle missing data points (mark as "N/A" or "Not listed")

### Step 4: Compare & Report

Output a markdown comparison table:

```markdown
## Competitor Comparison — {Category}

| | Competitor A | Competitor B | Competitor C |
|---|---|---|---|
| Free tier | 1K requests | 500 requests | None |
| Pro price | $20/mo | $25/mo | $19/mo |
| API rate limit | 100 req/s | 50 req/s | Unlimited |
| Key differentiator | Best DX | Most features | Cheapest |

### Key Insights
- Competitor A leads on developer experience
- Competitor B has the most comprehensive free tier
- Price range: $19-25/mo for pro plans
```

## Parameters

- `urls` (required): List of competitor URLs or product names
- `focus` (optional): What to compare — "pricing", "features", "limits", "all"
- `prompt` (optional): Custom extraction prompt for specific data points

## Examples

```
"Compare Vercel vs Netlify vs Cloudflare Pages pricing"
→ browser_json on each /pricing page → normalized comparison table

"What features does Cursor have that Copilot doesn't?"
→ Extract feature lists from both → diff analysis

"Compare the free tiers of Supabase, Firebase, and PlanetScale"
→ Extract pricing/limits → free tier comparison

"How does our pricing compare to competitors?"
→ Extract your pricing page + competitors → gap analysis
```
