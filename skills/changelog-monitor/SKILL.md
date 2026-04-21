---
name: changelog-monitor
description: Monitor release notes and changelogs from any software project via its web page
user_invocable: true
---

# Changelog Monitor

Track releases, changelogs, and breaking changes from any software project's web page.

## Prerequisites

CF Browser MCP server must be configured in `.mcp.json` (see [quick start](../../README.md#quick-start)).

## Why This Skill?

GitHub releases, framework changelogs, and library docs are often JS-rendered pages that `WebFetch` can't read. This skill uses `browser_json` to extract structured release data from any page.

## Workflow

### Step 1: Determine Source

From the user's input, resolve the changelog URL:
- GitHub project → `https://github.com/{owner}/{repo}/releases`
- npm package → `https://github.com/{owner}/{repo}/releases` (resolve via npm registry)
- Direct URL → use as-is (e.g., `https://nextjs.org/blog`)
- "latest changes to X" → search for the project's releases page

### Step 2: Extract Releases

```
browser_json(url, prompt="Extract the latest N releases with version, date, and key changes as JSON array")
```

For changelog pages (non-GitHub):
```
browser_json(url, prompt="Extract version entries with version number, release date, and list of changes")
```

### Step 3: Analyze

For each release:
- Flag **breaking changes** (look for "BREAKING", "migration", "deprecated")
- Flag **security fixes** (look for "CVE", "security", "vulnerability")
- Categorize changes: features, fixes, performance, deps
- Note if any changes affect the user's project (if context available)

### Step 4: Report

Output a structured summary:

```markdown
## {Project} — Latest Releases

### v2.1.74 (2026-03-12)
- **NEW**: Added `autoMemoryDirectory` setting
- **FIX**: Fixed memory leak in streaming API response buffers
- Action needed: None

### v2.1.73 (2026-03-11)
- **NEW**: Added `modelOverrides` setting
- **FIX**: Fixed freezes and 100% CPU loops
- Action needed: Update recommended (stability fix)

### v2.1.72 (2026-03-10)
- **NEW**: Tool search bypasses third-party proxy gate
- Action needed: None
```

## Parameters

- `url` or `project` (required): GitHub repo, npm package name, or direct changelog URL
- `count` (optional, default=5): Number of releases to fetch
- `watch` (optional): If set, compare against last known version and highlight new releases

## Examples

```
"What's new in Claude Code?"
→ browser_json("https://github.com/anthropics/claude-code/releases") → structured summary

"Check for breaking changes in Next.js 15"
→ browser_json("https://nextjs.org/blog") → filter breaking changes

"Latest Hono releases"
→ browser_json("https://github.com/honojs/hono/releases") → version + changes

"Has Astro released anything since 5.18?"
→ Extract releases → filter versions > 5.18
```
