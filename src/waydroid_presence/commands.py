"""Command implementations for the ``waydroid-presence`` entry point.

``cli.py`` only parses arguments and dispatches; the actual work lives here so
the flow of each command can be read top to bottom.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

from . import __version__
from .apps import app_metadata
from .config import ConfigReloader, load_config
from .database import AppDatabase, DatabaseError
from .detector import ADBDetector, ADBError
from .discord_rpc import DiscordRPC
from .play_store import MetadataResolver, fetch_package
from .runtime import PresenceRuntime

PACKAGE_PATTERN = re.compile(r"[A-Za-z0-9_.]+")


def run_profile_template(package: str) -> int:
    """Print a YAML snippet that can be pasted under ``apps.custom``."""
    if not PACKAGE_PATTERN.fullmatch(package):
        print(
            "Invalid package ID. Expected letters, numbers, underscores and dots.",
            file=sys.stderr,
        )
        return 2
    template = {
        package: {
            "name": package,
            "details": f"Playing {package}",
            "state": "Waydroid",
            "icon": "",
        }
    }
    print(yaml.safe_dump(template, sort_keys=False, allow_unicode=True), end="")
    return 0


def run_doctor(config: dict, config_path: str) -> int:
    """Run read-only diagnostics using only the current user's permissions."""
    failures = 0
    warnings = 0

    def report(label: str, status: str, detail: str = "") -> None:
        nonlocal failures, warnings
        print(f"[{status}] {label}" + (f": {detail}" if detail else ""))
        if status == "FAIL":
            failures += 1
        elif status == "WARN":
            warnings += 1

    config_file = Path(config_path).expanduser()
    report("Configuration", "OK", f"valid YAML: {config_file}")

    adb_setting = config["adb"]["executable"]
    adb_path = adb_setting if Path(adb_setting).is_absolute() else shutil.which(adb_setting)
    if adb_path and Path(adb_path).exists():
        report("ADB executable", "OK", str(adb_path))
    else:
        report("ADB executable", "FAIL", f"not found: {adb_setting}")

    detector = ADBDetector(adb_setting, str(config["adb"]["device"]), config["adb"]["timeout"])
    try:
        devices = detector.list_devices()
        online = [device for device in devices if device.state == "device"]
        unauthorized = [device.serial for device in devices if device.state == "unauthorized"]
        if config["adb"]["device"] != "auto":
            selected = [device for device in online if device.serial == config["adb"]["device"]]
        else:
            selected = online
        if len(selected) == 1:
            report("ADB device", "OK", f"{selected[0].serial} (authorized)")
            try:
                package = detector.foreground_package(set(config["apps"]["ignored_packages"]))
                report("Foreground detection", "OK", package or "idle / ignored package")
            except ADBError as exc:
                report("Foreground detection", "FAIL", str(exc))
        elif not selected:
            detail = "No authorized device selected."
            if unauthorized:
                detail += " Unauthorized: " + ", ".join(unauthorized)
            report("ADB device", "FAIL", detail)
        else:
            report("ADB device", "FAIL", "Multiple authorized devices; set adb.device to a serial.")
    except ADBError as exc:
        report("ADB device", "FAIL", str(exc))

    if config["discord"]["client_id"]:
        rpc = DiscordRPC(config["discord"]["client_id"], config["discord"]["reconnect_interval"])
        connected = rpc.connect(force=True)
        rpc.close()
        report(
            "Discord IPC",
            "OK" if connected else "WARN",
            "connected" if connected else "Discord desktop may be closed or IPC unavailable",
        )
    else:
        report("Discord IPC", "WARN", "discord.client_id is empty; RPC check skipped")

    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "waydroid-presence.service"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        state = result.stdout.strip() or result.stderr.strip() or "unknown"
        report("systemd user service", "OK" if state == "active" else "WARN", state)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        report("systemd user service", "WARN", str(exc))

    try:
        database = AppDatabase()
        report(
            "Application database",
            "OK",
            f"{database.bundled_count} bundled, {database.user_count} user entries",
        )
    except (DatabaseError, OSError) as exc:
        report("Application database", "WARN", str(exc))

    try:
        log_path = Path(config["logging"]["file"]).expanduser()
        writable = log_path.parent.exists() and os.access(log_path.parent, os.W_OK)
        report("Log directory", "OK" if writable else "WARN", str(log_path.parent))
    except (OSError, TypeError) as exc:
        report("Log directory", "WARN", str(exc))

    print(f"\nDoctor summary: {failures} failure(s), {warnings} warning(s).")
    return 1 if failures else 0


def run_inventory(args: argparse.Namespace, config: dict, detector: ADBDetector) -> int:
    """Handle ``--packages``, ``--current`` and ``--test``."""
    try:
        if args.packages:
            package_type = "user" if args.user else "system" if args.system else "all"
            packages = detector.installed_packages(package_type, args.search)
            print("\n".join(packages) if packages else "No packages found.")
            print(f"\n{len(packages)} package(s) found.", file=sys.stderr)
            return 0
        package = detector.foreground_package(set(config["apps"]["ignored_packages"]))
        print(f"Foreground package: {package or 'idle'}")
    except ADBError as exc:
        print(f"ADB: unavailable ({exc})", file=sys.stderr)
        return 1

    if args.current:
        return 0
    rpc = DiscordRPC(config["discord"]["client_id"], config["discord"]["reconnect_interval"])
    connected = rpc.connect(force=True)
    rpc.close()
    print(f"Discord IPC: {'connected' if connected else 'unavailable'}")
    return 0 if connected else 1


def run_database_command(args: argparse.Namespace) -> int:
    """Inspect and edit the package -> image database without touching config."""
    try:
        database = AppDatabase(strict=True)
    except (DatabaseError, OSError) as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 2

    if args.db_path:
        print(database.user_path)
        print(
            f"{database.user_count} user entry(ies), "
            f"{database.bundled_count} bundled entry(ies), "
            f"{len(database)} total."
        )
        return 0

    if args.db_lookup:
        return _database_lookup(args, database)
    if args.db_fetch:
        return _database_fetch(args, database)
    if args.db_set:
        return _database_set(args, database)
    return _database_remove(args, database)


def _database_lookup(args: argparse.Namespace, database: AppDatabase) -> int:
    package = args.db_lookup
    entry = database.lookup(package)
    if entry is None:
        print(f"No database entry for {package}.", file=sys.stderr)
        print("Add one with --db-set or an apps.custom override.", file=sys.stderr)
        return 1

    print(f"# source: {database.source_of(package)}")
    print(yaml.safe_dump({package: entry}, sort_keys=False, allow_unicode=True), end="")

    try:
        config = load_config(args.config, require_client_id=False)
    except (OSError, ValueError):
        return 0  # the database entry is still useful without a valid config
    activity = app_metadata(package, config, database)
    print("\n# effective activity")
    print(yaml.safe_dump(activity, sort_keys=False, allow_unicode=True), end="")
    return 0


def _database_set(args: argparse.Namespace, database: AppDatabase) -> int:
    package = args.db_set
    # Start from the existing user layer so a partial edit keeps other fields.
    entry = database.user_entry(package)
    if args.db_icon:
        entry["icon"] = args.db_icon
    if args.db_name:
        entry["name"] = args.db_name
    if args.db_large_text:
        entry["large_text"] = args.db_large_text
    if args.db_client_id:
        entry["client_id"] = args.db_client_id
    try:
        saved = database.set(package, entry)
    except (DatabaseError, OSError) as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 2
    print(f"Saved {package} in {database.user_path}:")
    print(yaml.safe_dump({package: saved}, sort_keys=False, allow_unicode=True), end="")
    return 0


def _database_fetch(args: argparse.Namespace, database: AppDatabase) -> int:
    package = args.db_fetch
    print(f"Looking up {package} on Google Play...", file=sys.stderr)
    entry = fetch_package(package, timeout=15.0)
    if entry is None:
        print(f"No Play Store listing found for {package}.", file=sys.stderr)
        print("Add the entry manually with --db-set.", file=sys.stderr)
        return 1
    try:
        saved = database.set(package, entry)
    except (DatabaseError, OSError) as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 2
    print(f"Saved {package} in {database.user_path}:")
    print(yaml.safe_dump({package: saved}, sort_keys=False, allow_unicode=True), end="")
    return 0


def _database_remove(args: argparse.Namespace, database: AppDatabase) -> int:
    package = args.db_remove
    if not database.remove(package):
        print(f"No user database entry for {package}.", file=sys.stderr)
        return 1
    print(f"Removed {package} from {database.user_path}.")
    if database.source_of(package) == "seed":
        print("A bundled entry still applies; add an apps.custom override to hide it.")
    return 0


def run_daemon(args: argparse.Namespace, config: dict, detector: ADBDetector) -> int:
    """Poll Android, publish presence and reload config until SIGTERM/SIGINT."""
    stop = False

    def request_stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    rpc = DiscordRPC(config["discord"]["client_id"], config["discord"]["reconnect_interval"])
    database = AppDatabase()
    runtime = PresenceRuntime(config, detector, rpc, database, MetadataResolver(database))
    interval = config["presence"]["poll_interval"]
    reloader = ConfigReloader(args.config, config)
    last_reload_check = 0.0
    log = logging.getLogger("waydroid-presence")

    log.info("Waydroid Presence %s started (poll interval: %ss).", __version__, interval)
    try:
        while not stop:
            now = time.monotonic()
            reload_interval = int(runtime.config["runtime"]["config_reload_interval"])
            if now - last_reload_check >= reload_interval:
                last_reload_check = now
                updated = reloader.reload_if_changed()
                if updated is not None:
                    runtime.reconfigure(updated)
                    interval = updated["presence"]["poll_interval"]
                    level_name = str(updated["logging"]["level"]).upper()
                    logging.getLogger().setLevel(getattr(logging, level_name, logging.INFO))
            runtime.tick()
            time.sleep(interval)
    finally:
        rpc.clear()
        rpc.close()
        log.info("Waydroid Presence stopped.")
    return 0
