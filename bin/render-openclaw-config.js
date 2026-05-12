#!/usr/bin/env node
const fs = require('fs');
const crypto = require('crypto');

const home = process.env.OPENCLAW_STATE_DIR || process.env.OPENCLAW_HOME || '/home/node/.openclaw';
const configPath = process.env.OPENCLAW_CONFIG || process.env.OPENCLAW_CONFIG_PATH || `${home}/openclaw.json`;
const publicUrl = (process.env.OPENCLAW_PUBLIC_URL || process.env.LARK_MCP_PUBLIC_URL || '').replace(/\/$/, '');
const ownerOpenId = process.env.FEISHU_OWNER_OPEN_ID || '';
const authTargetMode = process.env.FEISHU_AUTH_TARGET_MODE || 'fixed';
const defaultDmPolicy = authTargetMode === 'fixed' ? 'allowlist' : 'pairing';
const modelProvider = process.env.OPENCLAW_MODEL_PROVIDER || 'bailian-coding-plan';
const modelId = process.env.OPENCLAW_MODEL_ID || 'qwen3.6-plus';
const modelApiKey = process.env.OPENCLAW_MODEL_API_KEY || process.env.BAILIAN_CODING_API_KEY || '';
const modelBaseUrl = process.env.OPENCLAW_MODEL_BASE_URL || 'https://coding.dashscope.aliyuncs.com/v1';
const larkMcpTools = process.env.LARK_MCP_TOOLS || 'preset.default,drive.v1.file.list';
const embeddingProvider = process.env.OPENCLAW_EMBEDDING_PROVIDER || 'openai';
const embeddingModel = process.env.OPENCLAW_EMBEDDING_MODEL || 'text-embedding-v4';
const embeddingBaseUrl = process.env.OPENCLAW_EMBEDDING_BASE_URL || 'https://dashscope.aliyuncs.com/compatible-mode/v1';
const embeddingApiKeyRef = process.env.OPENCLAW_EMBEDDING_API_KEY
  ? '${OPENCLAW_EMBEDDING_API_KEY}'
  : '${DASHSCOPE_API_KEY}';
const gatewayToken = process.env.OPENCLAW_GATEWAY_TOKEN || crypto.randomBytes(24).toString('base64url');
const feishuEnabled = String(process.env.FEISHU_ENABLED || '').toLowerCase() === 'true'
  || Boolean(process.env.FEISHU_APP_ID && process.env.FEISHU_APP_SECRET);
const weixinPluginEnabled = String(process.env.OPENCLAW_WEIXIN_PLUGIN_ENABLED || '1') !== '0';

function list(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

const allowedOrigins = [
  'http://127.0.0.1:18789',
  'http://localhost:18789',
  publicUrl,
  ...list(process.env.OPENCLAW_ALLOWED_ORIGINS),
].filter(Boolean);
const uniqueAllowedOrigins = [...new Set(allowedOrigins)];

const modelDefinitions = [
  ['qwen3.6-plus', 'qwen3.6-plus', ['text', 'image']],
  ['qwen3-max', 'Qwen3-Max', ['text']],
  ['qwen3-coder-next', 'Qwen3-Coder-Next', ['text']],
  ['qwen3-coder-plus', 'Qwen3-Coder-Plus', ['text']],
  ['kimi-k2.5', 'Kimi-k2.5', ['text', 'image']],
  ['glm-5', 'GLM-5', ['text']],
  ['glm-4.7', 'GLM-4.7', ['text']],
  ['minimax-m2.5', 'MiniMax M2.5', ['text']],
].map(([id, name, input]) => ({
  id,
  name,
  input,
  reasoning: true,
  contextWindow: 256000,
  maxTokens: 32768,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
}));

const config = {
  agents: {
    defaults: {
      userTimezone: process.env.TZ || 'Asia/Shanghai',
      model: {
        primary: `${modelProvider}/${modelId}`,
      },
      models: Object.fromEntries(modelDefinitions.map((model) => [`${modelProvider}/${model.id}`, {}])),
      memorySearch: {
        enabled: true,
        provider: embeddingProvider,
        model: embeddingModel,
        fallback: 'none',
        sources: ['memory'],
        remote: {
          apiKey: embeddingApiKeyRef,
          baseUrl: embeddingBaseUrl,
          batch: {
            enabled: false,
            concurrency: 1,
            wait: true,
            pollIntervalMs: 2000,
            timeoutMinutes: 60,
          },
        },
        query: {
          maxResults: 8,
          minScore: 0.1,
          hybrid: {
            enabled: true,
            vectorWeight: 0.7,
            textWeight: 0.3,
            candidateMultiplier: 4,
          },
        },
        sync: {
          onSessionStart: true,
          onSearch: true,
          watch: true,
          watchDebounceMs: 1500,
        },
        cache: {
          enabled: true,
          maxEntries: 500,
        },
      },
    },
  },
  browser: {
    enabled: true,
    defaultProfile: 'openclaw',
    executablePath: '/home/node/.cache/ms-playwright/openclaw-browser',
    headless: true,
    noSandbox: true,
  },
  channels: {
    feishu: {
      enabled: feishuEnabled,
      domain: process.env.FEISHU_DOMAIN || 'feishu',
      appId: process.env.FEISHU_APP_ID || '',
      appSecret: process.env.FEISHU_APP_SECRET || '',
      connectionMode: 'websocket',
      dmPolicy: process.env.FEISHU_DM_POLICY || defaultDmPolicy,
      allowFrom: ownerOpenId ? [ownerOpenId] : [],
      groupPolicy: process.env.FEISHU_GROUP_POLICY || 'open',
      groupSenderAllowFrom: ownerOpenId && process.env.FEISHU_GROUP_OWNER_ONLY !== '0' ? [ownerOpenId] : [],
      requireMention: true,
      groupSessionScope: 'group_topic',
      replyInThread: 'enabled',
      reactionNotifications: 'own',
      resolveSenderNames: true,
      streaming: true,
      typingIndicator: true,
      renderMode: 'auto',
      webhookPath: '/feishu/events',
    },
  },
  commands: {
    ownerAllowFrom: ownerOpenId ? [`feishu:${ownerOpenId}`] : [],
  },
  gateway: {
    mode: 'local',
    bind: 'lan',
    port: Number(process.env.OPENCLAW_PORT || 18789),
    auth: {
      mode: 'token',
      token: gatewayToken,
    },
    controlUi: {
      allowedOrigins: uniqueAllowedOrigins,
      dangerouslyDisableDeviceAuth: true,
    },
    trustedProxies: ['127.0.0.1/32'],
  },
  mcp: {
    servers: {
      'feishu-user': {
        command: 'node',
        args: ['/opt/opendd/bin/start-feishu-mcp.js'],
        env: {
          HOME: '/home/node/.openclaw/home',
          XDG_DATA_HOME: '/home/node/.openclaw/home/.local/share',
          XDG_RUNTIME_DIR: '/home/node/.openclaw/runtime',
          XDG_STATE_HOME: '/home/node/.openclaw/state',
          XDG_CONFIG_HOME: '/home/node/.openclaw/config',
          XDG_CACHE_HOME: '/home/node/.openclaw/cache',
          LARK_MCP_PUBLIC_URL: publicUrl,
          LARK_MCP_LANGUAGE: 'zh',
          LARK_MCP_TOOLS: larkMcpTools,
        },
      },
    },
  },
  models: {
    mode: 'merge',
    providers: {
      [modelProvider]: {
        api: process.env.OPENCLAW_MODEL_API || 'openai-completions',
        apiKey: modelApiKey,
        baseUrl: modelBaseUrl,
        models: modelDefinitions,
      },
    },
  },
  plugins: {
    bundledDiscovery: 'compat',
    allow: [
      'browser',
      'feishu',
      'memory-core',
      'active-memory',
      ...(weixinPluginEnabled ? ['openclaw-weixin'] : []),
    ],
    entries: {
      browser: { enabled: true },
      feishu: { enabled: feishuEnabled, config: {} },
      ...(weixinPluginEnabled
        ? {
            'openclaw-weixin': { enabled: true, config: {} },
          }
        : {}),
      'active-memory': {
        enabled: true,
        config: {
          enabled: true,
          agents: ['main'],
          allowedChatTypes: ['direct', 'group', 'explicit'],
          queryMode: 'recent',
          qmd: { searchMode: 'search' },
          promptStyle: 'balanced',
          maxSummaryChars: 900,
          recentUserTurns: 3,
          recentAssistantTurns: 2,
          recentUserChars: 800,
          recentAssistantChars: 800,
          cacheTtlMs: 60000,
          timeoutMs: 10000,
          setupGraceTimeoutMs: 2000,
          thinking: 'off',
          logging: true,
          circuitBreakerMaxTimeouts: 3,
          circuitBreakerCooldownMs: 60000,
        },
      },
      'memory-core': {
        enabled: true,
        config: {
          dreaming: {
            enabled: true,
            frequency: process.env.OPENCLAW_DREAM_CRON || '15 3 * * *',
            timezone: process.env.TZ || 'Asia/Shanghai',
            storage: {
              mode: 'both',
              separateReports: true,
            },
            phases: {
              light: {
                enabled: true,
                lookbackDays: 3,
                limit: 20,
                dedupeSimilarity: 0.88,
              },
              deep: {
                enabled: true,
                maxAgeDays: 365,
                limit: 10,
                minScore: 0.72,
                minRecallCount: 1,
                minUniqueQueries: 1,
                recencyHalfLifeDays: 30,
              },
              rem: {
                enabled: true,
                lookbackDays: 7,
                limit: 10,
                minPatternStrength: 0.55,
              },
            },
          },
        },
      },
    },
  },
  session: {
    dmScope: 'per-account-channel-peer',
  },
  tools: {
    profile: 'full',
    sessions: {
      visibility: 'all',
    },
  },
  update: {
    checkOnStart: false,
  }
};

fs.mkdirSync(home, { recursive: true });
fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`);
console.log(`wrote ${configPath}`);
console.log(`gateway token: ${gatewayToken}`);
