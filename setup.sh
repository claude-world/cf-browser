#!/usr/bin/env bash
#
# CF Browser — One-Command Setup
#
# Creates all Cloudflare resources, deploys the Worker, and outputs
# a ready-to-paste .mcp.json config for Claude Code.
#
# Usage:
#   bash setup.sh
#
# Prerequisites:
#   - Node.js 18+, Python 3.10+
#   - wrangler CLI authenticated (npm i -g wrangler && wrangler login)
#   - Cloudflare account with Browser Rendering enabled
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
info "Checking prerequisites..."

if ! command -v wrangler &>/dev/null; then
  error "wrangler CLI not found. Install with: npm i -g wrangler"
  exit 1
fi

if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
  error "Python 3.10+ not found."
  exit 1
fi

PYTHON_CMD=$(command -v python3 || command -v python)
PYTHON_MCP_CMD=$(basename "$PYTHON_CMD")

# Verify Python version >= 3.10
if ! "$PYTHON_CMD" -c "import sys; assert sys.version_info >= (3,10)" 2>/dev/null; then
  error "Python 3.10+ required. Found: $($PYTHON_CMD --version 2>&1)"
  exit 1
fi

if ! command -v node &>/dev/null; then
  error "Node.js not found."
  exit 1
fi

# Check wrangler is authenticated
if ! wrangler whoami &>/dev/null 2>&1; then
  error "wrangler is not authenticated. Run: wrangler login"
  exit 1
fi

ok "All prerequisites met."

# ---------------------------------------------------------------------------
# Get Cloudflare Account ID
# ---------------------------------------------------------------------------
info "Detecting Cloudflare Account ID..."

CF_ACCOUNT_ID=$(wrangler whoami 2>/dev/null | grep -oE '[a-f0-9]{32}' | head -1 || true)
if [ -z "$CF_ACCOUNT_ID" ]; then
  # Fallback: ask user
  echo ""
  echo "Could not auto-detect Account ID."
  echo "Find it at: https://dash.cloudflare.com → select account → Overview → Account ID"
  read -rp "Enter your Cloudflare Account ID: " CF_ACCOUNT_ID
fi

if [ -z "$CF_ACCOUNT_ID" ]; then
  error "Account ID is required."
  exit 1
fi

ok "Account ID: ${CF_ACCOUNT_ID:0:8}..."

# ---------------------------------------------------------------------------
# Get CF API Token
# ---------------------------------------------------------------------------
info "Setting up CF API Token..."
echo ""
echo "Create an API token at: https://dash.cloudflare.com/profile/api-tokens"
echo "Required permission: 'Workers Browser Rendering Edit'"
echo ""
read -rsp "Enter your CF API Token (hidden): " CF_API_TOKEN
echo ""

if [ -z "$CF_API_TOKEN" ]; then
  error "API Token is required."
  exit 1
fi

ok "API Token received."

# ---------------------------------------------------------------------------
# Generate client API key
# ---------------------------------------------------------------------------
info "Generating client API key..."
API_KEY=$(openssl rand -hex 32)
ok "API key generated: ${API_KEY:0:16}..."

# ---------------------------------------------------------------------------
# Create KV namespaces
# ---------------------------------------------------------------------------
WORKER_DIR="$(cd "$(dirname "$0")/worker" && pwd)"
cd "$WORKER_DIR"

info "Installing Worker dependencies..."
npm install --silent 2>/dev/null
ok "Dependencies installed."

info "Creating KV namespace: CACHE..."
CACHE_OUTPUT=$(wrangler kv namespace create CACHE 2>&1)
CACHE_ID=$(echo "$CACHE_OUTPUT" | sed -n 's/.*id = "\([^"]*\)".*/\1/p' | head -1)
if [ -z "$CACHE_ID" ]; then
  # Namespace might already exist
  warn "Could not create CACHE namespace (may already exist)."
  echo "  Output: $CACHE_OUTPUT"
  read -rp "Enter existing CACHE namespace ID (or press Enter to skip): " CACHE_ID
fi
ok "CACHE namespace: ${CACHE_ID:-skipped}"

info "Creating KV namespace: RATE_LIMIT..."
RATE_LIMIT_OUTPUT=$(wrangler kv namespace create RATE_LIMIT 2>&1)
RATE_LIMIT_ID=$(echo "$RATE_LIMIT_OUTPUT" | sed -n 's/.*id = "\([^"]*\)".*/\1/p' | head -1)
if [ -z "$RATE_LIMIT_ID" ]; then
  warn "Could not create RATE_LIMIT namespace (may already exist)."
  echo "  Output: $RATE_LIMIT_OUTPUT"
  read -rp "Enter existing RATE_LIMIT namespace ID (or press Enter to skip): " RATE_LIMIT_ID
fi
ok "RATE_LIMIT namespace: ${RATE_LIMIT_ID:-skipped}"

# ---------------------------------------------------------------------------
# Create R2 bucket
# ---------------------------------------------------------------------------
info "Creating R2 bucket: cf-browser-storage..."
R2_OUTPUT=$(wrangler r2 bucket create cf-browser-storage 2>&1 || true)
if echo "$R2_OUTPUT" | grep -qi "already exists\|already owned"; then
  ok "R2 bucket already exists."
else
  ok "R2 bucket created."
fi

# ---------------------------------------------------------------------------
# Write wrangler.toml
# ---------------------------------------------------------------------------
info "Writing wrangler.toml..."

cat > wrangler.toml << TOML
name = "cf-browser"
main = "src/index.ts"
compatibility_date = "2026-03-01"
compatibility_flags = ["nodejs_compat"]

[[kv_namespaces]]
binding = "CACHE"
id = "${CACHE_ID}"

[[kv_namespaces]]
binding = "RATE_LIMIT"
id = "${RATE_LIMIT_ID}"

[[r2_buckets]]
binding = "STORAGE"
bucket_name = "cf-browser-storage"

# Browser Rendering binding (Workers Paid plan; required for interaction tools)
[browser]
binding = "BROWSER"

[dev]
port = 8787
TOML

ok "wrangler.toml written."

# ---------------------------------------------------------------------------
# Set secrets
# ---------------------------------------------------------------------------
info "Setting Worker secrets..."

echo "$CF_ACCOUNT_ID" | wrangler secret put CF_ACCOUNT_ID --force 2>/dev/null || \
  warn "Failed to set CF_ACCOUNT_ID secret"

echo "$CF_API_TOKEN" | wrangler secret put CF_API_TOKEN --force 2>/dev/null || \
  warn "Failed to set CF_API_TOKEN secret"

echo "$API_KEY" | wrangler secret put API_KEYS --force 2>/dev/null || \
  warn "Failed to set API_KEYS secret"

ok "Secrets configured."

# ---------------------------------------------------------------------------
# Deploy Worker
# ---------------------------------------------------------------------------
info "Deploying Worker..."
DEPLOY_OUTPUT=$(wrangler deploy 2>&1)
WORKER_URL=$(echo "$DEPLOY_OUTPUT" | grep -oE 'https://[^ ]+\.workers\.dev' | head -1 || true)

if [ -z "$WORKER_URL" ]; then
  warn "Could not detect Worker URL from deploy output."
  echo "  Output: $DEPLOY_OUTPUT"
  read -rp "Enter your Worker URL (e.g. https://cf-browser.xxx.workers.dev): " WORKER_URL
fi

ok "Worker deployed: $WORKER_URL"

# ---------------------------------------------------------------------------
# Verify deployment
# ---------------------------------------------------------------------------
info "Verifying deployment..."
HEALTH_OK=false
for i in 1 2 3; do
  sleep 2
  HEALTH=$(curl -s "${WORKER_URL}/health" 2>/dev/null || true)
  if echo "$HEALTH" | grep -q '"ok"'; then
    HEALTH_OK=true
    break
  fi
done

if $HEALTH_OK; then
  ok "Health check passed!"
else
  warn "Health check did not return expected response: $HEALTH"
  warn "The Worker may need a moment to propagate. Try: curl ${WORKER_URL}/health"
fi

# ---------------------------------------------------------------------------
# Install Python SDK + MCP Server
# ---------------------------------------------------------------------------
cd "$(dirname "$0")"

info "Installing Python SDK..."
cd sdk
$PYTHON_CMD -m pip install -e . --quiet 2>/dev/null || {
  warn "SDK pip install failed — you may need to create a venv first."
}
cd ..

info "Installing MCP Server..."
cd mcp-server
$PYTHON_CMD -m pip install -e . --quiet 2>/dev/null || {
  warn "MCP Server pip install failed — you may need to create a venv first."
}
cd ..

ok "Python packages installed."

# ---------------------------------------------------------------------------
# Output .mcp.json config
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Add this to your project's .mcp.json (or ~/.claude/.mcp.json for global):"
echo ""
echo -e "${YELLOW}"
cat << JSON
{
  "mcpServers": {
    "cf-browser": {
      "type": "stdio",
      "command": "${PYTHON_MCP_CMD}",
      "args": ["-m", "cf_browser_mcp.server"],
      "env": {
        "CF_BROWSER_URL": "${WORKER_URL}",
        "CF_BROWSER_API_KEY": "${API_KEY}"
      }
    }
  }
}
JSON
echo -e "${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Quick test:"
echo "  curl -X POST ${WORKER_URL}/markdown \\"
echo "    -H 'Authorization: Bearer ${API_KEY}' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"url\": \"https://example.com\"}'"
echo ""
echo "Your API key (save this): ${API_KEY}"
echo ""
