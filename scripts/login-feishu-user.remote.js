#!/usr/bin/env node
const fs = require('fs');
const { spawn } = require('child_process');
const { feishuOAuthScopeText } = require('./feishu-oauth-scopes');

const openclawHome = process.env.OPENCLAW_STATE_DIR || process.env.OPENCLAW_HOME || '/home/node/.openclaw';
const runtimeEnv = {
  ...process.env,
  OPENCLAW_STATE_DIR: openclawHome,
  OPENCLAW_HOME: openclawHome,
  HOME: `${openclawHome}/home`,
  XDG_DATA_HOME: `${openclawHome}/home/.local/share`,
  XDG_RUNTIME_DIR: `${openclawHome}/runtime`,
  XDG_STATE_HOME: `${openclawHome}/state`,
  XDG_CONFIG_HOME: `${openclawHome}/config`,
  XDG_CACHE_HOME: `${openclawHome}/cache`,
};
for (const dir of [runtimeEnv.HOME, runtimeEnv.XDG_RUNTIME_DIR, runtimeEnv.XDG_DATA_HOME, runtimeEnv.XDG_STATE_HOME, runtimeEnv.XDG_CONFIG_HOME, runtimeEnv.XDG_CACHE_HOME]) {
  fs.mkdirSync(dir, { recursive: true });
}

const configPath = process.env.OPENCLAW_CONFIG || process.env.OPENCLAW_CONFIG_PATH || `${openclawHome}/openclaw.json`;
const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const feishu = cfg.channels && cfg.channels.feishu ? cfg.channels.feishu : {};
const appId = feishu.appId || process.env.FEISHU_APP_ID;
const appSecret = feishu.appSecret || process.env.FEISHU_APP_SECRET;
if (!appId || !appSecret || typeof appSecret !== 'string') {
  console.error('Feishu appId/appSecret not found in OpenClaw config or environment.');
  process.exit(1);
}

const wrap = '/opt/opendd/bin/with-keyring.sh';
const bin = '/opt/opendd/lark-openapi/node_modules/.bin/lark-mcp';
const host = process.env.LARK_MCP_LOGIN_HOST || '0.0.0.0';
const port = process.env.LARK_MCP_LOGIN_PORT || '31888';
const scope = feishuOAuthScopeText();
const publicUrl = (process.env.LARK_MCP_PUBLIC_URL || process.env.OPENCLAW_PUBLIC_URL || `http://${host}:${port}`).replace(/\/$/, '');
const args = [
  bin,
  'login',
  '--app-id', appId,
  '--app-secret', appSecret,
  '--domain', feishu.domain === 'lark' ? 'https://open.larksuite.com' : 'https://open.feishu.cn',
  '--host', host,
  '--port', port,
  '--scope', scope,
];

console.log(`OAuth callback should be configured in Feishu as: ${publicUrl}/callback`);
const child = spawn(wrap, args, { stdio: 'inherit', env: runtimeEnv });
child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 0);
});
