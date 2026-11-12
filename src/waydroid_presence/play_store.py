"""Optional Google Play metadata discovery for unknown Android packages.

The Play Store page for an app exposes its name and icon as Open Graph tags,
which is enough to build a database entry without an API key. Lookups always run
in a background thread so a slow network never delays a Discord IPC update.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import Callable

from .database import AppDatabase

log = logging.getLogger("waydroid-presence.play")

STORE_URL = "https://play.google.com/store/apps/details"
ICON_HOST = "play-lh.googleusercontent.com"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_OG_IMAGE = re.compile(r'property="og:image"\s+content="([^"]+)"')
_OG_TITLE = re.compile(r'property="og:title"\s+content="([^"]+)"')
_TITLE_SUFFIX = re.compile(r"\s*-\s*Apps on Google Play\s*$")


def icon_url(raw: str) -> str:
    """Normalize a Play Store icon URL to a 512px variant, or return ''."""
    base = str(raw or "").split("=", 1)[0].strip()
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "https" or parsed.netloc != ICON_HOST:
        return ""
    return f"{base}=w512"


def parse_page(package: str, html: str, *, now: datetime | None = None) -> dict | None:
    """Extract a database entry from a Play Store app page."""
    title = _OG_TITLE.search(html)
    image = _OG_IMAGE.search(html)
    if not title or not image:
        return None

    name = _TITLE_SUFFIX.sub("", unescape(title.group(1))).strip()
    icon = icon_url(unescape(image.group(1)))
    if not name or not icon:
        return None

    moment = now or datetime.now(timezone.utc)
    return {
        "name": name,
        "icon": icon,
        "source": "play",
        "fetched_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def fetch_package(package: str, timeout: float = 8.0) -> dict | None:
    """Fetch package metadata from the public Play Store listing."""
    url = f"{STORE_URL}?id={urllib.parse.quote(package)}&hl=en&gl=US"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                return None
            html = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        log.debug("Play Store lookup failed for %s: %s", package, exc)
        return None
    return parse_page(package, html)


class MetadataResolver:
    """Fill missing database entries from the Play Store, off the main loop.

    A package is looked up at most once per ``cooldown`` seconds, only when the
    database has no entry for it. ``consume_update()`` reports that a new entry
    was stored so the runtime can republish the activity immediately.
    """

    def __init__(
        self,
        database: AppDatabase,
        *,
        enabled: bool = True,
        timeout: float = 8.0,
        cooldown: float = 600.0,
        fetch: Callable[[str, float], dict | None] = fetch_package,
    ):
        self.database = database
        self.enabled = enabled
        self.timeout = timeout
        self.cooldown = cooldown
        self.fetch = fetch
        self.updated = False
        self._attempts: dict[str, float] = {}
        self._inflight: set[str] = set()
        self._lock = threading.Lock()

    def configure(self, config: dict) -> None:
        settings = config.get("database", {})
        self.enabled = bool(settings.get("auto_lookup", True))
        self.timeout = float(settings.get("timeout", 8))
        self.cooldown = float(settings.get("cooldown", 600))

    def request(self, package: str | None) -> None:
        """Schedule a lookup when the package is unknown and not already queued."""
        if not package or not self.enabled:
            return
        if self.database.lookup(package) is not None:
            return

        now = time.monotonic()
        with self._lock:
            if package in self._inflight:
                return
            attempted = self._attempts.get(package)
            if attempted is not None and now - attempted < self.cooldown:
                return
            self._inflight.add(package)

        threading.Thread(
            target=self._lookup, args=(package,), daemon=True,
            name=f"play-lookup-{package}",
        ).start()

    def _lookup(self, package: str) -> None:
        try:
            entry = self.fetch(package, self.timeout)
            if entry:
                # Write through a separate instance: the runtime keeps reading
                # its own copy and reloads it by mtime.
                writer = AppDatabase(self.database.user_path, self.database.seed_path)
                writer.set(package, entry)
                self.updated = True
                log.info("Discovered Play Store metadata for %s: %s", package, entry.get("name"))
            else:
                log.debug("No Play Store metadata found for %s", package)
        except Exception as exc:  # a lookup must never break presence
            log.debug("Play Store lookup error for %s: %s", package, exc)
        finally:
            with self._lock:
                self._attempts[package] = time.monotonic()
                self._inflight.discard(package)

    def consume_update(self) -> bool:
        """Return True once after a lookup stored a new entry."""
        if not self.updated:
            return False
        self.updated = False
        return True
