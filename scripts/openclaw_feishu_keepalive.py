#!/usr/bin/env python3
"""
Keep Feishu user-identity MCP sessions warm for OpenClaw instances.

The script performs a lightweight `im_v1_chat_list` call with `useUAT=true`.
It intentionally does not print tokens, app secrets, or returned chat content.
If an auth-like failure is detected and an auth target is configured, it can
send a Feishu OAuth authorization card for that instance.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Optional


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "openclaw-feishu-keepalive", "version": "1"},
    },
}

INITIALIZED = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {},
}

CHAT_LIST_CALL = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "name": "im_v1_chat_list",
        "arguments": {"params": {"page_size": 1}, "useUAT": True},
    },
}


@dataclass(frozen=True)
class Instance:
    name: str
    container: str
    mcp_script: str
    public_url: str
    auth_target: str = ""
    auth_card_script: str = "/opt/opendd/bin/send-feishu-auth-card.js"


DEFAULT_INSTANCES = [
    Instance(
        name="ql1",
        container="1Panel-openclaw-ql1",
        mcp_script="/opt/opendd/bin/start-feishu-mcp.js",
        public_url="https://ql1.tyos.cc",
        auth_target="oc_725d39d8a18ac5467678cbcb26337a39",
    ),
    Instance(
        name="wq1",
        container="1Panel-openclaw-edhg",
        mcp_script="/opt/opendd/bin/start-feishu-mcp.js",
        public_url="https://wq1.tyos.cc",
        auth_target="oc_6318e241ae22f5a4f274100c73163f89",
    ),
    Instance(
        name="default",
        container="1Panel-openclaw-Nxuc",
        mcp_script="/home/node/.openclaw/mcp/lark-openapi/bin/start-feishu-mcp.js",
        public_url="https://ope.tyos.cc",
        auth_card_script="/home/node/.openclaw/mcp/lark-openapi/bin/send-feishu-auth-card.js",
    ),
]


AUTH_FAILURE_MARKERS = [
    "20038",
    "20043",
    "invalid_grant",
    "refresh token",
    "Token refresh failed",
    "NO_ACTIVE_SESSION",
    "no user authority",
    "unauthorized",
]

DEFAULT_STATE_FILE = Path("/var/lib/openclaw/feishu-keepalive-state.json")


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_epoch() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def parse_call_response(output: str) -> tuple[bool, str]:
    target: Optional[dict[str, Any]] = None
    for line in output.splitlines():
        line = line.strip()
        if not line or '"id":3' not in line:
            continue
        try:
            target = json.loads(line)
        except json.JSONDecodeError:
            continue

    lowered = output.lower()
    if target is None:
        marker = next((m for m in AUTH_FAILURE_MARKERS if m.lower() in lowered), "")
        if marker:
            return False, f"auth_failure:{marker}"
        return False, "no_tool_response"

    if "error" in target:
        message = json.dumps(target["error"], ensure_ascii=False)
        marker = next((m for m in AUTH_FAILURE_MARKERS if m.lower() in message.lower()), "")
        return False, f"auth_failure:{marker}" if marker else "mcp_error"

    result = target.get("result") or {}
    if result.get("isError"):
        message = json.dumps(result, ensure_ascii=False)
        marker = next((m for m in AUTH_FAILURE_MARKERS if m.lower() in message.lower()), "")
        return False, f"auth_failure:{marker}" if marker else "tool_error"

    return True, "ok"


def keepalive(instance: Instance, timeout: int) -> tuple[bool, str]:
    payload = "\n".join(
        [
            json.dumps(INIT, separators=(",", ":")),
            json.dumps(INITIALIZED, separators=(",", ":")),
            json.dumps(CHAT_LIST_CALL, separators=(",", ":")),
            "",
        ]
    )
    cmd = [
        "docker",
        "exec",
        "-i",
        instance.container,
        "bash",
        "-lc",
        f"timeout {timeout}s node {instance.mcp_script}",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=payload,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout + 10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout"

    ok, reason = parse_call_response(result.stdout)
    if ok:
        return True, "ok"
    if result.returncode not in (0, 124):
        return False, f"{reason}:exit_{result.returncode}"
    return False, reason


def send_auth_card(instance: Instance) -> bool:
    if not instance.auth_target:
        return False
    cmd = [
        "docker",
        "exec",
        "-d",
        instance.container,
        "sh",
        "-lc",
        (
            "mkdir -p /home/node/.openclaw/logs && "
            f"node {instance.auth_card_script} "
            f"--target {instance.auth_target} "
            f"--public-url {instance.public_url} "
            "> /home/node/.openclaw/logs/feishu-auth-card-keepalive.log 2>&1"
        ),
    ]
    result = run(cmd, timeout=20)
    return result.returncode == 0


def should_send_auth_card(
    args: argparse.Namespace,
    instance_state: dict[str, Any],
    reason: str,
) -> tuple[bool, str]:
    if not args.send_auth_card_on_fail:
        return False, "disabled"
    if not reason.startswith("auth_failure"):
        return False, "not_auth_failure"
    failures = int(instance_state.get("consecutive_auth_failures") or 0)
    if failures < args.failures_before_auth_card:
        return False, f"failure_threshold:{failures}/{args.failures_before_auth_card}"
    last_sent = int(instance_state.get("last_auth_card_sent_at") or 0)
    elapsed = now_epoch() - last_sent if last_sent else 10**9
    cooldown = args.auth_card_cooldown_hours * 3600
    if elapsed < cooldown:
        return False, f"cooldown:{elapsed}s/{cooldown}s"
    return True, "eligible"


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw Feishu user OAuth keepalive")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--send-auth-card-on-fail", action="store_true")
    parser.add_argument("--failures-before-auth-card", type=int, default=3)
    parser.add_argument("--auth-card-cooldown-hours", type=int, default=6)
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    args = parser.parse_args()

    state_file = Path(args.state_file)
    state = load_state(state_file)
    exit_code = 0
    for instance in DEFAULT_INSTANCES:
        instance_state = state.setdefault(instance.name, {})
        ok, reason = keepalive(instance, args.timeout)
        if ok:
            instance_state["last_ok_at"] = now_epoch()
            instance_state["consecutive_failures"] = 0
            instance_state["consecutive_auth_failures"] = 0
            instance_state["last_reason"] = "ok"
            print(f"{timestamp()} {instance.name} OK")
            continue

        exit_code = 1
        instance_state["last_fail_at"] = now_epoch()
        instance_state["last_reason"] = reason
        instance_state["consecutive_failures"] = int(instance_state.get("consecutive_failures") or 0) + 1
        if reason.startswith("auth_failure"):
            instance_state["consecutive_auth_failures"] = int(instance_state.get("consecutive_auth_failures") or 0) + 1
        else:
            instance_state["consecutive_auth_failures"] = 0

        sent = False
        eligible, send_reason = should_send_auth_card(args, instance_state, reason)
        if eligible:
            sent = send_auth_card(instance)
            if sent:
                instance_state["last_auth_card_sent_at"] = now_epoch()
        suffix = " auth_card_sent=true" if sent else ""
        suffix = suffix or f" auth_card_sent=false auth_card_reason={send_reason}"
        print(
            f"{timestamp()} {instance.name} FAIL reason={reason} "
            f"failures={instance_state['consecutive_failures']} "
            f"auth_failures={instance_state['consecutive_auth_failures']}{suffix}"
        )

    save_state(state_file, state)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
