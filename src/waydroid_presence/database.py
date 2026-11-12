from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("waydroid-presence.database")

DATABASE_VERSION = 1
PACKAGE_PATTERN = re.compile(r"[A-Za-z0-9_.]+")
# Package data shipped with the wheel; never written to at runtime.
SEED_PATH = Path(__file__).with_name("data") / "apps.json"


class DatabaseError(ValueError):
    """Raised when a local application database cannot be read or validated."""


def user_database_path() -> Path:
    """Return the per-user database path that survives installer updates."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base).expanduser() / "waydroid-presence" / "apps.json"


def _require_text(value: Any, field: str, package: str, *, limit: int = 2048) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise DatabaseError(f"apps.{package}.{field} must be text.")
    text = str(value).strip()
    if not text:
        raise DatabaseError(f"apps.{package}.{field} must not be empty.")
    if len(text) > limit:
        raise DatabaseError(f"apps.{package}.{field} must be at most {limit} characters.")
    return text


def normalize_entry(package: str, entry: dict) -> dict:
    """Validate one package entry and drop unknown fields."""
    if not isinstance(package, str) or not PACKAGE_PATTERN.fullmatch(package):
        raise DatabaseError(f"Invalid Android package name: {package!r}")
    if not isinstance(entry, dict):
        raise DatabaseError(f"apps.{package} must be an object.")

    result: dict[str, str] = {}
    if entry.get("name") is not None:
        result["name"] = _require_text(entry["name"], "name", package, limit=128)

    # `icon_url` is accepted as an alias so hand-written files stay readable.
    icon = entry.get("icon", entry.get("icon_url"))
    if icon:
        icon = _require_text(icon, "icon", package)
        if "://" in icon and not icon.startswith(("http://", "https://")):
            raise DatabaseError(
                f"apps.{package}.icon must be an http(s) URL or a Discord asset key."
            )
        result["icon"] = icon

    if entry.get("large_text") is not None:
        result["large_text"] = _require_text(entry["large_text"], "large_text", package, limit=128)
    if entry.get("application_name") is not None:
        result["application_name"] = _require_text(
            entry["application_name"], "application_name", package, limit=128
        )
    if entry.get("client_id") is not None:
        client_id = entry["client_id"]
        if isinstance(client_id, bool) or not isinstance(client_id, (str, int)):
            raise DatabaseError(f"apps.{package}.client_id must be a Discord application ID.")
        client_id = str(client_id).strip()
        if client_id and not client_id.isdigit():
            raise DatabaseError(f"apps.{package}.client_id must contain only digits.")
        if client_id:
            result["client_id"] = client_id
    if entry.get("source") is not None:
        result["source"] = _require_text(entry["source"], "source", package, limit=32)
    if entry.get("fetched_at") is not None:
        result["fetched_at"] = _require_text(entry["fetched_at"], "fetched_at", package, limit=32)

    if not any(key in result for key in ("name", "icon", "application_name", "client_id")):
        raise DatabaseError(f"apps.{package} needs at least a name, icon or client_id.")
    return result


def read_database(path: str | Path) -> dict[str, dict]:
    """Read one database file. Missing files are treated as empty databases."""
    database_path = Path(path)
    if not database_path.is_file():
        return {}
    try:
        raw = json.loads(database_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatabaseError(f"Cannot read {database_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DatabaseError(f"Invalid JSON in {database_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise DatabaseError(f"{database_path} must contain a JSON object.")

    # Accept both the documented {"version": 1, "apps": {...}} shape and a bare
    # package mapping, which is convenient for small hand-written files.
    apps = raw.get("apps")
    if apps is None:
        apps = {key: value for key, value in raw.items() if key != "version"}
    if not isinstance(apps, dict):
        raise DatabaseError(f"{database_path}: 'apps' must be an object.")

    return {
        str(package): normalize_entry(str(package), entry)
        for package, entry in apps.items()
    }


class AppDatabase:
    """Layered package -> presentation metadata lookup.

    Precedence is ``user database > bundled seed``. The user file is re-read
    when its modification time or size changes, so edits and ``--db-set``
    commands apply to a running daemon without a restart.
    """

    def __init__(
        self,
        user_path: str | Path | None = None,
        seed_path: str | Path | None = None,
        *,
        strict: bool = False,
    ):
        self.user_path = Path(user_path).expanduser() if user_path else user_database_path()
        self.seed_path = Path(seed_path) if seed_path else SEED_PATH
        self.strict = strict
        self.check_interval = 1.0
        self._seed: dict[str, dict] = {}
        self._user: dict[str, dict] = {}
        self._signature: tuple[int, int] | None = None
        self._last_check = 0.0
        self.reload(force=True)

    def _current_signature(self) -> tuple[int, int] | None:
        try:
            stat = self.user_path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _load(self, path: Path, label: str) -> dict[str, dict]:
        try:
            return read_database(path)
        except DatabaseError as exc:
            if self.strict:
                raise
            log.warning("Ignoring %s application database: %s", label, exc)
            return {}

    def reload(self, *, force: bool = False) -> bool:
        signature = self._current_signature()
        if not force and signature == self._signature:
            return False
        self._signature = signature
        self._seed = self._load(self.seed_path, "bundled")
        self._user = self._load(self.user_path, "user")
        log.debug(
            "Application database loaded: %d bundled, %d user entries.",
            len(self._seed), len(self._user),
        )
        return True

    def _refresh(self) -> None:
        now = time.monotonic()
        if now - self._last_check < self.check_interval:
            return
        self._last_check = now
        self.reload()

    def lookup(self, package: str | None) -> dict | None:
        """Return the merged entry for a package, or None when unknown."""
        if not package:
            return None
        self._refresh()
        merged = dict(self._seed.get(package) or {})
        merged.update(self._user.get(package) or {})
        return merged or None

    def source_of(self, package: str | None) -> str | None:
        """Report which layer supplied a package: 'user', 'seed' or None."""
        if not package:
            return None
        self._refresh()
        if package in self._user:
            return "user"
        if package in self._seed:
            return "seed"
        return None

    def user_entry(self, package: str | None) -> dict:
        """Return only the raw user layer for a package."""
        if not package:
            return {}
        self._refresh()
        return dict(self._user.get(package) or {})

    def icon_for(self, package: str | None) -> str:
        return str((self.lookup(package) or {}).get("icon") or "")

    def entries(self) -> dict[str, dict]:
        """Return the merged view, with user fields overriding bundled ones."""
        self._refresh()
        merged: dict[str, dict] = {}
        for package, entry in self._seed.items():
            merged[package] = dict(entry)
        for package, entry in self._user.items():
            merged.setdefault(package, {}).update(entry)
        return merged

    def __len__(self) -> int:
        return len(self.entries())

    def set(self, package: str, entry: dict) -> dict:
        """Validate and persist one entry in the user database."""
        normalized = normalize_entry(package, entry)
        self.reload()
        self._user[package] = normalized
        self._save()
        return normalized

    def remove(self, package: str) -> bool:
        """Delete a user entry. Bundled seed entries cannot be removed."""
        self.reload()
        if package not in self._user:
            return False
        del self._user[package]
        self._save()
        return True

    @property
    def bundled_count(self) -> int:
        self._refresh()
        return len(self._seed)

    @property
    def user_count(self) -> int:
        self._refresh()
        return len(self._user)

    def _save(self) -> None:
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": DATABASE_VERSION,
            "apps": {package: self._user[package] for package in sorted(self._user)},
        }
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.user_path.parent,
            prefix=f".{self.user_path.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(handle.name, self.user_path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
        self._signature = self._current_signature()
