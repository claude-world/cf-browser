# CF Browser

透過 [Cloudflare Browser Run](https://developers.cloudflare.com/browser-run/)（原 Browser Rendering）在 Python 或 Claude Code 讀取 JS 渲染頁面。專案包含 typed async SDK、可部署的 Worker proxy、**17 個 MCP 工具**與 6 個 Skill，支援 Markdown、HTML、截圖、PDF、結構化擷取、crawl、無障礙樹與瀏覽器互動。

**[English README](README.md)**

## 選擇模式

| | 直連模式 | Worker 模式 |
|---|---|---|
| 呼叫方式 | Cloudflare REST API | 你部署的認證 Worker |
| 設定 | 兩個 Cloudflare 憑證 | Worker、KV、R2、native rate limiter |
| MCP 工具 | 12 個唯讀/crawl 工具 | 完整 17 個工具 |
| 快取 | 無 | KV + R2，強制 TTL |
| 限流 | Cloudflare 帳號限制 | 每 key、每 location 每分鐘 60 次 |
| 互動 | 不支援 | 點擊、輸入、JS、action chain、表單 |

若兩組憑證都存在，必須明確設定 `CF_BROWSER_MODE=direct` 或 `worker`，避免不小心使用錯誤帳號。

## 快速開始

### 直連模式

建立具有「帳戶 → Browser Run（Browser Rendering）→ 編輯」權限的 API token：

```bash
python -m pip install cf-browser cf-browser-mcp
export CF_BROWSER_MODE=direct
export CF_ACCOUNT_ID="你的-account-id"
export CF_API_TOKEN="你的-browser-rendering-token"
```

Claude Code 的 `.mcp.json` 建議只引用環境變數，不要放 literal secret：

```json
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_BROWSER_MODE": "direct",
        "CF_ACCOUNT_ID": "${CF_ACCOUNT_ID}",
        "CF_API_TOKEN": "${CF_API_TOKEN}"
      }
    }
  }
}
```

直連模式支援所有唯讀 Quick Actions、crawl 查詢/分頁/等待/取消。五個互動工具會回傳明確的模式提示。

### Worker 模式

需求：Node.js 22+、Python 3.10+、已登入 Wrangler，以及啟用 Browser Run 的 Cloudflare 帳號。

```bash
git clone https://github.com/claude-world/cf-browser.git
cd cf-browser
cd worker && npx wrangler login && cd ..
bash setup.sh
```

`setup.sh` 會建立或重用 KV/R2、安裝實體 R2 expiration、把每個資源操作固定到選定帳號、設定 native rate limiter 與 secrets、部署 Worker、執行 readiness 與帶認證的 Markdown live smoke test、建立隔離 Python 環境，並在可用時註冊 Claude Code user-scope MCP。腳本會先備份既有的 `worker/wrangler.toml` 並保留 native rate-limit namespace ID，不會把 API key 印到終端；所有 Worker secrets 會透過單一私密暫存檔隨部署送出，備援設定則以 `0600` 儲存在 `$XDG_CONFIG_HOME/cf-browser/mcp.json` 或 `~/.config/cf-browser/mcp.json`。

若只需要唯讀端點、沒有 Workers Paid 的 browser binding：

```bash
CF_BROWSER_ENABLE_INTERACTIONS=0 bash setup.sh
```

#### 手動部署

```bash
cd worker
cp wrangler.toml.example wrangler.toml
npm ci

npx wrangler kv namespace create CACHE
# 將回傳 ID 貼入 wrangler.toml
npx wrangler r2 bucket create cf-browser-storage
npx wrangler r2 bucket lifecycle add cf-browser-storage cf-browser-expire-after-8-days --expire-days 8 --force
# 為 ratelimits.namespace_id 選擇帳號內唯一的正整數

npx wrangler secret put CF_ACCOUNT_ID
npx wrangler secret put CF_API_TOKEN
CF_BROWSER_API_KEY="$(openssl rand -hex 32)"
printf '%s' "$CF_BROWSER_API_KEY" | npx wrangler secret put API_KEYS

npm audit --audit-level=high
npm run type-check
npm test
npx wrangler deploy
```

`CF_API_TOKEN` 是給 Worker 呼叫 Browser Run API（權限名稱可能仍顯示 Browser Rendering）；管理 R2 lifecycle 另需 Workers R2 Storage Write 權限。關閉 shell 前，請把 `CF_BROWSER_API_KEY` 存入密碼管理器或 client 設定；Cloudflare 之後無法顯示已儲存的 secret。資源建立與部署由 Wrangler 登入授權。若不需要互動工具，可移除 `[browser]` 設定。

## MCP 工具

### 唯讀與 crawl（兩種模式）

| 工具 | 主要參數 | 回傳 |
|---|---|---|
| `browser_content` | `url` | 渲染後 HTML |
| `browser_markdown` | `url` | Markdown |
| `browser_screenshot` | `url`, `width`, `height`, `full_page` | 私有暫存 PNG 路徑 |
| `browser_pdf` | `url`, `format`, `landscape` | 私有暫存 PDF 路徑 |
| `browser_snapshot` | `url` | content、Markdown、screenshot、可選 a11y tree |
| `browser_scrape` | `url`, `selectors[]` | 正規化 selector 結果 |
| `browser_json` | `url`, `prompt?`, `response_format?` | AI 擷取 JSON |
| `browser_links` | `url`, `include_external`, `visible_only` | 正規化連結 |
| `browser_a11y` | `url` | Cloudflare native accessibility tree |
| `browser_crawl` | `url`, `limit` 與 crawl options | Job ID |
| `browser_crawl_status` | `job_id`, `wait`、cursor/filter | 狀態或 records |
| `browser_delete_crawl` | `job_id` | 取消結果 |

唯讀工具接受 structured `cookies`、`headers`、HTTP Basic `authenticate`、script/style tags、`wait_for`、`wait_until`、`user_agent`、導航 `timeout`（毫秒）與 `no_cache`。Crawl 預設會 render，並支援 `depth`、`formats`、`crawl_purposes`、上游 `cache_ttl`、時間篩選、include/exclude patterns、JSON 擷取與 request/resource/JavaScript/viewport controls；MCP 可使用簡化欄位或完整 `goto_options`、`wait_for_selector`、`viewport` 物件。`render=false` 會拒絕 browser-only options。

### 互動工具（僅 Worker）

| 工具 | 主要參數 | 回傳 |
|---|---|---|
| `browser_click` | `url`, `selector` | 點擊後頁面狀態 |
| `browser_type` | `url`, `selector`, `text`, `clear` | 輸入後頁面狀態 |
| `browser_evaluate` | `url`, `script` | JSON 可序列化結果 |
| `browser_interact` | `url`, structured `actions[]` | 每個 action 結果 |
| `browser_submit_form` | `url`, structured `fields`, `submit_selector?` | 提交後頁面狀態 |

互動端點需要 `BROWSER` binding。未設定時回傳 HTTP 501 並映射為 `BrowserUnavailableError`；直連模式則使用 `NotImplementedError`。

## Worker API

除了 `/health`，所有路由都需要 `Authorization: Bearer <API_KEY>`。

| 路由 | 方法 | 重點欄位 | 快取/行為 |
|---|---|---|---|
| `/health` | GET | — | readiness、版本、capabilities |
| `/content` | POST | `url`、共用選項 | KV 1 小時 |
| `/markdown` | POST | `url`、共用選項 | KV 1 小時 |
| `/screenshot` | POST | `url`, `width?`, `height?`, `full_page?` | R2 24 小時 |
| `/pdf` | POST | `url`, `format?`, `landscape?` | R2 24 小時 |
| `/snapshot` | POST | `url`、共用選項 | R2 JSON 30 分鐘 |
| `/scrape` | POST | `url`、非空 `elements[]` | KV 30 分鐘 |
| `/json` | POST | `url` 與 `prompt` 或 `response_format` | 本地不快取 |
| `/links` | POST | `url`, `include_external?`, `visible_only?` | KV 1 小時 |
| `/a11y` | POST | `url`、共用選項 | KV 5 分鐘 |
| `/crawl` | POST | `url`, `limit?`, `cache_ttl?`, `depth?`、formats/purposes/patterns 與 render options | 建立工作 |
| `/crawl/:id` | GET | `cursor?`, `limit?`, record `status?` | 完整結果存 R2 |
| `/crawl/:id` | DELETE | — | 取消上游工作並清本地狀態 |
| 五個互動路由 | POST | route-specific | 不快取 |

`/health` 是 readiness，不只是 process liveness。缺少核心 binding 時回 HTTP 503 與 `status: "degraded"`；`capabilities.interact` 表示是否有 `BROWSER`。

### JSON schema

Cloudflare 現行欄位是 `response_format`。Worker 與 SDK 保留舊 `schema=` 相容入口，但送出前會轉成新格式：

```json
{
  "url": "https://example.com/products",
  "prompt": "擷取產品",
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "type": "object",
      "properties": {
        "products": {"type": "array", "items": {"type": "object"}}
      },
      "required": ["products"]
    }
  }
}
```

### Crawl 語意

- 相容 `complete`、`completed`、`done` 成功狀態。
- 現行錯誤/取消狀態會拋出 `CrawlJobError`。
- 等待時以 `limit=1` 輪詢，完成後追完所有 cursor 並合併完整 records。
- Cursor 是 opaque string 或非負整數；分頁結果不會污染完整結果快取。
- 每個 crawl 綁定建立它的 API key；其他有效 key 會得到 404。
- Owner metadata 與完成結果七天後邏輯失效；setup 另安裝八天 R2 lifecycle，確保從未再讀取的物件也會實體刪除。
- `DELETE` 真的取消 Cloudflare 工作，不只是刪快取。

### 快取與限流

`no_cache: true` 會略過本地快取讀寫；建立 crawl 時也會送出 Cloudflare `cacheTTL=0`。可用 `cache_ttl`（0–86400 秒）獨立控制上游 crawl cache。文字使用 KV；binary 與大型 snapshot JSON 使用 R2。R2 TTL 會在讀取時強制執行，setup 安裝的 bucket lifecycle 也會實體刪除未再讀取的物件。

Native Cloudflare Rate Limiting binding 以 API key SHA-256 雜湊作 key，在每個 Cloudflare location 執行每 60 秒 60 次。429 回應包含 `Retry-After`、`X-RateLimit-Limit` 與 `X-RateLimit-Remaining: 0`；成功回應不偽造全域精確 remaining counter。

## Python SDK

```python
from cf_browser import CFBrowser, CFBrowserDirect

async with CFBrowserDirect(account_id="...", api_token="...") as browser:
    markdown = await browser.markdown("https://example.com")

async with CFBrowser(base_url="https://...workers.dev", api_key="...") as browser:
    tree = await browser.a11y("https://example.com", no_cache=True)
    data = await browser.json_extract(
        "https://example.com/products",
        response_format={
            "type": "json_schema",
            "json_schema": {
                "type": "object",
                "properties": {"products": {"type": "array"}},
            },
        },
    )
    job_id = await browser.crawl("https://example.com", limit=20, cache_ttl=3600)
    result = await browser.crawl_wait(job_id, timeout=300, poll_interval=2)
    await browser.delete_crawl(job_id)
```

SDK 內含 `py.typed`、typed HTTP exceptions、分離的 `TransportError`/`CrawlJobError`、安全編碼的 crawl ID，以及一致的 link/scrape normalizer。詳見 [sdk/README.md](sdk/README.md)。

## 安全設計

- Bearer keys 經 SHA-256 後用 constant-time loop 比對。
- 限流與 crawl owner metadata 不使用 raw API key。
- URL 驗證阻擋 private、loopback、link-local、CGNAT、multicast、reserved 等非公開位址；REST 前檢查 top-level 與注入資源 URL 的 DNS，互動模式再攔截每個 browser request。REST Quick Actions 在 Cloudflare 遠端瀏覽器執行，因此 redirect、page subresource 與 crawl-discovered URL 不在本 Worker 的攔截邊界，必須依賴 Cloudflare egress isolation。不要把 API key 交給不受信任的 tenant；需要應用層逐 request 攔截時請使用互動路由。
- 多 key 部署會檢查 crawl creator ownership。
- 共用選項、selectors、scripts 與 action chains 有型別/大小限制。
- MCP screenshot/PDF 使用不可預測檔名、process-private `0700` 目錄與 `0600` 檔案，不含 URL userinfo，並有單檔/數量/總容量限制，process 結束時清除。
- Setup 與 examples 不 hardcode 或顯示 secrets；請保持 `.dev.vars`、`wrangler.toml`、`.mcp.json` 私有。

生產使用前請查看 Cloudflare Browser Run 最新的 [limits](https://developers.cloudflare.com/browser-run/limits/) 與 [pricing](https://developers.cloudflare.com/browser-run/pricing/)。

## Skills

`skills/` 內含 content extraction、site audit、文件抓取、visual QA、changelog monitor、competitor comparison 六個 Skill：

```bash
cp -R skills/content-extractor .claude/skills/
# 或
cp -R skills/* .claude/skills/
```

## 開發與驗證

```bash
# Worker（Node 22 或 24）
cd worker
npm ci
npm audit --audit-level=high
npm run type-check
npm test

# SDK
python -m pip install -e './sdk[dev]'
python -m ruff check sdk/src sdk/tests examples
python -m mypy --config-file sdk/pyproject.toml sdk/src
python -m pytest -q sdk/tests

# MCP
python -m pip install -e './sdk' -e './mcp-server[dev]'
python -m ruff check mcp-server/src mcp-server/tests
python -m mypy --config-file mcp-server/pyproject.toml mcp-server/src
python -m pytest -q mcp-server/tests
```

CI 驗證 Python 3.10–3.13、Node 22/24、audit、型別、完整測試、Python 發行包內容、Actionlint、ShellCheck、setup mock end-to-end 與 Wrangler deploy dry-run。

## 疑難排解

- 互動回 501：啟用 `BROWSER` binding 並使用 Worker mode。
- 互動回 404：重新部署；`/health` 應顯示 `2.1.0`。
- MCP 同時存在兩組憑證：設定 `CF_BROWSER_MODE`。
- Crawl records 不完整：持續使用回傳的 opaque `cursor`，直到不再有 cursor。
- Setup 中途停止：查看實際失敗的 Wrangler/curl 步驟；腳本刻意不吞錯誤或宣稱假成功。

## 授權

[MIT](LICENSE)
