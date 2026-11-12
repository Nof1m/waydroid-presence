import json
from pathlib import Path

import pytest

from waydroid_presence.database import (
    AppDatabase,
    DatabaseError,
    normalize_entry,
    read_database,
    user_database_path,
)

SEED = Path(__file__).resolve().parents[1] / "src" / "waydroid_presence" / "data" / "apps.json"


def make_database(tmp_path, seed=None, strict=True):
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed or {"version": 1, "apps": {}}), encoding="utf-8")
    database = AppDatabase(tmp_path / "user.json", seed_path, strict=strict)
    database.check_interval = 0
    return database


def test_bundled_seed_covers_the_documented_packages():
    entries = read_database(SEED)
    for package in ("com.aniplex.fategrandorder", "ru.zdevs.zarchiver", "com.bilibili.trickcal"):
        assert package in entries
        assert entries[package]["icon"].startswith("https://")


def test_seed_entry_is_used_when_the_user_database_is_missing(tmp_path):
    database = make_database(tmp_path, {"apps": {
        "com.example.game": {"name": "Example", "icon": "https://cdn.example/icon.png"},
    }})
    assert database.lookup("com.example.game") == {
        "name": "Example", "icon": "https://cdn.example/icon.png",
    }
    assert database.source_of("com.example.game") == "seed"
    assert database.lookup("com.example.unknown") is None


def test_user_entry_overrides_seed_fields_without_dropping_the_rest(tmp_path):
    database = make_database(tmp_path, {"apps": {
        "com.example.game": {"name": "Seed Name", "icon": "https://cdn.example/seed.png"},
    }})
    database.set("com.example.game", {"icon": "https://cdn.example/user.png"})
    assert database.lookup("com.example.game") == {
        "name": "Seed Name", "icon": "https://cdn.example/user.png",
    }
    assert database.source_of("com.example.game") == "user"


def test_saved_entries_persist_and_reload_from_disk(tmp_path):
    database = make_database(tmp_path)
    database.set("com.example.game", {
        "name": "Example", "icon": "https://cdn.example/icon.png",
    })

    reopened = AppDatabase(tmp_path / "user.json", tmp_path / "seed.json", strict=True)
    assert reopened.icon_for("com.example.game") == "https://cdn.example/icon.png"
    payload = json.loads((tmp_path / "user.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["apps"]["com.example.game"]["name"] == "Example"


def test_database_reloads_when_the_user_file_changes(tmp_path):
    first = make_database(tmp_path)
    first.set("com.example.game", {"icon": "https://cdn.example/one.png"})

    second = AppDatabase(tmp_path / "user.json", tmp_path / "seed.json", strict=True)
    second.check_interval = 0
    assert second.icon_for("com.example.game") == "https://cdn.example/one.png"

    first.set("com.example.game", {"icon": "https://cdn.example/two.png"})
    assert second.icon_for("com.example.game") == "https://cdn.example/two.png"


def test_remove_deletes_only_the_user_layer(tmp_path):
    database = make_database(tmp_path, {"apps": {
        "com.example.seed": {"icon": "https://cdn.example/seed.png"},
    }})
    database.set("com.example.user", {"icon": "https://cdn.example/user.png"})

    assert database.remove("com.example.user") is True
    assert database.lookup("com.example.user") is None
    assert database.remove("com.example.user") is False
    assert database.remove("com.example.seed") is False
    assert database.lookup("com.example.seed") is not None


def test_icon_url_alias_is_accepted(tmp_path):
    database = make_database(tmp_path, {"apps": {
        "com.example.game": {"icon_url": "https://cdn.example/icon.png"},
    }})
    assert database.icon_for("com.example.game") == "https://cdn.example/icon.png"


def test_invalid_entries_are_rejected():
    with pytest.raises(DatabaseError):
        normalize_entry("com.example.game", {"icon": "ftp://cdn.example/icon.png"})
    with pytest.raises(DatabaseError):
        normalize_entry("com.example.game", {})
    with pytest.raises(DatabaseError):
        normalize_entry("not a package", {"icon": "https://cdn.example/icon.png"})
    assert normalize_entry("com.example.game", {"icon": "waydroid"}) == {"icon": "waydroid"}


def test_entries_accept_a_discord_application_and_name_override():
    entry = normalize_entry("com.example.game", {
        "name": "Example", "application_name": "Example App", "client_id": 123456789,
    })
    assert entry == {
        "name": "Example", "application_name": "Example App", "client_id": "123456789",
    }


def test_client_id_must_contain_only_digits():
    with pytest.raises(DatabaseError, match="client_id"):
        normalize_entry("com.example.game", {"client_id": "not-a-number"})


def test_client_id_alone_is_a_valid_user_entry(tmp_path):
    database = make_database(tmp_path, {"apps": {
        "com.example.game": {"name": "Seed Name", "icon": "https://cdn.example/seed.png"},
    }})
    database.set("com.example.game", {"client_id": "123456789"})
    assert database.lookup("com.example.game") == {
        "name": "Seed Name",
        "icon": "https://cdn.example/seed.png",
        "client_id": "123456789",
    }


def test_broken_user_database_is_ignored_unless_strict(tmp_path):
    user_path = tmp_path / "user.json"
    user_path.write_text("{ not json", encoding="utf-8")
    seed_path = tmp_path / "seed.json"

    lenient = AppDatabase(user_path, seed_path)
    assert lenient.lookup("com.example.game") is None

    with pytest.raises(DatabaseError):
        AppDatabase(user_path, seed_path, strict=True)


def test_user_database_path_follows_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert user_database_path() == tmp_path / "waydroid-presence" / "apps.json"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert user_database_path().name == "apps.json"
    assert user_database_path().parent.name == "waydroid-presence"
