#!/usr/bin/env bash
set -euo pipefail

export OPENCLAW_HOME="${OPENCLAW_HOME:-/home/node/.openclaw}"
export HOME="${HOME:-/home/node}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-${OPENCLAW_HOME}/runtime}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-${OPENCLAW_HOME}/home/.local/share}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-${OPENCLAW_HOME}/state}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-${OPENCLAW_HOME}/config}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${OPENCLAW_HOME}/cache}"
export LARK_MCP_PUBLIC_URL="${LARK_MCP_PUBLIC_URL:-${OPENCLAW_PUBLIC_URL:-}}"
export LARK_MCP_LOGIN_HOST="${LARK_MCP_LOGIN_HOST:-0.0.0.0}"
export LARK_MCP_LOGIN_PORT="${LARK_MCP_LOGIN_PORT:-31888}"

if [[ "$(id -u)" == "0" ]]; then
  mkdir -p "${OPENCLAW_HOME}"
  chown -R node:node "${OPENCLAW_HOME}"
  exec setpriv --reuid=node --regid=node --init-groups /opt/opendd/bin/opendd-entrypoint.sh "$@"
fi

mkdir -p \
  "${OPENCLAW_HOME}" \
  "${OPENCLAW_HOME}/credentials" \
  "${OPENCLAW_HOME}/workspace" \
  "${OPENCLAW_HOME}/mcp" \
  "${XDG_RUNTIME_DIR}" \
  "${XDG_DATA_HOME}" \
  "${XDG_STATE_HOME}" \
  "${XDG_CONFIG_HOME}" \
  "${XDG_CACHE_HOME}"

if [[ ! -e "${OPENCLAW_HOME}/mcp/lark-openapi" ]]; then
  ln -s /opt/opendd/lark-openapi "${OPENCLAW_HOME}/mcp/lark-openapi"
fi

if [[ -n "${FEISHU_OWNER_OPEN_ID:-}" && ! -f "${OPENCLAW_HOME}/credentials/feishu-default-allowFrom.json" ]]; then
  node -e "const fs=require('fs'); const p=process.env.OPENCLAW_HOME+'/credentials/feishu-default-allowFrom.json'; fs.writeFileSync(p, JSON.stringify({version:1, allowFrom:[process.env.FEISHU_OWNER_OPEN_ID]}, null, 2)+'\n');"
fi

if [[ ! -f "${OPENCLAW_HOME}/openclaw.json" || "${OPENDD_RENDER_CONFIG:-missing}" == "always" ]]; then
  node /opt/opendd/bin/render-openclaw-config.js
fi

if [[ "${OPENDD_SEND_AUTH_CARD_ON_START:-0}" == "1" ]]; then
  token_file="${XDG_DATA_HOME}/lark-mcp-nodejs/storage.json"
  if [[ ! -f "${token_file}" ]]; then
    nohup node /opt/opendd/bin/send-feishu-auth-card.js \
      >"${OPENCLAW_HOME}/send-feishu-auth-card.log" 2>&1 &
  fi
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
