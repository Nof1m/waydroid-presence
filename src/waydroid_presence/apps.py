from __future__ import annotations


def _custom_settings(package: str | None, config: dict) -> dict:
    return config.get("apps", {}).get("custom", {}).get(package) or {}


def _database_entry(package: str | None, database) -> dict:
    lookup = getattr(database, "lookup", None)
    if lookup is None:
        return {}
    return lookup(package) or {}


def app_client_id(package: str | None, config: dict, database=None) -> str:
    """Return the Discord application ID used to publish one Android package.

    ``apps.custom`` wins over a database entry, which wins over the global
    ``discord.client_id``. A database entry lets a game use its own Discord
    application (and therefore its own displayed name) automatically.
    """
    custom = _custom_settings(package, config)
    entry = _database_entry(package, database)
    return str(
        custom.get("client_id")
        or entry.get("client_id")
        or config.get("discord", {}).get("client_id", "")
        or ""
    ).strip()


def app_metadata(package: str, config: dict, database=None) -> dict:
    """Build a normalized Discord activity for one Android package.

    Precedence for presentation fields is: explicit ``apps.custom`` override,
    then the local application database (user entries before the bundled
    seed), then the global presence defaults.
    """
    custom = _custom_settings(package, config)
    entry = _database_entry(package, database)
    presence = config.get("presence", {})
    show_package = presence.get("show_package_name", True)

    name = str(custom.get("name") or entry.get("name") or package)
    details = str(custom.get("details") or f"Playing {name}")
    state = str(custom.get("state") or (package if show_package else "Waydroid"))
    icon = (
        custom.get("icon")
        or entry.get("icon")
        or presence.get("default_icon_key", "waydroid")
    )
    activity = {
        "details": details,
        "state": state,
        "large_image": icon,
        "large_text": str(custom.get("large_text") or entry.get("large_text") or name),
    }
    application_name = (
        custom.get("application_name")
        or config.get("discord", {}).get("application_name")
        or entry.get("application_name")
        or entry.get("name")
        or ""
    )
    if application_name:
        activity["application_name"] = str(application_name)
    for key in ("small_image", "small_text"):
        if custom.get(key):
            activity[key] = str(custom[key])
    buttons = custom.get("buttons") or []
    if buttons:
        activity["buttons"] = [{"label": str(b["label"]), "url": str(b["url"])} for b in buttons]
    return activity
