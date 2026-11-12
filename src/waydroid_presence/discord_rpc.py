from __future__ import annotations

import inspect
import logging
import time
from typing import Any

try:
    from pypresence import Presence
    from pypresence.exceptions import DiscordNotFound, PyPresenceException
except ImportError:  # pragma: no cover - reported when a connection is attempted
    Presence = None
    DiscordNotFound = PyPresenceException = Exception

log = logging.getLogger("waydroid-presence.discord")


class DiscordRPC:
    """Small stateful wrapper around Discord's local IPC Rich Presence API."""

    def __init__(self, client_id: str, reconnect_interval: int = 10):
        self.client_id = str(client_id)
        self.reconnect_interval = max(1, int(reconnect_interval))
        self.last_connect_attempt = 0.0
        self.rpc = None
        self._last_activity: dict[str, Any] | None = None
        self._name_supported: bool | None = None
        self._warned_about_name = False

    def reconfigure(self, client_id: str, reconnect_interval: int) -> None:
        """Apply updated Discord credentials without leaving the old IPC session alive."""
        client_id = str(client_id).strip()
        reconnect_interval = max(1, int(reconnect_interval))
        if client_id != self.client_id:
            self.close()
            self.client_id = client_id
            self.last_connect_attempt = 0.0
        self.reconnect_interval = reconnect_interval

    @property
    def connected(self) -> bool:
        return self.rpc is not None

    def _supports_activity_name(self) -> bool:
        """Older pypresence releases do not expose the custom activity name."""
        if self._name_supported is None:
            if Presence is None:
                self._name_supported = False
            else:
                try:
                    self._name_supported = "name" in inspect.signature(Presence.update).parameters
                except (TypeError, ValueError):
                    self._name_supported = False
        return self._name_supported

    def connect(self, *, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now - self.last_connect_attempt < self.reconnect_interval:
            return False
        self.last_connect_attempt = now
        if Presence is None:
            log.error("pypresence is not installed in the active Python environment.")
            return False
        try:
            client = Presence(self.client_id)
            client.connect()
            self.rpc = client
            self._last_activity = None
            log.info("Connected to Discord IPC.")
            return True
        except (DiscordNotFound, PyPresenceException, OSError) as exc:
            self.rpc = None
            self._last_activity = None
            log.debug("Discord IPC is unavailable: %s", exc)
            return False

    def update(self, details: str, state: str, icon: str | None = None,
               started_at: float | None = None, *, force: bool = False,
               application_name: str | None = None, **extra: Any) -> bool:
        payload: dict[str, Any] = {"details": details, "state": state}
        if icon:
            payload.update(large_image=icon, large_text=extra.pop("large_text", details))
        if started_at is not None:
            payload["start"] = int(started_at)
        if application_name:
            if self._supports_activity_name():
                payload["name"] = str(application_name)
            elif not self._warned_about_name:
                log.warning(
                    "Custom Discord application names require pypresence 4.6 or newer; "
                    "update pypresence or use apps.custom.<package>.client_id. The option will be ignored."
                )
                self._warned_about_name = True
        payload.update({k: v for k, v in extra.items() if v is not None})
        if not self.rpc and not self.connect():
            return False
        if payload == self._last_activity and not force:
            return True
        try:
            self.rpc.update(**payload)
            self._last_activity = payload.copy()
            return True
        except (PyPresenceException, OSError, AttributeError, RuntimeError) as exc:
            log.warning("Discord RPC update failed; connection will be retried: %s", exc)
            self.close()
            return False

    def clear(self) -> bool:
        self._last_activity = None
        if not self.rpc:
            return False
        try:
            self.rpc.clear()
            return True
        except (PyPresenceException, OSError, AttributeError, RuntimeError) as exc:
            log.warning("Discord RPC clear failed: %s", exc)
            self.close()
            return False

    def close(self) -> None:
        client, self.rpc = self.rpc, None
        self._last_activity = None
        if client:
            try:
                client.close()
            except Exception as exc:  # closing an already-lost IPC socket is harmless
                log.debug("Discord IPC close: %s", exc)
