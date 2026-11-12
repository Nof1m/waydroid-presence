#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/waydroid-presence"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waydroid-presence"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PYTHON="${PYTHON:-python3}"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Do not run this installer with sudo. It installs into your user account." >&2
  exit 1
fi

command -v "$PYTHON" >/dev/null || { echo "python3 is required." >&2; exit 1; }
command -v "${ADB_BIN:-/usr/bin/adb}" >/dev/null || echo "Warning: adb was not found; install android-tools first."

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$UNIT_DIR"
# Stop an existing user service before replacing its Python modules.
systemctl --user stop waydroid-presence.service 2>/dev/null || true
# Remove the source tree and any stale build artifacts. A leftover build/
# directory makes setuptools skip files whose copied mtime is older than the
# cached ones, which silently installs a mix of old and new modules.
rm -rf "$INSTALL_DIR/src" "$INSTALL_DIR/build" "$INSTALL_DIR"/*.egg-info
cp -R "$ROOT/src" "$INSTALL_DIR/src"
cp "$ROOT/pyproject.toml" "$INSTALL_DIR/pyproject.toml"

if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
  "$PYTHON" -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/python" -m pip install \
  --upgrade --force-reinstall --no-cache-dir "$INSTALL_DIR"

if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
  cp "$ROOT/config/config.yaml" "$CONFIG_DIR/config.yaml"
  echo "Created configuration: $CONFIG_DIR/config.yaml"
else
  echo "Keeping existing configuration: $CONFIG_DIR/config.yaml"
fi

sed "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
  "$ROOT/systemd/waydroid-presence.service.in" \
  > "$UNIT_DIR/waydroid-presence.service"

systemctl --user daemon-reload
systemctl --user enable --now waydroid-presence.service

echo
echo "Waydroid Presence installed: $("$INSTALL_DIR/.venv/bin/waydroid-presence" --version)"
if ! "$INSTALL_DIR/.venv/bin/waydroid-presence" --db-path >/dev/null 2>&1; then
  echo "Warning: this build looks incomplete. Re-run the installer." >&2
fi
echo "Edit: $CONFIG_DIR/config.yaml"
echo "Then restart: systemctl --user restart waydroid-presence.service"
echo "Logs: journalctl --user -u waydroid-presence.service -f"
