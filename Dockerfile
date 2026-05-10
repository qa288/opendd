ARG OPENCLAW_VERSION=2026.5.7
FROM 1panel/openclaw:${OPENCLAW_VERSION}

USER root

ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG LARK_MCP_VERSION=0.5.1
ARG FEISHU_PLUGIN_VERSION=2026.5.7

ENV OPENDD_HOME=/opt/opendd \
    OPENDD_LARK_MCP_HOME=/opt/opendd/lark-openapi \
    OPENCLAW_STATE_DIR=/home/node/.openclaw \
    OPENCLAW_CONFIG_PATH=/home/node/.openclaw/openclaw.json \
    OPENCLAW_PORT=18789 \
    LARK_MCP_LOGIN_PORT=31888 \
    NODE_ENV=production

RUN mkdir -p /opt/opendd/lark-openapi /opt/opendd/openclaw-npm /opt/opendd/bin /home/node/.openclaw \
  && chown -R node:node /opt/opendd /home/node/.openclaw

WORKDIR /opt/opendd/lark-openapi
RUN npm config set registry "${NPM_REGISTRY}" \
  && npm init -y >/dev/null \
  && npm install --omit=dev "@larksuiteoapi/lark-mcp@${LARK_MCP_VERSION}" express@4

WORKDIR /opt/opendd/openclaw-npm
RUN npm config set registry "${NPM_REGISTRY}" \
  && npm init -y >/dev/null \
  && npm install --omit=dev "@openclaw/feishu@${FEISHU_PLUGIN_VERSION}"

COPY --chown=node:node bin/ /opt/opendd/bin/
RUN chmod +x /opt/opendd/bin/*.sh /opt/opendd/bin/*.js \
  && ln -sf /opt/opendd/bin/send-feishu-auth-card.js /usr/local/bin/opendd-send-feishu-auth-card \
  && ln -sf /opt/opendd/bin/render-openclaw-config.js /usr/local/bin/opendd-render-config \
  && chown -R node:node /opt/opendd /home/node/.openclaw

USER root
WORKDIR /app

ENTRYPOINT ["/opt/opendd/bin/opendd-entrypoint.sh"]
CMD ["node", "openclaw.mjs", "gateway", "--allow-unconfigured"]
