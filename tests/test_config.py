import pytest
from waydroid_presence.config import load_config


def write_config(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_current_diagnostic_does_not_require_client_id(tmp_path):
    path = write_config(tmp_path, "discord:\n  client_id: ''\n")
    config = load_config(path, require_client_id=False)
    assert config["discord"]["client_id"] == ""


def test_runtime_requires_client_id(tmp_path):
    path = write_config(tmp_path, "discord:\n  client_id: ''\n")
    with pytest.raises(ValueError, match="client_id"):
        load_config(path)


def test_rejects_invalid_idle_behavior(tmp_path):
    path = write_config(tmp_path, "discord:\n  client_id: '123'\npresence:\n  idle_behavior: invalid\n")
    with pytest.raises(ValueError, match="idle_behavior"):
        load_config(path)


def test_rejects_more_than_two_buttons(tmp_path):
    path = write_config(tmp_path, "discord:\n  client_id: '123'\napps:\n  custom:\n    com.example.game:\n      buttons: [1, 2, 3]\n")
    with pytest.raises(ValueError, match="at most 2"):
        load_config(path)


def test_accepts_application_name_and_per_app_client_id(tmp_path):
    path = write_config(
        tmp_path,
        "discord:\n"
        "  client_id: '123'\n"
        "  application_name: '  Waydroid App  '\n"
        "apps:\n"
        "  custom:\n"
        "    com.example.game:\n"
        "      application_name: 'Example Game'\n"
        "      client_id: '456'\n",
    )
    config = load_config(path)
    assert config["discord"]["application_name"] == "Waydroid App"
    assert config["apps"]["custom"]["com.example.game"]["application_name"] == "Example Game"
    assert config["apps"]["custom"]["com.example.game"]["client_id"] == "456"


def test_rejects_non_numeric_per_app_client_id(tmp_path):
    path = write_config(
        tmp_path,
        "discord:\n  client_id: '123'\napps:\n  custom:\n"
        "    com.example.game:\n      client_id: 'not-a-number'\n",
    )
    with pytest.raises(ValueError, match="client_id"):
        load_config(path)


def test_config_reloader_applies_valid_change(tmp_path):
    from waydroid_presence.config import ConfigReloader

    path = write_config(tmp_path, "discord:\n  client_id: '123'\n")
    initial = load_config(path)
    reloader = ConfigReloader(path, initial)
    path.write_text("discord:\n  client_id: '456'\n", encoding="utf-8")
    updated = reloader.reload_if_changed()
    assert updated["discord"]["client_id"] == "456"


def test_config_reloader_keeps_previous_config_on_invalid_change(tmp_path):
    from waydroid_presence.config import ConfigReloader

    path = write_config(tmp_path, "discord:\n  client_id: '123'\n")
    initial = load_config(path)
    reloader = ConfigReloader(path, initial)
    path.write_text("discord:\n  client_id: ''\npresence:\n  idle_behavior: broken\n", encoding="utf-8")
    assert reloader.reload_if_changed() is None
    assert reloader.config["discord"]["client_id"] == "123"


def test_rejects_non_numeric_global_client_id(tmp_path):
    path = write_config(tmp_path, "discord:\n  client_id: 'ID'\n")
    with pytest.raises(ValueError, match="numeric application ID"):
        load_config(path)


def test_config_reload_interval_must_be_positive(tmp_path):
    path = write_config(tmp_path, "discord:\n  client_id: '123'\nruntime:\n  config_reload_interval: 0\n")
    with pytest.raises(ValueError, match="config_reload_interval"):
        load_config(path)


def test_database_section_has_defaults(tmp_path):
    path = write_config(tmp_path, "discord:\n  client_id: '123'\n")
    config = load_config(path)
    assert config["database"] == {"auto_lookup": True, "timeout": 8, "cooldown": 600}


def test_database_auto_lookup_must_be_boolean(tmp_path):
    path = write_config(
        tmp_path, "discord:\n  client_id: '123'\ndatabase:\n  auto_lookup: maybe\n"
    )
    with pytest.raises(ValueError, match="auto_lookup"):
        load_config(path)


def test_database_timeout_must_be_positive(tmp_path):
    path = write_config(
        tmp_path, "discord:\n  client_id: '123'\ndatabase:\n  timeout: 0\n"
    )
    with pytest.raises(ValueError, match="database.timeout"):
        load_config(path)


def test_profile_template_cli_does_not_require_discord_client_id(tmp_path, monkeypatch, capsys):
    from waydroid_presence.cli import main
    config = tmp_path / "config.yaml"
    config.write_text(
        "discord:\n  client_id: ''\nlogging:\n  file: '" + str(tmp_path / "app.log") + "'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["waydroid-presence", "--config", str(config), "--profile-template", "com.example.game"])
    assert main() == 0
    output = capsys.readouterr().out
    assert "com.example.game:" in output
    assert "details: Playing com.example.game" in output
