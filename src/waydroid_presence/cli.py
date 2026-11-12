"""Command-line entry point: parse arguments, then dispatch to ``commands``."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .commands import (
    run_daemon,
    run_database_command,
    run_doctor,
    run_inventory,
    run_profile_template,
)
from .config import load_config
from .detector import ADBDetector

EPILOG = """\
examples:
  waydroid-presence --current
  waydroid-presence --validate-config
  waydroid-presence --db-lookup com.aniplex.fategrandorder
  waydroid-presence --db-set com.example.game --db-icon https://cdn.example/icon.png
  waydroid-presence --packages --user
"""


def setup_logging(config: dict, verbose: bool = False) -> None:
    level_name = "DEBUG" if verbose else str(config["logging"]["level"]).upper()
    level = getattr(logging, level_name, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_path = Path(config["logging"]["file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers.append(RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="waydroid-presence",
        description="Discord Rich Presence for Waydroid",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"Waydroid Presence {__version__}")
    parser.add_argument("--config", default="~/.config/waydroid-presence/config.yaml",
                        help="configuration file (default: %(default)s)")
    parser.add_argument("--verbose", "-v", action="store_true", help="enable debug logging")

    diagnostics = parser.add_mutually_exclusive_group()
    diagnostics.add_argument("--current", action="store_true",
                             help="print the currently focused Android package")
    diagnostics.add_argument("--validate-config", action="store_true",
                             help="validate the configuration and exit")
    diagnostics.add_argument("--test", action="store_true",
                             help="test ADB and Discord connectivity")
    diagnostics.add_argument("--packages", action="store_true",
                             help="list package IDs installed in Waydroid")
    diagnostics.add_argument("--doctor", action="store_true",
                             help="run read-only environment diagnostics")

    database = parser.add_mutually_exclusive_group()
    database.add_argument("--db-path", action="store_true",
                          help="print the user application database path")
    database.add_argument("--db-lookup", metavar="PACKAGE",
                          help="show the database entry and effective activity for a package")
    database.add_argument("--db-set", metavar="PACKAGE",
                          help="add or update a user database entry")
    database.add_argument("--db-fetch", metavar="PACKAGE",
                          help="fetch a missing entry from Google Play and save it")
    database.add_argument("--db-remove", metavar="PACKAGE",
                          help="remove a user database entry")
    parser.add_argument("--db-icon", metavar="URL",
                        help="with --db-set: public image URL or Discord asset key")
    parser.add_argument("--db-name", metavar="NAME",
                        help="with --db-set: display name")
    parser.add_argument("--db-large-text", metavar="TEXT",
                        help="with --db-set: large image tooltip")
    parser.add_argument("--db-client-id", metavar="ID",
                        help="with --db-set: Discord application ID used for this package")

    parser.add_argument("--user", action="store_true",
                        help="with --packages, list third-party/user-installed packages")
    parser.add_argument("--system", action="store_true",
                        help="with --packages, list system packages")
    parser.add_argument("--search", metavar="TEXT",
                        help="with --packages, filter package IDs by substring")
    parser.add_argument("--profile-template", metavar="PACKAGE",
                        help="print a YAML profile template for a package ID")
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.user and args.system:
        parser.error("--user and --system cannot be used together")
    if (args.user or args.system or args.search) and not args.packages:
        parser.error("--user, --system and --search require --packages")

    database_action = (
        args.db_path or args.db_lookup or args.db_set or args.db_fetch or args.db_remove
    )
    other_action = (
        args.packages or args.doctor or args.current
        or args.test or args.validate_config or args.profile_template
    )
    if database_action and other_action:
        parser.error("--db-* commands cannot be combined with another diagnostic command")
    if args.profile_template and (
        args.packages or args.doctor or args.current or args.test or args.validate_config
    ):
        parser.error("--profile-template cannot be combined with another diagnostic command")

    set_fields = (args.db_icon, args.db_name, args.db_large_text, args.db_client_id)
    if any(set_fields) and not args.db_set:
        parser.error(
            "--db-icon, --db-name, --db-large-text and --db-client-id require --db-set"
        )
    if args.db_set and not any(set_fields):
        parser.error(
            "--db-set requires at least one of --db-icon, --db-name, "
            "--db-large-text or --db-client-id"
        )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _validate_args(parser, args)

    # Database commands work offline and do not require a valid configuration.
    if args.db_path or args.db_lookup or args.db_set or args.db_fetch or args.db_remove:
        return run_database_command(args)

    try:
        config = load_config(
            args.config,
            require_client_id=not (
                args.current or args.packages or args.validate_config
                or args.doctor or args.profile_template
            ),
        )
    except (OSError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.profile_template:
        return run_profile_template(args.profile_template)

    setup_logging(config, args.verbose)
    detector = ADBDetector(
        config["adb"]["executable"], str(config["adb"]["device"]), config["adb"]["timeout"]
    )

    if args.validate_config:
        print("Configuration is valid.")
        return 0
    if args.doctor:
        return run_doctor(config, args.config)
    if args.current or args.test or args.packages:
        return run_inventory(args, config, detector)
    return run_daemon(args, config, detector)


if __name__ == "__main__":
    raise SystemExit(main())
