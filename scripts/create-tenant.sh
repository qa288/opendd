#!/usr/bin/env bash
set -euo pipefail

tenant_id="${TENANT_ID:?set TENANT_ID, e.g. user001}"
tenant_domain="${TENANT_DOMAIN:?set TENANT_DOMAIN, e.g. user001.ope.tyos.cc}"
web_port="${WEB_PORT:?set WEB_PORT, e.g. 18791}"
oauth_port="${OAUTH_PORT:?set OAUTH_PORT, e.g. 31891}"
base_dir="${OPENCLAW_TENANT_ROOT:-/data/openclaw-tenants}"
tenant_dir="${base_dir}/${tenant_id}"

mkdir -p "${tenant_dir}/openclaw" "${tenant_dir}/backups"
install -m 0644 compose/docker-compose.tenant.yml "${tenant_dir}/docker-compose.yml"

gateway_token="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
cat >"${tenant_dir}/.env" <<ENV
TENANT_ID=${tenant_id}
TENANT_DOMAIN=${tenant_domain}
TENANT_DATA_DIR=${tenant_dir}/openclaw
WEB_PORT=${web_port}
OAUTH_PORT=${oauth_port}
OPENDD_IMAGE=${OPENDD_IMAGE:-ghcr.io/qa288/opendd:2026.5.7}
OPENDD_RENDER_CONFIG=missing
OPENDD_SEND_AUTH_CARD_ON_START=${OPENDD_SEND_AUTH_CARD_ON_START:-0}
OPENDD_PAIRING_AUTH_WATCHER=${OPENDD_PAIRING_AUTH_WATCHER:-1}
FEISHU_AUTH_CARD_MODE=${FEISHU_AUTH_CARD_MODE:-guided}
OPENCLAW_GATEWAY_TOKEN=${gateway_token}
OPENCLAW_MODEL_PROVIDER=${OPENCLAW_MODEL_PROVIDER:-bailian-coding-plan}
OPENCLAW_MODEL_ID=${OPENCLAW_MODEL_ID:-qwen3.6-plus}
OPENCLAW_MODEL_API=${OPENCLAW_MODEL_API:-openai-completions}
OPENCLAW_MODEL_BASE_URL=${OPENCLAW_MODEL_BASE_URL:-https://coding.dashscope.aliyuncs.com/v1}
OPENCLAW_MODEL_API_KEY=${OPENCLAW_MODEL_API_KEY:-}
DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY:-}
OPENCLAW_EMBEDDING_PROVIDER=${OPENCLAW_EMBEDDING_PROVIDER:-openai}
OPENCLAW_EMBEDDING_API_KEY=${OPENCLAW_EMBEDDING_API_KEY:-}
OPENCLAW_EMBEDDING_MODEL=${OPENCLAW_EMBEDDING_MODEL:-text-embedding-v4}
OPENCLAW_EMBEDDING_BASE_URL=${OPENCLAW_EMBEDDING_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}
FEISHU_ENABLED=true
FEISHU_DOMAIN=${FEISHU_DOMAIN:-feishu}
FEISHU_APP_ID=${FEISHU_APP_ID:-}
FEISHU_APP_SECRET=${FEISHU_APP_SECRET:-}
FEISHU_OWNER_OPEN_ID=${FEISHU_OWNER_OPEN_ID:-}
FEISHU_AUTH_TARGET_MODE=${FEISHU_AUTH_TARGET_MODE:-first_sender}
FEISHU_AUTH_BIND_FIRST_USER=${FEISHU_AUTH_BIND_FIRST_USER:-1}
FEISHU_DM_POLICY=${FEISHU_DM_POLICY:-pairing}
FEISHU_GROUP_POLICY=${FEISHU_GROUP_POLICY:-open}
FEISHU_GROUP_OWNER_ONLY=${FEISHU_GROUP_OWNER_ONLY:-1}
ENV
chmod 600 "${tenant_dir}/.env"

cat <<EOF
tenant=${tenant_id}
path=${tenant_dir}
compose=${tenant_dir}/docker-compose.yml
domain=https://${tenant_domain}
callback=https://${tenant_domain}/callback
gateway_token=${gateway_token}

Next:
  1. Fill ${tenant_dir}/.env with model, embedding, and Feishu app values.
  2. Add Feishu redirect URL: https://${tenant_domain}/callback
  3. Configure reverse proxy:
     https://${tenant_domain}/ -> 127.0.0.1:${web_port}
     https://${tenant_domain}/authorize and /callback -> 127.0.0.1:${oauth_port}
  4. Start:
     cd ${tenant_dir} && docker compose up -d
EOF
