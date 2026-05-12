#!/usr/bin/env node
const fs = require('fs');
const { spawn, spawnSync } = require('child_process');

const openclawHome = process.env.OPENCLAW_STATE_DIR || process.env.OPENCLAW_HOME || '/home/node/.openclaw';
const credentialsDir = `${openclawHome}/credentials`;
const pairingPath = process.env.FEISHU_PAIRING_FILE || `${credentialsDir}/feishu-pairing.json`;
const allowFromPath = process.env.FEISHU_ALLOW_FROM_FILE || `${credentialsDir}/feishu-default-allowFrom.json`;
const statePath = process.env.FEISHU_AUTH_WATCHER_STATE_FILE || `${credentialsDir}/feishu-auth-card-sent.json`;
const mode = process.env.FEISHU_AUTH_TARGET_MODE || 'first_sender';
const publicUrl = (process.env.OPENCLAW_PUBLIC_URL || process.env.LARK_MCP_PUBLIC_URL || '').replace(/\/$/, '');
const pollMs = Number(process.env.FEISHU_AUTH_WATCHER_POLL_MS || 15000);
const sendScript = process.env.FEISHU_AUTH_CARD_SCRIPT || '/opt/opendd/bin/send-feishu-auth-card.js';
const cardMode = process.env.FEISHU_AUTH_CARD_MODE || 'guided';
const defaultCooldownMs = cardMode === 'guided' ? 12 * 60 * 1000 : 6 * 60 * 60 * 1000;
const cooldownMs = Number(process.env.FEISHU_AUTH_CARD_COOLDOWN_MS || defaultCooldownMs);
const inFlightMs = Number(process.env.FEISHU_AUTH_CARD_INFLIGHT_MS || 90 * 1000);
const failedRetryMs = Number(process.env.FEISHU_AUTH_CARD_FAILED_RETRY_MS || 2 * 60 * 1000);
const bindFirstUser = String(process.env.FEISHU_AUTH_BIND_FIRST_USER || '1') !== '0';
const once = process.argv.includes('--once') || process.env.FEISHU_AUTH_WATCHER_ONCE === '1';
const cardLogPath = process.env.FEISHU_AUTH_CARD_LOG_FILE || `${openclawHome}/logs/feishu-auth-card-watcher.log`;

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

function normalizePairingCode(request) {
  for (const key of ['code', 'pairingCode', 'pairing_code', 'approvalCode', 'approval_code']) {
    const value = String(request && request[key] ? request[key] : '').trim();
    if (value) return value;
  }
  return '';
}

function pairingRequests() {
  const data = readJson(pairingPath, {});
  const requests = Array.isArray(data.requests) ? data.requests.slice() : [];
  requests.sort((a, b) => String(a.createdAt || '').localeCompare(String(b.createdAt || '')));
  return requests;
}

function firstPairingRequest() {
  for (const request of pairingRequests()) {
    const id = String(request.id || request.openId || request.open_id || '').trim();
    if (!id || !id.startsWith('ou_')) continue;
    return { ...request, id, code: normalizePairingCode(request) };
  }
  return null;
}

function firstPairingTarget() {
  const request = firstPairingRequest();
  return request ? request.id : '';
}

function approvePairing(request) {
  if (process.env.FEISHU_PAIRING_AUTO_APPROVE === '0') return false;
  if (!request || !request.code) return false;
  const result = spawnSync(
    'openclaw',
    ['pairing', 'approve', 'feishu', request.code],
    {
      encoding: 'utf8',
      timeout: 15000,
      env: {
        ...process.env,
        OPENCLAW_HOME: openclawHome,
        OPENCLAW_STATE_DIR: openclawHome,
      },
    },
  );
  const output = `${result.stdout || ''}${result.stderr || ''}`;
  if (result.status === 0 && !output.includes('Failed to start CLI')) {
    log(`PAIRING_APPROVED target=${safeId(request.id)} code=${request.code}`);
    return true;
  }
  log(`WARN pairing_approve_failed target=${safeId(request.id)} code=${request.code} status=${result.status} output=${output.trim().slice(0, 200)}`);
  return false;
}

function approveKnownPairings() {
  for (const request of pairingRequests()) {
    const id = String(request.id || request.openId || request.open_id || '').trim();
    if (!id || !id.startsWith('ou_')) continue;
    approvePairing({ ...request, id, code: normalizePairingCode(request) });
  }
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
  const record = state.targets && state.targets[target] ? state.targets[target] : {};
  const sentAt = Number(record.sentAt || 0);
  return record.status === 'sent' && sentAt && Date.now() - sentAt < cooldownMs;
}

function markTarget(state, target, values) {
  state.targets = state.targets || {};
  state.targets[target] = {
    ...(state.targets[target] || {}),
    ...values,
  };
  writeJson(statePath, state);
}

function markAttemptStarted(state, target) {
  markTarget(state, target, {
    startedAt: Date.now(),
    startedAtIso: now(),
    status: 'started',
  });
}

function markSent(state, target) {
  markTarget(state, target, {
    sentAt: Date.now(),
    sentAtIso: now(),
    status: 'sent',
  });
}

function markFailed(state, target, reason) {
  markTarget(state, target, {
    failedAt: Date.now(),
    failedAtIso: now(),
    status: 'failed',
    reason: String(reason || '').slice(0, 240),
  });
}

function latestCardLogForTarget(target) {
  try {
    if (!fs.existsSync(cardLogPath)) return '';
    const text = fs.readFileSync(cardLogPath, 'utf8');
    const exact = `target=${target}`;
    const safe = `target=${safeId(target)}`;
    const exactIndex = text.lastIndexOf(exact);
    const safeIndex = text.lastIndexOf(safe);
    const index = Math.max(exactIndex, safeIndex);
    return index >= 0 ? text.slice(index) : text.slice(-8000);
  } catch (error) {
    log(`WARN read_card_log_failed path=${cardLogPath} error=${error.message}`);
    return '';
  }
}

function refreshSendStatus(state, target) {
  const record = state.targets && state.targets[target] ? state.targets[target] : null;
  if (!record || record.status === 'sent') return record ? record.status : '';
  if (record.status === 'failed') return 'failed';

  const targetLog = latestCardLogForTarget(target);
  if (/(^|\n)(card_sent|setup_card_sent)=/.test(targetLog)) {
    markSent(state, target);
    log(`AUTH_CARD target=${safeId(target)} status=sent`);
    return 'sent';
  }

  const failure = targetLog.match(/(Error: .+|send card failed: .+|tenant_access_token failed: .+|Issuer URL must be HTTPS|Missing .+)/);
  if (failure) {
    markFailed(state, target, failure[1]);
    log(`WARN auth_card_failed target=${safeId(target)} reason=${failure[1].slice(0, 180)}`);
    return 'failed';
  }

  return record.status || '';
}

function shouldWaitBeforeSending(state, target) {
  const status = refreshSendStatus(state, target);
  const record = state.targets && state.targets[target] ? state.targets[target] : {};
  const age = (field) => Date.now() - Number(record[field] || 0);

  if (status === 'sent' && wasRecentlySent(state, target)) {
    log(`WAIT target=${safeId(target)} cooldown_active`);
    return true;
  }
  if (status === 'started' && record.startedAt && age('startedAt') < inFlightMs) {
    log(`WAIT target=${safeId(target)} auth_card_inflight`);
    return true;
  }
  if (status === 'failed' && record.failedAt && age('failedAt') < failedRetryMs) {
    log(`WAIT target=${safeId(target)} recent_auth_card_failure`);
    return true;
  }
  return false;
}

function sendAuthCard(target) {
  if (!publicUrl) {
    log('WARN missing_public_url');
    return false;
  }

  fs.mkdirSync(require('path').dirname(cardLogPath), { recursive: true });
  fs.appendFileSync(cardLogPath, `${now()} START target=${safeId(target)} mode=${cardMode} publicUrl=${publicUrl}\n`, { mode: 0o600 });
  const logFd = fs.openSync(cardLogPath, 'a');
  const child = spawn(
    process.execPath,
    [sendScript, '--target', target, '--public-url', publicUrl, '--mode', cardMode],
    {
      detached: true,
      stdio: ['ignore', logFd, logFd],
      env: {
        ...process.env,
        OPENCLAW_STATE_DIR: openclawHome,
        OPENCLAW_HOME: openclawHome,
        LARK_MCP_PUBLIC_URL: publicUrl,
        OPENCLAW_PUBLIC_URL: publicUrl,
      },
    },
  );
  fs.closeSync(logFd);
  child.on('error', (error) => {
    log(`WARN auth_card_spawn_failed target=${safeId(target)} error=${error.message}`);
  });
  child.on('exit', (code, signal) => {
    if (code && code !== 0) log(`WARN auth_card_process_exit target=${safeId(target)} code=${code}`);
    if (signal) log(`WARN auth_card_process_signal target=${safeId(target)} signal=${signal}`);
  });
  child.unref();
  return true;
}

function tick() {
  if (hasUserToken() && process.env.FEISHU_AUTH_WATCHER_IGNORE_TOKEN !== '1') {
    log('OK user_token_exists');
    return true;
  }

  approveKnownPairings();
  const target = resolveTarget();
  if (!target) {
    log(`WAIT mode=${mode} no_target`);
    return false;
  }

  const state = readJson(statePath, { version: 1, targets: {} });
  if (shouldWaitBeforeSending(state, target)) {
    ensureAllowFrom(target);
    return false;
  }

  ensureAllowFrom(target);
  if (sendAuthCard(target)) {
    markAttemptStarted(state, target);
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
