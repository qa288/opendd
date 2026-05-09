# opendd OpenClaw tenant image

This repository builds an OpenClaw image for one-user-per-container deployment.

The image contains only the runtime layer and initialization scripts. User data is not baked into the image. Each tenant must mount its own persistent directory to `/home/node/.openclaw`.

## Image

Default image:

```bash
ghcr.io/qa288/opendd:2026.5.7
```

Build locally:

```bash
docker build \
  --build-arg OPENCLAW_VERSION=2026.5.7 \
  -t ghcr.io/qa288/opendd:2026.5.7 .
```

Push manually:

```bash
echo "$GITHUB_PAT" | docker login ghcr.io -u qa288 --password-stdin
docker push ghcr.io/qa288/opendd:2026.5.7
```

The GitHub Actions workflow also publishes `2026.5.7` and `latest` to GHCR on every push to `main`.

## Tenant layout

Use one directory per user:

```bash
/data/openclaw-tenants/
  user001/
    openclaw/
    backups/
    .env
    docker-compose.yml
```

Mount:

```yaml
volumes:
  - /data/openclaw-tenants/user001/openclaw:/home/node/.openclaw
```

Everything important is stored under that mount, including:

- OpenClaw config: `openclaw.json`
- memory files and dream reports: `workspace/`
- conversation and agent state: `agents/`
- Feishu OAuth user token cache: `home/.local/share/lark-mcp-nodejs/`
- Feishu allowlist credentials: `credentials/`

## Create a tenant

```bash
export TENANT_ID=user001
export TENANT_DOMAIN=user001.ope.tyos.cc
export WEB_PORT=18791
export OAUTH_PORT=31891
bash scripts/create-tenant.sh
```

Then edit:

```bash
/data/openclaw-tenants/user001/.env
```

Required values:

- `OPENCLAW_MODEL_API_KEY`
- `DASHSCOPE_API_KEY`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_OWNER_OPEN_ID`

Start:

```bash
cd /data/openclaw-tenants/user001
docker compose up -d
```

Feishu OAuth redirect URL for this tenant:

```text
https://user001.ope.tyos.cc/callback
```

## Send Feishu authorization card

After the container starts:

```bash
docker exec -d openclaw-user001 opendd-send-feishu-auth-card
docker logs -f openclaw-user001
```

If `OPENDD_SEND_AUTH_CARD_ON_START=1` is set and no user token exists yet, the container sends the authorization card automatically on first start.

## Backup

For a clean backup, stop the container first:

```bash
docker stop openclaw-user001
tar -czf /data/openclaw-tenants/user001/backups/user001-$(date +%F-%H%M).tar.gz \
  -C /data/openclaw-tenants user001 \
  --exclude='user001/backups'
docker start openclaw-user001
```

Restore by extracting the tenant directory on the new server and mounting `openclaw/` back to `/home/node/.openclaw`.

If the public domain changes after restore, update:

- `OPENCLAW_PUBLIC_URL`
- `LARK_MCP_PUBLIC_URL`
- Feishu OAuth redirect URL
- reverse proxy rules

