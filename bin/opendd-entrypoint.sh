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

prepare_plugin_extension() {
  local plugin_id="$1"
  local package_dir="$2"
  local dependency_root="$3"
  local destination="${OPENCLAW_STATE_DIR}/extensions/${plugin_id}"

  [[ -d "${package_dir}" ]] || return 0

  if [[ ! -f "${destination}/openclaw.plugin.json" || "${OPENDD_REFRESH_PLUGIN_EXTENSIONS:-0}" == "1" ]]; then
    rm -rf "${destination}"
    mkdir -p "$(dirname "${destination}")"
    cp -a "${package_dir}" "${destination}"
  fi

  mkdir -p "${destination}/node_modules"
  ln -sfn /app "${destination}/node_modules/openclaw"
  node - "${package_dir}" "${dependency_root}" "${destination}" <<'NODE'
const fs = require('fs');
const path = require('path');

const [packageDir, dependencyRoot, destination] = process.argv.slice(2);
const packageJson = JSON.parse(fs.readFileSync(path.join(packageDir, 'package.json'), 'utf8'));
const deps = Object.keys(packageJson.dependencies || {});
for (const dep of deps) {
  const source = path.join(dependencyRoot, dep);
  if (!fs.existsSync(source)) continue;
  const link = path.join(destination, 'node_modules', dep);
  fs.mkdirSync(path.dirname(link), { recursive: true });
  fs.rmSync(link, { recursive: true, force: true });
  fs.symlinkSync(source, link, 'dir');
}
NODE

  # OpenClaw blocks plugin sources owned by the runtime user. Keep source files
  # root-owned but world-readable so the node process can load them.
  chown -R root:root "${destination}"
  find "${destination}" -type d -exec chmod 755 {} +
  find "${destination}" -type f -exec chmod 644 {} +
}

refresh_plugin_registry() {
  [[ -f "${OPENCLAW_CONFIG_PATH}" ]] || return 0
  mkdir -p "${OPENCLAW_STATE_DIR}/plugins"
  OPENCLAW_HOME="${OPENCLAW_STATE_DIR}" \
    OPENCLAW_CONFIG="${OPENCLAW_CONFIG_PATH}" \
    OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH}" \
    openclaw plugins registry --refresh || true
  chown -R node:node "${OPENCLAW_STATE_DIR}/plugins" 2>/dev/null || true
  chmod 700 "${OPENCLAW_STATE_DIR}/plugins" 2>/dev/null || true
  chmod 600 "${OPENCLAW_STATE_DIR}/plugins/installs.json" 2>/dev/null || true
}

if [[ "$(id -u)" == "0" ]]; then
  mkdir -p "${OPENCLAW_STATE_DIR}"
  chown -R node:node "${OPENCLAW_STATE_DIR}"
  prepare_plugin_extension \
    "feishu" \
    "/opt/opendd/openclaw-npm/node_modules/@openclaw/feishu" \
    "/opt/opendd/openclaw-npm/node_modules"
  if [[ "${OPENCLAW_WEIXIN_PLUGIN_ENABLED:-1}" != "0" ]]; then
    prepare_plugin_extension \
      "openclaw-weixin" \
      "/opt/opendd/weixin-npm/node_modules/@tencent-weixin/openclaw-weixin" \
      "/opt/opendd/weixin-npm/node_modules"
  fi
  if [[ ! -f "${OPENCLAW_CONFIG_PATH}" || "${OPENDD_RENDER_CONFIG:-missing}" == "always" ]]; then
    node /opt/opendd/bin/render-openclaw-config.js
    chown node:node "${OPENCLAW_CONFIG_PATH}" 2>/dev/null || true
    chmod 600 "${OPENCLAW_CONFIG_PATH}" 2>/dev/null || true
  fi
  refresh_plugin_registry
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

if [[ "${OPENDD_PAIRING_AUTH_WATCHER:-0}" == "1" || "${FEISHU_AUTH_TARGET_MODE:-fixed}" != "fixed" ]]; then
  mkdir -p "${OPENCLAW_STATE_DIR}/logs"
  nohup node /opt/opendd/bin/feishu-pairing-auth-watcher.js \
    >"${OPENCLAW_STATE_DIR}/logs/feishu-pairing-auth-watcher.log" 2>&1 &
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
