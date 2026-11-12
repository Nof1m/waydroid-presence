#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/waydroid-presence"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waydroid-presence"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Do not run this script with sudo." >&2
  exit 1
fi

systemctl --user disable --now waydroid-presence.service 2>/dev/null || true
rm -f "$UNIT_DIR/waydroid-presence.service"
systemctl --user daemon-reload
rm -rf "$INSTALL_DIR"

if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "$CONFIG_DIR" "${XDG_STATE_HOME:-$HOME/.local/state}/waydroid-presence"
  echo "Program, configuration and logs removed."
else
  echo "Program removed. Configuration preserved at: $CONFIG_DIR"
  echo "Run with --purge to also remove configuration and logs."
fi
