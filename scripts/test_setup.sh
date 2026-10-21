#!/usr/bin/env bash
# Run setup.sh end-to-end with local command doubles and no cloud writes.

set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_PYTHON="$(command -v python3)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/cf-browser-setup-test.XXXXXX")"
MOCK_BIN="${TEST_ROOT}/bin"
FIXTURE="${TEST_ROOT}/repo"
CALL_LOG="${TEST_ROOT}/calls.log"

cleanup() {
  case "$TEST_ROOT" in
    "${TMPDIR:-/tmp}"/cf-browser-setup-test.*)
      rm -rf -- "$TEST_ROOT"
      ;;
  esac
}
trap cleanup EXIT

mkdir -p "$MOCK_BIN" "$FIXTURE/worker" "$FIXTURE/sdk" "$FIXTURE/mcp-server"
cp "$ROOT_DIR/setup.sh" "$FIXTURE/setup.sh"
printf '%s\n' \
  'name = "existing-cf-browser"' \
  '[[ratelimits]]' \
  'name = "RATE_LIMITER"' \
  'namespace_id = "4242"' \
  > "$FIXTURE/worker/wrangler.toml"

cat > "$MOCK_BIN/dispatch" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail

command_name="$(basename "$0")"

case "$command_name" in
  node)
    if [ "${1:-}" = "-p" ]; then
      printf '24\n'
    else
      printf 'v24.0.0\n'
    fi
    ;;
  npm)
    [ -z "${CF_API_TOKEN+x}" ]
    [ -z "${CF_BROWSER_API_KEY+x}" ]
    [ -z "${CLOUDFLARE_API_TOKEN+x}" ]
    [ -z "${CLOUDFLARE_API_KEY+x}" ]
    [ -z "${CLOUDFLARE_EMAIL+x}" ]
    exit 0
    ;;
  npx)
    shift 2
    printf '%s\n' "$*" >> "$CF_BROWSER_TEST_CALL_LOG"
    previous_argument=""
    for argument in "$@"; do
      if [ "$previous_argument" = "--config" ]; then
        [ -f "$argument" ]
        grep -Fqx \
          "account_id = \"${CF_BROWSER_TEST_EXPECTED_ACCOUNT_ID}\"" \
          "$argument"
        break
      fi
      previous_argument="$argument"
    done
    case "${1:-} ${2:-}" in
      "whoami ")
        printf 'Account ID: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n'
        printf 'Account ID: cccccccccccccccccccccccccccccccc\n'
        ;;
      "kv namespace")
        if [ "${3:-}" = "list" ]; then
          printf '[{"title":"cf-browser-CACHE","id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]\n'
        else
          exit 1
        fi
        ;;
      "r2 bucket")
        if [ "${3:-}" = "lifecycle" ] && [ "${4:-}" = "list" ]; then
          [ "${5:-}" = "$CF_BROWSER_TEST_EXPECTED_BUCKET" ]
          if [ "${CF_BROWSER_TEST_LIFECYCLE_WRONG:-0}" = "1" ]; then
            printf '%s\n' '{"rules":[{"id":"cf-browser-prefix-expire-after-8-days","enabled":true,"conditions":{"prefix":"cf-browser/"},"deleteObjectsTransition":{"condition":{"type":"Age","maxAge":2592000}}}]}'
          elif [ "${CF_BROWSER_TEST_LIFECYCLE_PRESENT:-0}" = "1" ] \
              || [ -f "${CF_BROWSER_TEST_LIFECYCLE_MARKER:-/nonexistent}" ]; then
            printf '%s\n' '{"rules":[{"id":"cf-browser-prefix-expire-after-8-days","enabled":true,"conditions":{"prefix":"cf-browser/"},"deleteObjectsTransition":{"condition":{"type":"Age","maxAge":691200}}}]}'
          else
            printf '{"rules":[{"id":"cf-browser-prefix-expire-after-8-days-backup"}]}\n'
          fi
        elif [ "${3:-}" = "lifecycle" ] && [ "${4:-}" = "add" ]; then
          [ "${5:-}" = "$CF_BROWSER_TEST_EXPECTED_BUCKET" ]
          [ "${6:-}" = "cf-browser-prefix-expire-after-8-days" ]
          [ "${7:-}" = "cf-browser/" ]
          [ "${8:-}" = "--expire-days" ]
          [ "${9:-}" = "8" ]
          [ "${10:-}" = "--config" ]
          [ -f "${11:-}" ]
          [ -z "${CF_BROWSER_TEST_LIFECYCLE_MARKER:-}" ] \
            || : > "$CF_BROWSER_TEST_LIFECYCLE_MARKER"
          exit 0
        elif [ "${3:-}" = "list" ]; then
          printf 'Listing buckets...\n%s\n' \
            "${CF_BROWSER_TEST_BUCKET_LIST:-$CF_BROWSER_TEST_EXPECTED_BUCKET}"
        elif [ "${3:-}" = "create" ]; then
          [ "${4:-}" = "$CF_BROWSER_TEST_EXPECTED_BUCKET" ]
          [ "${CF_BROWSER_TEST_FAIL_R2_CREATE:-0}" != "1" ]
          exit 0
        else
          exit 1
        fi
        ;;
      "r2 object")
        object_path="${4:-}"
        [ "$object_path" = "${CF_BROWSER_TEST_EXPECTED_BUCKET}/.cf-browser-managed-v1" ]
        data_file=""
        previous_argument=""
        for argument in "$@"; do
          if [ "$previous_argument" = "--file" ]; then
            data_file="$argument"
            break
          fi
          previous_argument="$argument"
        done
        [ -n "$data_file" ]
        if [ "${3:-}" = "put" ]; then
          [ -f "$data_file" ]
          "$CF_BROWSER_TEST_REAL_PYTHON" - "$data_file" <<'PY'
import json
import os
import sys
from pathlib import Path

assert json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")) == {
    "schema": 1,
    "owner": "cf-browser",
    "account_id": os.environ["CF_BROWSER_TEST_EXPECTED_ACCOUNT_ID"],
    "bucket_name": os.environ["CF_BROWSER_TEST_EXPECTED_BUCKET"],
}
PY
          if [ -n "${CF_BROWSER_TEST_BUCKET_MARKER_STORE:-}" ]; then
            cp "$data_file" "$CF_BROWSER_TEST_BUCKET_MARKER_STORE"
          fi
        elif [ "${3:-}" = "get" ]; then
          if [ -f "${CF_BROWSER_TEST_BUCKET_MARKER_STORE:-/nonexistent}" ]; then
            cp "$CF_BROWSER_TEST_BUCKET_MARKER_STORE" "$data_file"
          elif [ "${CF_BROWSER_TEST_BUCKET_MARKER_MODE:-missing}" = "valid" ]; then
            "$CF_BROWSER_TEST_REAL_PYTHON" - "$data_file" <<'PY'
import json
import os
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(json.dumps({
    "schema": 1,
    "owner": "cf-browser",
    "account_id": os.environ["CF_BROWSER_TEST_EXPECTED_ACCOUNT_ID"],
    "bucket_name": os.environ["CF_BROWSER_TEST_EXPECTED_BUCKET"],
}) + "\n", encoding="utf-8")
PY
          elif [ "${CF_BROWSER_TEST_BUCKET_MARKER_MODE:-missing}" = "invalid" ]; then
            printf '{"owner":"some-other-application"}\n' > "$data_file"
          else
            exit 1
          fi
        else
          exit 1
        fi
        ;;
      "deploy --config")
        secrets_file=""
        while [ "$#" -gt 0 ]; do
          if [ "$1" = "--secrets-file" ]; then
            secrets_file="$2"
            break
          fi
          shift
        done
        [ -n "$secrets_file" ] && [ -f "$secrets_file" ]
        "$CF_BROWSER_TEST_REAL_PYTHON" - "$secrets_file" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text())
assert payload == {
    "CF_ACCOUNT_ID": os.environ["CF_BROWSER_TEST_EXPECTED_ACCOUNT_ID"],
    "CF_API_TOKEN": os.environ["CF_BROWSER_TEST_EXPECTED_TOKEN"],
    "API_KEYS": os.environ["CF_BROWSER_TEST_EXPECTED_KEY"],
}
assert stat.S_IMODE(path.stat().st_mode) == 0o600
PY
        printf 'Uploaded cf-browser\nhttps://cf-browser-test.workers.dev\n'
        ;;
      *)
        exit 1
        ;;
    esac
    ;;
  curl)
    for argument in "$@"; do
      [[ "$argument" != *"$CF_BROWSER_TEST_EXPECTED_KEY"* ]]
    done
    output_path=""
    url=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -o)
          output_path="$2"
          shift 2
          ;;
        http*)
          url="$1"
          shift
          ;;
        *)
          shift
          ;;
      esac
    done
    if [[ "$url" == */health ]]; then
      printf '{"ready":true}\n' > "$output_path"
    else
      printf '# rendered\n' > "$output_path"
    fi
    printf '200'
    ;;
  openssl)
    printf 'unused-test-key\n'
    ;;
  python|python3)
    if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
      mkdir -p "$3/bin"
      ln -s "$0" "$3/bin/python"
    elif [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then
      [ -z "${CF_API_TOKEN+x}" ]
      [ -z "${CF_BROWSER_API_KEY+x}" ]
      [ -z "${CLOUDFLARE_API_TOKEN+x}" ]
      [ -z "${CLOUDFLARE_API_KEY+x}" ]
      [ -z "${CLOUDFLARE_EMAIL+x}" ]
      for argument in "$@"; do
        [ "$argument" != "-e" ]
      done
      exit 0
    elif [ "${1:-}" = "-c" ] && [[ "${2:-}" == *"import cf_browser"* ]]; then
      [ -z "${CF_API_TOKEN+x}" ]
      [ -z "${CF_BROWSER_API_KEY+x}" ]
      [ -z "${CLOUDFLARE_API_TOKEN+x}" ]
      [ -z "${CLOUDFLARE_API_KEY+x}" ]
      [ -z "${CLOUDFLARE_EMAIL+x}" ]
      exit 0
    elif [ "${1:-}" = "-c" ] && [[ "${2:-}" == *"secrets.randbelow"* ]]; then
      printf '1001\n'
    else
      exec "$CF_BROWSER_TEST_REAL_PYTHON" "$@"
    fi
    ;;
  claude)
    printf 'claude %s\n' "$*" >> "$CF_BROWSER_TEST_CALL_LOG"
    for argument in "$@"; do
      [[ "$argument" != *"$CF_BROWSER_TEST_EXPECTED_KEY"* ]]
      if [ -n "${CF_BROWSER_TEST_OLD_MCP_SECRET:-}" ]; then
        [[ "$argument" != *"$CF_BROWSER_TEST_OLD_MCP_SECRET"* ]]
      fi
    done
    if [ "${1:-} ${2:-}" = "mcp remove" ]; then
      "$CF_BROWSER_TEST_REAL_PYTHON" - \
        "${CLAUDE_CONFIG_DIR:-${HOME}}/.claude.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if path.exists():
    state = json.loads(path.read_text(encoding="utf-8"))
    servers = state.get("mcpServers", {})
    servers.pop("cf-browser", None)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
PY
      exit 0
    fi
    if [ "${1:-} ${2:-}" = "mcp add" ] \
        && [ "${CF_BROWSER_TEST_CLAUDE_ADD_FAIL:-0}" = "1" ]; then
      exit 1
    fi
    exit 0
    ;;
  *)
    exit 127
    ;;
esac
MOCK
chmod 700 "$MOCK_BIN/dispatch"
for command_name in node npm npx curl openssl python3 claude; do
  ln -s "$MOCK_BIN/dispatch" "$MOCK_BIN/$command_name"
done

MOCK_API_TOKEN="test-token-not-a-secret"
MOCK_API_KEY="$(printf 'k%.0s' {1..32})"
MOCK_ACCOUNT_ID="cccccccccccccccccccccccccccccccc"
MOCK_R2_BUCKET="cf-browser-storage-${MOCK_ACCOUNT_ID}"
MOCK_WRANGLER_TOKEN="wrangler-token-sentinel"
MOCK_WRANGLER_KEY="wrangler-key-sentinel"
MOCK_WRANGLER_EMAIL="wrangler-email-sentinel@example.test"
SETUP_OUTPUT="$(
  env \
    PATH="$MOCK_BIN:/usr/bin:/bin" \
    HOME="$TEST_ROOT/home" \
    XDG_CONFIG_HOME="$TEST_ROOT/config" \
    CF_BROWSER_TEST_REAL_PYTHON="$REAL_PYTHON" \
    CF_BROWSER_TEST_CALL_LOG="$CALL_LOG" \
    CF_BROWSER_TEST_EXPECTED_TOKEN="$MOCK_API_TOKEN" \
    CF_BROWSER_TEST_EXPECTED_KEY="$MOCK_API_KEY" \
    CF_BROWSER_TEST_EXPECTED_ACCOUNT_ID="$MOCK_ACCOUNT_ID" \
    CF_BROWSER_TEST_EXPECTED_BUCKET="$MOCK_R2_BUCKET" \
    CF_BROWSER_TEST_BUCKET_MARKER_STORE="$TEST_ROOT/r2-ownership-marker" \
    CF_BROWSER_TEST_LIFECYCLE_MARKER="$TEST_ROOT/lifecycle-created" \
    CF_BROWSER_TEST_BUCKET_LIST="${MOCK_R2_BUCKET}-backup" \
    CF_ACCOUNT_ID="$MOCK_ACCOUNT_ID" \
    CF_API_TOKEN="$MOCK_API_TOKEN" \
    CF_BROWSER_API_KEY="$MOCK_API_KEY" \
    CLOUDFLARE_API_TOKEN="$MOCK_WRANGLER_TOKEN" \
    CLOUDFLARE_API_KEY="$MOCK_WRANGLER_KEY" \
    CLOUDFLARE_EMAIL="$MOCK_WRANGLER_EMAIL" \
    CF_BROWSER_ENABLE_INTERACTIONS=1 \
    /bin/bash "$FIXTURE/setup.sh" 2>&1
)"

[[ "$SETUP_OUTPUT" != *"$MOCK_API_TOKEN"* ]]
[[ "$SETUP_OUTPUT" != *"$MOCK_API_KEY"* ]]
[[ "$SETUP_OUTPUT" != *"$MOCK_WRANGLER_TOKEN"* ]]
[[ "$SETUP_OUTPUT" != *"$MOCK_WRANGLER_KEY"* ]]
[[ "$SETUP_OUTPUT" != *"$MOCK_WRANGLER_EMAIL"* ]]
grep -Fq 'deploy --config' "$CALL_LOG"
grep -Fq -- '--secrets-file' "$CALL_LOG"
grep -Fq "r2 bucket create ${MOCK_R2_BUCKET}" "$CALL_LOG"
grep -Fq \
  "r2 object put ${MOCK_R2_BUCKET}/.cf-browser-managed-v1 --file" \
  "$CALL_LOG"
grep -Fq \
  "r2 bucket lifecycle add ${MOCK_R2_BUCKET} cf-browser-prefix-expire-after-8-days cf-browser/ --expire-days 8 --config" \
  "$CALL_LOG"
if grep -Fq -- '--force' "$CALL_LOG"; then
  echo "setup unexpectedly bypassed Wrangler safety checks with --force" >&2
  exit 1
fi

WRONG_LIFECYCLE_FIXTURE="${TEST_ROOT}/wrong-lifecycle-repo"
WRONG_LIFECYCLE_CALL_LOG="${TEST_ROOT}/wrong-lifecycle-calls.log"
mkdir -p \
  "$WRONG_LIFECYCLE_FIXTURE/worker" \
  "$WRONG_LIFECYCLE_FIXTURE/sdk" \
  "$WRONG_LIFECYCLE_FIXTURE/mcp-server"
cp "$ROOT_DIR/setup.sh" "$WRONG_LIFECYCLE_FIXTURE/setup.sh"
if env \
    PATH="$MOCK_BIN:/usr/bin:/bin" \
    HOME="$TEST_ROOT/wrong-lifecycle-home" \
    XDG_CONFIG_HOME="$TEST_ROOT/wrong-lifecycle-config" \
    CF_BROWSER_TEST_REAL_PYTHON="$REAL_PYTHON" \
    CF_BROWSER_TEST_CALL_LOG="$WRONG_LIFECYCLE_CALL_LOG" \
    CF_BROWSER_TEST_EXPECTED_TOKEN="$MOCK_API_TOKEN" \
    CF_BROWSER_TEST_EXPECTED_KEY="$MOCK_API_KEY" \
    CF_BROWSER_TEST_EXPECTED_ACCOUNT_ID="$MOCK_ACCOUNT_ID" \
    CF_BROWSER_TEST_EXPECTED_BUCKET="$MOCK_R2_BUCKET" \
    CF_BROWSER_TEST_BUCKET_MARKER_MODE=valid \
    CF_BROWSER_TEST_LIFECYCLE_WRONG=1 \
    CF_BROWSER_TEST_BUCKET_LIST="$MOCK_R2_BUCKET" \
    CF_ACCOUNT_ID="$MOCK_ACCOUNT_ID" \
    CF_API_TOKEN="$MOCK_API_TOKEN" \
    CF_BROWSER_API_KEY="$MOCK_API_KEY" \
    /bin/bash "$WRONG_LIFECYCLE_FIXTURE/setup.sh" >/dev/null 2>&1; then
  echo "setup unexpectedly accepted a misconfigured lifecycle rule" >&2
  exit 1
fi
if grep -Fq 'r2 bucket lifecycle add' "$WRONG_LIFECYCLE_CALL_LOG"; then
  echo "setup unexpectedly attempted to duplicate a conflicting lifecycle rule" >&2
  exit 1
fi
if grep -Fq 'secret put' "$CALL_LOG"; then
  echo "setup unexpectedly used per-secret deployments" >&2
  exit 1
fi

MOCK_API_KEY="$MOCK_API_KEY" \
MOCK_ACCOUNT_ID="$MOCK_ACCOUNT_ID" \
MOCK_R2_BUCKET="$MOCK_R2_BUCKET" \
"$REAL_PYTHON" - "$TEST_ROOT" <<'PY'
import json
import os
import re
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
worker = (root / "repo/worker/wrangler.toml").read_text(encoding="utf-8")
assert re.search(
    rf'^account_id = "{os.environ["MOCK_ACCOUNT_ID"]}"$',
    worker,
    re.MULTILINE,
)
assert re.search(r'^compatibility_date = "2026-07-18"$', worker, re.MULTILINE)
assert re.search(
    r'^\[\[kv_namespaces\]\]\nbinding = "CACHE"\nid = "' + "b" * 32 + r'"$',
    worker,
    re.MULTILINE,
)
assert re.search(
    rf'^\[\[r2_buckets\]\]\nbinding = "STORAGE"\nbucket_name = "{os.environ["MOCK_R2_BUCKET"]}"$',
    worker,
    re.MULTILINE,
)
assert re.search(
    r'^\[\[ratelimits\]\]\nname = "RATE_LIMITER"\nnamespace_id = "4242"'
    r'\n\n  \[ratelimits\.simple\]\n  limit = 60\n  period = 60$',
    worker,
    re.MULTILINE,
)
assert re.search(r'^\[browser\]\nbinding = "BROWSER"$', worker, re.MULTILINE)

config_path = root / "config/cf-browser/mcp.json"
config = json.loads(config_path.read_text())
server = config["mcpServers"]["cf-browser"]
assert server["env"]["CF_BROWSER_MODE"] == "worker"
assert server["env"]["CF_BROWSER_URL"] == "https://cf-browser-test.workers.dev"
assert server["env"]["CF_BROWSER_API_KEY"] == os.environ["MOCK_API_KEY"]
assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
assert stat.S_IMODE(config_path.parent.stat().st_mode) == 0o700

launcher = root / "config/cf-browser/run-mcp"
assert launcher.exists()
assert stat.S_IMODE(launcher.stat().st_mode) == 0o700
assert os.environ["MOCK_API_KEY"] not in launcher.read_text(encoding="utf-8")

backups = list((root / "repo/worker").glob("wrangler.toml.*.bak"))
assert len(backups) == 1
assert 'name = "existing-cf-browser"' in backups[0].read_text()
assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
PY

ROLLBACK_CLAUDE_DIR="${TEST_ROOT}/rollback-claude"
ROLLBACK_CALL_LOG="${TEST_ROOT}/rollback-calls.log"
OLD_MCP_SECRET="old-registration-secret-sentinel"
mkdir -p "$ROLLBACK_CLAUDE_DIR"
OLD_MCP_SECRET="$OLD_MCP_SECRET" \
"$REAL_PYTHON" - "$ROLLBACK_CLAUDE_DIR/.claude.json" <<'PY'
import json
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
state = {
    "otherState": "must-survive",
    "mcpServers": {
        "other-server": {"command": "/other/server"},
        "cf-browser": {
            "type": "stdio",
            "command": "/old/server",
            "args": ["--old"],
            "env": {"OLD_SECRET": os.environ["OLD_MCP_SECRET"]},
        },
    },
}
path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
path.chmod(0o600)
PY

ROLLBACK_OUTPUT="$(
  env \
    PATH="$MOCK_BIN:/usr/bin:/bin" \
    HOME="$TEST_ROOT/rollback-home" \
    XDG_CONFIG_HOME="$TEST_ROOT/rollback-config" \
    CLAUDE_CONFIG_DIR="$ROLLBACK_CLAUDE_DIR" \
    CF_BROWSER_TEST_REAL_PYTHON="$REAL_PYTHON" \
    CF_BROWSER_TEST_CALL_LOG="$ROLLBACK_CALL_LOG" \
    CF_BROWSER_TEST_EXPECTED_TOKEN="$MOCK_API_TOKEN" \
    CF_BROWSER_TEST_EXPECTED_KEY="$MOCK_API_KEY" \
    CF_BROWSER_TEST_EXPECTED_ACCOUNT_ID="$MOCK_ACCOUNT_ID" \
    CF_BROWSER_TEST_OLD_MCP_SECRET="$OLD_MCP_SECRET" \
    CF_BROWSER_TEST_CLAUDE_ADD_FAIL=1 \
    CF_BROWSER_TEST_LIFECYCLE_PRESENT=1 \
    CF_BROWSER_TEST_BUCKET_LIST="cf-browser-storage" \
    CF_ACCOUNT_ID="$MOCK_ACCOUNT_ID" \
    CF_API_TOKEN="$MOCK_API_TOKEN" \
    CF_BROWSER_API_KEY="$MOCK_API_KEY" \
    CLOUDFLARE_API_TOKEN="$MOCK_WRANGLER_TOKEN" \
    CLOUDFLARE_API_KEY="$MOCK_WRANGLER_KEY" \
    CLOUDFLARE_EMAIL="$MOCK_WRANGLER_EMAIL" \
    /bin/bash "$FIXTURE/setup.sh" 2>&1
)"

[[ "$ROLLBACK_OUTPUT" == *"previous user-scoped registration was restored"* ]]
[[ "$ROLLBACK_OUTPUT" != *"$OLD_MCP_SECRET"* ]]
[[ "$ROLLBACK_OUTPUT" != *"$MOCK_API_TOKEN"* ]]
[[ "$ROLLBACK_OUTPUT" != *"$MOCK_API_KEY"* ]]
[[ "$ROLLBACK_OUTPUT" != *"$MOCK_WRANGLER_TOKEN"* ]]
[[ "$ROLLBACK_OUTPUT" != *"$MOCK_WRANGLER_KEY"* ]]
[[ "$ROLLBACK_OUTPUT" != *"$MOCK_WRANGLER_EMAIL"* ]]
[[ "$(<"$ROLLBACK_CALL_LOG")" != *"$OLD_MCP_SECRET"* ]]
grep -Fq 'claude mcp remove --scope user cf-browser' "$ROLLBACK_CALL_LOG"
grep -Fq 'claude mcp add --transport stdio --scope user cf-browser --' "$ROLLBACK_CALL_LOG"
grep -Fq 'r2 bucket lifecycle list cf-browser-storage' "$ROLLBACK_CALL_LOG"
if grep -Fq 'r2 bucket lifecycle add' "$ROLLBACK_CALL_LOG"; then
  echo "setup unexpectedly duplicated an existing R2 lifecycle rule" >&2
  exit 1
fi

OLD_MCP_SECRET="$OLD_MCP_SECRET" \
"$REAL_PYTHON" - "$ROLLBACK_CLAUDE_DIR/.claude.json" <<'PY'
import json
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
state = json.loads(path.read_text(encoding="utf-8"))
assert state["otherState"] == "must-survive"
assert state["mcpServers"]["other-server"] == {"command": "/other/server"}
assert state["mcpServers"]["cf-browser"] == {
    "type": "stdio",
    "command": "/old/server",
    "args": ["--old"],
    "env": {"OLD_SECRET": os.environ["OLD_MCP_SECRET"]},
}
assert stat.S_IMODE(path.stat().st_mode) == 0o600
PY

FAIL_FIXTURE="${TEST_ROOT}/failing-repo"
mkdir -p "$FAIL_FIXTURE/worker" "$FAIL_FIXTURE/sdk" "$FAIL_FIXTURE/mcp-server"
cp "$ROOT_DIR/setup.sh" "$FAIL_FIXTURE/setup.sh"
printf '%s\n' 'name = "must-survive"' > "$FAIL_FIXTURE/worker/wrangler.toml"
cp "$FAIL_FIXTURE/worker/wrangler.toml" "$FAIL_FIXTURE/original.toml"
if env \
    PATH="$MOCK_BIN:/usr/bin:/bin" \
    HOME="$TEST_ROOT/failing-home" \
    XDG_CONFIG_HOME="$TEST_ROOT/failing-config" \
    CF_BROWSER_TEST_REAL_PYTHON="$REAL_PYTHON" \
    CF_BROWSER_TEST_CALL_LOG="$CALL_LOG" \
    CF_BROWSER_TEST_EXPECTED_TOKEN="$MOCK_API_TOKEN" \
    CF_BROWSER_TEST_EXPECTED_KEY="$MOCK_API_KEY" \
    CF_BROWSER_TEST_EXPECTED_ACCOUNT_ID="$MOCK_ACCOUNT_ID" \
    CF_BROWSER_TEST_BUCKET_LIST="cf-browser-storage-backup" \
    CF_BROWSER_TEST_FAIL_R2_CREATE=1 \
    CF_ACCOUNT_ID="$MOCK_ACCOUNT_ID" \
    CF_API_TOKEN="$MOCK_API_TOKEN" \
    CF_BROWSER_API_KEY="$MOCK_API_KEY" \
    CLOUDFLARE_API_TOKEN="$MOCK_WRANGLER_TOKEN" \
    CLOUDFLARE_API_KEY="$MOCK_WRANGLER_KEY" \
    CLOUDFLARE_EMAIL="$MOCK_WRANGLER_EMAIL" \
    /bin/bash "$FAIL_FIXTURE/setup.sh" >/dev/null 2>&1; then
  echo "setup unexpectedly succeeded when R2 creation failed" >&2
  exit 1
fi
cmp -s "$FAIL_FIXTURE/original.toml" "$FAIL_FIXTURE/worker/wrangler.toml"
if compgen -G "$FAIL_FIXTURE/worker/.wrangler.setup.*.toml" >/dev/null; then
  echo "setup left a pending Wrangler config after failure" >&2
  exit 1
fi

echo "setup mock end-to-end: OK"
