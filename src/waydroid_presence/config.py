from __future__ import annotations

import os
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


DEFAULTS: dict[str, Any] = {
    "discord": {
        "client_id": "", "application_name": "",
        "reconnect_interval": 10, "presence_refresh_interval": 15,
    },
    "adb": {
        "executable": "/usr/bin/adb", "device": "auto", "timeout": 15,
        "reconnect": True, "reconnect_interval": 5, "endpoint": "",
    },
    "presence": {
        "poll_interval": 5, "idle_behavior": "clear",
        "unavailable_behavior": "keep", "unavailable_clear_after": 30, "default_icon_key": "waydroid",
        "default_icon_text": "Waydroid", "show_package_name": True,
        "show_elapsed_time": True, "idle_details": "Idle",
    },
    "apps": {"ignored_packages": ["com.android.launcher3"], "custom": {}},
    "database": {"auto_lookup": True, "timeout": 8, "cooldown": 600},
    "runtime": {"config_reload_interval": 3},
    "logging": {"level": "INFO", "file": "~/.local/state/waydroid-presence/waydroid-presence.log"},
}


def _merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _positive_int(section: dict, key: str, label: str) -> int:
    try:
        value = int(section[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer of at least 1.") from exc
    if value < 1:
        raise ValueError(f"{label} must be at least 1.")
    section[key] = value
    return value


def _optional_text(section: dict, key: str, label: str, *, max_length: int = 128) -> str:
    value = section.get(key, "")
    if value is None:
        value = ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{label} must be text.")
    value = str(value).strip()
    if len(value) > max_length:
        raise ValueError(f"{label} must be at most {max_length} characters.")
    section[key] = value
    return value


def load_config(path: str | Path, *, require_client_id: bool = True) -> dict:
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with config_path.open(encoding="utf-8") as stream:
        loaded = yaml.safe_load(stream) or {}
    if not isinstance(loaded, dict):
        raise ValueError("The YAML root must be a mapping/object.")
    config = _merge(DEFAULTS, loaded)

    for section in ("discord", "adb", "presence", "apps", "database", "runtime", "logging"):
        if not isinstance(config.get(section), dict):
            raise ValueError(f"Configuration section '{section}' must be a mapping.")

    client_id = str(config["discord"].get("client_id", "")).strip()
    if require_client_id and not client_id:
        raise ValueError("discord.client_id is required. Set it in config.yaml.")
    if client_id and not client_id.isdigit():
        raise ValueError(
            "discord.client_id must be the numeric application ID from the Discord "
            "Developer Portal (for example 123456789012345678)."
        )
    config["discord"]["client_id"] = client_id
    _optional_text(config["discord"], "application_name", "discord.application_name")
    _positive_int(config["discord"], "reconnect_interval", "discord.reconnect_interval")
    _positive_int(config["discord"], "presence_refresh_interval", "discord.presence_refresh_interval")
    _positive_int(config["adb"], "timeout", "adb.timeout")
    _positive_int(config["adb"], "reconnect_interval", "adb.reconnect_interval")
    _positive_int(config["presence"], "poll_interval", "presence.poll_interval")
    _positive_int(config["runtime"], "config_reload_interval", "runtime.config_reload_interval")
    _positive_int(config["database"], "timeout", "database.timeout")
    _positive_int(config["database"], "cooldown", "database.cooldown")
    if not isinstance(config["database"].get("auto_lookup"), bool):
        raise ValueError("database.auto_lookup must be true or false.")
    if "unavailable_clear_after" not in config["presence"] or int(config["presence"]["unavailable_clear_after"]) < 0:
        raise ValueError("presence.unavailable_clear_after must be 0 or greater.")
    config["presence"]["unavailable_clear_after"] = int(config["presence"]["unavailable_clear_after"])

    if config["presence"]["idle_behavior"] not in {"clear", "show_idle"}:
        raise ValueError("presence.idle_behavior must be 'clear' or 'show_idle'.")
    if config["presence"]["unavailable_behavior"] not in {"keep", "clear"}:
        raise ValueError("presence.unavailable_behavior must be 'keep' or 'clear'.")
    if not isinstance(config["apps"].get("ignored_packages"), list):
        raise ValueError("apps.ignored_packages must be a list of package names.")
    if not isinstance(config["apps"].get("custom"), dict):
        raise ValueError("apps.custom must be a mapping of package names to settings.")
    for package, settings in config["apps"]["custom"].items():
        if not isinstance(settings, dict):
            raise ValueError(f"apps.custom.{package} must be a mapping.")
        _optional_text(settings, "application_name", f"apps.custom.{package}.application_name")
        client_id = settings.get("client_id")
        if client_id is not None:
            if isinstance(client_id, bool) or not isinstance(client_id, (str, int)):
                raise ValueError(f"apps.custom.{package}.client_id must be a Discord application ID.")
            client_id = str(client_id).strip()
            if client_id and not client_id.isdigit():
                raise ValueError(f"apps.custom.{package}.client_id must contain only digits.")
            settings["client_id"] = client_id
        buttons = settings.get("buttons", [])
        if not isinstance(buttons, list) or len(buttons) > 2:
            raise ValueError(f"apps.custom.{package}.buttons must be a list with at most 2 items.")
        for button in buttons:
            if not isinstance(button, dict) or not button.get("label") or not button.get("url"):
                raise ValueError(f"Each button in apps.custom.{package}.buttons needs label and url.")

    config["adb"]["executable"] = str(Path(os.path.expandvars(str(config["adb"]["executable"]))).expanduser())
    config["logging"]["file"] = str(Path(os.path.expandvars(str(config["logging"]["file"]))).expanduser())
    return config


class ConfigReloader:
    """Reload YAML when its file changes, retaining the last valid config on errors."""

    def __init__(self, path: str | Path, initial_config: dict):
        self.path = Path(path).expanduser()
        self.config = initial_config
        self._signature = self._file_signature()
        self.log = logging.getLogger("waydroid-presence.config")

    def _file_signature(self):
        try:
            stat = self.path.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None

    def reload_if_changed(self) -> dict | None:
        signature = self._file_signature()
        if signature is None or signature == self._signature:
            return None
        try:
            updated = load_config(self.path)
        except (OSError, ValueError) as exc:
            self.log.error("Configuration reload rejected; keeping previous settings: %s", exc)
            self._signature = signature
            return None
        self._signature = signature
        self.config = updated
        self.log.info("Configuration reloaded successfully.")
        return updated
