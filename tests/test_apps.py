from waydroid_presence.apps import app_client_id, app_metadata


def test_default_metadata_uses_package_name():
    result = app_metadata("com.example.game", {"apps": {"custom": {}}, "presence": {"show_package_name": True}})
    assert result["details"] == "Playing com.example.game"
    assert result["state"] == "com.example.game"
    assert result["large_image"] == "waydroid"


def test_custom_metadata_and_buttons():
    config = {"apps": {"custom": {"com.example.game": {
        "name": "Example", "details": "Playing", "state": "Level 4", "icon": "example",
        "small_image": "rank", "small_text": "Gold",
        "buttons": [{"label": "Wiki", "url": "https://example.com"}],
    }}}, "presence": {}}
    result = app_metadata("com.example.game", config)
    assert result["large_image"] == "example"
    assert result["small_text"] == "Gold"
    assert result["buttons"][0]["label"] == "Wiki"


def test_application_name_uses_package_override_then_global():
    config = {
        "discord": {"client_id": "global", "application_name": "Global App"},
        "apps": {"custom": {
            "com.example.one": {"application_name": "One"},
            "com.example.two": {},
        }},
        "presence": {},
    }
    assert app_metadata("com.example.one", config)["application_name"] == "One"
    assert app_metadata("com.example.two", config)["application_name"] == "Global App"
    assert "application_name" not in app_metadata("com.example.three", {
        "discord": {"client_id": "global"}, "apps": {"custom": {}}, "presence": {},
    })


def test_client_id_uses_package_override_then_global():
    config = {
        "discord": {"client_id": "111"},
        "apps": {"custom": {"com.example.game": {"client_id": "222"}}},
    }
    assert app_client_id("com.example.game", config) == "222"
    assert app_client_id("com.example.other", config) == "111"
    assert app_client_id(None, config) == "111"


def test_database_can_supply_the_discord_application():
    database = FakeDatabase({"com.example.game": {"client_id": "333", "name": "Example"}})
    config = {"discord": {"client_id": "111"}, "apps": {"custom": {}}}
    assert app_client_id("com.example.game", config, database) == "333"
    assert app_client_id("com.example.other", config, database) == "111"

    overridden = {"discord": {"client_id": "111"},
                  "apps": {"custom": {"com.example.game": {"client_id": "222"}}}}
    assert app_client_id("com.example.game", overridden, database) == "222"


def test_application_name_falls_back_to_the_database():
    database = FakeDatabase({"com.example.game": {"name": "Example Game"}})
    config = {"discord": {"client_id": "111"}, "apps": {"custom": {}}, "presence": {}}
    assert app_metadata("com.example.game", config, database)["application_name"] == "Example Game"

    explicit = {"discord": {"client_id": "111", "application_name": "Global"},
                "apps": {"custom": {}}, "presence": {}}
    assert app_metadata("com.example.game", explicit, database)["application_name"] == "Global"


def test_database_application_name_beats_the_display_name():
    database = FakeDatabase({
        "com.example.game": {"name": "Example Game", "application_name": "Example"},
    })
    config = {"discord": {"client_id": "111"}, "apps": {"custom": {}}, "presence": {}}
    activity = app_metadata("com.example.game", config, database)
    assert activity["application_name"] == "Example"
    assert activity["details"] == "Playing Example Game"


class FakeDatabase:
    def __init__(self, entries):
        self.entries = entries

    def lookup(self, package):
        return self.entries.get(package)


def test_database_supplies_name_and_icon_for_known_packages():
    database = FakeDatabase({
        "com.example.game": {"name": "Example Game", "icon": "https://cdn.example/icon.png"},
    })
    result = app_metadata("com.example.game", {"apps": {"custom": {}}, "presence": {}}, database)
    assert result["details"] == "Playing Example Game"
    assert result["state"] == "com.example.game"
    assert result["large_image"] == "https://cdn.example/icon.png"
    assert result["large_text"] == "Example Game"


def test_config_override_beats_the_database():
    database = FakeDatabase({
        "com.example.game": {"name": "DB Name", "icon": "https://cdn.example/db.png"},
    })
    config = {"apps": {"custom": {"com.example.game": {
        "name": "Custom Name", "icon": "custom_asset", "large_text": "Custom tip",
    }}}, "presence": {}}
    result = app_metadata("com.example.game", config, database)
    assert result["details"] == "Playing Custom Name"
    assert result["large_image"] == "custom_asset"
    assert result["large_text"] == "Custom tip"


def test_unknown_package_still_falls_back_to_the_default_icon():
    database = FakeDatabase({})
    result = app_metadata("com.example.unknown", {
        "apps": {"custom": {}}, "presence": {"default_icon_key": "waydroid"},
    }, database)
    assert result["large_image"] == "waydroid"
    assert result["details"] == "Playing com.example.unknown"

