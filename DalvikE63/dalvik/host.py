"""PC service broker for adapter DEX; filesystem lives in dalvik.vfs.

The J2ME Canvas UI is interpreted by dalvik.ui_vm. This legacy host only
provides APK service actions and a controlled package/VFS backend.
"""
from __future__ import annotations

import io
import json
import wave

from .assembler import HOST, method_parts, proto_types
from .dex import Dex
from .store_j2me import J2MEStoreState
from .vfs import HostError, VFS


class DesktopHost:
    ALLOWED = {
        HOST + "->title(Ljava/lang/String;)V": "title",
        HOST + "->text(Ljava/lang/String;)V": "text",
        HOST + "->option(ILjava/lang/String;)V": "option",
        HOST + "->image(Ljava/lang/String;)V": "image",
        HOST + "->input(ILjava/lang/String;I)V": "input",
        HOST + "->dialog(Ljava/lang/String;)V": "dialog",
        HOST + "->open(Ljava/lang/String;)V": "open",
        HOST + "->getFlag(Ljava/lang/String;)I": "get_flag",
        HOST + "->setFlag(Ljava/lang/String;I)V": "set_flag",
        HOST + "->isInstalled(Ljava/lang/String;)I": "is_installed",
        HOST + "->storeAction()I": "store_action",
        HOST + "->install(Ljava/lang/String;)I": "install",
        HOST + "->list(Ljava/lang/String;)V": "list_files",
        HOST + "->searchFile(Ljava/lang/String;)I": "search_file",
        HOST + "->mkdir(Ljava/lang/String;)I": "mkdir",
        HOST + "->touch(Ljava/lang/String;)I": "touch",
        HOST + "->rename(Ljava/lang/String;Ljava/lang/String;)I": "rename",
        HOST + "->delete(Ljava/lang/String;)I": "delete",
        HOST + "->importFile(Ljava/lang/String;Ljava/lang/String;)I": "import_file",
        HOST + "->wav(Ljava/lang/String;)I": "wav",
    }

    def __init__(self, vfs: VFS):
        self.vfs = vfs
        self.current: str | None = None
        self.pending: str | None = None
        self.events: list[tuple] = []
        self.flags_file = vfs.root / "settings" / "flags.json"
        self.store_state: J2MEStoreState | None = None
        self.owned_assets: dict[str, frozenset[str]] = {}
        self.flags = json.loads(self.flags_file.read_text(encoding="utf-8")) \
            if self.flags_file.is_file() else {"wifi_demo": 0, "adjust_clock": 0}

    def _require(self, packages: tuple[str, ...]) -> None:
        if self.current not in packages:
            raise HostError("app lacks permission for this host operation")

    def _emit(self, kind: str, *values):
        self.events.append((kind, *values))

    def call(self, ref: str, args: tuple):
        method = self.ALLOWED.get(ref)
        if not method or method_parts(ref)[0] != HOST:
            raise HostError("unknown/untrusted native method " + ref)
        types, _ = proto_types(method_parts(ref)[2])
        if len(types) != len(args):
            raise HostError("host call argument count does not match DEX prototype")
        for desc, value in zip(types, args):
            if desc == "I" and type(value) is not int or \
               desc == "Ljava/lang/String;" and (type(value) is not str or len(value) > 512):
                raise HostError("host call argument type/size is invalid")
        return getattr(self, method)(*args)

    def title(self, text: str): self._emit("title", text)
    def text(self, text: str): self._emit("text", text)
    def option(self, index: int, text: str): self._emit("option", index, text)

    def image(self, name: str):
        if name not in self.owned_assets.get(self.current or "", frozenset()):
            raise HostError("image is not an asset of this APK: " + name)
        self._emit("image", name)

    def input(self, code: int, label: str, arity: int):
        self._require(("org.e63.dalvik.store", "org.e63.dalvik.files"))
        if code < 1 or code > 7 or arity not in (1, 2):
            raise HostError("invalid input control")
        self._emit("input", code, label, arity)

    def dialog(self, text: str):
        self._require(("org.e63.dalvik.systemui",))
        self._emit("dialog", text)

    def open(self, package: str):
        if not self.vfs.installed(package):
            self._emit("message", "App not installed: " + str(package))
            return
        self.pending = package

    def get_flag(self, key: str) -> int:
        self._require(("org.e63.dalvik.settings",))
        if key not in ("wifi_demo", "adjust_clock"): raise HostError("invalid setting")
        return int(bool(self.flags.get(key, 0)))

    def set_flag(self, key: str, value: int):
        self._require(("org.e63.dalvik.settings",))
        if key not in ("wifi_demo", "adjust_clock") or value not in (0, 1):
            raise HostError("invalid setting/value")
        self.flags[key] = value
        tmp = self.flags_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.flags), encoding="utf-8")
        tmp.replace(self.flags_file)

    def is_installed(self, package: str) -> int:
        if package not in self.vfs.catalog: raise HostError("package not catalogued")
        if package == "org.e63.dalvik.files" and self.store_state is not None:
            return int(self.store_state.is_installed())  # executes the actual J2ME DEX
        return int(self.vfs.installed(package))

    def store_action(self) -> int:
        self._require(("org.e63.dalvik.store",))
        if self.store_state is None: raise HostError("converted J2ME StoreState is not loaded")
        return self.store_state.activate()  # original INSTALL=1, OPEN=2, WAIT=3

    def install(self, package: str) -> int:
        self._require(("org.e63.dalvik.packageinstaller",))
        try:
            self.vfs.install(package)
        except (OSError, HostError) as exc:
            if self.store_state is not None:
                self.store_state = J2MEStoreState(self.store_state.dex, self.vfs.installed(package))
            self._emit("message", "INSTALL failed: " + str(exc))
            return 0
        if package == "org.e63.dalvik.files" and self.store_state is not None:
            if not self.store_state.is_installing(): self.store_state.activate()
            self.store_state.finish_install()
        self._emit("message", "INSTALL -> OPEN: " + package + " (PC VFS only)")
        return 1

    def list_files(self, path: str):
        self._require(("org.e63.dalvik.files",))
        try:
            self._emit("text", path + ": " + ", ".join(self.vfs.list(path)))
        except (OSError, HostError) as exc:
            self._emit("message", "ls: " + str(exc))

    def search_file(self, query: str) -> int:
        self._require(("org.e63.dalvik.store",))
        return int(query.strip().casefold() in ("file manager", "file", "file man"))

    def _file_op(self, method: str, *paths) -> int:
        self._require(("org.e63.dalvik.files",))
        try:
            getattr(self.vfs, method)(*paths, caller=self.current)
        except (OSError, HostError) as exc:
            self._emit("message", method + ": " + str(exc))
            return 0
        self._emit("message", method + ": OK")
        return 1

    def mkdir(self, path: str) -> int: return self._file_op("mkdir", path)
    def touch(self, path: str) -> int: return self._file_op("touch", path)
    def rename(self, before: str, after: str) -> int: return self._file_op("rename", before, after)
    def delete(self, path: str) -> int: return self._file_op("delete", path)
    def import_file(self, source: str, dest: str) -> int:
        return self._file_op("import_file", source, dest)

    def wav(self, path: str) -> int:
        self._require(("org.e63.dalvik.files", "org.e63.dalvik.systemui"))
        try:
            if path.startswith("/system/"):
                stream = io.BytesIO(self.vfs.system_read(path))  # RAM asset
            else:
                target = self.vfs.resolve(path)
                if not target.is_file(): raise HostError("WAV not found")
                stream = str(target)
            with wave.open(stream, "rb") as audio:
                summary = f"WAV OK: {audio.getnchannels()}ch, {audio.getframerate()} Hz, {audio.getnframes()} frames"
            self._emit("message", summary + " (host audio playback not implemented)")
            return 1
        except (OSError, HostError, wave.Error) as exc:
            self._emit("message", "WAV: " + str(exc))
            return 0
