# CF Browser

> 開源代理服務，為 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 提供 **9 個 MCP 工具 + 4 個即用 Skill**，支援 JavaScript 渲染的網頁。

**[English README](README.md)**

Claude Code 內建的 `WebFetch` 只能取得原始 HTML — 單頁應用程式（SPA）、動態內容和 JS 渲染的頁面都會回傳空白。CF Browser 將 [Cloudflare Browser Rendering](https://developers.cloudflare.com/browser-rendering/) 包裝在 Worker 代理後方，提供認證、快取和速率限制，並以 MCP 工具的形式對外開放。

## 架構

```
Claude Code
  └── MCP Server（9 個工具）
         │ HTTP + Bearer token
         ▼
  Cloudflare Worker（Edge）
  ├── 認證中介層（API key，timing-safe）
  ├── 速率限制（KV，60 req/min）
  └── 快取（KV 文字 / R2 二進位）
         │
         ▼
  CF Browser Rendering API（無頭 Chrome）
```

| 套件 | 語言 | 用途 |
|------|------|------|
| `worker/` | TypeScript (Hono) | Edge 代理，含認證、快取、速率限制 |
| `sdk/` | Python (httpx) | 非同步客戶端函式庫 |
| `mcp-server/` | Python (FastMCP) | 9 個 MCP 工具供 Claude Code 使用 |

## MCP 工具

| 工具 | 輸入 | 輸出 | 使用情境 |
|------|------|------|----------|
| `browser_markdown` | url | Markdown | 將任何網頁轉為乾淨的文字 |
| `browser_content` | url | HTML | 取得完整渲染的 HTML（JS 已執行） |
| `browser_screenshot` | url, width, height | PNG 檔案 | 視覺驗證、多裝置測試 |
| `browser_pdf` | url, format | PDF 檔案 | 產生報告、封存頁面 |
| `browser_scrape` | url, selectors[] | JSON | 以 CSS 選擇器擷取特定元素 |
| `browser_json` | url, prompt | JSON | AI 驅動的結構化資料擷取 |
| `browser_links` | url | JSON 陣列 | 發現頁面上所有超連結 |
| `browser_crawl` | url, limit | Job ID | 啟動非同步多頁面爬取 |
| `browser_crawl_status` | job_id, wait | JSON | 輪詢或等待爬取結果 |

### 在 Claude Code 中可以這樣問

```
「幫我讀 React 19 遷移指南」
→ browser_markdown("https://react.dev/blog/2024/12/05/react-19")

「我們首頁在手機上長怎樣？」
→ browser_screenshot("https://example.com", width=375, height=667)

「擷取前 5 個產品的名稱、價格和評分」
→ browser_json("https://example.com/products", prompt="Extract top 5 products...")

「檢查我們網站有沒有壞掉的連結」
→ browser_crawl("https://example.com", limit=50) + browser_crawl_status(job_id, wait=True)
```

## 安裝設定

### 方案 A：連接已部署的 Worker（2 分鐘）

如果已經有人部署了 Worker（例如團隊成員），你只需要 URL 和 API key：

```bash
# 安裝到專用的虛擬環境
python3 -m venv ~/.cf-browser-venv
~/.cf-browser-venv/bin/pip install \
  "cf-browser @ git+https://github.com/claude-world/cf-browser.git#subdirectory=sdk" \
  "cf-browser-mcp @ git+https://github.com/claude-world/cf-browser.git#subdirectory=mcp-server"
```

在你專案的 `.mcp.json` 加入：

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "~/.cf-browser-venv/bin/python",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_BROWSER_URL": "https://cf-browser.<subdomain>.workers.dev",
        "CF_BROWSER_API_KEY": "<your-api-key>"
      }
    }
  }
}
```

重啟 Claude Code — 9 個 `browser_*` 工具即可使用。

### 方案 B：自行部署 Worker（5 分鐘）

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
# {"status":"ok","version":"1.0.0"}
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

重啟 Claude Code — 9 個 `browser_*` 工具即可使用。

## Worker API 參考

所有路由（除了 `/health`）都需要 `Authorization: Bearer <api-key>` 標頭。

### 端點

| 路由 | 方法 | 請求體 | 快取 | 回應 |
|------|------|--------|------|------|
| `/health` | GET | — | — | `{"status":"ok"}` |
| `/content` | POST | `{url, wait_for?, no_cache?}` | KV 1hr | HTML |
| `/markdown` | POST | `{url, wait_for?, no_cache?}` | KV 1hr | Markdown |
| `/screenshot` | POST | `{url, width?, height?, full_page?, no_cache?}` | R2 24hr | PNG |
| `/pdf` | POST | `{url, format?, landscape?, no_cache?}` | R2 24hr | PDF |
| `/snapshot` | POST | `{url, wait_for?, no_cache?}` | KV 30min | JSON |
| `/scrape` | POST | `{url, elements[], wait_for?, no_cache?}` | KV 30min | JSON |
| `/json` | POST | `{url, prompt, schema?, no_cache?}` | 無 | JSON |
| `/links` | POST | `{url, wait_for?, no_cache?}` | KV 1hr | JSON |
| `/crawl` | POST | `{url, limit?, no_cache?}` | — | `{"job_id":"..."}` |
| `/crawl/:id` | GET | — | R2 | JSON |

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

| 方法 | 回傳型別 | 說明 |
|------|----------|------|
| `content(url, **opts)` | `str` | 渲染後的 HTML |
| `markdown(url, **opts)` | `str` | 乾淨的 Markdown |
| `screenshot(url, **opts)` | `bytes` | PNG 圖片 |
| `pdf(url, **opts)` | `bytes` | PDF 文件 |
| `snapshot(url, **opts)` | `dict` | HTML + 中繼資料 |
| `scrape(url, selectors, **opts)` | `dict` | 依選擇器擷取的元素 |
| `json_extract(url, prompt, **opts)` | `dict` | AI 擷取的資料 |
| `links(url, **opts)` | `list[dict]` | 所有超連結 |
| `crawl(url, **opts)` | `str` | Job ID |
| `crawl_status(job_id)` | `dict` | 任務狀態 |
| `crawl_wait(job_id, timeout, poll_interval)` | `dict` | 等待完成 |

所有方法都接受 `no_cache=True` 來繞過快取。

## Skills（附贈）

CF Browser 附帶 4 個即用的 [Claude Code Skills](https://docs.anthropic.com/en/docs/claude-code/skills)，放在 `skills/` 目錄。將 skill 資料夾複製到你專案的 `.claude/skills/` 即可啟用。

| Skill | 指令 | 功能 |
|-------|------|------|
| **content-extractor** | `/content-extractor` | 讀取頁面、擷取結構化資料、抓取元素、發現連結 |
| **site-auditor** | `/site-auditor` | 爬取網站並產生 SEO / 連結 / 無障礙審計報告 |
| **doc-fetcher** | `/doc-fetcher` | 將整個文件站抓取為本地 Markdown，供 RAG 使用 |
| **visual-qa** | `/visual-qa` | 多裝置視窗截圖（手機/平板/筆電/桌機）+ 視覺檢查 |

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
```

## 安全性

- **認證**：使用 SHA-256 進行 timing-safe Bearer token 比對
- **速率限制**：以雜湊後的 key 材料在 KV 中進行每 key 追蹤
- **SSRF 防護**：僅允許 `http://` 和 `https://` URL
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

# SDK（28 個測試）
cd sdk && pip install -e ".[dev]" && pytest tests/ -v

# MCP Server
cd mcp-server && pip install -e ../sdk && pip install -e ".[dev]"
```

## 專案結構

```
cf-browser/
├── worker/                  Cloudflare Worker（TypeScript/Hono）
│   ├── src/
│   │   ├── index.ts         應用程式進入點
│   │   ├── types.ts         Env 綁定與請求型別
│   │   ├── middleware/      認證、快取、速率限制
│   │   ├── routes/          9 個端點處理器
│   │   └── lib/             CF API 客戶端、快取鍵、URL 驗證
│   ├── tests/
│   └── wrangler.toml.example
├── sdk/                     Python SDK（httpx + Pydantic）
│   ├── src/cf_browser/      客戶端、模型、例外
│   └── tests/test_client.py
├── mcp-server/              MCP Server（FastMCP）
│   └── src/cf_browser_mcp/server.py
├── skills/                  Claude Code Skills（複製到 .claude/skills/）
│   ├── content-extractor/   網頁內容讀取與擷取
│   ├── site-auditor/        SEO 與連結健康審計
│   ├── doc-fetcher/         文件抓取供 RAG 使用
│   └── visual-qa/           多裝置視窗截圖 QA
├── LICENSE                  MIT
├── README.md
└── README.zh-TW.md
```

## 貢獻

1. Fork 此專案
2. 建立功能分支
3. 撰寫你的變更與測試
4. 執行 `npm test`（worker）和 `pytest`（SDK）
5. 提交 Pull Request

## 授權

[MIT](LICENSE)
