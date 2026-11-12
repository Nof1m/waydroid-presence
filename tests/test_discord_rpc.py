from waydroid_presence import discord_rpc


class FakePresence:
    instances = []
    def __init__(self, client_id):
        self.client_id = client_id
        self.updates = []
        self.clears = 0
        self.closed = False
        self.instances.append(self)
    def connect(self):
        return None
    def update(self, name=None, **payload):
        if name is not None:
            payload["name"] = name
        self.updates.append(payload)
    def clear(self):
        self.clears += 1
    def close(self):
        self.closed = True


def test_rpc_connects_and_skips_duplicate_activity(monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(discord_rpc, "Presence", FakePresence)
    rpc = discord_rpc.DiscordRPC("123", reconnect_interval=1)
    assert rpc.update("Playing", "Level 1", "game", 100, large_text="Game")
    assert rpc.connected
    assert rpc.update("Playing", "Level 1", "game", 100, large_text="Game")
    assert len(FakePresence.instances[0].updates) == 1


def test_rpc_clear_and_close(monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(discord_rpc, "Presence", FakePresence)
    rpc = discord_rpc.DiscordRPC("123")
    assert rpc.connect(force=True)
    assert rpc.clear()
    rpc.close()
    assert FakePresence.instances[0].clears == 1
    assert FakePresence.instances[0].closed
    assert not rpc.connected


def test_rpc_force_sends_duplicate_activity(monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(discord_rpc, "Presence", FakePresence)
    rpc = discord_rpc.DiscordRPC("123", reconnect_interval=1)
    assert rpc.update("Playing", "Level 1", "game", 100)
    assert rpc.update("Playing", "Level 1", "game", 100, force=True)
    assert len(FakePresence.instances[0].updates) == 2


def test_rpc_reconfigure_client_id_closes_old_connection(monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(discord_rpc, "Presence", FakePresence)
    rpc = discord_rpc.DiscordRPC("123")
    assert rpc.connect(force=True)
    old = FakePresence.instances[0]
    rpc.reconfigure("456", 4)
    assert old.closed
    assert rpc.client_id == "456"
    assert rpc.reconnect_interval == 4
    assert not rpc.connected


def test_rpc_sends_custom_application_name(monkeypatch):
    FakePresence.instances.clear()
    monkeypatch.setattr(discord_rpc, "Presence", FakePresence)
    rpc = discord_rpc.DiscordRPC("123")
    assert rpc.update("Playing", "Level 1", "game", 100, application_name="Example Game")
    assert FakePresence.instances[0].updates[0]["name"] == "Example Game"


def test_rpc_ignores_application_name_on_old_pypresence(monkeypatch):
    class LegacyPresence(FakePresence):
        def update(self, **payload):
            self.updates.append(payload)

    FakePresence.instances.clear()
    monkeypatch.setattr(discord_rpc, "Presence", LegacyPresence)
    rpc = discord_rpc.DiscordRPC("123")
    assert rpc.update("Playing", "Level 1", "game", 100, application_name="Example Game")
    assert "name" not in LegacyPresence.instances[0].updates[0]
