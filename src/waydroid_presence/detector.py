from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


class ADBError(RuntimeError):
    pass


@dataclass(frozen=True)
class ADBDevice:
    serial: str
    state: str


class ADBDetector:
    def __init__(self, executable: str = "/usr/bin/adb", device: str = "auto", timeout: int = 15):
        self.executable = executable
        self.device = device
        self.timeout = timeout

    def _run(self, args: list[str], *, use_device: bool = True) -> str:
        command = [self.executable]
        if use_device and args and args[0] != "devices":
            serial = self.resolve_device()
            command += ["-s", serial]
        command += args
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except FileNotFoundError as exc:
            raise ADBError(f"ADB executable not found: {self.executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ADBError(f"ADB command timed out after {self.timeout}s") from exc
        except OSError as exc:
            raise ADBError(f"Could not execute ADB: {exc}") from exc
        if result.returncode:
            message = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise ADBError(message)
        return result.stdout

    def reconfigure(self, executable: str, device: str, timeout: int) -> None:
        self.executable = str(executable)
        self.device = str(device)
        self.timeout = int(timeout)

    def installed_packages(self, package_type: str = "all", search: str | None = None) -> list[str]:
        """Return package IDs, optionally filtering user/system packages and a substring.

        Android package manager flags: -3 lists third-party (user-installed) packages;
        -s lists system packages. Classification follows Android's package manager.
        """
        flags = {"all": [], "user": ["-3"], "system": ["-s"]}
        if package_type not in flags:
            raise ValueError("package_type must be 'all', 'user', or 'system'.")
        output = self._run(["shell", "pm", "list", "packages", *flags[package_type]])
        packages = set()
        for line in output.splitlines():
            value = line.strip()
            if value.startswith("package:"):
                package = value.removeprefix("package:").strip()
                if package:
                    packages.add(package)
        if search:
            needle = search.casefold()
            packages = {package for package in packages if needle in package.casefold()}
        return sorted(packages)

    def connect_endpoint(self, endpoint: str) -> str:
        """Ask the host ADB server to connect to a configured TCP endpoint."""
        try:
            result = subprocess.run(
                [self.executable, "connect", endpoint],
                capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except FileNotFoundError as exc:
            raise ADBError(f"ADB executable not found: {self.executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ADBError(f"ADB connect timed out after {self.timeout}s") from exc
        except OSError as exc:
            raise ADBError(f"Could not execute ADB connect: {exc}") from exc
        if result.returncode:
            raise ADBError(result.stderr.strip() or result.stdout.strip() or "ADB connect failed")
        return result.stdout.strip()

    def list_devices(self) -> list[ADBDevice]:
        output = self._run(["devices"], use_device=False)
        devices: list[ADBDevice] = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                devices.append(ADBDevice(parts[0], parts[1]))
        return devices

    def resolve_device(self) -> str:
        if self.device != "auto":
            devices = {d.serial: d.state for d in self.list_devices()}
            state = devices.get(self.device)
            if state != "device":
                raise ADBError(f"Configured ADB device '{self.device}' is not connected/authorized (state: {state or 'missing'}).")
            return self.device

        online = [d.serial for d in self.list_devices() if d.state == "device"]
        if not online:
            raise ADBError("No authorized ADB devices found. Connect Waydroid with 'adb connect IP:5555'.")
        if len(online) > 1:
            raise ADBError("Multiple ADB devices found. Set adb.device to the desired serial in config.yaml.")
        return online[0]

    def foreground_package(self, ignored: set[str] | None = None) -> str | None:
        ignored = ignored or set()
        output = self._run(["shell", "dumpsys", "window"])
        # Prefer the focused window; use focused activity as a fallback.
        patterns = (
            r"mCurrentFocus=Window\{[^}]*\s+([A-Za-z0-9_.]+)/",
            r"mFocusedApp=ActivityRecord\{[^}]*?\s([A-Za-z0-9_.]+)/",
        )
        package = None
        for pattern in patterns:
            matches = re.findall(pattern, output)
            if matches:
                package = matches[-1]
                break
        if not package:
            return None
        return None if package in ignored else package
