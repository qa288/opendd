#!/usr/bin/env python3
"""
Check one OpenClaw tenant without changing it.

The provisioning script should stay focused on creating instances. This checker
handles operational validation: container health, generated config, 1Panel site
records, and certificate records.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


DEFAULT_PANEL_DB = Path("/opt/1panel/db/agent.db")
DEFAULT_PANEL_BASE = Path("/opt/1panel/apps/openclaw")


def run(cmd: Iterable[str], timeout: int = 12) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"WARN read_json_failed path={path} error={error}")
        return {}


def status(label: str, state: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"{state:4} {label}{suffix}")


def resolve_manifest(args: argparse.Namespace) -> Dict[str, Any]:
    base_dir = Path(args.base_dir or DEFAULT_PANEL_BASE)
    manifest_path = Path(args.manifest) if args.manifest else base_dir / args.name / "tenant.json"
    manifest = read_json(manifest_path)
    if manifest:
        status("tenant manifest", "OK", str(manifest_path))
    else:
        status("tenant manifest", "WARN", f"not found: {manifest_path}")
    return manifest


def check_container(name: str) -> None:
    result = run(["docker", "inspect", "--format", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}", name])
    if result.returncode != 0:
        status("container", "FAIL", result.stdout.strip()[:200])
        return
    detail = result.stdout.strip()
    state = "OK" if "running" in detail and ("healthy" in detail or detail == "running") else "WARN"
    status("container", state, detail)

    logs = run(["docker", "logs", "--tail", "500", name], timeout=20).stdout
    interesting = []
    for line in logs.splitlines():
        if any(pattern in line for pattern in ["agent model:", "ws client ready", "EACCES", "failed to dispatch", "failed to start server"]):
            interesting.append(line)
    if interesting:
        for line in interesting[-8:]:
            redacted = line.replace("Authorization", "Authorization<redacted>")
            print(f"LOG  {redacted[:260]}")
    else:
        status("readiness logs", "INFO", "no model/ws readiness lines found in latest log tail")


def check_config(instance_dir: Path, domain: str) -> None:
    config_path = instance_dir / "data/conf/openclaw.json"
    config = read_json(config_path)
    if not config:
        status("openclaw config", "WARN", f"not rendered yet: {config_path}")
        return

    origins = config.get("gateway", {}).get("controlUi", {}).get("allowedOrigins", [])
    expected = f"https://{domain}"
    if expected in origins and not any(item.startswith("https://") and item != expected for item in origins):
        status("allowed origins", "OK", ", ".join(origins))
    elif expected in origins:
        status("allowed origins", "WARN", f"contains extra HTTPS origins: {origins}")
    else:
        status("allowed origins", "FAIL", f"missing {expected}: {origins}")

    primary = config.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")
    status("agent model", "OK" if primary else "WARN", primary or "missing")
    feishu = config.get("channels", {}).get("feishu", {})
    status("feishu channel config", "OK" if feishu.get("enabled") else "WARN", f"enabled={feishu.get('enabled')}")


def check_feishu_user_token(instance_dir: Path) -> None:
    candidates = [
        instance_dir / "data/conf/home/.local/share/lark-mcp-nodejs/storage.json",
        instance_dir / "data/conf/home/.local/share/lark-mcp-nodejs/default/storage.json",
    ]
    for path in candidates:
        if path.exists() and path.stat().st_size > 0:
            fallback_key = path.with_name("encryption-key")
            detail = str(path)
            if fallback_key.exists() and fallback_key.stat().st_size > 0:
                detail += " fallback_key=present"
            else:
                detail += " fallback_key=absent_or_keytar"
            status("feishu user token", "OK", detail)
            return
    for path in candidates:
        fallback_key = path.with_name("encryption-key")
        if fallback_key.exists() and fallback_key.stat().st_size > 0:
            status("feishu user token", "WARN", f"fallback key exists but token storage is missing: {path}")
            return
    status("feishu user token", "WARN", "missing or empty; user OAuth may still be pending")


def resolve_container_name(
    name: str,
    explicit_container_name: str,
    manifest: Dict[str, Any],
    panel_db: Path,
) -> str:
    if explicit_container_name:
        return explicit_container_name
    if manifest.get("containerName"):
        return str(manifest["containerName"])
    if panel_db.exists():
        conn = sqlite3.connect(str(panel_db))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "select container_name from app_installs where name = ? order by id desc",
                (name,),
            ).fetchone()
            if row and row["container_name"]:
                container_name = str(row["container_name"])
                status("container name", "OK", f"from 1Panel app install: {container_name}")
                return container_name
        finally:
            conn.close()
    return f"1Panel-openclaw-{name}"


def check_panel(name: str, domain: str, container_name: str, instance_dir: Path, panel_db: Path) -> None:
    if not panel_db.exists():
        status("1Panel db", "WARN", f"not found: {panel_db}")
        return

    conn = sqlite3.connect(str(panel_db))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        agent = cur.execute(
            "select id, name, status, app_install_id, website_id, config_path from agents where name = ?",
            (name,),
        ).fetchone()
        expected_config_path = str(instance_dir / "data/conf/openclaw.json")
        if agent:
            a = dict(agent)
            detail = (
                f"id={a['id']} status={a['status']} app_install_id={a['app_install_id']} "
                f"website_id={a['website_id']}"
            )
            state = "OK" if a.get("config_path") == expected_config_path else "WARN"
            if state == "WARN":
                detail += f" config_path={a.get('config_path')}"
            status("1Panel agent record", state, detail)
        else:
            status("1Panel agent record", "FAIL", "missing")

        app_install = cur.execute(
            "select id, name, status, container_name, service_name, http_port from app_installs where name = ? or container_name = ? order by id desc",
            (name, container_name),
        ).fetchone()
        if app_install:
            app = dict(app_install)
            detail = f"id={app['id']} status={app['status']} container={app['container_name']} http_port={app['http_port']}"
            if app["container_name"] != container_name:
                state = "WARN"
                detail += f" expected_container={container_name}"
            else:
                state = "OK" if app["status"] == "Running" else "WARN"
            status("1Panel app install", state, detail)
        else:
            status("1Panel app install", "FAIL", "missing")

        website = cur.execute(
            "select id, protocol, primary_domain, status, http_config, proxy, website_ssl_id from websites where primary_domain = ?",
            (domain,),
        ).fetchone()
        if website:
            w = dict(website)
            detail = f"id={w['id']} protocol={w['protocol']} status={w['status']} ssl_id={w['website_ssl_id']} proxy={w['proxy']}"
            state = "OK" if w["status"] == "Running" else "WARN"
            status("1Panel website", state, detail)
        else:
            status("1Panel website", "FAIL", "missing")

        ssl_rows = cur.execute(
            "select id, created_at, provider, status, expire_date, message from website_ssls where primary_domain = ? or domains like ? order by id desc",
            (domain, f"%{domain}%"),
        ).fetchall()
        if not ssl_rows:
            status("1Panel certificate record", "WARN", "missing")
            return
        latest = dict(ssl_rows[0])
        raw_message = (latest.get("message") or "").replace("\n", " ")
        message = raw_message[:220]
        detail = f"id={latest['id']} provider={latest['provider']} status={latest['status']} expire={latest['expire_date']}"
        if latest["status"] == "ready" and raw_message:
            detail += " message=<stale non-blocking>"
        elif message:
            detail += f" message={message}"
        state = "OK" if latest["status"] == "ready" else "WARN"
        status("1Panel certificate record", state, detail)
    finally:
        conn.close()


def check_public_http(domain: str) -> None:
    for scheme in ["http", "https"]:
        result = run(["curl", "-skI", "--max-time", "8", f"{scheme}://{domain}/healthz"], timeout=10)
        first = result.stdout.splitlines()[0] if result.stdout.splitlines() else result.stdout.strip()
        if result.returncode == 0 and (" 200 " in first or " 301 " in first or " 302 " in first or " 401 " in first):
            state = "OK"
        else:
            state = "WARN"
        status(f"public {scheme}", state, first[:180] or f"curl exit {result.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check an OpenClaw tenant")
    parser.add_argument("--name", required=True)
    parser.add_argument("--domain", default="")
    parser.add_argument("--container-name", default="")
    parser.add_argument("--base-dir", default=str(DEFAULT_PANEL_BASE))
    parser.add_argument("--panel-db", default=str(DEFAULT_PANEL_DB))
    parser.add_argument("--manifest", default="")
    parser.add_argument("--skip-public-http", action="store_true")
    args = parser.parse_args()

    manifest = resolve_manifest(args)
    domain = args.domain or manifest.get("domain") or ""
    if not domain:
        status("domain", "FAIL", "pass --domain or provide tenant.json")
        return 1

    base_dir = Path(args.base_dir)
    instance_dir = Path(manifest.get("paths", {}).get("instance") or base_dir / args.name)
    container_name = resolve_container_name(args.name, args.container_name, manifest, Path(args.panel_db))

    status("instance", "OK", f"{args.name} {domain}")
    check_container(container_name)
    check_config(instance_dir, domain)
    check_feishu_user_token(instance_dir)
    check_panel(args.name, domain, container_name, instance_dir, Path(args.panel_db))
    if not args.skip_public_http:
        check_public_http(domain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
