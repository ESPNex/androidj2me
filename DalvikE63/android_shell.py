#!/usr/bin/env python3
"""PC proof of the SIX Android Java Activity APKs' actual Program DEX.

The manifest launches Main extends an Android Activity on a real Android
runtime; this restricted VM instead executes Program.onStart/onSelect/onCommand
from each APK's primary classes.dex. Android widgets/services are explicitly
brokered, NOT implemented by an Android runtime on PC or Nokia E63.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from dalvik.apk_program import load_apk, APKProgramError
from dalvik.host import DesktopHost, HostError, VFS
from dalvik.ids import LAUNCHER
from dalvik.tools import jdk_tool
from dalvik.vm import VM
from shell import DesktopShell, repl

HERE = Path(__file__).resolve().parent


class AndroidShell(DesktopShell):
    def __init__(self, apks: Path | None = None, state: Path | None = None,
                 import_root: Path | None = None, check_signatures: bool = True):
        self.apks = (Path(apks) if apks else HERE / "apks_android").resolve()
        self.state = (Path(state) if state else HERE / "build/android_state").resolve()
        self.import_root = (Path(import_root) if import_root else
                            self.state / "imports").resolve()
        items = json.loads((self.apks / "catalog.json").read_text(encoding="utf-8"))
        if (not isinstance(items, list) or len(items) != 6 or
                any(item.get("name") != Path(item.get("name", "")).name or
                    not isinstance(item.get("package"), str) for item in items)):
            raise HostError("Android Java APK catalog malformed")
        self.catalog = {item["package"]: item for item in items}
        if len(self.catalog) != 6 or LAUNCHER not in self.catalog:
            raise HostError("catalog has duplicate packages or no Java Launcher")
        self.vfs = VFS(self.state, self.apks, self.catalog, self.import_root)
        self.host = DesktopHost(self.vfs)
        self.active = LAUNCHER
        self.history: list[str] = []
        self.events: list[tuple] = []
        self._vms: dict[str, VM] = {}
        self.check_signatures = check_signatures
        self.refresh()

    def _vm(self, package: str) -> VM:
        if package not in self._vms:
            if not self.vfs.installed(package):
                raise HostError("package not installed: " + package)
            item = self.catalog[package]
            path = (self.apks / item["name"] if item["system"] else
                    self.vfs.root / "data/app" / item["name"])
            if self.check_signatures:
                signer = jdk_tool("jarsigner")
                if not signer: raise HostError("JDK jarsigner required to check APK v1 signature")
                result = subprocess.run([signer, "-verify", str(path)],
                                        capture_output=True, text=True)
                if result.returncode or "jar verified." not in result.stdout:
                    raise HostError("invalid Java APK v1 signature: " + path.name)
            program = load_apk(path, expected=item)
            self.host.owned_assets[package] = frozenset(program.assets)
            self._vms[package] = VM(program, self.host)
        return self._vms[package]

    def text(self) -> str:
        rendered = super().text()
        additions = ["[own APK asset] " + e[1] if e[0] == "image" else
                     "[input] " + e[2] for e in self.events if e[0] in ("image", "input")]
        return rendered + ("\n" if rendered and additions else "") + "\n".join(additions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apks", type=Path, default=HERE / "apks_android")
    parser.add_argument("--state", type=Path, default=HERE / "build/android_state")
    parser.add_argument("--import-root", type=Path)
    args = parser.parse_args()
    try:
        repl(AndroidShell(apks=args.apks, state=args.state, import_root=args.import_root))
    except (HostError, APKProgramError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
