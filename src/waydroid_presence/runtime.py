from __future__ import annotations

import logging
import time

from .apps import app_client_id, app_metadata
from .detector import ADBDetector, ADBError
from .discord_rpc import DiscordRPC

log = logging.getLogger("waydroid-presence.runtime")


class PresenceRuntime:
    def __init__(self, config: dict, detector: ADBDetector, rpc: DiscordRPC,
                 database=None, metadata=None):
        self.config = config
        self.detector = detector
        self.rpc = rpc
        self.database = database
        self.metadata = metadata
        if self.metadata is not None:
            self.metadata.configure(config)
        self.ignored = set(config["apps"]["ignored_packages"])
        self.last_package: object | str | None = object()
        self.session_start: float | None = None
        self.last_adb_connect_attempt = 0.0
        self.adb_unavailable_since: float | None = None
        self.presence_suppressed = False
        self.last_presence_refresh = 0.0

    def reconfigure(self, config: dict) -> None:
        """Apply a validated configuration while preserving the active Android session."""
        self.config = config
        self.ignored = set(config["apps"]["ignored_packages"])
        self.detector.reconfigure(
            config["adb"]["executable"], str(config["adb"]["device"]), config["adb"]["timeout"]
        )
        active_package = self.last_package if isinstance(self.last_package, str) else None
        effective_client_id = (
            app_client_id(active_package, config, self.database)
            if active_package
            else str(config["discord"]["client_id"]).strip()
        )
        if effective_client_id:
            self.rpc.reconfigure(
                effective_client_id, config["discord"]["reconnect_interval"]
            )
        if self.metadata is not None:
            self.metadata.configure(config)
        # Re-publish on the next tick so changed details, icons or names apply live.
        self.last_presence_refresh = 0.0
        log.info("Runtime configuration applied.")

    def _select_client(self, client_id: str | None) -> None:
        """Switch to the Discord application configured for the focused Android app."""
        client_id = str(client_id or "").strip()
        if not client_id or client_id == getattr(self.rpc, "client_id", None):
            return
        reconfigure = getattr(self.rpc, "reconfigure", None)
        if reconfigure is None:
            return
        reconfigure(client_id, int(self.config["discord"].get("reconnect_interval", 10)))

    def _publish_package(self, package: str, *, force: bool = False) -> None:
        activity = app_metadata(package, self.config, self.database)
        self._select_client(app_client_id(package, self.config, self.database))
        started_at = self.session_start if self.config["presence"].get("show_elapsed_time", True) else None
        extra = {
            k: v for k, v in activity.items()
            if k not in {"details", "state", "large_image", "large_text", "application_name"}
        }
        self.rpc.update(
            activity["details"], activity["state"], activity["large_image"], started_at,
            large_text=activity.get("large_text"), force=force,
            application_name=activity.get("application_name"), **extra,
        )
        self.last_presence_refresh = time.monotonic()
        self.presence_suppressed = False

    def tick(self) -> str:
        adb = self.config["adb"]
        endpoint = str(adb.get("endpoint", "")).strip()
        reconnect_interval = int(adb.get("reconnect_interval", 5))
        if adb.get("reconnect", True) and endpoint and time.monotonic() - self.last_adb_connect_attempt >= reconnect_interval:
            self.last_adb_connect_attempt = time.monotonic()
            try:
                result = self.detector.connect_endpoint(endpoint)
                log.debug("ADB connect: %s", result)
            except ADBError as exc:
                log.debug("ADB auto-connect: %s", exc)

        now = time.monotonic()
        try:
            package = self.detector.foreground_package(self.ignored)
        except ADBError as exc:
            log.warning("ADB unavailable: %s", exc)
            if self.adb_unavailable_since is None:
                self.adb_unavailable_since = now
            behavior = self.config["presence"]["unavailable_behavior"]
            clear_after = int(self.config["presence"].get("unavailable_clear_after", 30))
            unavailable_for = now - self.adb_unavailable_since
            should_clear = behavior == "clear" or (clear_after > 0 and unavailable_for >= clear_after)
            if should_clear and not self.presence_suppressed:
                self.rpc.clear()
                self.presence_suppressed = True
                log.info("ADB has been unavailable for %.0fs; stale presence cleared.", unavailable_for)
            return "unavailable"

        recovered = self.adb_unavailable_since is not None
        self.adb_unavailable_since = None
        if recovered:
            log.info("ADB connection restored.")

        if self.metadata is not None:
            # Unknown packages are resolved from the Play Store in the
            # background; a stored entry triggers an immediate republish.
            self.metadata.request(package)
            if self.metadata.consume_update():
                self.last_presence_refresh = 0.0

        if package != self.last_package:
            self.last_package = package
            self.session_start = time.time() if package else None
            if package:
                activity = app_metadata(package, self.config, self.database)
                log.info("Foreground app: %s (%s)", activity["details"], package)
                self._publish_package(package)
            elif self.config["presence"]["idle_behavior"] == "clear":
                self._select_client(self.config["discord"].get("client_id", ""))
                self.rpc.clear()
                self.presence_suppressed = False
                log.info("Launcher/idle detected; presence cleared.")
            else:
                self._select_client(self.config["discord"].get("client_id", ""))
                self.rpc.update(
                    self.config["presence"]["idle_details"], "Waydroid",
                    self.config["presence"]["default_icon_key"], None,
                    large_text=self.config["presence"].get("default_icon_text", "Waydroid"),
                    application_name=self.config["discord"].get("application_name") or None,
                )
                self.presence_suppressed = False
        elif package and self.presence_suppressed:
            # ADB recovered after the stale activity was cleared; keep the original session start.
            self._publish_package(package)
        elif package and not self.rpc.connected:
            # Re-publish after an IPC disconnect even if Android's foreground package did not change.
            self._publish_package(package, force=True)
        elif package:
            refresh_interval = int(self.config["discord"].get("presence_refresh_interval", 15))
            if now - self.last_presence_refresh >= refresh_interval:
                # A periodic IPC write detects a Discord restart that leaves the old socket stale.
                self._publish_package(package, force=True)
        return package or "idle"
