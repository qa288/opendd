#!/usr/bin/env python3
"""
Backfill safe metadata for older 1Panel-managed OpenClaw instances.

This writes a secret-free tenant.json and aligns the 1Panel agent status/website
link so operational checkers can treat old instances like newly provisioned
ones. It never copies OAuth tokens, model keys, or app secrets into tenant.json.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict


DEFAULT_PANEL_DB = Path("/opt/1panel/db/agent.db")
DEFAULT_PANEL_BASE = Path("/opt/1panel/apps/openclaw")


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


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_instance(value: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in value.split(":", 2)]
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError("instance must be name:domain:container_name")
    return parts[0], parts[1], parts[2]


def backfill_instance(base_dir: Path, panel_db: Path, name: str, domain: str, container_name: str) -> None:
    instance_dir = base_dir / name
    if not instance_dir.exists():
        raise SystemExit(f"instance directory not found: {instance_dir}")

    env = load_env(instance_dir / ".env")
    conn = sqlite3.connect(str(panel_db))
    conn.row_factory = sqlite3.Row
    try:
        app = conn.execute(
            "select id, http_port, container_name from app_installs "
            "where name = ? or container_name = ? order by id desc",
            (name, container_name),
        ).fetchone()
        website = conn.execute(
            "select id from websites where primary_domain = ?",
            (domain,),
        ).fetchone()

        app_install_id = int(app["id"]) if app else 0
        website_id = int(website["id"]) if website else 0
        http_port = int(app["http_port"]) if app and app["http_port"] else int(env.get("PANEL_APP_PORT_HTTP") or 0)
        oauth_port = int(env.get("PANEL_APP_PORT_OAUTH") or 31888)

        manifest = {
            "schemaVersion": 1,
            "name": name,
            "domain": domain,
            "publicUrl": f"https://{domain}",
            "createdAt": utc_now(),
            "mode": "panel",
            "image": env.get("OPENDD_IMAGE") or "ghcr.io/qa288/opendd:2026.5.7",
            "containerName": container_name,
            "dockerNetwork": env.get("OPENDD_DOCKER_NETWORK", ""),
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
                "containerHttp": 18789,
                "containerOauth": 31888,
            },
            "panel": {
                "appInstallId": app_install_id,
                "websiteId": website_id,
            },
            "feishu": {
                "appId": env.get("FEISHU_APP_ID", ""),
                "domain": env.get("FEISHU_DOMAIN", "feishu"),
                "authTargetMode": env.get("FEISHU_AUTH_TARGET_MODE", ""),
                "authCardMode": env.get("FEISHU_AUTH_CARD_MODE", "guided"),
                "ownerOpenIdConfigured": bool(env.get("FEISHU_OWNER_OPEN_ID")),
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
                "source": "backfilled",
                "renderPolicy": env.get("OPENDD_RENDER_CONFIG", "missing"),
            },
        }
        (instance_dir / "tenant.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if website_id:
            conn.execute(
                "update agents set status = ?, website_id = ? where name = ?",
                ("Running", website_id, name),
            )
        else:
            conn.execute("update agents set status = ? where name = ?", ("Running", name))
        conn.commit()
        print(f"OK {name} tenant.json={instance_dir / 'tenant.json'} website_id={website_id}")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill OpenClaw 1Panel metadata")
    parser.add_argument("--base-dir", default=str(DEFAULT_PANEL_BASE))
    parser.add_argument("--panel-db", default=str(DEFAULT_PANEL_DB))
    parser.add_argument(
        "--instance",
        action="append",
        type=parse_instance,
        required=True,
        help="name:domain:container_name, repeatable",
    )
    args = parser.parse_args()

    for name, domain, container_name in args.instance:
        backfill_instance(Path(args.base_dir), Path(args.panel_db), name, domain, container_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
