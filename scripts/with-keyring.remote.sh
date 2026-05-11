#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${HOME:-}" || "${HOME}" == "/home/node" ]]; then
  export HOME="/home/node/.openclaw/home"
fi
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/home/node/.openclaw/runtime}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-/home/node/.openclaw/home/.local/share}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-/home/node/.openclaw/state}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-/home/node/.openclaw/config}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/home/node/.openclaw/cache}"

mkdir -p "$XDG_RUNTIME_DIR" "$XDG_RUNTIME_DIR/keyring" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$HOME/.local/share/keyrings"
chmod 700 "$XDG_RUNTIME_DIR" "$XDG_RUNTIME_DIR/keyring" "$XDG_DATA_HOME" "$HOME/.local/share/keyrings"

if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]] && command -v dbus-daemon >/dev/null 2>&1; then
  rm -f "$XDG_RUNTIME_DIR/bus"
  dbus-daemon --session --address="unix:path=${XDG_RUNTIME_DIR}/bus" --fork
  export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
fi

if command -v gnome-keyring-daemon >/dev/null 2>&1; then
  pkill -u "$(id -u)" -f gnome-keyring-daemon 2>/dev/null || true
  sleep 0.2
  gnome-keyring-daemon --unlock --components=secrets --control-directory="$XDG_RUNTIME_DIR/keyring" < <(printf '') >/tmp/openclaw-gnome-keyring.out 2>/tmp/openclaw-gnome-keyring.err || true
  eval "$(gnome-keyring-daemon --start --components=secrets --control-directory="$XDG_RUNTIME_DIR/keyring" 2>/tmp/openclaw-gnome-keyring-start.err || true)"
  export GNOME_KEYRING_CONTROL="$XDG_RUNTIME_DIR/keyring"
  for _ in $(seq 1 50); do
    if gdbus introspect --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets >/dev/null 2>&1; then
      break
    fi
    sleep 0.1
  done
  gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets --method org.freedesktop.Secret.Service.CreateCollection "{'org.freedesktop.Secret.Collection.Label': <'login'>}" "login" >/dev/null 2>&1 || true
  gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets --method org.freedesktop.Secret.Service.SetAlias "login" "/org/freedesktop/secrets/collection/login" >/dev/null 2>&1 || true
fi

exec "$@"
