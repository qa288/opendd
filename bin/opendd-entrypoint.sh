#!/usr/bin/env bash
set -euo pipefail

export HOME="${HOME:-/home/node}"
export OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-/home/node/.openclaw}"
export OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-${OPENCLAW_STATE_DIR}/openclaw.json}"
export OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-${OPENCLAW_CONFIG_PATH}}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-${OPENCLAW_STATE_DIR}/runtime}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-${OPENCLAW_STATE_DIR}/home/.local/share}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-${OPENCLAW_STATE_DIR}/state}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-${OPENCLAW_STATE_DIR}/config}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${OPENCLAW_STATE_DIR}/cache}"
export LARK_MCP_PUBLIC_URL="${LARK_MCP_PUBLIC_URL:-${OPENCLAW_PUBLIC_URL:-}}"
export LARK_MCP_LOGIN_HOST="${LARK_MCP_LOGIN_HOST:-0.0.0.0}"
export LARK_MCP_LOGIN_PORT="${LARK_MCP_LOGIN_PORT:-31888}"

if [[ "$(id -u)" == "0" ]]; then
  mkdir -p "${OPENCLAW_STATE_DIR}"
  chown -R node:node "${OPENCLAW_STATE_DIR}"
  exec setpriv --reuid=node --regid=node --init-groups /opt/opendd/bin/opendd-entrypoint.sh "$@"
fi

mkdir -p \
  "${OPENCLAW_STATE_DIR}" \
  "${OPENCLAW_STATE_DIR}/credentials" \
  "${OPENCLAW_STATE_DIR}/workspace" \
  "${OPENCLAW_STATE_DIR}/mcp" \
  "${XDG_RUNTIME_DIR}" \
  "${XDG_DATA_HOME}" \
  "${XDG_STATE_HOME}" \
  "${XDG_CONFIG_HOME}" \
  "${XDG_CACHE_HOME}"

if [[ ! -e "${OPENCLAW_STATE_DIR}/mcp/lark-openapi" ]]; then
  ln -s /opt/opendd/lark-openapi "${OPENCLAW_STATE_DIR}/mcp/lark-openapi"
fi

if [[ ! -d "${OPENCLAW_STATE_DIR}/npm/node_modules/@openclaw/feishu" ]]; then
  mkdir -p "${OPENCLAW_STATE_DIR}/npm"
  cp -a /opt/opendd/openclaw-npm/. "${OPENCLAW_STATE_DIR}/npm/"
fi

if [[ -n "${FEISHU_OWNER_OPEN_ID:-}" && ! -f "${OPENCLAW_STATE_DIR}/credentials/feishu-default-allowFrom.json" ]]; then
  node -e "const fs=require('fs'); const p=process.env.OPENCLAW_STATE_DIR+'/credentials/feishu-default-allowFrom.json'; fs.writeFileSync(p, JSON.stringify({version:1, allowFrom:[process.env.FEISHU_OWNER_OPEN_ID]}, null, 2)+'\n');"
fi

if [[ ! -f "${OPENCLAW_CONFIG_PATH}" || "${OPENDD_RENDER_CONFIG:-missing}" == "always" ]]; then
  node /opt/opendd/bin/render-openclaw-config.js
fi

if [[ "${OPENDD_SEND_AUTH_CARD_ON_START:-0}" == "1" ]]; then
  token_file="${XDG_DATA_HOME}/lark-mcp-nodejs/storage.json"
  if [[ ! -f "${token_file}" ]]; then
    nohup node /opt/opendd/bin/send-feishu-auth-card.js \
      >"${OPENCLAW_STATE_DIR}/send-feishu-auth-card.log" 2>&1 &
  fi
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
