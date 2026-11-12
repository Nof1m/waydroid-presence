import pytest

from waydroid_presence import play_store
from waydroid_presence.database import AppDatabase
from waydroid_presence.play_store import MetadataResolver, icon_url, parse_page

PAGE = """
<html><head>
<meta property="og:title" content="Fate/Grand Order - Apps on Google Play">
<meta property="og:image" content="https://play-lh.googleusercontent.com/pTlA4kXv9=s0-br30">
</head><body>app page</body></html>
"""


class InlineThread:
    """Run resolver lookups synchronously so tests stay deterministic."""

    def __init__(self, target, args=(), **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


def test_parse_page_builds_a_database_entry():
    entry = parse_page("com.example.game", PAGE)
    assert entry["name"] == "Fate/Grand Order"
    assert entry["icon"] == "https://play-lh.googleusercontent.com/pTlA4kXv9=w512"
    assert entry["source"] == "play"
    assert entry["fetched_at"].endswith("Z")


def test_parse_page_strips_entities_and_title_suffix():
    page = PAGE.replace("Fate/Grand Order", "Call of Duty&amp; Mobile")
    assert parse_page("com.example.game", page)["name"] == "Call of Duty& Mobile"


def test_parse_page_returns_none_without_open_graph_tags():
    assert parse_page("com.example.game", "<html><body>not found</body></html>") is None


@pytest.mark.parametrize("raw", [
    "https://evil.example/icon=s0",
    "http://play-lh.googleusercontent.com/icon=s0",
    "ftp://play-lh.googleusercontent.com/icon",
    "",
])
def test_icon_url_rejects_untrusted_hosts(raw):
    assert icon_url(raw) == ""


def test_icon_url_normalizes_to_512px():
    assert icon_url("https://play-lh.googleusercontent.com/abc=s0-br30") == (
        "https://play-lh.googleusercontent.com/abc=w512"
    )


def make_database(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text('{"version": 1, "apps": {}}', encoding="utf-8")
    database = AppDatabase(tmp_path / "user.json", seed)
    database.check_interval = 0
    return database


def test_resolver_stores_entries_and_reports_an_update(tmp_path, monkeypatch):
    monkeypatch.setattr(play_store.threading, "Thread", InlineThread)
    calls = []

    def fetch(package, timeout):
        calls.append(package)
        return {"name": "Example Game", "icon": "https://cdn.example/i.png"}

    database = make_database(tmp_path)
    resolver = MetadataResolver(database, fetch=fetch)
    resolver.request("com.example.game")

    assert calls == ["com.example.game"]
    assert database.icon_for("com.example.game") == "https://cdn.example/i.png"
    assert resolver.consume_update() is True
    assert resolver.consume_update() is False


def test_resolver_skips_packages_already_in_the_database(tmp_path, monkeypatch):
    monkeypatch.setattr(play_store.threading, "Thread", InlineThread)
    database = make_database(tmp_path)
    database.set("com.example.game", {"name": "Known", "icon": "https://cdn.example/i.png"})
    calls = []

    resolver = MetadataResolver(database, fetch=lambda package, timeout: calls.append(package))
    resolver.request("com.example.game")

    assert calls == []


def test_resolver_honors_the_cooldown_after_a_failed_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(play_store.threading, "Thread", InlineThread)
    calls = []

    def fetch(package, timeout):
        calls.append(package)
        return None

    database = make_database(tmp_path)
    resolver = MetadataResolver(database, fetch=fetch, cooldown=600)
    resolver.request("com.example.game")
    resolver.request("com.example.game")

    assert calls == ["com.example.game"]
    assert resolver.consume_update() is False


def test_resolver_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(play_store.threading, "Thread", InlineThread)
    calls = []
    resolver = MetadataResolver(
        make_database(tmp_path), enabled=False,
        fetch=lambda package, timeout: calls.append(package),
    )
    resolver.request("com.example.game")
    assert calls == []


def test_resolver_configure_reads_the_database_section(tmp_path):
    resolver = MetadataResolver(make_database(tmp_path))
    resolver.configure({"database": {"auto_lookup": False, "timeout": 3, "cooldown": 60}})
    assert resolver.enabled is False
    assert resolver.timeout == 3
    assert resolver.cooldown == 60
