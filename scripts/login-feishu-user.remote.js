#!/usr/bin/env node
const fs = require('fs');
const { spawn } = require('child_process');

const runtimeEnv = {
  ...process.env,
  HOME: '/home/node/.openclaw/home',
  XDG_DATA_HOME: '/home/node/.openclaw/home/.local/share',
  XDG_RUNTIME_DIR: '/home/node/.openclaw/runtime',
  XDG_STATE_HOME: '/home/node/.openclaw/state',
  XDG_CONFIG_HOME: '/home/node/.openclaw/config',
  XDG_CACHE_HOME: '/home/node/.openclaw/cache',
};
for (const dir of [runtimeEnv.XDG_RUNTIME_DIR, runtimeEnv.XDG_DATA_HOME, runtimeEnv.XDG_STATE_HOME, runtimeEnv.XDG_CONFIG_HOME, runtimeEnv.XDG_CACHE_HOME]) {
  fs.mkdirSync(dir, { recursive: true });
}

const configPath = process.env.OPENCLAW_CONFIG || '/home/node/.openclaw/openclaw.json';
const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const feishu = cfg.channels && cfg.channels.feishu ? cfg.channels.feishu : {};
const appId = feishu.appId;
const appSecret = feishu.appSecret;
if (!appId || !appSecret || typeof appSecret !== 'string') {
  console.error('Feishu appId/appSecret not found in OpenClaw config.');
  process.exit(1);
}

const wrap = '/home/node/.openclaw/mcp/lark-openapi/bin/with-keyring.sh';
const bin = '/home/node/.openclaw/mcp/lark-openapi/node_modules/.bin/lark-mcp';
const host = process.env.LARK_MCP_LOGIN_HOST || 'localhost';
const port = process.env.LARK_MCP_LOGIN_PORT || '31888';
const defaultOAuthScope = "auth:user.id:read contact:user.base:readonly contact:user.basic_profile:readonly contact:contact.base:readonly wiki:space:retrieve wiki:node:read wiki:node:retrieve space:document:retrieve docx:document:readonly sheets:spreadsheet.meta:read sheets:spreadsheet:read base:app:read base:table:read base:field:read base:view:read base:record:retrieve search:docs:read im:chat:read im:chat.members:read im:message:readonly im:message.group_msg:get_as_user im:message.p2p_msg:get_as_user search:message";
const scope = process.env.LARK_MCP_SCOPE || defaultOAuthScope;
const args = [
  bin,
  'login',
  '--app-id', appId,
  '--app-secret', appSecret,
  '--domain', feishu.domain === 'lark' ? 'https://open.larksuite.com' : 'https://open.feishu.cn',
  '--host', host,
  '--port', port,
];
if (scope) args.push('--scope', scope);

console.log(`OAuth callback should be configured in Feishu as: http://${host}:${port}/callback`);
const child = spawn(wrap, args, { stdio: 'inherit', env: runtimeEnv });
child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 0);
});
