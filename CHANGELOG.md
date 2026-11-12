# Changelog

## 0.6.0

- Added a package-keyed application database so known Android apps automatically display the correct Discord image and display name.
- Added a bundled seed database (`src/waydroid_presence/data/apps.json`) with a curated set of popular games, plus a user database at `~/.local/share/waydroid-presence/apps.json` that survives installer updates.
- Lookup precedence is `apps.custom` override, then user database, then bundled seed, then `presence.default_icon_key`; updates layer field by field instead of replacing whole entries.
- Database icons are public `http(s)` URLs, which Discord fetches and caches, so games no longer need an uploaded Rich Presence asset per title.
- Added `--db-path`, `--db-lookup PACKAGE`, `--db-fetch PACKAGE`, `--db-set PACKAGE [--db-icon] [--db-name] [--db-large-text] [--db-client-id]` and `--db-remove PACKAGE`.
- The database now supplies the Discord activity name automatically: `apps.custom` override, then `discord.application_name`, then the database `application_name`/`name`. Clients that honor the RPC `name` field (Vesktop, Equibop, Vencord) get per-game names with no configuration.
- Database entries accept `client_id`, so the runtime can switch Discord applications per game on the official client and return to `discord.client_id` on idle.
- Added optional Google Play discovery (`database.auto_lookup`, on by default) that resolves unknown packages in a background thread, caches name and icon in the user database and republishes the activity immediately; `--db-fetch PACKAGE` runs the same lookup manually.
- `--doctor` now reports the application database path and how many bundled/user entries it loaded.
- Split the CLI into a thin argument parser (`cli.py`) and readable command implementations (`commands.py`), and rewrote the example `config.yaml` with consistent formatting and commented overrides.
- Fixed an installer bug where a stale `build/` directory made setuptools skip files, installing a mix of old and new modules (for example, an installed binary without `--db-lookup`). The installer now removes build artifacts and force-reinstalls.
- `discord.client_id` must now be numeric, so placeholder values fail with a clear message instead of silently preventing the Discord IPC connection.
- The running daemon picks up database edits on its next activity refresh (`discord.presence_refresh_interval`, 15s by default); a malformed user database is logged and ignored at runtime instead of stopping presence.
- Kept the daemon, installer and ADB integration unprivileged; no root or sudo requirement was introduced.

## 0.5.0

- Added `discord.application_name` and `apps.custom.<package>.application_name` for clients that support custom RPC activity names (Vesktop/Vencord).
- Added optional `apps.custom.<package>.client_id` to use a different Discord Developer Application per Android app, which changes the displayed application name and asset library on the official Discord client.
- The runtime now switches Discord RPC connections when the foreground app changes and returns to the global client ID on idle.
- Re-publishes the current activity after a live configuration reload so name, icon and detail changes apply without waiting for the periodic refresh.
- Raised the pypresence requirement to 4.6 for activity-name support; older versions continue to work and log a warning when the option is used.
- Kept the daemon, installer and ADB integration unprivileged; no root or sudo requirement was introduced.

## 0.4.0

- Added package inventory filters: all packages, third-party/user-installed (`--user`) and system (`--system`).
- Added case-insensitive package ID substring search with `--search`.
- Added read-only `--doctor` diagnostics for configuration, ADB executable/device, foreground detection, Discord IPC, systemd user service and log directory.
- Added `--profile-template PACKAGE` to generate a YAML starter profile for an Android package.
- Kept the daemon, installer, diagnostics and ADB integration unprivileged; no root service or sudo requirement was introduced.
- Preserved live config reload and Discord/ADB recovery behavior from 0.2.1/0.3.0.

## 0.3.0

- Added live YAML configuration reload without restarting the daemon.
- Added ADB package inventory with `--packages`.
- Added runtime reconfiguration for ADB and Discord settings.

## 0.2.1

- Re-publish activity after Discord restarts without restarting the Android app.
- Clear stale activity after a configurable ADB outage timeout and restore it after ADB recovery.

## 0.2.0

- Refactored runtime coordination and improved Discord RPC reconnect handling.
- Added richer per-app Discord activity metadata and user-service hardening.

## 0.1.0

- Initial unprivileged Waydroid Discord Rich Presence daemon.
