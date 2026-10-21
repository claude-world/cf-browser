#!/usr/bin/env bash
#
# CF Browser — verified one-command setup
#
# Creates Cloudflare storage, configures bindings and secrets, deploys the
# Worker, verifies an authenticated render, and installs/registers the MCP
# server without printing credentials.
#
# Prerequisites: Node.js 22+, Python 3.10+, npm, curl, openssl, and an
# authenticated Wrangler session (`npx wrangler login`).

# Never trace: later commands handle secrets, and xtrace (bash -x or an
# inherited SHELLOPTS) would print them.
set +x
set -euo pipefail
umask 077

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { error "$*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_DIR="${SCRIPT_DIR}/worker"
FINAL_WRANGLER_CONFIG="${WORKER_DIR}/wrangler.toml"
WRANGLER_CONFIG="$FINAL_WRANGLER_CONFIG"
ENABLE_INTERACTIONS="${CF_BROWSER_ENABLE_INTERACTIONS:-1}"
INPUT_CF_ACCOUNT_ID="${CF_ACCOUNT_ID:-}"
INPUT_CF_API_TOKEN="${CF_API_TOKEN:-}"
INPUT_CF_BROWSER_API_KEY="${CF_BROWSER_API_KEY:-}"
unset CF_ACCOUNT_ID CF_API_TOKEN CF_BROWSER_API_KEY

PENDING_WRANGLER_CONFIG=""
SECRETS_FILE=""
SMOKE_BODY=""
SMOKE_CURL_CONFIG=""
MCP_REGISTRATION_BACKUP=""
R2_MARKER_FILE=""
R2_MARKER_PROBE=""
MCP_STAGED_DIR=""
MCP_STAGED_RETAIN=0
# Every credential variable Wrangler reads, including deprecated aliases.
SCRUBBED_INSTALL_ENV=(
  env
  -u CF_API_TOKEN
  -u CF_API_KEY
  -u CF_EMAIL
  -u CF_BROWSER_API_KEY
  -u CLOUDFLARE_API_TOKEN
  -u CLOUDFLARE_API_KEY
  -u CLOUDFLARE_EMAIL
  -u CLOUDFLARE_ACCESS_CLIENT_ID
  -u CLOUDFLARE_ACCESS_CLIENT_SECRET
  -u WRANGLER_CF_AUTHORIZATION_TOKEN
  -u WRANGLER_BASIN_SQL_AUTH_TOKEN
)
cleanup() {
  [ -z "$PENDING_WRANGLER_CONFIG" ] || rm -f -- "$PENDING_WRANGLER_CONFIG"
  [ -z "$SECRETS_FILE" ] || rm -f -- "$SECRETS_FILE"
  [ -z "$SMOKE_BODY" ] || rm -f -- "$SMOKE_BODY"
  [ -z "$SMOKE_CURL_CONFIG" ] || rm -f -- "$SMOKE_CURL_CONFIG"
  [ -z "$MCP_REGISTRATION_BACKUP" ] || rm -f -- "$MCP_REGISTRATION_BACKUP"
  [ -z "$R2_MARKER_FILE" ] || rm -f -- "$R2_MARKER_FILE"
  [ -z "$R2_MARKER_PROBE" ] || rm -f -- "$R2_MARKER_PROBE"
  if [ -n "$MCP_STAGED_DIR" ] && [ "$MCP_STAGED_RETAIN" != "1" ]; then
    case "$MCP_STAGED_DIR" in
      "${CONFIG_DIR:-}"/generation.*)
        rm -rf -- "$MCP_STAGED_DIR"
        ;;
    esac
  fi
}
trap cleanup EXIT

for command_name in node npm curl openssl; do
  command -v "$command_name" >/dev/null 2>&1 || die "$command_name is required."
done

if command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD="$(command -v python)"
else
  die "Python 3.10+ is required."
fi

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
[ "$NODE_MAJOR" -ge 22 ] || die "Node.js 22+ is required; found $(node --version)."
"$PYTHON_CMD" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null \
  || die "Python 3.10+ is required; found $($PYTHON_CMD --version 2>&1)."
[ "$ENABLE_INTERACTIONS" = "0" ] || [ "$ENABLE_INTERACTIONS" = "1" ] \
  || die "CF_BROWSER_ENABLE_INTERACTIONS must be 0 or 1."

EXISTING_RATE_LIMIT_NAMESPACE_ID=""
if [ -f "$WRANGLER_CONFIG" ]; then
  EXISTING_RATE_LIMIT_NAMESPACE_ID="$(
    "$PYTHON_CMD" - "$WRANGLER_CONFIG" <<'PY' || true
import re
import sys

def finish_binding(binding):
    if binding.get("name") != "RATE_LIMITER":
        return None
    value = binding.get("namespace_id", "")
    return value if value.isdigit() and int(value) > 0 else None

try:
    binding = {}
    in_ratelimit = False
    with open(sys.argv[1], encoding="utf-8") as stream:
        for raw_line in stream:
            line = raw_line.split("#", 1)[0].strip()
            table = re.fullmatch(r"\[\[\s*([^]]+)\s*\]\]", line)
            if table:
                value = finish_binding(binding) if in_ratelimit else None
                if value:
                    print(value)
                    raise SystemExit
                in_ratelimit = table.group(1).strip() == "ratelimits"
                binding = {}
                continue
            if not in_ratelimit:
                continue
            assignment = re.fullmatch(
                r"(name|namespace_id)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\d+))",
                line,
            )
            if assignment:
                binding[assignment.group(1)] = next(
                    value for value in assignment.groups()[1:] if value is not None
                )
    value = finish_binding(binding) if in_ratelimit else None
    if value:
        print(value)
except Exception:
    pass
PY
  )"
  CONFIG_BACKUP="${WRANGLER_CONFIG}.$(date -u +%Y%m%dT%H%M%SZ).bak"
  cp -p "$WRANGLER_CONFIG" "$CONFIG_BACKUP"
  chmod 600 "$CONFIG_BACKUP"
  info "Existing Worker config backed up to ${CONFIG_BACKUP}."
fi

info "Installing locked Worker dependencies..."
cd "$WORKER_DIR"
"${SCRUBBED_INSTALL_ENV[@]}" npm ci --silent
WRANGLER=(npx --no-install wrangler)
# Plain `whoami` succeeds even when logged out; `--json` fails instead.
WHOAMI_JSON="$("${WRANGLER[@]}" whoami --json 2>/dev/null </dev/null)" \
  || die "Wrangler is not authenticated. Run: cd worker && npx wrangler login"
ok "Prerequisites and Wrangler authentication verified."

CF_ACCOUNT_ID="$INPUT_CF_ACCOUNT_ID"
if [ -z "$CF_ACCOUNT_ID" ]; then
  DISCOVERED_ACCOUNT_IDS="$(
    printf '%s' "$WHOAMI_JSON" | "$PYTHON_CMD" -c '
import json, re, sys
try:
    accounts = json.load(sys.stdin).get("accounts") or []
except Exception:
    accounts = []
for account in accounts:
    account_id = str(account.get("id", "")) if isinstance(account, dict) else ""
    if re.fullmatch(r"[a-f0-9]{32}", account_id):
        print(account_id)
' | sort -u || true
  )"
  DISCOVERED_ACCOUNT_COUNT="$(
    printf '%s\n' "$DISCOVERED_ACCOUNT_IDS" | sed '/^$/d' | wc -l | tr -d ' '
  )"
  if [ "$DISCOVERED_ACCOUNT_COUNT" = "1" ]; then
    CF_ACCOUNT_ID="$DISCOVERED_ACCOUNT_IDS"
  elif [ "$DISCOVERED_ACCOUNT_COUNT" -gt 1 ]; then
    echo "Wrangler is authenticated to multiple accounts:"
    printf '%s\n' "$DISCOVERED_ACCOUNT_IDS" | sed 's/^/  /'
  fi
fi
if [ -z "$CF_ACCOUNT_ID" ]; then
  echo "Find the Account ID in the Cloudflare dashboard account overview."
  read -rp "Cloudflare Account ID: " CF_ACCOUNT_ID || true
fi
[[ "$CF_ACCOUNT_ID" =~ ^[a-fA-F0-9]{32}$ ]] || die "A valid 32-character Account ID is required."

CF_API_TOKEN="$INPUT_CF_API_TOKEN"
if [ -z "$CF_API_TOKEN" ]; then
  echo "Create a token with Account > Browser Run (Browser Rendering) > Edit permission:"
  echo "https://dash.cloudflare.com/profile/api-tokens"
  read -rsp "Cloudflare API Token (hidden): " CF_API_TOKEN || true
  echo
fi
[ -n "$CF_API_TOKEN" ] || die "Cloudflare API Token is required."

API_KEY="$INPUT_CF_BROWSER_API_KEY"
if [ -z "$API_KEY" ]; then
  API_KEY="$(openssl rand -hex 32)"
fi
[ "${#API_KEY}" -ge 32 ] || die "CF_BROWSER_API_KEY must be at least 32 characters."
# The Worker splits API_KEYS on commas, and clients send the key as a header.
CFB_SETUP_API_KEY="$API_KEY" "$PYTHON_CMD" -c '
import os
key = os.environ["CFB_SETUP_API_KEY"]
raise SystemExit(0 if all("!" <= c <= "~" and c != "," for c in key) else 1)
' || die "CF_BROWSER_API_KEY must use visible ASCII characters without commas or whitespace."
ok "Credentials loaded without displaying secret values."

# Use a real .toml filename: current Wrangler intentionally ignores unknown
# config extensions such as wrangler.toml.example.
PENDING_WRANGLER_CONFIG="$(
  "$PYTHON_CMD" - "$WORKER_DIR" <<'PY'
import pathlib, sys, tempfile

with tempfile.NamedTemporaryFile(
    prefix=".wrangler.setup.", suffix=".toml", dir=sys.argv[1], delete=False
) as output:
    path = pathlib.Path(output.name)
path.chmod(0o600)
print(path)
PY
)"
WRANGLER_CONFIG="$PENDING_WRANGLER_CONFIG"
cat > "$WRANGLER_CONFIG" <<TOML
name = "cf-browser"
main = "src/index.ts"
account_id = "${CF_ACCOUNT_ID}"
compatibility_date = "2026-07-18"
compatibility_flags = ["nodejs_compat"]
TOML

# Wrangler titles a namespace exactly as named, so create and look up the same
# project-specific title.
KV_NAMESPACE_TITLE="cf-browser-CACHE"
find_cache_id() {
  "${WRANGLER[@]}" kv namespace list --config "$WRANGLER_CONFIG" 2>/dev/null | "$PYTHON_CMD" -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
for item in data:
    if item.get("title") == sys.argv[1]:
        print(item.get("id", ""))
        break
' "$KV_NAMESPACE_TITLE"
}

info "Ensuring the CACHE KV namespace exists..."
CACHE_ID="$(find_cache_id || true)"
if [ -z "$CACHE_ID" ]; then
  "${WRANGLER[@]}" kv namespace create "$KV_NAMESPACE_TITLE" \
    --config "$WRANGLER_CONFIG" >/dev/null 2>&1 </dev/null || true
  CACHE_ID="$(find_cache_id || true)"
fi
if [[ ! "$CACHE_ID" =~ ^[a-fA-F0-9]{32}$ ]]; then
  read -rp "Existing CACHE namespace ID: " CACHE_ID || true
fi
[[ "$CACHE_ID" =~ ^[a-fA-F0-9]{32}$ ]] || die "A valid CACHE namespace ID is required."
ok "CACHE namespace is ready."

NORMALIZED_ACCOUNT_ID="$(printf '%s' "$CF_ACCOUNT_ID" | tr '[:upper:]' '[:lower:]')"
R2_BUCKET_NAME="${CF_BROWSER_R2_BUCKET_NAME:-cf-browser-storage-${NORMALIZED_ACCOUNT_ID}}"
R2_BUCKET_MARKER_KEY=".cf-browser-managed-v1"
R2_OBJECT_PREFIX="cf-browser/"
R2_LIFECYCLE_RULE="cf-browser-prefix-expire-after-8-days"

if [ "${#R2_BUCKET_NAME}" -lt 3 ] || [ "${#R2_BUCKET_NAME}" -gt 63 ] \
    || [[ ! "$R2_BUCKET_NAME" =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$ ]]; then
  die "CF_BROWSER_R2_BUCKET_NAME must be a 3-63 character lowercase R2 bucket name using only letters, digits, and hyphens."
fi

bucket_exists() {
  local bucket_output
  # `bucket info` looks up the exact name; `bucket list` returns only one page.
  bucket_output="$(
    "${WRANGLER[@]}" r2 bucket info "$R2_BUCKET_NAME" --json \
      --config "$WRANGLER_CONFIG" 2>/dev/null
  )" || return 1
  printf '%s\n' "$bucket_output" | "$PYTHON_CMD" -c '
import json, sys

try:
    payload = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if isinstance(payload, dict) and payload.get("name") == sys.argv[1] else 1)
' "$R2_BUCKET_NAME"
}

verify_bucket_marker() {
  rm -f -- "$R2_MARKER_PROBE"
  # Wrangler 4 defaults `r2 object` commands to local storage.
  if ! "${WRANGLER[@]}" r2 object get \
      "${R2_BUCKET_NAME}/${R2_BUCKET_MARKER_KEY}" \
      --remote \
      --file "$R2_MARKER_PROBE" \
      --config "$WRANGLER_CONFIG" >/dev/null 2>&1; then
    return 1
  fi
  CFB_R2_ACCOUNT_ID="$NORMALIZED_ACCOUNT_ID" \
  CFB_R2_BUCKET_NAME="$R2_BUCKET_NAME" \
  "$PYTHON_CMD" - "$R2_MARKER_PROBE" <<'PY'
import json
import os
import pathlib
import sys

expected = {
    "schema": 1,
    "owner": "cf-browser",
    "account_id": os.environ["CFB_R2_ACCOUNT_ID"],
    "bucket_name": os.environ["CFB_R2_BUCKET_NAME"],
}
try:
    actual = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if actual == expected else 1)
PY
}

write_bucket_marker() {
  CFB_R2_ACCOUNT_ID="$NORMALIZED_ACCOUNT_ID" \
  CFB_R2_BUCKET_NAME="$R2_BUCKET_NAME" \
  "$PYTHON_CMD" - "$R2_MARKER_FILE" <<'PY'
import json
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
    "schema": 1,
    "owner": "cf-browser",
    "account_id": os.environ["CFB_R2_ACCOUNT_ID"],
    "bucket_name": os.environ["CFB_R2_BUCKET_NAME"],
}, separators=(",", ":")) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
  "${WRANGLER[@]}" r2 object put \
    "${R2_BUCKET_NAME}/${R2_BUCKET_MARKER_KEY}" \
    --remote \
    --file "$R2_MARKER_FILE" \
    --content-type application/json \
    --config "$WRANGLER_CONFIG" >/dev/null 2>&1
}

R2_MARKER_FILE="$(mktemp)"
R2_MARKER_PROBE="$(mktemp)"
info "Ensuring the account-scoped R2 bucket exists..."
if bucket_exists; then
  verify_bucket_marker \
    || die "R2 bucket ${R2_BUCKET_NAME} already exists but is not verified as CF Browser-managed for this account. Set CF_BROWSER_R2_BUCKET_NAME to a new dedicated bucket name and rerun setup."
else
  if "${WRANGLER[@]}" r2 bucket create "$R2_BUCKET_NAME" \
      --config "$WRANGLER_CONFIG" >/dev/null 2>&1; then
    write_bucket_marker \
      || die "Created R2 bucket ${R2_BUCKET_NAME}, but could not write its CF Browser ownership marker. Refusing to install a lifecycle rule."
    verify_bucket_marker \
      || die "Created R2 bucket ${R2_BUCKET_NAME}, but its CF Browser ownership marker could not be verified. Refusing to install a lifecycle rule."
  elif bucket_exists && verify_bucket_marker; then
    : # A concurrent safe setup created and marked the same dedicated bucket.
  else
    die "Unable to create a dedicated, verified R2 bucket named ${R2_BUCKET_NAME}."
  fi
fi
ok "Dedicated R2 bucket ownership is verified."

lifecycle_rule_is_valid() {
  local lifecycle_output
  lifecycle_output="$(
    "${WRANGLER[@]}" r2 bucket lifecycle list "$R2_BUCKET_NAME" \
      --config "$WRANGLER_CONFIG" 2>/dev/null
  )" || return 1
  printf '%s\n' "$lifecycle_output" | "$PYTHON_CMD" -c '
import json, re, sys

target = sys.argv[1]
expected_prefix = sys.argv[2]
raw = sys.stdin.read()
try:
    payload = json.loads(raw)
except Exception:
    payload = None

def find_rule(value):
    if isinstance(value, dict):
        if value.get("id") == target or value.get("name") == target:
            return value
        for item in value.values():
            found = find_rule(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_rule(item)
            if found is not None:
                return found
    return None

rule = find_rule(payload)
if rule is not None:
    transition = rule.get("deleteObjectsTransition")
    condition = transition.get("condition") if isinstance(transition, dict) else None
    conditions = rule.get("conditions")
    prefix = conditions.get("prefix") if isinstance(conditions, dict) else None
    valid = (
        rule.get("enabled") is True
        and prefix == expected_prefix
        and isinstance(condition, dict)
        and condition.get("type") == "Age"
        and condition.get("maxAge") == 8 * 24 * 60 * 60
    )
    raise SystemExit(0 if valid else 2)

for block in re.split(r"\n\s*\n", raw):
    fields = {}
    for line in block.splitlines():
        match = re.match(r"\s*([A-Za-z]+)\s*:\s*(.*?)\s*$", line)
        if match:
            fields[match.group(1).lower()] = match.group(2)
    if fields.get("name") != target:
        continue
    valid = (
        fields.get("enabled", "").lower() == "yes"
        and fields.get("prefix") == expected_prefix
        and "Expire objects after 8 days" in fields.get("action", "")
    )
    raise SystemExit(0 if valid else 2)

raise SystemExit(1)
' "$R2_LIFECYCLE_RULE" "$R2_OBJECT_PREFIX"
}

info "Ensuring R2 objects physically expire after eight days..."
if lifecycle_rule_is_valid; then
  :
else
  LIFECYCLE_STATUS=$?
  if [ "$LIFECYCLE_STATUS" = "2" ]; then
    die "R2 lifecycle rule ${R2_LIFECYCLE_RULE} exists but is not an enabled ${R2_OBJECT_PREFIX} prefix 8-day expiration rule. Correct or remove that rule, then rerun setup."
  fi
  if ! "${WRANGLER[@]}" r2 bucket lifecycle add \
      "$R2_BUCKET_NAME" "$R2_LIFECYCLE_RULE" "$R2_OBJECT_PREFIX" \
      --expire-days 8 \
      --config "$WRANGLER_CONFIG" >/dev/null 2>&1; then
    die "Unable to install the R2 object-expiration lifecycle rule."
  fi
  lifecycle_rule_is_valid || die "The R2 object-expiration lifecycle rule could not be verified after creation."
fi
ok "R2 object-expiration lifecycle rule is ready."

RATE_LIMIT_NAMESPACE_ID="${CF_BROWSER_RATE_LIMIT_NAMESPACE_ID:-${EXISTING_RATE_LIMIT_NAMESPACE_ID}}"
if [ -z "$RATE_LIMIT_NAMESPACE_ID" ]; then
  RATE_LIMIT_NAMESPACE_ID="$(
    "$PYTHON_CMD" -c 'import secrets; print(secrets.randbelow(2_000_000_000) + 1)'
  )"
fi
[[ "$RATE_LIMIT_NAMESPACE_ID" =~ ^[1-9][0-9]*$ ]] \
  || die "CF_BROWSER_RATE_LIMIT_NAMESPACE_ID must be a positive integer."

info "Writing the deployment configuration..."
cat > "$WRANGLER_CONFIG" <<TOML
name = "cf-browser"
main = "src/index.ts"
account_id = "${CF_ACCOUNT_ID}"
compatibility_date = "2026-07-18"
compatibility_flags = ["nodejs_compat"]

[[kv_namespaces]]
binding = "CACHE"
id = "${CACHE_ID}"

[[r2_buckets]]
binding = "STORAGE"
bucket_name = "${R2_BUCKET_NAME}"

[[ratelimits]]
name = "RATE_LIMITER"
namespace_id = "${RATE_LIMIT_NAMESPACE_ID}"

  [ratelimits.simple]
  limit = 60
  period = 60
TOML

if [ "$ENABLE_INTERACTIONS" = "1" ]; then
  cat >> "$WRANGLER_CONFIG" <<'TOML'

[browser]
binding = "BROWSER"
TOML
fi

cat >> "$WRANGLER_CONFIG" <<'TOML'

[dev]
port = 8787
TOML
ok "Worker bindings configured."

SECRETS_FILE="$(mktemp)"
SMOKE_BODY="$(mktemp)"
SMOKE_CURL_CONFIG="$(mktemp)"
CFB_SETUP_ACCOUNT_ID="$CF_ACCOUNT_ID" \
CFB_SETUP_API_TOKEN="$CF_API_TOKEN" \
CFB_SETUP_API_KEY="$API_KEY" \
"$PYTHON_CMD" - "$SECRETS_FILE" <<'PY'
import json, os, pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
    "CF_ACCOUNT_ID": os.environ["CFB_SETUP_ACCOUNT_ID"],
    "CF_API_TOKEN": os.environ["CFB_SETUP_API_TOKEN"],
    "API_KEYS": os.environ["CFB_SETUP_API_KEY"],
}), encoding="utf-8")
path.chmod(0o600)
PY

info "Deploying the Worker with encrypted secrets..."
DEPLOY_STATUS=0
DEPLOY_OUTPUT="$(
  "${WRANGLER[@]}" deploy \
    --config "$WRANGLER_CONFIG" \
    --secrets-file "$SECRETS_FILE" 2>&1
)" || DEPLOY_STATUS=$?
rm -f -- "$SECRETS_FILE"
SECRETS_FILE=""
if [ "$DEPLOY_STATUS" != "0" ]; then
  error "$DEPLOY_OUTPUT"
  die "Worker deployment failed."
fi
mv -f -- "$WRANGLER_CONFIG" "$FINAL_WRANGLER_CONFIG"
WRANGLER_CONFIG="$FINAL_WRANGLER_CONFIG"
PENDING_WRANGLER_CONFIG=""
WORKER_URL="${CF_BROWSER_URL:-}"
if [ -z "$WORKER_URL" ]; then
  WORKER_URL="$(
    printf '%s' "$DEPLOY_OUTPUT" \
      | grep -oE 'https://[^[:space:]]+\.workers\.dev' \
      | head -1 \
      || true
  )"
fi
if [ -z "$WORKER_URL" ]; then
  read -rp "Deployed Worker URL: " WORKER_URL || true
fi
[[ "$WORKER_URL" =~ ^https:// ]] || die "A valid HTTPS Worker URL is required."
ok "Worker deployment completed."

info "Waiting for readiness and running an authenticated render..."
READY=false
for _attempt in 1 2 3 4 5 6; do
  HEALTH_CODE="$(
    curl --disable -sS -o "$SMOKE_BODY" -w '%{http_code}' "${WORKER_URL}/health" \
      || true
  )"
  if [ "$HEALTH_CODE" = "200" ] && "$PYTHON_CMD" - "$SMOKE_BODY" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    data = json.load(stream)
raise SystemExit(0 if data.get("ready") is True else 1)
PY
  then
    READY=true
    break
  fi
  sleep 2
done
$READY || die "The deployed Worker did not become ready."

CFB_SETUP_API_KEY="$API_KEY" \
"$PYTHON_CMD" - "$SMOKE_CURL_CONFIG" <<'PY'
import os, pathlib, sys

path = pathlib.Path(sys.argv[1])
key = os.environ["CFB_SETUP_API_KEY"].replace("\\", "\\\\").replace('"', '\\"')
path.write_text(
    f'header = "Authorization: Bearer {key}"\n'
    'header = "Content-Type: application/json"\n',
    encoding="utf-8",
)
path.chmod(0o600)
PY

SMOKE_CODE="$(
  curl --disable --config "$SMOKE_CURL_CONFIG" -sS -o "$SMOKE_BODY" -w '%{http_code}' \
    -X POST "${WORKER_URL}/markdown" \
    --data '{"url":"https://example.com","no_cache":true}' \
    || true
)"
rm -f -- "$SMOKE_CURL_CONFIG"
SMOKE_CURL_CONFIG=""
[ "$SMOKE_CODE" = "200" ] || die "Authenticated Markdown smoke test returned HTTP ${SMOKE_CODE}."
[ -s "$SMOKE_BODY" ] || die "Authenticated Markdown smoke test returned an empty body."
ok "Readiness and authenticated Markdown smoke tests passed."

CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
CONFIG_DIR="${CONFIG_HOME}/cf-browser"
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
MCP_STAGED_DIR="$(mktemp -d "${CONFIG_DIR}/generation.XXXXXX")"
chmod 700 "$MCP_STAGED_DIR"
VENV_DIR="${MCP_STAGED_DIR}/venv"
MCP_CONFIG="${MCP_STAGED_DIR}/mcp.json"
MCP_LAUNCHER="${MCP_STAGED_DIR}/run-mcp"

info "Staging the SDK and MCP server in an isolated generation..."
"${SCRUBBED_INSTALL_ENV[@]}" "$PYTHON_CMD" -m venv "$VENV_DIR"
VENV_PYTHON="${VENV_DIR}/bin/python"
"${SCRUBBED_INSTALL_ENV[@]}" "$VENV_PYTHON" -m pip install --quiet --upgrade pip
"${SCRUBBED_INSTALL_ENV[@]}" "$VENV_PYTHON" -m pip install --quiet \
  --upgrade \
  "${SCRIPT_DIR}/sdk" \
  "${SCRIPT_DIR}/mcp-server"
"${SCRUBBED_INSTALL_ENV[@]}" "$VENV_PYTHON" -c 'import cf_browser, cf_browser_mcp.server'
ok "SDK and MCP imports verified."

CFB_SETUP_URL="$WORKER_URL" \
CFB_SETUP_KEY="$API_KEY" \
CFB_SETUP_PYTHON="$VENV_PYTHON" \
"$PYTHON_CMD" - "$MCP_CONFIG" <<'PY'
import json, os, pathlib, sys
path = pathlib.Path(sys.argv[1])
config = {
    "mcpServers": {
        "cf-browser": {
            "type": "stdio",
            "command": os.environ["CFB_SETUP_PYTHON"],
            "args": ["-m", "cf_browser_mcp.server"],
            "env": {
                "CF_BROWSER_MODE": "worker",
                "CF_BROWSER_URL": os.environ["CFB_SETUP_URL"],
                "CF_BROWSER_API_KEY": os.environ["CFB_SETUP_KEY"],
            },
        }
    }
}
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
PY
chmod 600 "$MCP_CONFIG"

CFB_SETUP_CONFIG="$MCP_CONFIG" \
"$PYTHON_CMD" - "$MCP_LAUNCHER" <<'PY'
import os, pathlib, sys

path = pathlib.Path(sys.argv[1])
config_path = os.environ["CFB_SETUP_CONFIG"]
source = f'''#!/usr/bin/env python3
import json
import os

with open({config_path!r}, encoding="utf-8") as stream:
    server = json.load(stream)["mcpServers"]["cf-browser"]
environment = os.environ.copy()
environment.update(server["env"])
os.execve(server["command"], [server["command"], *server["args"]], environment)
'''
path.write_text(source, encoding="utf-8")
path.chmod(0o700)
PY

MCP_REGISTRATION_STATUS="required"
restore_claude_registration() {
  CFB_CLAUDE_STATE_FILE="$CLAUDE_STATE_FILE" \
  "$PYTHON_CMD" - "$MCP_REGISTRATION_BACKUP" <<'PY'
import json
import os
import pathlib
import tempfile
import sys

state_path = pathlib.Path(os.environ["CFB_CLAUDE_STATE_FILE"])
backup_path = pathlib.Path(sys.argv[1])
entry = json.loads(backup_path.read_text(encoding="utf-8"))

if state_path.exists():
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise TypeError("Claude state root is not an object")
else:
    state = {}

servers = state.get("mcpServers")
if servers is None:
    servers = {}
    state["mcpServers"] = servers
elif not isinstance(servers, dict):
    raise TypeError("Claude MCP registry is not an object")
servers["cf-browser"] = entry

state_path.parent.mkdir(parents=True, exist_ok=True)
temporary_name = None
try:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".claude.json.cf-browser-restore.",
        dir=state_path.parent,
        delete=False,
    ) as output:
        temporary_name = output.name
        json.dump(state, output, indent=2)
        output.write("\n")
    os.chmod(temporary_name, 0o600)
    os.replace(temporary_name, state_path)
    temporary_name = None
finally:
    if temporary_name is not None:
        pathlib.Path(temporary_name).unlink(missing_ok=True)
PY
}

if command -v claude >/dev/null 2>&1; then
  CLAUDE_STATE_FILE="${CLAUDE_CONFIG_DIR:-${HOME}}/.claude.json"
  MCP_REGISTRATION_BACKUP="$(mktemp)"
  if CFB_CLAUDE_STATE_FILE="$CLAUDE_STATE_FILE" \
      "$PYTHON_CMD" - "$MCP_REGISTRATION_BACKUP" <<'PY'
import json
import os
import pathlib
import sys

state_path = pathlib.Path(os.environ["CFB_CLAUDE_STATE_FILE"])
backup_path = pathlib.Path(sys.argv[1])
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    servers = state.get("mcpServers")
    if not isinstance(servers, dict) or "cf-browser" not in servers:
        raise KeyError("cf-browser")
    backup_path.write_text(
        json.dumps(servers["cf-browser"]) + "\n",
        encoding="utf-8",
    )
    backup_path.chmod(0o600)
except Exception:
    raise SystemExit(1)
PY
  then
    if claude mcp remove --scope user cf-browser >/dev/null 2>&1; then
      # Deploying replaced the Worker API key, so keep the new generation if the
      # old registration has to be restored.
      MCP_STAGED_RETAIN=1
      if claude mcp add \
          --transport stdio \
          --scope user \
          cf-browser -- "$MCP_LAUNCHER" >/dev/null 2>&1; then
        MCP_REGISTRATION_STATUS="current"
      elif restore_claude_registration; then
        MCP_REGISTRATION_STATUS="restored"
        warn "Claude Code registration failed; the previous user-scoped registration was restored, but this deployment replaced the Worker API key it may use."
      else
        die "Claude Code registration failed and the previous registration could not be restored. New private MCP config: ${MCP_CONFIG}"
      fi
    elif restore_claude_registration; then
      MCP_STAGED_RETAIN=1
      MCP_REGISTRATION_STATUS="restored"
      warn "Claude Code registration could not be replaced; the previous user-scoped registration was preserved, but this deployment replaced the Worker API key it may use."
    else
      MCP_STAGED_RETAIN=1
      die "Claude Code registration could not be replaced or restored. New private MCP config: ${MCP_CONFIG}"
    fi
  else
    rm -f -- "$MCP_REGISTRATION_BACKUP"
    MCP_REGISTRATION_BACKUP=""
    if claude mcp add \
        --transport stdio \
        --scope user \
        cf-browser -- "$MCP_LAUNCHER" >/dev/null 2>&1; then
      MCP_REGISTRATION_STATUS="current"
      MCP_STAGED_RETAIN=1
    else
      MCP_STAGED_RETAIN=1
      warn "Claude Code registration failed; use the private config file shown below."
    fi
  fi
  if [ "$MCP_REGISTRATION_STATUS" = "current" ]; then
    ok "Claude Code user-scoped MCP server registered."
  fi
else
  MCP_STAGED_RETAIN=1
  warn "Claude Code CLI was not found; MCP configuration was saved but not registered."
fi

echo
echo -e "${GREEN}CF Browser setup and live verification completed.${NC}"
echo "Worker: ${WORKER_URL}"
case "$MCP_REGISTRATION_STATUS" in
  current)
    echo "Private MCP config: ${MCP_CONFIG}"
    echo "Claude Code: user-scoped server registered"
    ;;
  restored)
    echo "Private MCP config: ${MCP_CONFIG}"
    echo "Claude Code: previous registration restored; register the new server with:"
    echo "  claude mcp remove --scope user cf-browser"
    echo "  claude mcp add --transport stdio --scope user cf-browser -- ${MCP_LAUNCHER}"
    ;;
  *)
    echo "Private MCP config: ${MCP_CONFIG}"
    echo "Claude Code: registration still required"
    ;;
esac
echo "Credentials were not printed; the private config is mode 0600."
