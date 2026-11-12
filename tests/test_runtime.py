import time
from waydroid_presence.runtime import PresenceRuntime


class Detector:
    def __init__(self, packages):
        self.packages = iter(packages)
    def foreground_package(self, ignored):
        return next(self.packages)
    def connect_endpoint(self, endpoint):
        return "connected"


class RPC:
    def __init__(self):
        self.connected = True
        self.updates = []
        self.clears = 0
    def update(self, *args, **kwargs):
        self.updates.append((args, kwargs))
        return True
    def clear(self):
        self.clears += 1
        return True


def make_config():
    return {
        "apps": {"ignored_packages": ["com.android.launcher3"], "custom": {}},
        "adb": {"reconnect": False, "endpoint": "", "reconnect_interval": 5},
        "discord": {"presence_refresh_interval": 15},
        "presence": {"unavailable_behavior": "keep", "idle_behavior": "clear", "show_elapsed_time": True,
                     "poll_interval": 5, "unavailable_clear_after": 30, "default_icon_key": "waydroid", "default_icon_text": "Waydroid", "idle_details": "Idle"},
    }


def test_runtime_updates_on_app_change_only():
    rpc = RPC()
    runtime = PresenceRuntime(make_config(), Detector(["com.example.game", "com.example.game"]), rpc)
    runtime.tick()
    runtime.tick()
    assert len(rpc.updates) == 1


def test_runtime_clears_when_launcher_is_detected():
    rpc = RPC()
    runtime = PresenceRuntime(make_config(), Detector([None]), rpc)
    assert runtime.tick() == "idle"
    assert rpc.clears == 1


def test_runtime_clears_stale_presence_after_adb_timeout():
    class BrokenDetector(Detector):
        def foreground_package(self, ignored):
            from waydroid_presence.detector import ADBError
            raise ADBError("offline")

    rpc = RPC()
    runtime = PresenceRuntime(make_config(), BrokenDetector([]), rpc)
    runtime.config["presence"]["unavailable_clear_after"] = 0
    runtime.config["presence"]["unavailable_behavior"] = "clear"
    runtime.tick()
    runtime.tick()
    assert rpc.clears == 1


def test_runtime_republishes_same_app_after_adb_recovery():
    class IntermittentDetector(Detector):
        def __init__(self):
            self.results = iter(["com.example.game", None, "com.example.game"])
        def foreground_package(self, ignored):
            result = next(self.results)
            if result is None:
                from waydroid_presence.detector import ADBError
                raise ADBError("offline")
            return result

    rpc = RPC()
    runtime = PresenceRuntime(make_config(), IntermittentDetector(), rpc)
    runtime.tick()
    runtime.config["presence"]["unavailable_behavior"] = "clear"
    runtime.tick()
    runtime.tick()
    assert len(rpc.updates) == 2
    assert rpc.clears == 1


def test_runtime_clears_stale_presence_after_keep_timeout(monkeypatch):
    from waydroid_presence import runtime as runtime_module
    from waydroid_presence.detector import ADBError

    class BrokenDetector(Detector):
        def foreground_package(self, ignored):
            raise ADBError("offline")

    clock = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: clock[0])
    rpc = RPC()
    runtime = PresenceRuntime(make_config(), BrokenDetector([]), rpc)
    runtime.config["presence"]["unavailable_clear_after"] = 30
    runtime.config["presence"]["unavailable_behavior"] = "keep"
    runtime.tick()
    assert rpc.clears == 0
    clock[0] = 131.0
    runtime.tick()
    runtime.tick()
    assert rpc.clears == 1


def test_runtime_forces_periodic_refresh(monkeypatch):
    from waydroid_presence import runtime as runtime_module

    clock = [100.0]
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: clock[0])
    rpc = RPC()
    runtime = PresenceRuntime(make_config(), Detector(["com.example.game"] * 3), rpc)
    runtime.config["discord"]["presence_refresh_interval"] = 15
    runtime.tick()
    clock[0] = 116.0
    runtime.tick()
    assert len(rpc.updates) == 2
    assert rpc.updates[-1][1]["force"] is True


def test_runtime_reconfigure_updates_ignored_packages_and_settings():
    class ReconfigurableDetector(Detector):
        def reconfigure(self, executable, device, timeout):
            self.settings = (executable, device, timeout)

    class ReconfigurableRPC(RPC):
        def reconfigure(self, client_id, reconnect_interval):
            self.settings = (client_id, reconnect_interval)

    config = make_config()
    config["discord"]["client_id"] = "123"
    config["discord"]["reconnect_interval"] = 10
    config["adb"].update(executable="/usr/bin/adb", device="auto", timeout=15)
    detector = ReconfigurableDetector([])
    rpc = ReconfigurableRPC()
    runtime = PresenceRuntime(config, detector, rpc)

    updated = make_config()
    updated["discord"].update(client_id="456", reconnect_interval=7)
    updated["adb"].update(executable="/custom/adb", device="waydroid", timeout=20)
    updated["apps"]["ignored_packages"] = ["com.android.launcher3", "com.example.ignore"]
    runtime.reconfigure(updated)

    assert runtime.ignored == {"com.android.launcher3", "com.example.ignore"}
    assert detector.settings == ("/custom/adb", "waydroid", 20)
    assert rpc.settings == ("456", 7)


def test_runtime_publishes_database_icons_for_known_packages():
    class Database:
        def lookup(self, package):
            if package == "com.example.game":
                return {"name": "Example Game", "icon": "https://cdn.example/icon.png"}
            return None

    rpc = RPC()
    runtime = PresenceRuntime(
        make_config(), Detector(["com.example.game"]), rpc, Database()
    )
    runtime.tick()
    args, kwargs = rpc.updates[0]
    assert args[2] == "https://cdn.example/icon.png"
    assert kwargs["large_text"] == "Example Game"


def test_runtime_switches_discord_application_from_the_database():
    class SwitchingRPC(RPC):
        def __init__(self):
            super().__init__()
            self.client_id = "global"
            self.reconfigures = []

        def reconfigure(self, client_id, reconnect_interval):
            self.reconfigures.append(client_id)
            self.client_id = client_id

    class Database:
        def lookup(self, package):
            if package == "com.example.game":
                return {"name": "Example Game", "client_id": "999"}
            return None

    config = make_config()
    config["discord"].update(client_id="global", reconnect_interval=10)
    rpc = SwitchingRPC()
    runtime = PresenceRuntime(
        config, Detector(["com.example.game", None]), rpc, Database()
    )

    runtime.tick()
    assert rpc.reconfigures == ["999"]
    assert rpc.updates[0][1]["application_name"] == "Example Game"

    runtime.tick()
    assert rpc.reconfigures == ["999", "global"]


def test_runtime_asks_the_resolver_for_unknown_packages():
    class Resolver:
        def __init__(self):
            self.requested = []
            self.updated = False

        def configure(self, config):
            self.config = config

        def request(self, package):
            self.requested.append(package)

        def consume_update(self):
            return self.updated

    rpc = RPC()
    resolver = Resolver()
    runtime = PresenceRuntime(
        make_config(), Detector(["com.example.game", "com.example.game"]), rpc,
        None, resolver,
    )
    runtime.tick()
    assert resolver.requested == ["com.example.game"]

    resolver.updated = True
    runtime.tick()
    assert len(rpc.updates) == 2  # a discovered entry republishes immediately


def test_runtime_switches_discord_application_per_package():
    class SwitchingRPC(RPC):
        def __init__(self):
            super().__init__()
            self.client_id = "global"
            self.reconfigures = []

        def reconfigure(self, client_id, reconnect_interval):
            self.reconfigures.append(client_id)
            self.client_id = client_id

    config = make_config()
    config["discord"].update(client_id="global", reconnect_interval=10)
    config["apps"]["custom"]["com.example.game"] = {
        "client_id": "custom", "application_name": "Custom Game",
    }
    rpc = SwitchingRPC()
    runtime = PresenceRuntime(config, Detector(["com.example.game", None]), rpc)

    runtime.tick()
    assert rpc.reconfigures == ["custom"]
    assert rpc.updates[0][1]["application_name"] == "Custom Game"

    runtime.tick()
    assert rpc.reconfigures == ["custom", "global"]
    assert rpc.clears == 1
