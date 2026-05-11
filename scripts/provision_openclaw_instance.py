#!/usr/bin/env python3
"""
Provision an isolated OpenClaw instance.

This script is intended to run on the server that hosts Docker and, optionally,
1Panel. It creates a clean per-user instance directory, writes env/compose and
manifest files, starts the container, and can register the instance in 1Panel's
agent/app list for visibility. The OpenClaw config is rendered by the container
on first start from the environment, which keeps stale template domains or
channel state from leaking into new tenants.

It deliberately does not copy another user's data directory. Model defaults can
be inherited from a template instance, but OAuth tokens, memories, vector stores,
logs, and chat history are left empty for the new instance.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


DEFAULT_IMAGE = "ghcr.io/qa288/opendd:2026.5.7"
DEFAULT_PANEL_DB = Path("/opt/1panel/db/agent.db")
DEFAULT_PANEL_BASE = Path("/opt/1panel/apps/openclaw")
DEFAULT_DIRECT_BASE = Path("/opt/openclaw-instances")
CONTAINER_HTTP_PORT = 18789
CONTAINER_OAUTH_PORT = 31888


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd: Iterable[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    printable = " ".join(cmd)
    print(f"+ {printable}")
    return subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def ask(prompt: str, default: Optional[str] = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        if secret:
            value = getpass.getpass(f"{prompt}{suffix}: ").strip()
        else:
            value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default


def yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        value = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "1", "true"}:
            return True
        if value in {"n", "no", "0", "false"}:
            return False


def load_env(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "'\"'\"'")
    return f"'{escaped}'"


def write_env(path: Path, values: Dict[str, str]) -> None:
    lines = []
    for key in sorted(values):
        lines.append(f"{key}={quote_env(str(values[key]))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def next_free_port(start: int) -> int:
    port = start
    while port < 65535:
        if port_is_free(port):
            return port
        port += 1
    die(f"no free port found from {start}")
    return -1


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def compose_yaml(service_name: str, container_name: str, image: str) -> str:
    return f"""services:
  {service_name}:
    image: ${{OPENDD_IMAGE:-{image}}}
    container_name: {container_name}
    restart: unless-stopped
    ports:
      - "${{PANEL_APP_PORT_HTTP:-18800}}:{CONTAINER_HTTP_PORT}"
      - "${{PANEL_APP_PORT_OAUTH:-31888}}:{CONTAINER_OAUTH_PORT}"
    env_file:
      - .env
    environment:
      HOME: /home/node
      OPENCLAW_HOME: /home/node/.openclaw
      XDG_DATA_HOME: /home/node/.openclaw/home/.local/share
      OPENCLAW_PUBLIC_URL: ${{OPENCLAW_PUBLIC_URL}}
      LARK_MCP_PUBLIC_URL: ${{LARK_MCP_PUBLIC_URL}}
      OPENCLAW_ALLOWED_ORIGINS: ${{OPENCLAW_ALLOWED_ORIGINS:-}}
      OPENCLAW_CONFIG: ${{OPENCLAW_CONFIG:-/home/node/.openclaw/openclaw.json}}
      OPENCLAW_CONFIG_PATH: ${{OPENCLAW_CONFIG_PATH:-/home/node/.openclaw/openclaw.json}}
      OPENCLAW_STATE_DIR: ${{OPENCLAW_STATE_DIR:-/home/node/.openclaw}}
      OPENCLAW_GATEWAY_TOKEN: ${{OPENCLAW_GATEWAY_TOKEN}}
      FEISHU_ENABLED: ${{FEISHU_ENABLED:-true}}
      FEISHU_DOMAIN: ${{FEISHU_DOMAIN:-feishu}}
      FEISHU_APP_ID: ${{FEISHU_APP_ID}}
      FEISHU_APP_SECRET: ${{FEISHU_APP_SECRET}}
      FEISHU_OWNER_OPEN_ID: ${{FEISHU_OWNER_OPEN_ID:-}}
      FEISHU_AUTH_TARGET_MODE: ${{FEISHU_AUTH_TARGET_MODE:-first_sender}}
      FEISHU_AUTH_TARGET: ${{FEISHU_AUTH_TARGET:-}}
      FEISHU_AUTH_CARD_MODE: ${{FEISHU_AUTH_CARD_MODE:-guided}}
      FEISHU_AUTH_BIND_FIRST_USER: ${{FEISHU_AUTH_BIND_FIRST_USER:-1}}
      OPENDD_PAIRING_AUTH_WATCHER: ${{OPENDD_PAIRING_AUTH_WATCHER:-1}}
      FEISHU_DM_POLICY: ${{FEISHU_DM_POLICY:-pairing}}
      FEISHU_GROUP_POLICY: ${{FEISHU_GROUP_POLICY:-open}}
      FEISHU_GROUP_OWNER_ONLY: ${{FEISHU_GROUP_OWNER_ONLY:-1}}
      OPENCLAW_MODEL_PROVIDER: ${{OPENCLAW_MODEL_PROVIDER:-}}
      OPENCLAW_MODEL_ID: ${{OPENCLAW_MODEL_ID:-}}
      OPENCLAW_MODEL_API: ${{OPENCLAW_MODEL_API:-}}
      OPENCLAW_MODEL_BASE_URL: ${{OPENCLAW_MODEL_BASE_URL:-}}
      OPENCLAW_MODEL_API_KEY: ${{OPENCLAW_MODEL_API_KEY:-}}
      DASHSCOPE_API_KEY: ${{DASHSCOPE_API_KEY:-}}
      OPENCLAW_EMBEDDING_PROVIDER: ${{OPENCLAW_EMBEDDING_PROVIDER:-openai}}
      OPENCLAW_EMBEDDING_API_KEY: ${{OPENCLAW_EMBEDDING_API_KEY:-}}
      OPENCLAW_EMBEDDING_MODEL: ${{OPENCLAW_EMBEDDING_MODEL:-text-embedding-v4}}
      OPENCLAW_EMBEDDING_BASE_URL: ${{OPENCLAW_EMBEDDING_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}}
      LARK_MCP_LOGIN_HOST: 0.0.0.0
      LARK_MCP_LOGIN_PORT: "{CONTAINER_OAUTH_PORT}"
    volumes:
      - ./data/conf:/home/node/.openclaw
      - ./data/workspace:/home/node/.openclaw/workspace
"""


def copy_model_defaults(template_env: Dict[str, str]) -> Dict[str, str]:
    keys = [
        "PROVIDER",
        "API_TYPE",
        "MAX_TOKENS",
        "API_KEY",
        "MODEL",
        "CONTEXT_WINDOW",
        "BASE_URL",
        "OPENCLAW_MODEL_PROVIDER",
        "OPENCLAW_MODEL_ID",
        "OPENCLAW_MODEL_API",
        "OPENCLAW_MODEL_BASE_URL",
        "OPENCLAW_MODEL_API_KEY",
        "DASHSCOPE_API_KEY",
        "OPENCLAW_EMBEDDING_PROVIDER",
        "OPENCLAW_EMBEDDING_API_KEY",
        "OPENCLAW_EMBEDDING_MODEL",
        "OPENCLAW_EMBEDDING_BASE_URL",
    ]
    return {key: template_env[key] for key in keys if template_env.get(key)}


def tenant_manifest(
    args: argparse.Namespace,
    instance_dir: Path,
    container_name: str,
    http_port: int,
    oauth_port: int,
    env: Dict[str, str],
    app_install_id: int = 0,
    website_id: int = 0,
) -> Dict[str, Any]:
    return {
        "schemaVersion": 1,
        "name": args.name,
        "domain": args.domain,
        "publicUrl": f"https://{args.domain}",
        "createdAt": utc_now(),
        "mode": "panel" if args.panel else "direct",
        "image": args.image,
        "containerName": container_name,
        "paths": {
            "instance": str(instance_dir),
            "env": str(instance_dir / ".env"),
            "compose": str(instance_dir / "docker-compose.yml"),
            "data": str(instance_dir / "data"),
            "config": str(instance_dir / "data/conf/openclaw.json"),
            "workspace": str(instance_dir / "data/workspace"),
        },
        "ports": {
            "http": http_port,
            "oauth": oauth_port,
            "containerHttp": CONTAINER_HTTP_PORT,
            "containerOauth": CONTAINER_OAUTH_PORT,
        },
        "panel": {
            "appInstallId": app_install_id,
            "websiteId": website_id,
        },
        "feishu": {
            "appId": args.feishu_app_id,
            "domain": env.get("FEISHU_DOMAIN", "feishu"),
            "authTargetMode": args.auth_target_mode,
            "authCardMode": env.get("FEISHU_AUTH_CARD_MODE", "guided"),
            "ownerOpenIdConfigured": bool(args.owner_open_id),
        },
        "model": {
            "provider": env.get("OPENCLAW_MODEL_PROVIDER") or env.get("PROVIDER", ""),
            "id": env.get("OPENCLAW_MODEL_ID") or env.get("MODEL", ""),
            "api": env.get("OPENCLAW_MODEL_API") or env.get("API_TYPE", ""),
            "baseUrl": env.get("OPENCLAW_MODEL_BASE_URL") or env.get("BASE_URL", ""),
        },
        "embedding": {
            "provider": env.get("OPENCLAW_EMBEDDING_PROVIDER", ""),
            "model": env.get("OPENCLAW_EMBEDDING_MODEL", ""),
            "baseUrl": env.get("OPENCLAW_EMBEDDING_BASE_URL", ""),
            "hasDedicatedKey": bool(env.get("OPENCLAW_EMBEDDING_API_KEY")),
        },
        "config": {
            "source": "container-entrypoint",
            "renderPolicy": env.get("OPENDD_RENDER_CONFIG", "missing"),
        },
    }


def write_tenant_manifest(
    args: argparse.Namespace,
    instance_dir: Path,
    container_name: str,
    http_port: int,
    oauth_port: int,
    env: Dict[str, str],
    app_install_id: int = 0,
    website_id: int = 0,
) -> None:
    write_json(
        instance_dir / "tenant.json",
        tenant_manifest(args, instance_dir, container_name, http_port, oauth_port, env, app_install_id, website_id),
    )


def create_instance_files(args: argparse.Namespace) -> Tuple[Path, str, int, int, Dict[str, str]]:
    base_dir = Path(args.base_dir or (DEFAULT_PANEL_BASE if args.panel else DEFAULT_DIRECT_BASE))
    instance_dir = base_dir / args.name
    if instance_dir.exists() and not args.force:
        die(f"instance directory already exists: {instance_dir}")

    template_dir = base_dir / args.template
    if not template_dir.exists() and args.template_path:
        template_dir = Path(args.template_path)
    template_env = load_env(template_dir / ".env")

    http_port = int(args.http_port or next_free_port(args.http_start))
    oauth_port = int(args.oauth_port or next_free_port(args.oauth_start))
    container_name = args.container_name or f"1Panel-openclaw-{args.name}" if args.panel else f"openclaw-{args.name}"
    service_name = "openclaw"

    if instance_dir.exists() and args.force:
        die("refusing to overwrite an existing instance with --force; move it aside manually first")
    (instance_dir / "data/conf").mkdir(parents=True, exist_ok=True)
    (instance_dir / "data/workspace").mkdir(parents=True, exist_ok=True)
    (instance_dir / "data/conf/logs").mkdir(parents=True, exist_ok=True)

    env = copy_model_defaults(template_env)
    env.update(
        {
            "CONTAINER_NAME": container_name,
            "CPUS": args.cpus,
            "MEMORY_LIMIT": args.memory_limit,
            "PANEL_APP_PORT_HTTP": str(http_port),
            "PANEL_APP_PORT_OAUTH": str(oauth_port),
            "HOST_IP": "",
            "ALLOWED_ORIGIN": f"https://{args.domain}",
            "OPENDD_IMAGE": args.image,
            "OPENDD_RENDER_CONFIG": "missing",
            "OPENDD_SEND_AUTH_CARD_ON_START": "0",
            "OPENCLAW_PUBLIC_URL": f"https://{args.domain}",
            "LARK_MCP_PUBLIC_URL": f"https://{args.domain}",
            "OPENCLAW_ALLOWED_ORIGINS": f"https://{args.domain}",
            "HOME": "/home/node",
            "OPENCLAW_HOME": "/home/node/.openclaw",
            "OPENCLAW_CONFIG": "/home/node/.openclaw/openclaw.json",
            "OPENCLAW_CONFIG_PATH": "/home/node/.openclaw/openclaw.json",
            "OPENCLAW_STATE_DIR": "/home/node/.openclaw",
            "XDG_DATA_HOME": "/home/node/.openclaw/home/.local/share",
            "OPENCLAW_GATEWAY_TOKEN": args.gateway_token or secrets.token_urlsafe(32),
            "OPENCLAW_EMBEDDING_PROVIDER": args.embedding_provider or env.get("OPENCLAW_EMBEDDING_PROVIDER", "openai"),
            "OPENCLAW_EMBEDDING_API_KEY": args.embedding_api_key or env.get("OPENCLAW_EMBEDDING_API_KEY", ""),
            "OPENCLAW_EMBEDDING_MODEL": args.embedding_model or env.get("OPENCLAW_EMBEDDING_MODEL", "text-embedding-v4"),
            "OPENCLAW_EMBEDDING_BASE_URL": args.embedding_base_url or env.get("OPENCLAW_EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "FEISHU_ENABLED": "true",
            "FEISHU_DOMAIN": "feishu",
            "FEISHU_APP_ID": args.feishu_app_id,
            "FEISHU_APP_SECRET": args.feishu_app_secret,
            "FEISHU_OWNER_OPEN_ID": args.owner_open_id or "",
            "FEISHU_AUTH_TARGET_CHAT_ID": args.auth_chat_id,
            "FEISHU_AUTH_TARGET": args.auth_chat_id,
            "FEISHU_AUTH_CARD_MODE": "guided",
            "FEISHU_AUTH_TARGET_MODE": args.auth_target_mode,
            "FEISHU_AUTH_BIND_FIRST_USER": "1" if args.auth_target_mode != "fixed" else "0",
            "OPENDD_PAIRING_AUTH_WATCHER": "1" if args.auth_target_mode != "fixed" else "0",
            "FEISHU_DM_POLICY": "allowlist" if args.owner_open_id else ("pairing" if args.auth_target_mode != "fixed" else "open"),
            "FEISHU_GROUP_POLICY": "open",
            "FEISHU_GROUP_OWNER_ONLY": "1",
        }
    )
    write_env(instance_dir / ".env", env)
    write_tenant_manifest(args, instance_dir, container_name, http_port, oauth_port, env)
    (instance_dir / "docker-compose.yml").write_text(
        compose_yaml(service_name, container_name, args.image),
        encoding="utf-8",
    )

    return instance_dir, container_name, http_port, oauth_port, env


def sqlite_columns(cur: sqlite3.Cursor, table: str) -> list[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def insert_row(cur: sqlite3.Cursor, table: str, values: Dict[str, Any]) -> int:
    columns = sqlite_columns(cur, table)
    filtered = {key: value for key, value in values.items() if key in columns}
    keys = list(filtered)
    placeholders = ",".join(["?"] * len(keys))
    quoted_keys = ",".join([f'"{key}"' for key in keys])
    cur.execute(
        f'INSERT INTO "{table}" ({quoted_keys}) VALUES ({placeholders})',
        [filtered[key] for key in keys],
    )
    return int(cur.lastrowid)


def panel_register(args: argparse.Namespace, instance_dir: Path, container_name: str, http_port: int) -> int:
    db_path = Path(args.panel_db)
    if not db_path.exists():
        die(f"1Panel database not found: {db_path}")

    backup = db_path.with_suffix(f".db.bak-{int(time.time())}")
    shutil.copy2(db_path, backup)
    print(f"1Panel database backup: {backup}")

    env_text = (instance_dir / ".env").read_text(encoding="utf-8")
    compose_text = (instance_dir / "docker-compose.yml").read_text(encoding="utf-8")
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM app_installs WHERE name = ?", (args.name,))
        row = cur.fetchone()
        if row:
            print(f"1Panel app_install already exists: id={row[0]}")
            app_install_id = int(row[0])
        else:
            cur.execute("SELECT * FROM app_installs WHERE name = ?", (args.template,))
            template = cur.fetchone()
            template_cols = [desc[0] for desc in cur.description] if template else []
            template_map = dict(zip(template_cols, template)) if template else {}
            app_install_id = insert_row(
                cur,
                "app_installs",
                {
                    "created_at": now,
                    "updated_at": now,
                    "name": args.name,
                    "app_id": template_map.get("app_id", 0),
                    "app_detail_id": template_map.get("app_detail_id", 0),
                    "version": args.app_version,
                    "status": "Running",
                    "description": args.description or args.name,
                    "message": "",
                    "container_name": container_name,
                    "service_name": "openclaw",
                    "http_port": http_port,
                    "web_ui": f"https://{args.domain}",
                    "docker_compose": compose_text,
                    "env": env_text,
                    "param": json.dumps({"name": args.name, "domain": args.domain}, ensure_ascii=False),
                    "favorite": 0,
                    "sort_order": int(time.time()),
                },
            )
            print(f"registered 1Panel app_install: id={app_install_id}")

        cur.execute("SELECT id FROM agents WHERE name = ?", (args.name,))
        if cur.fetchone():
            print("1Panel agent already exists")
        else:
            cur.execute("SELECT * FROM agents WHERE name = ?", (args.template,))
            template = cur.fetchone()
            template_cols = [desc[0] for desc in cur.description] if template else []
            template_map = dict(zip(template_cols, template)) if template else {}
            insert_row(
                cur,
                "agents",
                {
                    "created_at": now,
                    "updated_at": now,
                    "name": args.name,
                    "remark": args.description or args.name,
                    "agent_type": template_map.get("agent_type", "openclaw"),
                    "provider": template_map.get("provider", ""),
                    "model": template_map.get("model", ""),
                    "api_type": template_map.get("api_type", ""),
                    "max_tokens": template_map.get("max_tokens", 32768),
                    "context_window": template_map.get("context_window", 256000),
                    "base_url": template_map.get("base_url", ""),
                    "api_key": template_map.get("api_key", ""),
                    "token": load_env(instance_dir / ".env").get("OPENCLAW_GATEWAY_TOKEN", ""),
                    "status": "Installing",
                    "message": "",
                    "app_install_id": app_install_id,
                    "website_id": 0,
                    "account_id": template_map.get("account_id", 0),
                    "config_path": str(instance_dir / "data/conf/openclaw.json"),
                },
            )
            print("registered 1Panel agent")
        conn.commit()
        return app_install_id
    finally:
        conn.close()


def start_container(instance_dir: Path) -> None:
    compose = shutil.which("docker-compose")
    if compose:
        cmd = [compose, "up", "-d"]
    else:
        cmd = ["docker", "compose", "up", "-d"]
    result = run(cmd, cwd=instance_dir, check=False)
    print(result.stdout)
    if result.returncode != 0:
        die("docker compose up failed")


def proxy_location(location: str, port: int) -> str:
    prefix = "location ^~ /" if location == "/" else f"location {location}"
    return f"""{prefix} {{
    proxy_pass http://127.0.0.1:{port}; 
    proxy_set_header Host $host; 
    proxy_set_header X-Real-IP $remote_addr; 
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; 
    proxy_set_header REMOTE-HOST $remote_addr; 
    proxy_set_header Upgrade $http_upgrade; 
    proxy_set_header Connection $http_connection; 
    proxy_set_header X-Forwarded-Proto $scheme; 
    proxy_set_header X-Forwarded-Port $server_port; 
    proxy_http_version 1.1; 
    add_header X-Cache $upstream_cache_status; 
    proxy_ssl_server_name off; 
    proxy_ssl_name $proxy_host; 
}}
"""


def write_openresty_site(args: argparse.Namespace, http_port: int, oauth_port: int) -> None:
    domain = args.domain
    site_dir = Path("/opt/1panel/www/sites") / domain
    conf_dir = Path("/opt/1panel/www/conf.d")
    (site_dir / "proxy").mkdir(parents=True, exist_ok=True)
    (site_dir / "log").mkdir(parents=True, exist_ok=True)
    (site_dir / "index").mkdir(parents=True, exist_ok=True)
    conf_dir.mkdir(parents=True, exist_ok=True)

    (site_dir / "proxy/root.conf").write_text(proxy_location("/", http_port), encoding="utf-8")
    (site_dir / "proxy/feishu-callback.conf").write_text(proxy_location("/callback", oauth_port), encoding="utf-8")
    (site_dir / "proxy/feishu-authorize.conf").write_text(proxy_location("/authorize", oauth_port), encoding="utf-8")

    https = bool(args.website_ssl_id or args.https_site)
    listen = "    listen 80 ; \n"
    ssl_block = ""
    redirect_block = ""
    if https:
        listen += "    listen 443 ssl ; \n"
        redirect_block = """    if ($scheme = http) {
        return 301 https://$host$request_uri; 
    }
"""
        ssl_block = f"""    http2 on; 
    ssl_certificate /www/sites/{domain}/ssl/fullchain.pem; 
    ssl_certificate_key /www/sites/{domain}/ssl/privkey.pem; 
    ssl_protocols TLSv1.3 TLSv1.2; 
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256; 
    ssl_prefer_server_ciphers off; 
    ssl_session_cache shared:SSL:10m; 
    ssl_session_timeout 10m; 
    error_page 497 https://$host$request_uri; 
    proxy_set_header X-Forwarded-Proto https; 
    add_header Strict-Transport-Security "max-age=31536000"; 
"""

    server_conf = f"""server {{
{listen}    server_name {domain}; 
    index index.php index.html index.htm default.php default.htm default.html; 
    access_log /www/sites/{domain}/log/access.log main; 
    error_log /www/sites/{domain}/log/error.log; 
    location ~ ^/(\\.user.ini|\\.htaccess|\\.git|\\.env|\\.svn|\\.project|LICENSE|README.md) {{
        return 404; 
    }}
    location ^~ /.well-known/acme-challenge {{
        allow all; 
        root /usr/share/nginx/html; 
    }}
    if ( $uri ~ "^/\\.well-known/.*\\.(php|jsp|py|js|css|lua|ts|go|zip|tar\\.gz|rar|7z|sql|bak)$" ) {{
        return 403; 
    }}
    root /www/sites/{domain}/index; 
{redirect_block}{ssl_block}    include /www/sites/{domain}/proxy/*.conf; 
}}
"""
    (conf_dir / f"{domain}.conf").write_text(server_conf, encoding="utf-8")
    run(["docker", "exec", "1Panel-openresty-cLtk", "nginx", "-s", "reload"], check=False)


def panel_register_website(args: argparse.Namespace, app_install_id: int, http_port: int) -> int:
    db_path = Path(args.panel_db)
    if not db_path.exists():
        die(f"1Panel database not found: {db_path}")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    protocol = "HTTPS" if args.website_ssl_id or args.https_site else "HTTP"
    http_config = "HTTPToHTTPS" if protocol == "HTTPS" else "HTTPOnly"
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM websites WHERE primary_domain = ?", (args.domain,))
        row = cur.fetchone()
        if row:
            website_id = int(row[0])
            print(f"1Panel website already exists: id={website_id}")
        else:
            website_id = insert_row(
                cur,
                "websites",
                {
                    "created_at": now,
                    "updated_at": now,
                    "protocol": protocol,
                    "primary_domain": args.domain,
                    "type": "proxy",
                    "alias": args.domain,
                    "remark": args.description or args.name,
                    "status": "Running",
                    "http_config": http_config,
                    "expire_date": None,
                    "proxy": f"http://127.0.0.1:{http_port}",
                    "proxy_type": "proxy",
                    "site_dir": f"/www/sites/{args.domain}/index",
                    "error_log": 1,
                    "access_log": 1,
                    "default_server": 0,
                    "ip_v6": 0,
                    "rewrite": "",
                    "website_group_id": 0,
                    "website_ssl_id": int(args.website_ssl_id or 0),
                    "runtime_id": 0,
                    "app_install_id": 0,
                    "ftp_id": 0,
                    "parent_website_id": 0,
                    "user": "",
                    "group": "",
                    "db_type": "",
                    "db_id": 0,
                    "favorite": 0,
                    "stream_ports": "",
                },
            )
            print(f"registered 1Panel website: id={website_id}")
        cur.execute(
            "UPDATE agents SET website_id = ? WHERE app_install_id = ?",
            (website_id, app_install_id),
        )
        conn.commit()
        return website_id
    finally:
        conn.close()


def send_auth_card(container_name: str, domain: str, auth_chat_id: str) -> None:
    script = "/opt/opendd/bin/send-feishu-auth-card.js"
    target = shlex.quote(auth_chat_id)
    public_url = shlex.quote(f"https://{domain}")
    shell = (
        "mkdir -p /home/node/.openclaw/logs && "
        f"nohup node {script} "
        f"--target {target} --public-url {public_url} --mode guided "
        "> /home/node/.openclaw/logs/feishu-auth-card.log 2>&1 &"
    )
    result = run(["docker", "exec", "-d", container_name, "sh", "-lc", shell], check=False)
    if result.returncode == 0:
        print("authorization card task started inside container")
    else:
        print(result.stdout)
        print("authorization card was not sent automatically; send it after the container is healthy")


def print_next_steps(args: argparse.Namespace, http_port: int, oauth_port: int) -> None:
    print("\nDONE")
    print(f"Instance: {args.name}")
    print(f"Domain: https://{args.domain}")
    print(f"Container HTTP: 127.0.0.1:{http_port} -> {CONTAINER_HTTP_PORT}")
    print(f"OAuth callback: 127.0.0.1:{oauth_port} -> {CONTAINER_OAUTH_PORT}")
    print("\nFeishu open platform must contain this redirect URL:")
    print(f"  https://{args.domain}/callback")
    print("\nReverse proxy should route:")
    print(f"  /          -> http://127.0.0.1:{http_port}")
    print(f"  /callback  -> http://127.0.0.1:{oauth_port}")
    print(f"  /authorize -> http://127.0.0.1:{oauth_port}")
    if args.panel:
        print("\n1Panel:")
        print("  App/agent record has been registered if --register-panel was enabled.")
        print("  Website record and OpenResty proxy were written if --register-website was enabled.")
        print("  If HTTPS was not enabled yet, request/bind SSL in 1Panel and then switch the site to HTTPS.")
    if not args.send_auth_card:
        print("\nAfter HTTPS and Feishu redirect are ready, send the OAuth card:")
        print(f"  python3 {Path(__file__).name} --send-auth-card-only --name {args.name} --domain {args.domain} --auth-chat-id <chat_id>")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision an isolated OpenClaw instance")
    parser.add_argument("--interactive", action="store_true", help="ask for missing values")
    parser.add_argument("--panel", action="store_true", help="use /opt/1panel/apps/openclaw as base path")
    parser.add_argument("--direct", action="store_true", help="deploy outside 1Panel")
    parser.add_argument("--register-panel", action="store_true", help="insert 1Panel app/agent DB records")
    parser.add_argument("--register-website", action="store_true", help="insert 1Panel website DB record and write OpenResty proxy files")
    parser.add_argument("--website-ssl-id", type=int, default=0, help="existing 1Panel website_ssl id to bind")
    parser.add_argument("--https-site", action="store_true", help="write HTTPS OpenResty config; requires cert files already present")
    parser.add_argument("--panel-db", default=str(DEFAULT_PANEL_DB))
    parser.add_argument("--base-dir")
    parser.add_argument("--template", default="ql1", help="template instance for model defaults")
    parser.add_argument("--template-path")
    parser.add_argument("--name")
    parser.add_argument("--domain")
    parser.add_argument("--feishu-app-id")
    parser.add_argument("--feishu-app-secret")
    parser.add_argument("--auth-chat-id")
    parser.add_argument("--auth-target-mode", choices=["fixed", "first_sender", "first_dm"], default="first_sender")
    parser.add_argument("--owner-open-id", default="")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--app-version", default="2026.5.7")
    parser.add_argument("--description", default="")
    parser.add_argument("--http-port", type=int)
    parser.add_argument("--oauth-port", type=int)
    parser.add_argument("--http-start", type=int, default=18813)
    parser.add_argument("--oauth-start", type=int, default=31893)
    parser.add_argument("--gateway-token")
    parser.add_argument("--embedding-provider", default="")
    parser.add_argument("--embedding-api-key", default="")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--embedding-base-url", default="")
    parser.add_argument("--container-name")
    parser.add_argument("--cpus", default="0")
    parser.add_argument("--memory-limit", default="0")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--send-auth-card", action="store_true")
    parser.add_argument("--send-auth-card-only", action="store_true")
    args = parser.parse_args()

    if args.direct:
        args.panel = False

    if args.interactive:
        if not args.direct and not args.panel:
            args.panel = yes_no("是否使用 1Panel 管理这个实例", True)
        args.name = args.name or ask("实例编号/名称，例如 user03")
        args.domain = args.domain or ask("已解析好的域名，例如 user03.tyos.cc")
        args.feishu_app_id = args.feishu_app_id or ask("飞书 App ID")
        args.feishu_app_secret = args.feishu_app_secret or ask("飞书 App Secret", secret=True)
        args.auth_target_mode = ask("授权目标模式 fixed/first_sender/first_dm", args.auth_target_mode or "first_sender")
        if args.auth_target_mode not in {"fixed", "first_sender", "first_dm"}:
            die("auth target mode must be fixed, first_sender, or first_dm")
        if args.auth_target_mode == "fixed":
            args.auth_chat_id = args.auth_chat_id or ask("授权卡片接收 chat_id/open_chat_id")
            args.owner_open_id = args.owner_open_id or ask("用户 open_id，可空", "")
        else:
            args.auth_chat_id = args.auth_chat_id or ask("固定授权目标 chat_id/open_id，可空，空则等第一个用户", "")
            args.owner_open_id = args.owner_open_id or ask("预设用户 open_id，可空，空则绑定第一个用户", "")
        if yes_no("是否覆盖模板里的向量/Embedding 配置", False):
            args.embedding_provider = args.embedding_provider or ask("Embedding provider", "openai")
            args.embedding_model = args.embedding_model or ask("Embedding model", "text-embedding-v4")
            args.embedding_base_url = args.embedding_base_url or ask("Embedding Base URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            args.embedding_api_key = args.embedding_api_key or ask("Embedding API Key，可空则沿用模板/DASHSCOPE_API_KEY", "", secret=True)
        if args.panel:
            args.register_panel = yes_no("是否写入 1Panel 应用/智能体列表", True)
            args.register_website = yes_no("是否写入 1Panel 网站记录和反代配置", True)
        args.send_auth_card = yes_no("容器启动后是否尝试发送授权卡片", False)

    if args.send_auth_card_only:
        for key in ("name", "domain", "auth_chat_id"):
            if not getattr(args, key):
                die(f"--{key.replace('_', '-')} is required")
        return args

    required = ["name", "domain", "feishu_app_id", "feishu_app_secret"]
    if args.auth_target_mode == "fixed":
        required.append("auth_chat_id")
    missing = [key for key in required if not getattr(args, key)]
    if missing:
        die("missing required options: " + ", ".join("--" + key.replace("_", "-") for key in missing))
    return args


def main() -> None:
    args = parse_args()

    if args.send_auth_card_only:
        container_name = args.container_name or (f"1Panel-openclaw-{args.name}" if args.panel else f"openclaw-{args.name}")
        send_auth_card(container_name, args.domain, args.auth_chat_id)
        return

    if shutil.which("docker") is None:
        die("docker is not installed or not in PATH")

    instance_dir, container_name, http_port, oauth_port, env = create_instance_files(args)

    app_install_id = 0
    website_id = 0
    if args.register_panel:
        app_install_id = panel_register(args, instance_dir, container_name, http_port)

    if args.register_website:
        if not app_install_id and args.register_panel:
            die("could not resolve 1Panel app_install_id")
        write_openresty_site(args, http_port, oauth_port)
        website_id = panel_register_website(args, app_install_id, http_port)

    write_tenant_manifest(args, instance_dir, container_name, http_port, oauth_port, env, app_install_id, website_id)

    if not args.no_start:
        start_container(instance_dir)

    if args.send_auth_card and args.auth_chat_id:
        send_auth_card(container_name, args.domain, args.auth_chat_id)
    elif args.send_auth_card:
        print("authorization card was not sent immediately because no fixed target was provided; pairing watcher will wait for the first user.")

    print_next_steps(args, http_port, oauth_port)


if __name__ == "__main__":
    main()
