#!/usr/bin/env python3
"""Legacy PC service/CLI harness for APK installation and sandbox VFS.

It interprets the adapters in classes2.dex and J2ME StoreState DEX. The actual
OS display is now interpreted from E63Midlet/E63Canvas by dalvik.ui_vm; this
module is only a package/VFS backend for that UI. No E63 SIS is claimed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path

from dalvik.ids import LAUNCHER, STORE, FILES
from dalvik.tools import jdk_tool
from dalvik.dex import Dex, DexError
from dalvik.dex_j2me import J2MEDex, J2MEDexError
from dalvik.store_j2me import J2MEStoreState, StoreVMError
from dalvik.axml_reader import inspect, AXMLError
from dalvik.host import DesktopHost, HostError, VFS
from dalvik.vm import VM, VMError

HERE = Path(__file__).resolve().parent


class DesktopShell:
    def __init__(self, apks: Path | None = None, state: Path | None = None,
                 import_root: Path | None = None, check_signatures: bool = True):
        self.apks = (Path(apks) if apks else HERE / "apks").resolve()
        self.state = (Path(state) if state else HERE / "state").resolve()
        self.import_root = (Path(import_root) if import_root else HERE / "imports").resolve()
        catalog = json.loads((self.apks / "catalog.json").read_text(encoding="utf-8"))
        self.catalog = {item["package"]: item for item in catalog}
        if len(self.catalog) != len(catalog) or LAUNCHER not in self.catalog:
            raise HostError("catalog has duplicate packages or no Launcher")
        self.vfs = VFS(self.state, self.apks, self.catalog, self.import_root)
        self.host = DesktopHost(self.vfs)
        self.active = LAUNCHER
        self.history: list[str] = []
        self.events: list[tuple] = []
        self._vms: dict[str, VM] = {}
        self._j2me: dict[str, J2MEDex] = {}
        self.check_signatures = check_signatures
        self._vm(STORE)  # validate the real MIDP DEX before using its store state
        self.host.store_state = J2MEStoreState(self._j2me[STORE], self.vfs.installed(FILES))
        self.refresh()

    def _vm(self, package: str) -> VM:
        if package not in self._vms:
            if not self.vfs.installed(package):
                raise HostError("package not installed: " + package)
            item = self.catalog[package]
            file = self.apks / item["name"] if item["system"] else \
                self.vfs.root / "data/app" / item["name"]
            if self.check_signatures:
                signer = jdk_tool("jarsigner")
                if not signer: raise HostError("JDK jarsigner needed for host APK integrity check")
                check = subprocess.run([signer, "-verify", str(file)], capture_output=True,
                                       text=True)
                if check.returncode or "jar verified." not in check.stdout:
                    raise HostError("invalid APK v1 signature: " + file.name)
            with zipfile.ZipFile(file) as archive:
                files = archive.namelist()
                if (files.count("AndroidManifest.xml") != 1 or files.count("classes.dex") != 1 or
                    files.count("classes2.dex") != 1 or any(
                        name.startswith("classes") and name.endswith(".dex") and
                        name not in ("classes.dex", "classes2.dex") for name in files)):
                    raise HostError("APK missing/duplicating converted J2ME or adapter DEX")
                info = inspect(archive.read("AndroidManifest.xml"))
                midp_bytes = archive.read("classes.dex")
                converted = J2MEDex(midp_bytes)
                dex_bytes = archive.read("classes2.dex")
                dex = Dex(dex_bytes)
            if (info.package != package or info.main_class != item["entry"] or
                    info.min_sdk != 17 or info.target_sdk != 17 or
                    dex.class_desc != item["class"] or
                    hashlib.sha256(midp_bytes).hexdigest() != item["j2me_dex_sha256"] or
                    hashlib.sha256(dex_bytes).hexdigest() != item["adapter_sha256"] or
                    len(converted.classes) != item["j2me_classes"] or
                    "Landroid/j2me/edition/E63Midlet;" not in converted.classes or
                    "Landroid/j2me/edition/BridgeClient;" not in converted.classes):
                raise HostError("APK package/manifest/converted J2ME/adapter differs from catalog")
            self._j2me[package] = converted
            self._vms[package] = VM(dex, self.host)
        return self._vms[package]

    def _invoke(self, name: str, proto: str, *args):
        self.host.current = self.active
        return self._vm(self.active).call(name, proto, *args)

    def _apply_navigation(self) -> bool:
        nxt = self.host.pending
        self.host.pending = None
        if nxt is None: return False
        if nxt != self.active:
            self.history.append(self.active)
            self.active = nxt
        self.refresh()
        return True

    def refresh(self):
        self.events = []
        self.host.events = self.events
        self._invoke("onStart", "()V")
        self._apply_navigation() if self.host.pending else None
        return self.events

    def select(self, number: int):
        if not isinstance(number, int) or number < 0:
            raise ValueError("option index must be nonnegative")
        if number not in [e[1] for e in self.events if e[0] == "option"]:
            raise HostError("option not present on this screen")
        self.host.events = []
        self._invoke("onSelect", "(I)V", number)
        notifications = [ev for ev in self.host.events if ev[0] in ("message", "dialog")]
        if not self._apply_navigation():
            self.refresh()
        self.events += notifications
        return self.events

    def command(self, name: str, *args: str):
        number = {"search": 1, "mkdir": 1, "touch": 2, "rename": 3,
                  "delete": 4, "import": 5, "ls": 6, "wav": 7}.get(name)
        if number is None or self.active not in (STORE, FILES):
            raise HostError("command unavailable in this app")
        expected = 1 if name not in ("rename", "import") else 2
        if len(args) != expected:
            raise HostError(f"{name} requires {expected} argument(s)")
        if name == "search" and self.active != STORE or name != "search" and self.active != FILES:
            raise HostError("command unavailable in this app")
        self.host.events = []
        self._invoke("onCommand", "(ILjava/lang/String;Ljava/lang/String;)V",
                     number, args[0], args[1] if expected == 2 else "")
        notifications = [ev for ev in self.host.events if ev[0] in ("message", "text", "dialog")]
        if not self._apply_navigation():
            self.refresh()
        self.events += notifications
        return self.events

    def back(self):
        self.active = self.history.pop() if self.history else LAUNCHER
        return self.refresh()

    def home(self):
        self.active = LAUNCHER
        self.history = []
        return self.refresh()

    def text(self) -> str:
        lines = []
        for event in self.events:
            if event[0] == "title": lines.append("== " + event[1] + " ==")
            elif event[0] == "option": lines.append(f"  {event[1]}. {event[2]}")
            elif event[0] == "dialog": lines.append("[SIMULATED DIALOG] " + event[1])
            elif event[0] == "message": lines.append("[INFO] " + event[1])
            elif event[0] == "text": lines.append(event[1])
        return "\n".join(lines)


def repl(shell: DesktopShell):
    print("DalvikE63: real DEX-035 interpreter, PC only. 'help' lists commands.")
    print(shell.text())
    while True:
        try:
            line = input("dalvik> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        try:
            parts = shlex.split(line)
            if not parts: continue
            cmd, args = parts[0], parts[1:]
            if cmd in ("quit", "exit"): break
            if cmd == "help":
                print("select N | back | home | ls PATH | mkdir PATH | touch PATH | "
                      "rename OLD NEW | delete PATH | import RELATIVE_SOURCE GUEST_DEST | "
                      "wav PATH | search WORDS | quit")
                continue
            if cmd == "select" and len(args) == 1: shell.select(int(args[0]))
            elif cmd == "back" and not args: shell.back()
            elif cmd == "home" and not args: shell.home()
            elif cmd in ("ls", "mkdir", "touch", "rename", "delete", "import", "wav", "search"):
                shell.command(cmd, *args)
            else:
                print("Unknown command; type help")
                continue
            print(shell.text())
        except (HostError, DexError, J2MEDexError, AXMLError, VMError, ValueError, OSError,
                zipfile.BadZipFile) as exc:
            print("Error:", exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, help="PC persistence folder (default: ./state)")
    parser.add_argument("--import-root", type=Path,
                        help="PC folder whose files may be copied into the guest (default: ./imports)")
    args = parser.parse_args()
    repl(DesktopShell(state=args.state, import_root=args.import_root))


if __name__ == "__main__":
    main()
