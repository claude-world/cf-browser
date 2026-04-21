# CF Browser

> 開源工具，為 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 提供 **15 個 MCP 工具 + 6 個即用 Skill**，支援 JavaScript 渲染的網頁與瀏覽器互動。

**[English README](README.md)**

Claude Code 內建的 `WebFetch` 只能取得原始 HTML — 單頁應用程式（SPA）、動態內容和 JS 渲染的頁面都會回傳空白。CF Browser 透過 [Cloudflare Browser Rendering](https://developers.cloudflare.com/browser-rendering/) 解決這個問題，支援兩種模式：**直連模式**（免部署，唯讀）和 **Worker 模式**（含快取、限流與瀏覽器互動）。

## 架構

```
                          ┌─────────────────────┐
                          │     Claude Code      │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │ MCP Server（15 個工具）│
                          └──────────┬───────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                  │
              直連模式                           Worker 模式
            (CF_ACCOUNT_ID                     (CF_BROWSER_URL
             + CF_API_TOKEN)                    + CF_BROWSER_API_KEY)
                    │                                  │
                    │                    ┌─────────────▼──────────────┐
                    │                    │   Cloudflare Worker        │
                    │                    │  ├── 認證（timing-safe）    │
                    │                    │  ├── 速率限制（KV）         │
                    │                    │  └── 快取（KV + R2）        │
                    │                    └─────────────┬──────────────┘
                    │                                  │
                    └────────────────┬─────────────────┘
                                     │
                          ┌──────────▼───────────┐
                          │ CF Browser Rendering │
                          │   API（無頭 Chrome）  │
                          └──────────────────────┘
```

| 套件 | 語言 | 用途 |
|------|------|------|
| `worker/` | TypeScript (Hono) | Edge 代理，含認證、快取、速率限制與瀏覽器互動 |
| `sdk/` | Python (httpx) | 非同步客戶端函式庫 |
| `mcp-server/` | Python (FastMCP) | 15 個 MCP 工具供 Claude Code 使用 |

## MCP 工具

### 唯讀工具（直連 + Worker 模式）

| 工具 | 輸入 | 輸出 | 使用情境 |
|------|------|------|----------|
| `browser_markdown` | url | Markdown | 將任何網頁轉為乾淨的文字 |
| `browser_content` | url | HTML | 取得完整渲染的 HTML（JS 已執行） |
| `browser_screenshot` | url, width, height | PNG 檔案 | 視覺驗證、多裝置測試 |
| `browser_pdf` | url, format | PDF 檔案 | 產生報告、封存頁面 |
| `browser_scrape` | url, selectors[] | `{"elements":[...]}` | 以 CSS 選擇器擷取特定元素並正規化結果 |
| `browser_json` | url, prompt | JSON | AI 驅動的結構化資料擷取 |
| `browser_links` | url | `[{href, text}]` | 發現頁面上所有超連結 |
| `browser_a11y` | url | JSON | 無障礙導向快照，已移除截圖資料 |
| `browser_crawl` | url, limit | `{"job_id","status"}` | 啟動非同步多頁面爬取 |
| `browser_crawl_status` | job_id, wait | JSON | 輪詢或等待爬取結果 |

### 互動工具（僅 Worker 模式 — 需要 BROWSER 綁定）

| 工具 | 輸入 | 輸出 | 使用情境 |
|------|------|------|----------|
| `browser_click` | url, selector | JSON | 點擊按鈕/連結，取得結果頁面 |
| `browser_type` | url, selector, text | JSON | 在輸入框中輸入文字 |
| `browser_evaluate` | url, script | JSON | 執行 JavaScript 並取得回傳值 |
| `browser_interact` | url, actions[] | JSON | 串接多個動作（點擊、輸入、等待、截圖等） |
| `browser_submit_form` | url, fields | JSON | 一次填寫並提交表單 |

所有工具都接受可選的 `cookies`、`headers`、`wait_for`、`wait_until` 和 `user_agent` 參數。對 SPA 網站（React、Next.js、X/Twitter）使用 `wait_until="networkidle0"` 確保完整渲染。

### 在 Claude Code 中可以這樣問

```
「幫我讀 React 19 遷移指南」
→ browser_markdown("https://react.dev/blog/2024/12/05/react-19")

「我們首頁在手機上長怎樣？」
→ browser_screenshot("https://example.com", width=375, height=667)

「擷取前 5 個產品的名稱、價格和評分」
→ browser_json("https://example.com/products", prompt="Extract top 5 products...")

「取得頁面結構做無障礙分析」
→ browser_a11y("https://example.com")

「擷取需要登入的儀表板」
→ browser_markdown("https://app.example.com/dashboard", cookies='[{"name":"session","value":"abc"}]')

「檢查我們網站有沒有壞掉的連結」
→ browser_crawl("https://example.com", limit=50) + browser_crawl_status(job_id, wait=True)

「登入測試環境並檢查儀表板」
→ browser_interact("https://staging.example.com/login", actions=[
    {"action":"type", "selector":"#email", "text":"admin@example.com"},
    {"action":"type", "selector":"#password", "text":"secret"},
    {"action":"click", "selector":"button[type=submit]"},
    {"action":"wait", "selector":".dashboard"},
    {"action":"screenshot"}
  ])

「填寫聯絡表單」
→ browser_submit_form("https://example.com/contact",
    fields={"#name":"Claude", "#email":"claude@example.com", "#message":"你好！"},
    submit_selector="button.submit")
```

## 安裝設定

兩種使用方式 — 選適合你的：

| | 直連模式 | Worker 模式 |
|---|---|---|
| **設定** | `pip install` + 2 個環境變數 | 部署 Worker + `pip install` |
| **上手時間** | 2 分鐘 | 10 分鐘 |
| **需要什麼** | CF Account ID + API Token | Worker + KV + R2 |
| **可用工具** | 10 個唯讀工具 | 完整 15 個工具 |
| **快取** | 無 | KV + R2（省 ~70% API 配額） |
| **速率限制** | 無 | 每 key 60 req/min |
| **多用戶** | 否（共用你的 CF 憑證） | 是（每個用戶獨立 API key） |
| **適合** | 個人使用、快速上手 | 團隊、生產環境、高流量 |

### 方案 A：直連模式（免部署 Worker）

直接呼叫 Cloudflare Browser Rendering API — 不需要部署任何東西。

```bash
pip install cf-browser cf-browser-mcp
```

在你專案的 `.mcp.json` 加入：

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_ACCOUNT_ID": "<你的帳號-ID>",
        "CF_API_TOKEN": "<你的-API-Token>"
      }
    }
  }
}
```

取得憑證：
- **Account ID**：`wrangler whoami` 或 [Cloudflare Dashboard](https://dash.cloudflare.com) → 任意域名 → 概覽 → 右側欄
- **API Token**：[dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens) → 建立 Token → 使用「編輯 Cloudflare Workers」模板

重啟 Claude Code 後，10 個唯讀工具可立即使用；另外 5 個互動工具需要 Worker 模式。

### 方案 B：Worker 模式（含快取與限流）

部署 Worker 作為 Edge 代理。

```bash
git clone https://github.com/claude-world/cf-browser.git
cd cf-browser
bash setup.sh
```

<details>
<summary>展開手動部署步驟</summary>

### 方案 B（手動）：自行部署 Worker（5 分鐘）

#### 前置需求

- Node.js 18+、Python 3.10+
- 已啟用 [Browser Rendering](https://developers.cloudflare.com/browser-rendering/) 的 Cloudflare 帳號
- `wrangler` CLI（`npm i -g wrangler && wrangler login`）

#### 步驟 1：部署 Worker

```bash
git clone https://github.com/claude-world/cf-browser.git
cd cf-browser/worker
cp wrangler.toml.example wrangler.toml
npm install
```

建立資源並將 namespace ID 貼入 `wrangler.toml`：

```bash
wrangler kv namespace create CACHE
wrangler kv namespace create RATE_LIMIT
wrangler r2 bucket create cf-browser-storage
```

設定密鑰：

```bash
# 帳號 ID（透過 wrangler whoami 查看）
wrangler secret put CF_ACCOUNT_ID

# API token — 在 https://dash.cloudflare.com/profile/api-tokens 建立
# 所需權限：帳戶 → Workers 瀏覽器轉譯 → 編輯
wrangler secret put CF_API_TOKEN

# 產生客戶端 API key（記下來，.mcp.json 會用到）
echo "$(openssl rand -hex 32)" | wrangler secret put API_KEYS
```

部署：

```bash
wrangler deploy
# → https://cf-browser.<your-subdomain>.workers.dev
```

驗證：

```bash
curl https://cf-browser.<your-subdomain>.workers.dev/health
# {"status":"ok","version":"2.0.1","capabilities":{"interact":false}}
```

#### 步驟 2：安裝 SDK + MCP Server

```bash
cd ../sdk && pip install -e .
cd ../mcp-server && pip install -e .
```

#### 步驟 3：註冊 MCP

在你專案的 `.mcp.json` 加入：

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_BROWSER_URL": "https://cf-browser.<your-subdomain>.workers.dev",
        "CF_BROWSER_API_KEY": "<你產生的-api-key>"
      }
    }
  }
}
```

重啟 Claude Code — 15 個 `browser_*` 工具即可使用。

</details>

## Worker API 參考

所有路由（除了 `/health`）都需要 `Authorization: Bearer <api-key>` 標頭。

### 端點

| 路由 | 方法 | 請求體 | 快取 | 回應 |
|------|------|--------|------|------|
| `/health` | GET | — | — | `{"status":"ok","version":"2.0.1","capabilities":{"interact":...}}` |
| `/content` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 1hr | HTML |
| `/markdown` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 1hr | Markdown |
| `/screenshot` | POST | `{url, width?, height?, full_page?, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | R2 24hr | PNG |
| `/pdf` | POST | `{url, format?, landscape?, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | R2 24hr | PDF |
| `/snapshot` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 30min | JSON |
| `/scrape` | POST | `{url, elements[], wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 30min | `{"elements":[...]}` |
| `/json` | POST | `{url, prompt, schema?, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | 無 | JSON |
| `/links` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 1hr | `[{href, text}]` |
| `/a11y` | POST | `{url, wait_for?, wait_until?, user_agent?, cookies?, headers?, no_cache?}` | KV 5min | `{"type":"accessibility_snapshot", ...}` |
| `/crawl` | POST | `{url, limit?, user_agent?, cookies?, headers?, no_cache?}` | — | `{"job_id":"..."}` |
| `/crawl/:id` | GET | — | R2 | JSON |
| `/crawl/:id` | DELETE | — | — | 204 |
| `/click` | POST | `{url, selector, wait_for?, ...}` | 無 | JSON |
| `/type` | POST | `{url, selector, text, clear?, ...}` | 無 | JSON |
| `/evaluate` | POST | `{url, script, ...}` | 無 | JSON |
| `/interact` | POST | `{url, actions[], ...}` | 無 | JSON |
| `/submit-form` | POST | `{url, fields, submit_selector?, ...}` | 無 | JSON |

互動路由（`/click`、`/type`、`/evaluate`、`/interact`、`/submit-form`）需要 `BROWSER` 綁定。未設定時回傳 501。若這些路由回傳 404，表示你目前指向的是舊版 Worker，請重新部署並確認 `/health` 顯示 `version: "2.0.1"`。

目前 Worker、SDK 與 MCP 會統一正規化以下回應格式：

- `/scrape` 會回傳 `{"elements":[{"selector":"...", "results":[...]}]}`。
- `/links` 會回傳 `{href, text}` 物件陣列；若上游只有字串 URL，會自動補成 `{href, text: null}`。
- `/a11y` 來自 `/snapshot`，會移除 base64 截圖並加上 `type: "accessibility_snapshot"`。

### 請求範例

```bash
# 取得 Markdown
curl -X POST https://cf-browser.example.workers.dev/markdown \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://react.dev"}'

# 自訂視窗大小截圖
curl -X POST https://cf-browser.example.workers.dev/screenshot \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "width": 1280, "height": 720}' \
  -o screenshot.png

# AI 驅動的結構化擷取
curl -X POST https://cf-browser.example.workers.dev/json \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://news.ycombinator.com", "prompt": "Extract top 5 stories with title and score"}'

# 擷取特定元素
curl -X POST https://cf-browser.example.workers.dev/scrape \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "elements": ["h1", ".price", "#main"]}'

# 啟動非同步爬取
curl -X POST https://cf-browser.example.workers.dev/crawl \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "limit": 10}'

# 查詢爬取狀態
curl https://cf-browser.example.workers.dev/crawl/JOB_ID \
  -H "Authorization: Bearer YOUR_KEY"
```

### 快取行為

- 在請求體中設定 `"no_cache": true` 可繞過快取
- 快取命中的回應會包含 `X-Cache: HIT` 標頭
- 文字內容（HTML、Markdown、JSON）→ KV 儲存
- 二進位內容（PNG、PDF）→ R2 儲存
- 完成的爬取結果會持久化到 R2

### 速率限制

- 預設：每個 API key 每分鐘 60 次請求
- 回應標頭：`X-RateLimit-Limit`、`X-RateLimit-Remaining`
- 超過限制：HTTP 429，附帶 `Retry-After` 標頭

## Python SDK

```python
# 直連模式 — 免部署 Worker
from cf_browser import CFBrowserDirect

async with CFBrowserDirect(
    account_id="your-cf-account-id",
    api_token="your-cf-api-token",
) as browser:
    md = await browser.markdown("https://example.com")

# Worker 模式 — 透過已部署的 Worker
from cf_browser import CFBrowser

async with CFBrowser(
    base_url="https://cf-browser.example.workers.dev",
    api_key="your-key",
) as browser:
    # 讀取頁面
    markdown = await browser.markdown("https://react.dev")

    # 截圖
    png_bytes = await browser.screenshot("https://example.com", width=1280, height=720)

    # AI 驅動的擷取
    data = await browser.json_extract(
        "https://news.ycombinator.com",
        prompt="Extract the top 5 stories with title and score",
    )

    # 以 CSS 選擇器擷取
    elements = await browser.scrape("https://example.com", selectors=["h1", ".price"])

    # 非同步爬取
    job_id = await browser.crawl("https://example.com", limit=10)
    result = await browser.crawl_wait(job_id, timeout=120)
```

### SDK 方法

**唯讀（直連 + Worker 模式）：**

| 方法 | 回傳型別 | 說明 |
|------|----------|------|
| `content(url, **opts)` | `str` | 渲染後的 HTML |
| `markdown(url, **opts)` | `str` | 乾淨的 Markdown |
| `screenshot(url, **opts)` | `bytes` | PNG 圖片 |
| `pdf(url, **opts)` | `bytes` | PDF 文件 |
| `snapshot(url, **opts)` | `dict` | HTML + 中繼資料 |
| `scrape(url, selectors, **opts)` | `dict` | 正規化為 `{"elements": [...]}` |
| `json_extract(url, prompt, **opts)` | `dict` | AI 擷取的資料 |
| `links(url, **opts)` | `list[dict]` | 正規化為 `{href, text}` 物件陣列 |
| `a11y(url, **opts)` | `dict` | 無障礙導向快照，已移除截圖資料 |
| `crawl(url, **opts)` | `str` | Job ID |
| `crawl_status(job_id)` | `dict` | 任務狀態 |
| `crawl_wait(job_id, timeout, poll_interval)` | `dict` | 等待完成 |

**互動（僅 Worker 模式）：**

| 方法 | 回傳型別 | 說明 |
|------|----------|------|
| `click(url, selector, **opts)` | `dict` | 點擊元素，回傳頁面狀態 |
| `type_text(url, selector, text, clear?, **opts)` | `dict` | 在輸入框中輸入文字 |
| `evaluate(url, script, **opts)` | `dict` | 執行 JS，回傳結果 |
| `interact(url, actions, **opts)` | `dict` | 串接多個動作 |
| `submit_form(url, fields, submit_selector?, **opts)` | `dict` | 填寫並提交表單 |
| `delete_crawl(job_id)` | `None` | 刪除快取的爬取結果 |

所有方法都接受 `no_cache=True` 來繞過快取、`cookies`/`headers` 來擷取需要登入的頁面、`wait_for` 等待 CSS 選擇器、`wait_until` 設定導航策略（SPA 用 `networkidle0`）、`user_agent` 設定自訂 User-Agent。互動方法在直連模式下會拋出 `NotImplementedError`。若 Worker 模式下互動方法回傳 404，通常代表部署版本過舊，需要重新部署。

## Skills（附贈）

CF Browser 附帶 6 個即用的 [Claude Code Skills](https://docs.anthropic.com/en/docs/claude-code/skills)，放在 `skills/` 目錄。將 skill 資料夾複製到你專案的 `.claude/skills/` 即可啟用。

| Skill | 指令 | 功能 |
|-------|------|------|
| **content-extractor** | `/content-extractor` | 讀取頁面、擷取結構化資料、抓取元素、發現連結 |
| **site-auditor** | `/site-auditor` | 爬取網站並產生 SEO / 連結 / 無障礙審計報告 |
| **doc-fetcher** | `/doc-fetcher` | 將整個文件站抓取為本地 Markdown，供 RAG 使用 |
| **visual-qa** | `/visual-qa` | 多裝置視窗截圖（手機/平板/筆電/桌機）+ 視覺檢查 |
| **changelog-monitor** | `/changelog-monitor` | 追蹤任何專案的版本更新與破壞性變更 |
| **competitor-watch** | `/competitor-watch` | 擷取並比較競爭對手的定價 / 功能 |

### 安裝 Skill

```bash
# 複製單一 skill
cp -r skills/content-extractor .claude/skills/

# 或全部複製
cp -r skills/* .claude/skills/
```

重啟 Claude Code — skill 即可作為斜線指令使用。

### 工作流程範例

```
「讀取 Hono 文件並摘要路由章節」
→ /content-extractor → browser_markdown → 乾淨摘要

「審計 claude-world.com 的 SEO 問題」
→ /site-auditor → 爬取 50 頁 → 擷取 meta 標籤 → Markdown 報告

「下載 Astro 文件做離線參考」
→ /doc-fetcher → 發現 20 頁 → 逐頁 browser_markdown → 儲存到 docs/

「在手機、平板和桌機上 QA 檢查我們的網站」
→ /visual-qa → 每頁 4 種視窗截圖 → 視覺檢查報告

「Claude Code 最近更新了什麼？」
→ /changelog-monitor → 從 GitHub releases 擷取 → 結構化摘要

「比較 Vercel、Netlify、Cloudflare Pages 的定價」
→ /competitor-watch → 擷取各家定價頁 → 標準化比較表
```

## 安全性

- **認證**：使用 SHA-256 進行 timing-safe Bearer token 比對
- **速率限制**：以雜湊後的 key 材料在 KV 中進行每 key 追蹤
- **SSRF 防護**：僅允許 `http://` 和 `https://` URL，阻擋 localhost、私有 IP literal，以及 DNS 解析到私有 IP 的主機名稱
- **Cookie 隔離**：Cookie 僅逐次請求注入，不會持久化儲存
- **密鑰**：所有憑證透過 `wrangler secret put` 儲存，絕不寫入程式碼

## 費用

| 元件 | 免費方案 | 付費方案（$5/月 Workers） |
|------|----------|--------------------------|
| Browser Rendering | 每日 10 分鐘，5 個爬取任務 | 更高限制 |
| KV | 每日 100K 讀取 | 每月 10M 讀取 |
| R2 | 10GB 儲存 | 包含 10GB |
| Workers | 每日 100K 請求 | 每月 10M 請求 |

## 開發

```bash
# Worker
cd worker && npm install && npm test

# SDK（68 個測試）
cd sdk && pip install -e ".[dev]" && pytest tests/ -v

# MCP Server
cd mcp-server && pip install -e ../sdk && pip install -e ".[dev]" && pytest tests/ -v
```

## 疑難排解

- `browser_click` / `browser_type` / `browser_evaluate` / `browser_interact` / `browser_submit_form` 回傳 `501`：Worker 缺少 `[browser] binding = "BROWSER"`。
- 這些互動工具回傳 `404`：目前連到的是舊版 Worker，請重新部署並確認 `/health` 版本。
- `browser_scrape` 或 `browser_links` 在不同環境長得不一樣：新版 SDK / MCP 會自動正規化，但最乾淨的作法仍是重新部署 Worker。

## 專案結構

```
cf-browser/
├── worker/                  Cloudflare Worker（TypeScript/Hono）
│   ├── src/
│   │   ├── index.ts         應用程式進入點
│   │   ├── types.ts         Env 綁定與請求型別
│   │   ├── middleware/      認證、快取、速率限制
│   │   ├── routes/          15 個端點處理器
│   │   └── lib/             CF API 客戶端、參數映射、回應正規化、快取鍵、URL 驗證
│   ├── tests/
│   └── wrangler.toml.example
├── sdk/                     Python SDK（httpx + Pydantic）
│   ├── src/cf_browser/
│   │   ├── client.py        CFBrowser 客戶端（Worker 模式）
│   │   ├── direct.py        CFBrowserDirect 客戶端（直連模式）
│   │   ├── _normalizers.py  回應格式正規化工具
│   │   ├── _shared.py       共用工具（爬取輪詢）
│   │   ├── models.py        Pydantic 回應模型
│   │   └── exceptions.py    型別化例外階層
│   └── tests/               test_client.py + test_direct.py
├── mcp-server/              MCP Server（FastMCP）
│   └── src/cf_browser_mcp/server.py
├── skills/                  Claude Code Skills（複製到 .claude/skills/）
│   ├── content-extractor/   網頁內容讀取與擷取
│   ├── site-auditor/        SEO 與連結健康審計
│   ├── doc-fetcher/         文件抓取供 RAG 使用
│   ├── visual-qa/           多裝置視窗截圖 QA
│   ├── changelog-monitor/   版本更新與破壞性變更追蹤
│   └── competitor-watch/    競品定價與功能比較
├── LICENSE                  MIT
├── README.md
└── README.zh-TW.md
```

## 貢獻

1. Fork 此專案
2. 建立功能分支
3. 撰寫你的變更與測試
4. 執行 `npm test`（worker）和 `pytest`（SDK + MCP Server）
5. 提交 Pull Request

## 授權

[MIT](LICENSE)
