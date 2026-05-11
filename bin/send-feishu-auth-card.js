#!/usr/bin/env node
const fs = require('fs');

const openclawHome = process.env.OPENCLAW_STATE_DIR || process.env.OPENCLAW_HOME || '/home/node/.openclaw';
const DEFAULTS = {
  HOME: `${openclawHome}/home`,
  XDG_DATA_HOME: `${openclawHome}/home/.local/share`,
  XDG_RUNTIME_DIR: `${openclawHome}/runtime`,
  XDG_STATE_HOME: `${openclawHome}/state`,
  XDG_CONFIG_HOME: `${openclawHome}/config`,
  XDG_CACHE_HOME: `${openclawHome}/cache`,
};

for (const [key, value] of Object.entries(DEFAULTS)) {
  process.env[key] = process.env[key] || value;
  fs.mkdirSync(process.env[key], { recursive: true });
}

const BASE_DIR = '/opt/opendd/lark-openapi';
const { LarkAuthHandlerLocal } = require(`${BASE_DIR}/node_modules/@larksuiteoapi/lark-mcp/dist/auth/handler/handler-local`);
const express = require(`${BASE_DIR}/node_modules/express`);

class PublicLarkAuthHandlerLocal extends LarkAuthHandlerLocal {
  get callbackUrl() {
    const publicUrl = String(this.options && this.options.publicUrl ? this.options.publicUrl : '').replace(/\/$/, '');
    return publicUrl ? `${publicUrl}/callback` : super.callbackUrl;
  }

  get issuerUrl() {
    const publicUrl = String(this.options && this.options.publicUrl ? this.options.publicUrl : '').replace(/\/$/, '');
    return publicUrl || super.issuerUrl;
  }
}

function arg(name) {
  const index = process.argv.indexOf(name);
  if (index >= 0 && index + 1 < process.argv.length) return process.argv[index + 1];
  return '';
}

function readJson(path) {
  return JSON.parse(fs.readFileSync(path, 'utf8'));
}

function defaultTarget() {
  const path = `${openclawHome}/credentials/feishu-default-allowFrom.json`;
  if (!fs.existsSync(path)) return '';
  const data = readJson(path);
  return Array.isArray(data.allowFrom) ? data.allowFrom[0] || '' : '';
}

function domainFromConfig(feishu) {
  return feishu.domain === 'lark' ? 'https://open.larksuite.com' : 'https://open.feishu.cn';
}

function appConsoleUrl(domain) {
  return domain.includes('larksuite.com') ? 'https://open.larksuite.com/app' : 'https://open.feishu.cn/app';
}

async function getTenantAccessToken(domain, appId, appSecret) {
  const response = await fetch(`${domain}/open-apis/auth/v3/tenant_access_token/internal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
  });
  const data = await response.json();
  if (!response.ok || data.code !== 0 || !data.tenant_access_token) {
    throw new Error(`tenant_access_token failed: ${JSON.stringify(data)}`);
  }
  return data.tenant_access_token;
}

async function sendInteractiveCard({ domain, appId, appSecret, target, card }) {
  const tenantToken = await getTenantAccessToken(domain, appId, appSecret);
  const receiveIdType = target.startsWith('oc_') ? 'chat_id' : 'open_id';
  const response = await fetch(`${domain}/open-apis/im/v1/messages?receive_id_type=${receiveIdType}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${tenantToken}`,
      'Content-Type': 'application/json; charset=utf-8',
    },
    body: JSON.stringify({
      receive_id: target,
      msg_type: 'interactive',
      content: JSON.stringify(card),
    }),
  });
  const data = await response.json();
  if (!response.ok || data.code !== 0) {
    throw new Error(`send card failed: ${JSON.stringify(data)}`);
  }
  return data;
}

function authCard(authUrl) {
  return {
    config: { wide_screen_mode: true },
    header: {
      template: 'blue',
      title: { tag: 'plain_text', content: 'OpenClaw 用户身份授权' },
    },
    elements: [
      {
        tag: 'markdown',
        content: [
          '请点击下方按钮完成飞书用户身份授权。',
          '',
          '授权后，OpenClaw 会按你的飞书权限读取知识库、文档和消息等数据。',
          '',
          '该链接 10 分钟内有效；过期后请重新发送授权卡片。',
        ].join('\n'),
      },
      {
        tag: 'action',
        actions: [
          {
            tag: 'button',
            text: { tag: 'plain_text', content: '去授权' },
            type: 'primary',
            url: authUrl,
          },
        ],
      },
    ],
  };
}

function setupGuideCard({ appId, callbackUrl, consoleUrl, authUrl }) {
  const actions = [
    {
      tag: 'button',
      text: { tag: 'plain_text', content: '打开开放平台' },
      type: 'default',
      url: consoleUrl,
    },
  ];
  if (authUrl) {
    actions.push({
      tag: 'button',
      text: { tag: 'plain_text', content: '配置完成后授权' },
      type: 'primary',
      url: authUrl,
    });
  }

  return {
    config: { wide_screen_mode: true },
    header: {
      template: 'blue',
      title: { tag: 'plain_text', content: 'OpenClaw 飞书授权配置' },
    },
    elements: [
      {
        tag: 'markdown',
        content: [
          '第一次使用前，需要先在飞书开放平台配置 OAuth 重定向 URL。',
          '',
          `App ID：${appId}`,
          `重定向 URL：${callbackUrl}`,
          '',
          '步骤：',
          '1. 打开飞书开放平台应用列表，选择上面的 App ID 对应应用。',
          '2. 进入「安全设置」->「重定向 URL」，添加上面的地址并保存。',
          authUrl ? '3. 保存后回到这张卡片，点击「配置完成后授权」。' : '3. 保存后重新给机器人发一条消息，或让管理员重发授权卡片。',
          authUrl ? '授权按钮约 10 分钟内有效；过期后系统会自动重发。' : '',
        ].join('\n'),
      },
      {
        tag: 'action',
        actions,
      },
    ],
  };
}

async function sendAuthCard({ domain, appId, appSecret, target, authUrl }) {
  return sendInteractiveCard({
    domain,
    appId,
    appSecret,
    target,
    card: authCard(authUrl),
  });
}

async function sendSetupGuideCard({ domain, appId, appSecret, target, publicUrl, authUrl }) {
  return sendInteractiveCard({
    domain,
    appId,
    appSecret,
    target,
    card: setupGuideCard({
      appId,
      callbackUrl: `${publicUrl}/callback`,
      consoleUrl: appConsoleUrl(domain),
      authUrl,
    }),
  });
}

async function sendGuidedAuthCard({ domain, appId, appSecret, target, publicUrl, authUrl }) {
  return sendSetupGuideCard({ domain, appId, appSecret, target, publicUrl, authUrl });
}

async function main() {
  const configPath = process.env.OPENCLAW_CONFIG || process.env.OPENCLAW_CONFIG_PATH || `${openclawHome}/openclaw.json`;
  const cfg = readJson(configPath);
  const feishu = cfg.channels && cfg.channels.feishu ? cfg.channels.feishu : {};
  const appId = feishu.appId || process.env.FEISHU_APP_ID;
  const appSecret = feishu.appSecret || process.env.FEISHU_APP_SECRET;
  const target = arg('--target') || process.env.FEISHU_AUTH_TARGET || process.env.FEISHU_OWNER_OPEN_ID || defaultTarget();
  const publicUrl = (arg('--public-url') || process.env.LARK_MCP_PUBLIC_URL || process.env.OPENCLAW_PUBLIC_URL || '').replace(/\/$/, '');
  const mode = arg('--mode') || process.env.FEISHU_AUTH_CARD_MODE || 'auth';
  const host = arg('--host') || process.env.LARK_MCP_LOGIN_HOST || '0.0.0.0';
  const port = Number(arg('--port') || process.env.LARK_MCP_LOGIN_PORT || 31888);
  const scopeText = process.env.LARK_MCP_SCOPE || [
    'offline_access',
    'auth:user.id:read',
    'contact:user.base:readonly',
    'contact:user.basic_profile:readonly',
    'contact:contact.base:readonly',
    'wiki:space:retrieve',
    'wiki:node:read',
    'wiki:node:retrieve',
    'space:document:retrieve',
    'docx:document:readonly',
    'sheets:spreadsheet.meta:read',
    'sheets:spreadsheet:read',
    'base:app:read',
    'base:table:read',
    'base:field:read',
    'base:view:read',
    'base:record:retrieve',
    'search:docs:read',
    'im:chat:read',
    'im:chat.members:read',
    'im:message:readonly',
    'im:message.group_msg:get_as_user',
    'im:message.p2p_msg:get_as_user',
    'search:message',
  ].join(' ');

  if (!appId || !appSecret || typeof appSecret !== 'string') {
    throw new Error('Feishu appId/appSecret not found in OpenClaw config or environment.');
  }
  if (!target) {
    throw new Error('Missing target. Pass --target <open_id|chat_id> or set FEISHU_OWNER_OPEN_ID.');
  }
  if (!publicUrl) {
    throw new Error('Missing public URL. Set OPENCLAW_PUBLIC_URL or LARK_MCP_PUBLIC_URL.');
  }

  process.env.LARK_MCP_PUBLIC_URL = publicUrl;
  const domain = domainFromConfig(feishu);
  if (mode === 'setup') {
    const sent = await sendSetupGuideCard({
      domain,
      appId,
      appSecret,
      target,
      publicUrl,
      authUrl: '',
    });
    console.log(`callback=${publicUrl}/callback`);
    console.log(`target=${target}`);
    console.log(`setup_card_sent=${sent.data?.message_id || 'ok'}`);
    return;
  }

  const app = express();
  app.set('trust proxy', 1);
  app.use(express.json());

  const authHandler = new PublicLarkAuthHandlerLocal(app, {
    port,
    host,
    domain,
    appId,
    appSecret,
    publicUrl,
    scope: scopeText.split(/\s+/).filter(Boolean),
  });

  authHandler.setupRoutes();
  const result = await authHandler.reAuthorize(undefined, true);
  if (!result.authorizeUrl) throw new Error('Authorization URL was not generated.');
  const authorizeUrl = new URL(result.authorizeUrl);
  authorizeUrl.protocol = new URL(publicUrl).protocol;
  authorizeUrl.host = new URL(publicUrl).host;

  console.log(`callback=${authHandler.callbackUrl}`);
  console.log(`target=${target}`);
  console.log(`authorization_url=${authorizeUrl.toString()}`);

  const sender = mode === 'guided' ? sendGuidedAuthCard : sendAuthCard;
  const sent = await sender({
    domain,
    appId,
    appSecret,
    target,
    publicUrl,
    authUrl: authorizeUrl.toString(),
  });
  console.log(`card_sent=${sent.data?.message_id || 'ok'}`);
  console.log('waiting_for_authorization=10m');
  setTimeout(() => {
    console.log('auth_card_window_expired');
    process.exit(0);
  }, 11 * 60 * 1000);
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
