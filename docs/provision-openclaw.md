# OpenClaw Instance Provisioning

For the current colleague-facing implementation guide, see:

```text
docs/openclaw-tenant-implementation-v2.md
```

This document describes the operator flow for creating one isolated OpenClaw
container per user.

The provisioning script creates a clean instance. It can inherit model and
embedding defaults from an existing template instance, but it does not copy
OAuth tokens, memories, vector stores, chat history, logs, workspace files, or
the template `openclaw.json`.

The tenant's `.env` is the source of truth. The container renders
`data/conf/openclaw.json` from that environment on first start. This avoids
stale domains, plugin state, or old channel settings leaking from another
tenant.

## Server Script

```bash
provision-openclaw --interactive --panel
```

Equivalent direct path:

```bash
python3 scripts/provision_openclaw_instance.py --interactive --panel
```

Use `--direct` instead of `--panel` when you only want Docker Compose and do not
want to register the instance in 1Panel.

## Required Inputs

- Instance name, for example `user03`
- Public domain, for example `user03.example.com`
- Feishu App ID
- Feishu App Secret
- Optional Feishu authorization target chat ID
- Optional owner open ID for DM allowlist mode
- Authorization target mode, default `first_sender`
- Optional embedding provider, model, base URL, and API key override

The script auto-generates the OpenClaw gateway token unless `--gateway-token` is
provided.

## Embedding Configuration

Each instance should have explicit embedding defaults. If no override is
provided, the provisioning script inherits them from the template instance.

Default DashScope/Qwen-compatible values:

```text
OPENCLAW_EMBEDDING_PROVIDER=openai
OPENCLAW_EMBEDDING_MODEL=text-embedding-v4
OPENCLAW_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

`OPENCLAW_EMBEDDING_API_KEY` can be set when the embedding provider uses a
separate key. If it is empty, the image falls back to `DASHSCOPE_API_KEY`.

## Docker Network

New instances use one shared Docker bridge network by default:

```text
OPENDD_DOCKER_NETWORK=openclaw-net
```

The provisioning script checks whether this network exists before starting the
container and creates it only when missing. Per-tenant isolation is still handled
by separate container names, host ports, data directories, gateway tokens,
Feishu app credentials, OAuth token stores, memories, and vector data. Use
`--docker-network <name>` only when a host needs a different shared network.

## Feishu Open Platform

Before sending the authorization card, add this redirect URL in the Feishu app:

```text
https://<domain>/callback
```

For example:

```text
https://user03.example.com/callback
```

The default event callback mode is Feishu long connection. The script does not
require a public event callback URL for message receiving.

## Authorization Target Modes

Recommended default:

```text
FEISHU_AUTH_TARGET_MODE=first_sender
OPENDD_PAIRING_AUTH_WATCHER=1
FEISHU_DM_POLICY=pairing
```

In this mode, the operator does not need to know the user's `open_id` or target
`chat_id` before deployment. The user sends the bot a direct message, or
mentions it in a group. OpenClaw records the pairing request, and the watcher
sends a guided OAuth card to the first sender.

The guided card includes:

- The Feishu app ID.
- The exact redirect URL that must be added in Feishu Open Platform.
- A button to open the Feishu app console.
- A button to start user OAuth after the redirect URL has been saved.

Default:

```text
FEISHU_AUTH_CARD_MODE=guided
```

Set `FEISHU_AUTH_CARD_MODE=auth` only when the redirect URL has already been
configured and the user should receive a plain authorization card.

In guided mode, the watcher uses a shorter default resend interval of 30
minutes because the OAuth URL embedded in the card is short-lived. Override with
`FEISHU_AUTH_CARD_COOLDOWN_MS` when needed.

Manual mode:

```text
FEISHU_AUTH_TARGET_MODE=fixed
FEISHU_AUTH_TARGET=<open_id or chat_id>
```

Use this only when the operator already knows exactly where the authorization
card should be sent.

## 1Panel Mode

Panel mode creates the instance under:

```text
/opt/1panel/apps/openclaw/<instance-name>
```

It writes:

- `.env`
- `docker-compose.yml`
- `tenant.json`
- clean `data/workspace`

`tenant.json` is a non-secret manifest with the instance name, domain, ports,
container name, model IDs, embedding model, and 1Panel IDs. It is intended for
operations, checks, and future migration scripts. Secrets stay in `.env` and
OpenClaw's own data files.

With `--register-panel`, the script inserts 1Panel app and agent records.

With `--register-website`, it also creates a 1Panel website record and writes
OpenResty reverse proxy files:

```text
/opt/1panel/www/conf.d/<domain>.conf
/opt/1panel/www/sites/<domain>/proxy/root.conf
/opt/1panel/www/sites/<domain>/proxy/feishu-callback.conf
/opt/1panel/www/sites/<domain>/proxy/feishu-authorize.conf
```

Reverse proxy routes:

```text
/          -> http://127.0.0.1:<http-port>
/callback  -> http://127.0.0.1:<oauth-port>
/authorize -> http://127.0.0.1:<oauth-port>
```

SSL should still be requested or bound in 1Panel so certificate renewal remains
visible and manageable in the panel. Use DNS account validation when available;
for example, the Tencent Cloud DNS account in 1Panel can issue certificates
without relying on public HTTP access to `/.well-known/acme-challenge`.

Recommended certificate flow:

1. Create the website/reverse proxy with this script.
2. In 1Panel SSL, apply a certificate with validation method `DNS account`.
3. Select the Tencent Cloud DNS account.
4. Bind the issued certificate to the tenant website.
5. Run the check script and confirm the certificate record is `ready` and
   public HTTPS returns `HTTP/2 200` or `HTTP/1.1 200`.

## Check Script

After deploying, validate the instance without changing it:

```bash
python3 scripts/check_openclaw_instance.py --name user03 --domain user03.example.com
```

On the current server, the same script is installed as:

```bash
check-openclaw-instance --name user03 --domain user03.example.com
```

The checker reports:

- Docker container status and health.
- Recent model and Feishu WebSocket readiness log lines.
- Generated `openclaw.json` domain/model/channel sanity.
- 1Panel agent and app install records.
- 1Panel website record.
- 1Panel certificate record and latest error message.
- Public HTTP/HTTPS health probes.
- Feishu user token storage status.

## Data Isolation

Each user gets an independent directory:

```text
/opt/1panel/apps/openclaw/<instance-name>/data
```

Back up this directory to preserve that user's:

- OpenClaw config
- memory data
- vector data
- OAuth/session files
- workspace files
- logs

To restore on another server, deploy the same image, mount the saved data
directory, and keep the domain/Feishu redirect URL consistent or reauthorize.

## Example

```bash
provision-openclaw \
  --panel \
  --register-panel \
  --register-website \
  --template ql1 \
  --name user03 \
  --domain user03.example.com \
  --feishu-app-id cli_xxx \
  --feishu-app-secret '***' \
  --auth-target-mode first_sender \
  --embedding-provider openai \
  --embedding-model text-embedding-v4 \
  --embedding-base-url https://dashscope.aliyuncs.com/compatible-mode/v1
```

After HTTPS is available and the Feishu redirect URL is configured, send the
authorization card:

```bash
provision-openclaw \
  --send-auth-card-only \
  --panel \
  --name user03 \
  --domain user03.example.com \
  --auth-chat-id oc_xxx
```
