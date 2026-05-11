#!/usr/bin/env node
const fs = require('fs');
const { spawn } = require('child_process');

const openclawHome = process.env.OPENCLAW_STATE_DIR || process.env.OPENCLAW_HOME || '/home/node/.openclaw';
const credentialsDir = `${openclawHome}/credentials`;
const pairingPath = process.env.FEISHU_PAIRING_FILE || `${credentialsDir}/feishu-pairing.json`;
const allowFromPath = process.env.FEISHU_ALLOW_FROM_FILE || `${credentialsDir}/feishu-default-allowFrom.json`;
const statePath = process.env.FEISHU_AUTH_WATCHER_STATE_FILE || `${credentialsDir}/feishu-auth-card-sent.json`;
const mode = process.env.FEISHU_AUTH_TARGET_MODE || 'first_sender';
const publicUrl = (process.env.OPENCLAW_PUBLIC_URL || process.env.LARK_MCP_PUBLIC_URL || '').replace(/\/$/, '');
const pollMs = Number(process.env.FEISHU_AUTH_WATCHER_POLL_MS || 15000);
const cooldownMs = Number(process.env.FEISHU_AUTH_CARD_COOLDOWN_MS || 6 * 60 * 60 * 1000);
const sendScript = process.env.FEISHU_AUTH_CARD_SCRIPT || '/opt/opendd/bin/send-feishu-auth-card.js';
const bindFirstUser = String(process.env.FEISHU_AUTH_BIND_FIRST_USER || '1') !== '0';
const once = process.argv.includes('--once') || process.env.FEISHU_AUTH_WATCHER_ONCE === '1';

function now() {
  return new Date().toISOString();
}

function log(message) {
  console.log(`${now()} ${message}`);
}

function safeId(value) {
  const text = String(value || '');
  if (text.length <= 10) return text || '-';
  return `${text.slice(0, 6)}...${text.slice(-4)}`;
}

function readJson(path, fallback) {
  try {
    if (!fs.existsSync(path)) return fallback;
    return JSON.parse(fs.readFileSync(path, 'utf8'));
  } catch (error) {
    log(`WARN read_json_failed path=${path} error=${error.message}`);
    return fallback;
  }
}

function writeJson(path, value) {
  fs.mkdirSync(require('path').dirname(path), { recursive: true });
  const tmp = `${path}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(tmp, path);
}

function hasUserToken() {
  const candidates = [
    `${process.env.XDG_DATA_HOME || `${openclawHome}/home/.local/share`}/lark-mcp-nodejs/storage.json`,
    `${openclawHome}/home/.local/share/lark-mcp-nodejs/storage.json`,
  ];
  return candidates.some((path) => fs.existsSync(path) && fs.statSync(path).size > 0);
}

function firstPairingTarget() {
  const data = readJson(pairingPath, {});
  const requests = Array.isArray(data.requests) ? data.requests.slice() : [];
  requests.sort((a, b) => String(a.createdAt || '').localeCompare(String(b.createdAt || '')));
  for (const request of requests) {
    const id = String(request.id || '').trim();
    if (!id) continue;
    if (id.startsWith('ou_')) return id;
  }
  return '';
}

function fixedTarget() {
  return String(process.env.FEISHU_AUTH_TARGET || process.env.FEISHU_OWNER_OPEN_ID || '').trim();
}

function resolveTarget() {
  if (mode === 'fixed') return fixedTarget();
  const paired = firstPairingTarget();
  if (paired) return paired;
  return fixedTarget();
}

function ensureAllowFrom(target) {
  if (!bindFirstUser || !target.startsWith('ou_')) return;
  const data = readJson(allowFromPath, { version: 1, allowFrom: [] });
  const allowFrom = Array.isArray(data.allowFrom) ? data.allowFrom : [];
  if (allowFrom.includes(target)) return;
  if (allowFrom.length > 0 && process.env.FEISHU_AUTH_REPLACE_ALLOW_FROM !== '1') return;
  data.version = data.version || 1;
  data.allowFrom = [target];
  writeJson(allowFromPath, data);
  log(`allow_from_bound target=${safeId(target)}`);
}

function wasRecentlySent(state, target) {
  const sentAt = Number((state.targets && state.targets[target] && state.targets[target].sentAt) || 0);
  return sentAt && Date.now() - sentAt < cooldownMs;
}

function markSent(state, target, status) {
  state.targets = state.targets || {};
  state.targets[target] = {
    sentAt: Date.now(),
    sentAtIso: now(),
    status,
  };
  writeJson(statePath, state);
}

function sendAuthCard(target) {
  if (!publicUrl) {
    log('WARN missing_public_url');
    return false;
  }

  const child = spawn(
    process.execPath,
    [sendScript, '--target', target, '--public-url', publicUrl],
    {
      detached: true,
      stdio: ['ignore', 'ignore', 'ignore'],
      env: {
        ...process.env,
        OPENCLAW_STATE_DIR: openclawHome,
        OPENCLAW_HOME: openclawHome,
        LARK_MCP_PUBLIC_URL: publicUrl,
        OPENCLAW_PUBLIC_URL: publicUrl,
      },
    },
  );
  child.unref();
  return true;
}

function tick() {
  if (hasUserToken() && process.env.FEISHU_AUTH_WATCHER_IGNORE_TOKEN !== '1') {
    log('OK user_token_exists');
    return true;
  }

  const target = resolveTarget();
  if (!target) {
    log(`WAIT mode=${mode} no_target`);
    return false;
  }

  const state = readJson(statePath, { version: 1, targets: {} });
  if (wasRecentlySent(state, target)) {
    log(`WAIT target=${safeId(target)} cooldown_active`);
    ensureAllowFrom(target);
    return false;
  }

  ensureAllowFrom(target);
  if (sendAuthCard(target)) {
    markSent(state, target, 'started');
    log(`AUTH_CARD target=${safeId(target)} status=started`);
    return true;
  }
  return false;
}

function main() {
  fs.mkdirSync(credentialsDir, { recursive: true });
  log(`START mode=${mode} pairing=${pairingPath}`);
  const ok = tick();
  if (once) process.exit(ok ? 0 : 1);
  setInterval(tick, pollMs);
}

main();
