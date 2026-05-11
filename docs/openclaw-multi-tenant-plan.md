# OpenClaw 多用户独立容器部署方案

> 当前执行版请优先阅读：
>
> `docs/openclaw-tenant-implementation-v2.md`
>
> v2 的关键变化是：`.env` 是单一事实来源，部署脚本不再复制模板
> `openclaw.json`；容器启动时自行渲染配置；每个实例生成无密钥
> `tenant.json`；证书默认通过 1Panel 已配置的 DNS 解析账号申请。

## 1. 目标

当前目标是把 OpenClaw 做成“一人一套独立实例”的交付方式。每个用户拥有独立容器、独立数据目录、独立管理 Token、独立飞书应用、独立飞书用户授权、独立记忆库和独立聊天记录。

运维侧统一维护基础镜像、默认模型、默认向量配置、1Panel 管理入口、备份策略和健康检查。用户侧只需要提供飞书应用参数、完成飞书开放平台回调配置，并点击授权卡片。

核心目标：

- 支持快速复制部署多个 OpenClaw 实例。
- 每个用户数据完全隔离，不互相污染。
- 容器、网站、证书、日志尽量能在 1Panel 中查看和管理。
- 默认使用当前模板的模型、记忆、梦境模式和向量配置。
- 新用户部署时允许覆盖自己的飞书参数、域名、授权目标和向量密钥。
- 后续可以从脚本演进成后台管理系统。

## 2. 当前实现概览

当前已经具备三个关键能力：

1. 自定义 OpenClaw 镜像

   镜像用于一人一容器部署。镜像内包含 OpenClaw 运行环境、飞书 MCP 启动脚本、飞书授权卡片发送脚本、配置渲染逻辑。

   当前镜像示例：

   ```text
   ghcr.io/qa288/opendd:2026.5.7
   ```

2. 部署脚本

   服务器上已经放置：

   ```bash
   /usr/local/bin/provision-openclaw
   ```

   本地脚本路径：

   ```text
   scripts/provision_openclaw_instance.py
   ```

   作用：

   - 创建新实例目录。
   - 自动分配端口。
   - 生成 `.env`。
   - 生成 `docker-compose.yml`。
   - 生成无密钥 `tenant.json`。
   - 继承模板 `.env` 中的模型和向量默认值。
   - 写入新的飞书 App ID / Secret。
   - 可注册到 1Panel 应用/智能体列表。
   - 可写入 1Panel 网站记录和 OpenResty 反代配置。
   - 可发送飞书 OAuth 授权卡片。

   注意：部署脚本不再复制模板实例的 `openclaw.json`。容器首次启动时由镜像内
   `render-openclaw-config.js` 根据 `.env` 渲染新实例配置。

3. 飞书授权 keepalive

   服务器上已经放置：

   ```bash
   /usr/local/bin/openclaw-feishu-keepalive
   ```

   cron 每 15 分钟运行一次：

   ```text
   /etc/cron.d/openclaw-feishu-keepalive
   ```

   作用：

   - 定期用用户身份调用轻量飞书接口。
   - 验证用户 OAuth 是否有效。
   - 降低 MCP 冷启动超时概率。
   - 如果确认是授权类失败，可自动推送授权卡片。

## 3. 整体架构

```text
用户
  |
  | 访问独立域名
  v
1Panel / OpenResty
  |
  | 反向代理
  | /          -> OpenClaw Web/API 端口
  | /callback  -> Feishu OAuth 回调端口
  | /authorize -> Feishu OAuth 授权端口
  v
独立 Docker 容器
  |
  | 挂载独立数据目录
  v
/opt/1panel/apps/openclaw/<instance>/data
  |
  | 保存配置、记忆、向量、授权缓存、聊天记录、日志
  v
OpenClaw + Feishu Channel + lark-mcp user identity
```

每个实例独立：

```text
域名：user01.example.com
容器：1Panel-openclaw-user01
Web 端口：例如 18813 -> 18789
OAuth 端口：例如 31893 -> 31888
数据目录：/opt/1panel/apps/openclaw/user01/data
飞书应用：用户自己的 App ID / App Secret
飞书授权：用户自己的 user_access_token / refresh_token
```

## 4. 数据隔离和备份逻辑

每个实例必须有独立数据目录：

```text
/opt/1panel/apps/openclaw/<instance>/data
```

这个目录是最重要的备份对象，里面包括：

- `conf/openclaw.json`：OpenClaw 主配置。
- `workspace/`：工作区、记忆相关文件。
- `state/`：MCP 状态和日志。
- `home/.local/share/`：飞书 MCP 用户 OAuth 缓存。
- `credentials/`：飞书 allowlist、配对信息等。
- 记忆库、梦境报告、向量索引、聊天记录和运行日志。

备份原则：

- 备份用户数据时，只备份该用户目录。
- 容器损坏时，可以重建容器并挂回同一个数据目录。
- 跨服务器迁移时，复制该目录、保持域名和飞书回调 URL 一致，或重新授权。
- 不要把某个用户的数据目录复制给另一个用户。
- 制作基础镜像时不要把任何用户数据、OAuth token、飞书密钥、聊天记录打进镜像。

## 5. 模型和向量配置

### 5.1 大模型

大模型用于对话、推理、调用工具、总结记忆等。当前默认可继承模板配置，例如百炼 Coding Plan / Qwen。

关键变量：

```text
OPENCLAW_MODEL_PROVIDER
OPENCLAW_MODEL_ID
OPENCLAW_MODEL_API
OPENCLAW_MODEL_BASE_URL
OPENCLAW_MODEL_API_KEY
```

大模型可以换成 DeepSeek、OpenAI、Kimi、千问等，只要 OpenClaw 支持对应接口或 OpenAI-compatible 接口。

### 5.2 向量 / Embedding

向量用于记忆检索、文档检索和语义召回。它和大模型是两套配置。更换大模型通常不影响已有向量库，但更换 embedding 模型可能会影响检索效果，严重时需要重建向量索引。

当前默认策略：

- 默认使用模板实例的千问 / DashScope 向量配置。
- 默认模型为 `text-embedding-v4`。
- 默认接口为 DashScope OpenAI-compatible 地址。
- 部署新实例时可以只覆盖该用户自己的向量 API Key。

推荐默认变量：

```text
OPENCLAW_EMBEDDING_PROVIDER=openai
OPENCLAW_EMBEDDING_MODEL=text-embedding-v4
OPENCLAW_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=<默认百炼/千问 key>
OPENCLAW_EMBEDDING_API_KEY=
```

逻辑：

- 如果 `OPENCLAW_EMBEDDING_API_KEY` 为空，就使用 `DASHSCOPE_API_KEY`。
- 如果部署某个用户时填写 `OPENCLAW_EMBEDDING_API_KEY`，则该实例优先使用自己的向量 key。
- `OPENCLAW_EMBEDDING_PROVIDER=openai` 表示 OpenAI-compatible 协议，不代表必须用 OpenAI。

如果未来使用本地 BGE-M3，只要本地服务暴露 OpenAI-compatible embeddings 接口，可以配置为：

```text
OPENCLAW_EMBEDDING_PROVIDER=openai
OPENCLAW_EMBEDDING_MODEL=bge-m3
OPENCLAW_EMBEDDING_BASE_URL=http://127.0.0.1:<port>/v1
OPENCLAW_EMBEDDING_API_KEY=
```

## 6. 飞书集成逻辑

飞书分两层能力：

1. 飞书机器人通道

   用于接收用户消息、群聊消息、私聊消息和回复消息。当前采用飞书长连接模式。

2. 飞书用户身份 MCP

   用于以用户身份访问知识库、文档、群聊列表、群成员等能力。用户身份需要 OAuth 授权。

关键配置：

```text
FEISHU_ENABLED=true
FEISHU_DOMAIN=feishu
FEISHU_APP_ID=<用户飞书应用 App ID>
FEISHU_APP_SECRET=<用户飞书应用 App Secret>
FEISHU_OWNER_OPEN_ID=<用户 open_id，可空>
FEISHU_AUTH_TARGET_MODE=first_sender
OPENDD_PAIRING_AUTH_WATCHER=1
FEISHU_AUTH_BIND_FIRST_USER=1
FEISHU_DM_POLICY=pairing
FEISHU_GROUP_POLICY=open
FEISHU_GROUP_OWNER_ONLY=1
LARK_MCP_PUBLIC_URL=https://<domain>
OPENCLAW_PUBLIC_URL=https://<domain>
```

飞书开放平台必须配置重定向 URL：

```text
https://<domain>/callback
```

授权流程：

1. 运维创建实例。
2. 运维或用户在飞书开放平台添加回调地址。
3. 系统向用户飞书会话发送引导式授权卡片，卡片里包含 App ID、回调地址和开放平台入口。
4. 用户在飞书开放平台添加回调地址后，点击卡片里的授权按钮。
5. lark-mcp 保存 user token 和 refresh token。
6. 后续 OpenClaw 使用用户身份访问飞书资源。

推荐的授权目标模式是 `first_sender`。在这个模式下，运维不需要提前知道用户的 `open_id` 或授权目标 `chat_id`。用户只要先私聊机器人，或在群里 @ 机器人，OpenClaw 飞书插件会写入 `feishu-pairing.json`，镜像内的 `feishu-pairing-auth-watcher.js` 会读取第一个用户并自动发送引导式 OAuth 授权卡片。

如果已经知道固定目标，也可以使用：

```text
FEISHU_AUTH_TARGET_MODE=fixed
FEISHU_AUTH_TARGET=<open_id 或 chat_id>
```

注意点：

- 用户身份 token 会过期，需要 refresh token 自动续期。
- 如果 refresh token 失效、权限 scope 变更、应用密钥变更、回调域名变更，需要重新授权。
- 当前通过 keepalive 定期验证授权状态。
- 如果确认授权失败，可以自动再次推送授权卡片。

## 7. 用户使用流程

### 7.1 用户需要提供

用户或交付人员需要提供：

- 实例名称，例如 `user03`。
- 已解析域名，例如 `user03.example.com`。
- 飞书 App ID。
- 飞书 App Secret。
- 授权目标模式，默认 `first_sender`。
- 授权卡片接收会话 ID，可选。
- 用户 open_id，可选。
- 如需单独计费或隔离向量额度，提供用户自己的向量 API Key。

### 7.2 用户需要在飞书后台操作

在飞书开放平台对应应用中添加：

```text
https://<domain>/callback
```

如果是国内飞书，域名需要使用飞书国内开放平台配置。

### 7.3 用户需要点击

用户收到授权卡片后，点击授权。

完成后，系统可以用该用户权限访问：

- 知识库。
- 文档。
- 多维表格。
- 群聊列表。
- 群成员。
- 已暴露工具范围内的其他飞书资源。

具体可访问范围最终以飞书开放平台 scope、用户实际权限、机器人加入情况为准。

## 8. 运维部署流程

推荐命令：

```bash
provision-openclaw --interactive --panel
```

交互流程：

1. 选择是否使用 1Panel。
2. 填实例名。
3. 填域名。
4. 填飞书 App ID。
5. 填飞书 App Secret。
6. 选择授权目标模式，默认 `first_sender`。
7. 固定目标模式下填授权卡片接收 chat_id。
8. 可选填用户 open_id。
9. 选择是否覆盖模板向量配置。
10. 选择是否写入 1Panel 应用/智能体列表。
11. 选择是否写入 1Panel 网站记录和反代配置。
12. 选择是否尝试发送授权卡片。

如果不使用 1Panel：

```bash
provision-openclaw --interactive --direct
```

1Panel 模式下需要关注：

- 应用/智能体列表是否可见。
- 网站反代是否生效。
- SSL 证书是否由 1Panel 管理和续期。
- 域名是否能访问。
- `/callback` 和 `/authorize` 是否代理到 OAuth 端口。

## 9. 1Panel 管理要求

使用 1Panel 的目的：

- 方便查看容器状态。
- 方便查看日志和终端。
- 方便管理网站、反代和 SSL。
- 后续方便给非开发同事操作。

当前方案中：

- 容器通过 Docker Compose 启动。
- 脚本可写入 1Panel app/agent 记录。
- 脚本可写入 1Panel website 记录和 OpenResty 反代文件。
- SSL 建议仍通过 1Panel 申请和续期，避免后续证书状态脱离面板。

后续优化方向：

- 使用 1Panel API 创建网站和证书，而不是直接写 DB/配置文件。
- 在后台中展示 1Panel app_install_id、agent_id、website_id、ssl_id。
- 增加一键重启、一键发送授权卡片、一键检测 OAuth 状态。

## 10. 基础资源要求

每个 OpenClaw 实例消耗资源取决于：

- OpenClaw 主进程。
- MCP 进程。
- 记忆插件。
- 梦境模式。
- 浏览器能力。
- 当前模型调用并发。
- 向量索引规模。

建议：

- 少量实例可先用现有服务器继续测试。
- 如果目标是 10 个实例长期稳定运行，建议至少 16GB 内存，并配置 8GB 左右 swap。
- 每个容器应逐步加内存限制和 CPU 限制，防止某个实例拖垮整机。
- keepalive、梦境模式、记忆索引任务需要错峰，避免同一时间集中启动。

当前曾观察到的问题：

- 无 swap 时内存压力会导致服务器卡死或非正常重启。
- MCP 冷启动有时超过 30 秒，导致 OpenClaw 判断工具不可用。
- 记忆插件在高负载或模型慢时可能 timeout。

## 11. 当前功能点要求

基础功能：

- 创建独立容器。
- 创建独立数据目录。
- 创建独立 `.env`。
- 创建独立 `openclaw.json`。
- 独立管理 Token。
- 独立飞书 App ID / Secret。
- 独立飞书用户 OAuth。
- 独立记忆库和向量库。
- 支持 1Panel 可见和管理。
- 支持域名反代。
- 支持飞书授权卡片。
- 支持默认模型和默认向量。
- 支持覆盖用户自己的向量 key。

飞书功能：

- 飞书机器人长连接。
- 私聊回复。
- 群聊被 @ 后回复。
- 用户身份读取知识库和文档。
- 用户身份读取群聊列表和群成员。
- 授权失败时可重新推送授权卡片。
- 定时 keepalive 检测用户授权。

记忆功能：

- 文件记忆。
- active-memory。
- 梦境模式。
- 向量检索。
- 独立备份和恢复。

运维功能：

- 一键部署。
- 一键启动。
- 一键发送授权卡片。
- 定期健康检查。
- 日志可查。
- 备份可恢复。

## 12. 需要避免的问题

- 不要把用户 OAuth token 打进镜像。
- 不要复制某个用户的数据目录作为新用户模板。
- 不要把飞书 App Secret、API Key、GitHub token 提交到 GitHub。
- 不要所有实例共用一个数据目录。
- 不要把 SSL 证书完全绕过 1Panel 管理，除非已经有独立证书管理方案。
- 不要在没有资源限制的情况下快速扩到 10 个以上实例。
- 不要随意更换 embedding 模型，否则可能需要重建向量索引。

## 13. 后续优化空间

### 13.1 后台管理系统

可以把当前脚本封装成后台：

- 新建实例表单。
- 填飞书参数。
- 填域名。
- 填用户 open_id。
- 选择是否使用默认向量 key。
- 选择是否使用用户自己的向量 key。
- 一键创建容器。
- 一键创建 1Panel 网站。
- 一键申请 SSL。
- 一键发送授权卡片。
- 展示授权状态。
- 展示容器状态。
- 展示最近错误日志。

后台需要保存：

- 实例名称。
- 域名。
- HTTP 端口。
- OAuth 端口。
- 容器名。
- 数据目录。
- 1Panel app_install_id。
- 1Panel agent_id。
- 1Panel website_id。
- 飞书 App ID。
- 加密后的 Feishu App Secret。
- 授权目标 chat_id。
- 用户 open_id。
- 向量配置。
- 当前状态。

### 13.2 Secret 管理

目前脚本使用 `.env` 保存配置。后续建议：

- 后台数据库加密保存密钥。
- `.env` 文件权限固定为 `600`。
- 日志中屏蔽 key、secret、token。
- GitHub token 和服务器密码不进入任何仓库。

### 13.3 监控和告警

需要补：

- 容器健康状态。
- MCP 初始化耗时。
- OAuth refresh 成功率。
- 飞书消息收发成功率。
- 模型 API 失败率。
- 向量检索失败率。
- 内存、CPU、磁盘、swap 使用率。
- 证书到期提醒。

### 13.4 备份策略

建议：

- 每个实例每天备份一次数据目录。
- 备份前可短暂停容器或做文件级一致性处理。
- 保留 7 天日备份、4 周周备份。
- 定期做恢复演练。
- 大量向量库可单独压缩或对象存储归档。

### 13.5 资源隔离

建议补：

- 每个容器 memory limit。
- 每个容器 CPU limit。
- 梦境任务错峰。
- keepalive 错峰。
- 大文件索引任务限流。

### 13.6 镜像和版本管理

建议：

- 镜像使用明确版本号，例如 `2026.5.7`。
- 不建议生产固定使用 `latest`。
- 升级前先复制一个测试实例验证。
- 升级后保留旧镜像一段时间，便于回滚。
- 配置和数据目录与镜像版本解耦。

## 14. 推荐分工

运维同事：

- DNS 解析。
- 1Panel 网站/证书。
- 容器资源限制。
- 数据备份。
- 服务器监控。

交付同事：

- 收集用户飞书 App ID / Secret。
- 收集用户 open_id 和授权目标 chat_id。
- 指导用户添加回调 URL。
- 指导用户点击授权卡片。

研发同事：

- 维护镜像。
- 维护部署脚本。
- 封装后台。
- 优化 MCP keepalive。
- 优化 1Panel API 接入。
- 做权限、密钥、日志脱敏。

## 15. 标准交付清单

每个新用户交付时检查：

- [ ] 域名已解析到服务器。
- [ ] 1Panel 网站已创建。
- [ ] SSL 证书已申请并启用。
- [ ] `/` 可访问 OpenClaw。
- [ ] `/callback` 可访问 OAuth 回调服务。
- [ ] `/authorize` 可访问 OAuth 授权服务。
- [ ] 飞书开放平台已配置 `https://<domain>/callback`。
- [ ] 飞书 App ID / Secret 已写入实例。
- [ ] 用户 open_id 已写入 allowlist。
- [ ] 用户已点击授权卡片。
- [ ] `im_v1_chat_list useUAT=true` 测试成功。
- [ ] 知识库读取测试成功。
- [ ] 记忆功能开启。
- [ ] 向量配置正确。
- [ ] 数据目录进入备份计划。
- [ ] keepalive 覆盖该实例。
