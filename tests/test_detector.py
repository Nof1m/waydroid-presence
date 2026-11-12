from waydroid_presence.detector import ADBDetector


def test_extracts_current_focus_package(monkeypatch):
    detector = ADBDetector()
    output = """
    mCurrentFocus=Window{82b9af5 u0 com.aniplex.fategrandorder/jp.delightworks.Fgo.player.AndroidPlugin}
    mFocusedApp=ActivityRecord{bb3273b u0 com.aniplex.fategrandorder/jp.delightworks.Fgo.player.AndroidPlugin t8}
    """
    monkeypatch.setattr(detector, "_run", lambda args: output)
    assert detector.foreground_package() == "com.aniplex.fategrandorder"


def test_launcher_can_be_ignored(monkeypatch):
    detector = ADBDetector()
    output = "mCurrentFocus=Window{9b2b3b8 u0 com.android.launcher3/com.android.launcher3.Launcher}"
    monkeypatch.setattr(detector, "_run", lambda args: output)
    assert detector.foreground_package({"com.android.launcher3"}) is None


def test_falls_back_to_focused_app(monkeypatch):
    detector = ADBDetector()
    output = "mFocusedApp=ActivityRecord{b835cdc u0 ru.zdevs.zarchiver/.ZArchiver t9}"
    monkeypatch.setattr(detector, "_run", lambda args: output)
    assert detector.foreground_package() == "ru.zdevs.zarchiver"


def test_lists_installed_packages(monkeypatch):
    detector = ADBDetector()
    monkeypatch.setattr(
        detector,
        "_run",
        lambda args: "package:com.example.game\npackage:com.android.settings\npackage:com.example.game\n",
    )
    assert detector.installed_packages() == ["com.android.settings", "com.example.game"]


def test_lists_only_user_packages(monkeypatch):
    detector = ADBDetector()
    seen = []
    def fake_run(args):
        seen.append(args)
        return "package:com.example.game\npackage:com.android.settings\n"
    monkeypatch.setattr(detector, "_run", fake_run)
    assert detector.installed_packages("user") == ["com.android.settings", "com.example.game"]
    assert seen == [["shell", "pm", "list", "packages", "-3"]]


def test_lists_only_system_packages(monkeypatch):
    detector = ADBDetector()
    seen = []
    def fake_run(args):
        seen.append(args)
        return "package:com.android.settings\n"
    monkeypatch.setattr(detector, "_run", fake_run)
    assert detector.installed_packages("system") == ["com.android.settings"]
    assert seen == [["shell", "pm", "list", "packages", "-s"]]


def test_filters_packages_by_case_insensitive_search(monkeypatch):
    detector = ADBDetector()
    monkeypatch.setattr(detector, "_run", lambda args: "package:com.aniplex.fategrandorder\npackage:ru.zdevs.zarchiver\n")
    assert detector.installed_packages(search="FATE") == ["com.aniplex.fategrandorder"]


def test_rejects_unknown_package_type():
    import pytest
    detector = ADBDetector()
    with pytest.raises(ValueError, match="package_type"):
        detector.installed_packages("third-party")
