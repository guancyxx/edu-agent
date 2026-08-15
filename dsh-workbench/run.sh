#!/usr/bin/env bash
set -euo pipefail

# Configurable via flags or env
PORT="${PORT:-3090}"
DSH_HOME_DIR="${DSH_HOME_DIR:-$PWD/.dsh-home}"
EDU_BACKEND="${EDU_BACKEND:-http://127.0.0.1:8000}"
EDU_JWT_SECRET="${EDU_JWT_SECRET:-}"   # empty -> plugin default (matches backend dev default)
EDU_TOKEN="${EDU_TOKEN:-}"             # student JWT; edu-tools calls the backend with it
NODE_BIN="${NODE_BIN:-/Users/guanchunyuan/.nvm/versions/node/v24.12.0/bin/node}"
DSH_REPO="${DSH_REPO:-$HOME/workspace/deepseek-harness}"
WORKBENCH_DIR="$(cd "$(dirname "$0")" && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --dsh-home) DSH_HOME_DIR="$2"; shift 2 ;;
    --edu-backend) EDU_BACKEND="$2"; shift 2 ;;
    --jwt-secret) EDU_JWT_SECRET="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$DSH_HOME_DIR/patches"

# 1) Generate per-run cordis.yml overlays with correct absolute paths.
#    The committed yml files were authored in different worktrees, so match
#    ANY existing path that ends in dsh-workbench/plugins/<plug>/src/index.ts.
for plug in edu-auth edu-session-owner edu-tools; do
  sed "s#name: '[^']*dsh-workbench/plugins/$plug/src/index.ts'#name: '$WORKBENCH_DIR/plugins/$plug/src/index.ts'#g" \
    "$WORKBENCH_DIR/plugins/$plug/cordis.yml" > "$DSH_HOME_DIR/patches/$plug.cordis.yml"
done

# 2) Provision the student preset (presets only load from DSH_HOME)
mkdir -p "$DSH_HOME_DIR/.agent-presets/student"
cp "$WORKBENCH_DIR/presets/student/preset.yml" "$DSH_HOME_DIR/.agent-presets/student/"
# swap greet placeholder row for the edu-tools plugin row
sed "s#- id: edu-greet#- id: edu-tools#; \
     s#name: '.*scratch-plugin/src/my-plugin.ts'#name: '$WORKBENCH_DIR/plugins/edu-tools/src/index.ts'#" \
    "$WORKBENCH_DIR/presets/student/agent.cordis.yml" > "$DSH_HOME_DIR/.agent-presets/student/agent.cordis.yml"

# 3) Launch
cd "$DSH_REPO"
exec env DSH_HOME="$DSH_HOME_DIR" EDU_BASE_URL="$EDU_BACKEND" \
  ${EDU_JWT_SECRET:+EDU_JWT_SECRET="$EDU_JWT_SECRET"} \
  ${EDU_TOKEN:+EDU_TOKEN="$EDU_TOKEN"} \
  "$NODE_BIN" --import tsx/esm apps/cli/src/bin.ts --profile web \
  --patch "$DSH_HOME_DIR/patches/edu-auth.cordis.yml" \
  --patch "$DSH_HOME_DIR/patches/edu-session-owner.cordis.yml" \
  --patch "$DSH_HOME_DIR/patches/edu-tools.cordis.yml" \
  --port "$PORT"
