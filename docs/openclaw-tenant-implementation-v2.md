# OpenClaw 多租户独立容器实施文档 v2

更新时间：2026-05-12

本文档给运维和交付同事使用，描述当前推荐的 OpenClaw 一人一容器部署方式。

## 1. 交付目标

每个用户独立一套 OpenClaw：

- 独立 Docker 容器。
- 独立域名和 1Panel 网站。
- 独立 gateway token。
- 独立飞书 App ID / App Secret。
- 独立飞书 OAuth 用户授权。
- 独立数据目录、记忆、向量、聊天记录和日志。

统一由运维维护：

- 基础镜像。
- 默认大模型配置。
- 默认 embedding/向量配置。
- 1Panel 网站、证书和反代。
- 检查脚本和备份策略。

## 2. 当前实现原则

### 2.1 `.env` 是单一事实来源

部署脚本只生成：

- `.env`
- `docker-compose.yml`
- `tenant.json`
- 空的 `data/` 目录

部署脚本不再复制模板实例的 `openclaw.json`。容器第一次启动时，镜像内的 `render-openclaw-config.js` 会根据 `.env` 渲染：

```text
data/conf/openclaw.json
```

这样可以避免把旧实例的域名、授权状态、插件状态、用户配置复制到新实例。

### 2.2 `tenant.json` 不保存密钥

每个实例目录下会有：

```text
/opt/1panel/apps/openclaw/<instance>/tenant.json
```

它只记录运维信息：

- 实例名。
- 域名。
- 容器名。
- Web/OAuth 端口。
- 1Panel app/website/ssl ID。
- 模型和向量模型名称。
- 飞书 App ID。

密钥仍只在 `.env` 和 OpenClaw 自己的数据文件中。

### 2.3 证书默认走 1Panel DNS 解析账号

证书不建议走 HTTP 验证。当前推荐：

- 在 1Panel 后台配置腾讯云 DNS 解析账号。
- 新实例网站创建后，用 1Panel 的 DNS 账号申请证书。
- 证书申请、续期、绑定都留在 1Panel 管理。

不要把腾讯云密钥写入部署脚本或仓库。

### 2.4 容器网络默认共用

后续实例默认加入同一个 Docker bridge 网络：

```text
openclaw-net
```

部署脚本会在启动容器前检查并创建这个网络。实例隔离依赖独立容器名、宿主机端口、数据目录、管理 token、飞书应用配置、OAuth token、记忆库和向量库，不依赖每个容器单独分配一个网段。

## 3. 目录结构

1Panel 模式实例目录：

```text
/opt/1panel/apps/openclaw/<instance>/
  .env
  docker-compose.yml
  tenant.json
  data/
    conf/
      openclaw.json
    workspace/
    credentials/
    home/.local/share/
    logs/
```

备份一个用户时，备份整个实例目录，重点是 `data/`。

### 3.1 飞书身份分层

当前飞书接入分两层：

- OpenClaw 飞书 channel：机器人身份，负责长连接、私聊、群聊、回复和卡片。
- `lark-mcp` 用户身份桥接：飞书官方 OAuth `user_access_token`，负责按用户权限访问知识库、文档、群聊列表、群成员、消息等工具。

授权卡片只是机器人发送的引导入口，不是新的身份体系。

## 4. 部署前准备

每个新用户需要准备：

- 实例名，例如 `m2`。
- 域名，例如 `m2.op.tyos.cc`。
- DNS 已解析到服务器。
- 飞书 App ID。
- 飞书 App Secret。
- 飞书开放平台事件订阅使用长连接。
- 飞书开放平台安全设置里添加回调地址：

```text
https://<domain>/callback
```

1Panel 侧需要准备：

- Docker 可用。
- OpenResty 网站功能可用。
- 腾讯云 DNS 解析账号已配置。
- ACME 账号已配置。

### 4.1 运维和用户分工

运维负责：

- 创建实例、分配端口、启动容器。
- 在 1Panel 创建网站、申请并绑定证书。
- 配置默认大模型、默认 embedding、飞书 App 参数。
- 检查容器、网站、证书、飞书长连接和用户授权状态。
- 备份实例目录。

用户负责：

- 提供飞书 App ID / App Secret。
- 在飞书开放平台添加 `https://<domain>/callback`。
- 私聊机器人或在群里 @ 机器人触发授权卡。
- 点击授权卡完成用户身份 OAuth。

### 4.2 推荐推进顺序

每个实例按下面顺序推进：

1. 确认域名解析到服务器。
2. 执行部署脚本生成实例。
3. 在 1Panel 中确认应用/智能体记录可见。
4. 用 1Panel DNS 账号申请并绑定证书。
5. 访问 `https://<domain>/healthz` 确认反代正常。
6. 用户给机器人发第一条消息，触发 pairing。
7. watcher 自动发送飞书 OAuth 引导卡片。
8. 用户在飞书开放平台添加回调地址后点击授权。
9. 运行检查脚本确认容器、网站、证书、飞书长连接和用户 token。

## 5. 部署步骤

### 5.1 创建实例

推荐交互式命令：

```bash
provision-openclaw --interactive --panel
```

常用非交互命令示例：

```bash
provision-openclaw \
  --panel \
  --register-panel \
  --register-website \
  --template ql1 \
  --name m2 \
  --domain m2.op.tyos.cc \
  --feishu-app-id cli_xxx \
  --feishu-app-secret '***' \
  --auth-target-mode first_sender
```

脚本会完成：

- 分配端口。
- 确认共享 Docker 网络 `openclaw-net` 存在。
- 生成 `.env`。
- 生成 `docker-compose.yml`。
- 生成 `tenant.json`。
- 创建独立数据目录。
- 注册 1Panel 应用/智能体记录。
- 写入网站和反代配置。
- 启动容器。

### 5.2 申请并绑定证书

在 1Panel 后台操作：

1. 进入证书申请。
2. 验证方式选择 `DNS 账号`。
3. DNS 账号选择 `dns解析 [腾讯云]`。
4. 域名填新实例域名。
5. 申请成功后绑定到对应网站。
6. 确认网站协议是 HTTPS，HTTP 跳转 HTTPS。

说明：不要选择 HTTP 验证。公网 HTTP 可能被备案或平台策略拦截，导致 ACME 失败。

### 5.3 用户授权飞书

默认模式是：

```text
FEISHU_AUTH_TARGET_MODE=first_sender
FEISHU_AUTH_CARD_MODE=guided
```

用户第一次私聊机器人，或在群里 @ 机器人后：

1. OpenClaw 记录第一个用户。
2. watcher 自动批准 pairing。
3. watcher 向该用户发送引导式授权卡片。
4. 卡片展示 App ID、回调地址、开放平台入口和授权按钮。
5. 用户配置回调地址后点击授权。

授权按钮必须是无内部端口的公网地址：

```text
https://<domain>/authorize?... 
```

不能出现：

```text
https://<domain>:31888/authorize?... 
```

如果出现内部端口，说明授权卡脚本版本过旧，需要更新镜像或热更新 `send-feishu-auth-card.js`。

授权卡发送日志：

```text
data/conf/logs/feishu-auth-card-watcher.log
```

watcher 只有看到 `card_sent` 或 `setup_card_sent` 后才进入正常冷却；发送失败会短间隔重试。

## 6. 检查步骤

部署后运行：

```bash
python3 scripts/check_openclaw_instance.py --name m2 --domain m2.op.tyos.cc
```

在服务器上也可以直接运行已同步的检查脚本：

```bash
check-openclaw-instance --name m1 --domain m1.op.tyos.cc
```

部署后或排查飞书用户身份问题时，运行深度检查：

```bash
check-openclaw-instance --name m2 --domain m2.op.tyos.cc --deep
```

检查项包括：

- `tenant.json` 是否存在。
- 容器名是否能从 `tenant.json` 或 1Panel app install 记录解析出来。
- 容器是否 `running healthy`。
- 容器是否加入共享 Docker 网络。
- 授权卡脚本是否是支持公网 issuer 的新版。
- lark-mcp storage fallback patch 是否生效。
- lark-mcp OAuth public URL patch 是否生效。
- `--deep` 模式会真实启动 `feishu-user` MCP 并执行 `tools/list` 握手。
- 近期日志是否有 `agent model`。
- 飞书 WebSocket 是否 `ws client ready`。
- `allowedOrigins` 是否只包含当前域名和 localhost。
- feishu-user MCP public URL 是否等于当前域名。
- 1Panel agent 记录是否存在。
- 1Panel app install 记录是否存在且 `Running`。
- 1Panel website 是否存在且 `Running`。
- 1Panel certificate 是否 `ready`。
- 公网 HTTPS 是否 200/301/302/401。
- 飞书用户 token 是否已落盘，文件密钥 fallback 是否存在。

当前正常输出示例：

```text
OK   tenant manifest
OK   container - running healthy
OK   allowed origins
OK   agent model - bailian-coding-plan/qwen3.6-plus
OK   feishu channel config - enabled=True
OK   feishu user token
OK   1Panel agent record
OK   1Panel app install
OK   1Panel website - protocol=HTTPS status=Running
OK   1Panel certificate record - provider=dnsAccount status=ready
OK   public https - HTTP/2 200
```

如果 `feishu user token` 是 `WARN`，说明容器已经起来，但用户身份 OAuth
还没有完成，或 token 存储文件还没有生成。此时重发授权卡，让用户点击最新版
无内部端口的授权链接。

### 飞书工具边界

当前镜像同时存在两类飞书能力：

- OpenClaw 飞书频道插件：用于长连接收发消息、机器人回复、发送授权卡。它使用
  app/tenant 身份。
- `feishu-user` MCP：用于用户 OAuth 后按用户身份读取云文档、知识库、通讯录等。

模型查询飞书知识库、云文档、多维表格时，应优先使用 `feishu-user` MCP 工具。
如果日志里出现 `token_type=tenant` 的 wiki/doc/drive 权限错误，通常说明模型调用了
频道插件暴露的 app 身份工具，或 `feishu-user` MCP 没有正常启动。

`lark-mcp 0.5.1` 的 `im.v1.message.list` 工具定义仍是 `tenant` access token，
在 `user_access_token` 模式下不会作为用户身份消息历史工具暴露。用户身份能列群聊和
成员，但读取完整私聊/群聊历史仍需要按飞书开放平台的 tenant/app 权限链路单独处理。

旧实例可能没有 `tenant.json`。这不影响继续运行，但建议在维护窗口补一份无密钥
`tenant.json`，方便后续批量检查、备份和迁移。

## 7. 常见问题

### 7.1 飞书收到消息但不回复

看容器日志。如果出现：

```text
EACCES: permission denied, mkdir '/root/.openclaw/workspace'
```

说明容器 `HOME` 错了。当前新镜像已固定：

```text
HOME=/home/node
XDG_DATA_HOME=/home/node/.openclaw/home/.local/share
```

旧实例需要补环境变量并重建容器。

### 7.2 授权链接带 `:31888`

这是旧授权卡脚本问题。正确链接应走反代：

```text
https://<domain>/authorize
```

修复版本已提交：

```text
f1cacf3 Drop internal port from Feishu auth links
```

### 7.3 证书申请记录有历史 HTTP 失败信息

如果最终状态是：

```text
provider=dnsAccount
status=ready
```

并且网站已绑定 `website_ssl_id`，则证书可用。历史 `message` 里可能还保留 HTTP 验证失败文本，不代表当前证书不可用。

### 7.4 外部 HTTP 返回 403

这通常是公网备案或平台侧拦截，不影响 DNS-01 证书申请。证书申请应使用 DNS 账号。

### 7.5 MCP 用户身份授权失效

可能原因：

- refresh token 过期。
- 飞书 App Secret 改动。
- scope 变更。
- 回调域名变更。
- 用户撤销授权。

处理方式：重新发送授权卡，让用户重新授权。

### 7.6 `libsecret-1.so.0` 缺失

如果发送授权卡或处理 OAuth 时出现：

```text
libsecret-1.so.0: cannot open shared object file
```

说明 lark-mcp 默认尝试使用系统 keyring。容器里不应依赖系统 keyring，
当前镜像会把 lark-mcp 存储改成实例目录内的文件密钥 fallback：

```text
data/conf/home/.local/share/lark-mcp-nodejs/encryption-key
data/conf/home/.local/share/lark-mcp-nodejs/storage.json
```

这两个文件都在用户实例目录里，跟随 `data/` 一起备份和迁移。旧容器需要更新镜像
并重建，或临时执行同样的 patch。

## 8. 后续优化

不要继续把部署脚本做成后台。推荐保持三件事：

- `provision_openclaw_instance.py`：只创建实例和注册 1Panel 记录。
- `check_openclaw_instance.py`：只检查状态，不做修改。
- 1Panel：负责证书申请、续期和可视化管理。

后续如果要继续自动化，优先考虑：

- 调用 1Panel API 申请 DNS 证书，而不是手写数据库。
- 批量读取 `tenant.json` 做健康检查。
- 增加批量备份和恢复脚本。
- 增加一键重发飞书授权卡命令。

## 9. 当前关键提交

```text
44027e5 Simplify tenant provisioning structure
934b74d Use public Feishu OAuth issuer
f1cacf3 Drop internal port from Feishu auth links
```
