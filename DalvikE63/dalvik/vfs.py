"""PC mount namespace: RAM root + read-only bundles + persistent C: analogue.

This is a host simulation, NOT an RFs implementation or Symbian filesystem.
The namespace and /tmp, /cache files live in Python memory. /system is a
read-only view of the signed APK sources (assets are loaded on demand); only
/data and /sdcard have a PC-disk backing under state/c_drive. Never copy the
entire signed APK set into RAM on a small E63.
"""
from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class HostError(RuntimeError):
    pass


class MountKind(str, Enum):
    RAM = "ram"
    BUNDLE_RO = "bundle-ro"
    C_PRIVATE = "c-private"
    C_MEDIA = "c-media"


@dataclass(frozen=True)
class Mount:
    guest: str
    kind: MountKind


class VFS:
    RAM_FILE_MAX = 1024 * 1024
    RAM_TOTAL_MAX = 8 * 1024 * 1024

    def __init__(self, state_dir: Path, apks: Path, catalog: dict[str, dict], import_root: Path):
        self.state = Path(state_dir).resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.drive = self.state / "c_drive"  # PC analogue, NOT the Nokia C:
        self.root = self.drive / "private" / "e63os"  # private persistent app data
        self.media = self.drive / "media" / "0"
        self.apks = Path(apks).resolve()
        self.catalog = catalog
        self.import_root = Path(import_root).resolve()
        self.mounts = (
            Mount("/", MountKind.RAM),
            Mount("/system", MountKind.BUNDLE_RO),
            Mount("/tmp", MountKind.RAM),
            Mount("/cache", MountKind.RAM),
            Mount("/data", MountKind.C_PRIVATE),
            Mount("/sdcard", MountKind.C_MEDIA),
            Mount("/storage/emulated/0", MountKind.C_MEDIA),
            Mount("/storage/emulated/legacy", MountKind.C_MEDIA),
        )
        self.ram_root: dict[str, bytes] = {}  # files on /tmp and /cache only
        self._migrate_legacy()
        for path in (self.root / "data/app", self.root / "data/data",
                     self.root / "settings", self.media):
            if path.is_symlink(): raise HostError("symlink is not a drive mount")
            path.mkdir(parents=True, exist_ok=True)
        for name in ("Android/data", "Android/obb", "DCIM", "Download", "Ringtones", "Music"):
            (self.media / name).mkdir(parents=True, exist_ok=True)
        self.import_root.mkdir(parents=True, exist_ok=True)
        self.system_apps = {item["name"]: self.apks / item["name"]
                            for item in catalog.values() if item["system"]}
        # The small WAV is in RAM; APK files/images remain lazy read-only bundles.
        with zipfile.ZipFile(self.apks / catalog["org.e63.dalvik.systemui"]["name"]) as archive:
            self.system_assets = {
                "/system/media/audio/ui/lowbattery.wav": archive.read("assets/lowbattery.wav")}

    def _migrate_legacy(self):
        """One-way migration of old state/rootfs/data; never erase old /system."""
        legacy = self.state / "rootfs" / "data"
        target = self.root / "data"
        if legacy.is_symlink(): raise HostError("legacy data is a symlink")
        if legacy.exists():
            if target.exists():
                raise HostError("legacy and new data both exist; resolve migration conflict manually")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(target))
        old_media = target / "media" / "0"
        if old_media.is_symlink(): raise HostError("legacy media is a symlink")
        if old_media.exists():
            if self.media.exists():
                raise HostError("legacy and new media both exist; resolve migration conflict manually")
            self.media.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_media), str(self.media))
        old_flags = self.state / "flags.json"
        new_flags = self.root / "settings" / "flags.json"
        if old_flags.is_file() and not new_flags.exists():
            new_flags.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_flags), str(new_flags))

    @staticmethod
    def _parts(path: str) -> list[str]:
        if not isinstance(path, str): raise HostError("absolute guest path required")
        try:
            encoded = path.encode("utf-8")
        except UnicodeError as exc:
            raise HostError("invalid UTF-8 guest path") from exc
        if (not path.startswith("/") or len(encoded) > 512 or
                "\\" in path or ":" in path or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)):
            raise HostError("absolute guest path required")
        if path == "/": return []
        parts = path.split("/")[1:]
        if any(p in ("", ".", "..") for p in parts):
            raise HostError("invalid guest path segment")
        return parts

    @staticmethod
    def _under(target: Path, root: Path) -> bool:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False

    def resolve(self, path: str, *, write: bool = False, caller: str | None = None) -> Path:
        p = self._parts(path)
        if not p: raise HostError("/ is a RAM namespace, not a disk path")
        if p[0] == "system":
            if write: raise HostError("/system is read-only")
            if len(p) == 3 and p[1] == "app" and p[2] in self.system_apps:
                return self.system_apps[p[2]]
            raise HostError("/system file not in the bundled read-only catalog")
        if p[0] in ("tmp", "cache"):
            raise HostError("RAM files have no disk path; use temp_read/temp_write")
        if p[0] == "sdcard":
            anchor, parts = self.media, p[1:]
        elif p[:3] in (["storage", "emulated", "0"], ["storage", "emulated", "legacy"],
                       ["data", "media", "0"]):
            anchor, parts = self.media, p[3:]
        elif p[0] == "data":
            anchor, parts = self.root / "data", p[1:]
        else:
            raise HostError("guest mount not available: /" + p[0])
        if write:
            if anchor == self.media:
                if (caller != "org.e63.dalvik.files" or
                    p[:3] in (["data", "media", "0"], ["storage", "emulated", "legacy"])):
                    raise HostError("only FileManager may write to /sdcard or /storage/emulated/0")
            elif (not caller or p[:3] != ["data", "data", caller] or
                  len(p) == 3):
                raise HostError("writes outside owned app data denied")
        anchor = anchor.resolve()
        target = anchor.joinpath(*parts).resolve()
        if not self._under(target, anchor):
            raise HostError("path escapes guest mount (symlink?)")
        if write and target == anchor:
            raise HostError("cannot modify mount root")
        return target

    def system_read(self, path: str) -> bytes:
        self._parts(path)
        if path not in self.system_assets: raise HostError("unavailable system asset")
        return self.system_assets[path]

    def imported(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative:
            raise HostError("source must be relative to the import directory")
        self._parts("/" + relative)
        src = (self.import_root / relative).resolve()
        if not self._under(src, self.import_root) or not src.is_file():
            raise HostError("import source outside allowed directory or not a file")
        if src.stat().st_size > 16 * 1024 * 1024:
            raise HostError("import exceeds 16 MiB demo limit")
        return src

    def _dest(self, path: str, caller: str) -> Path:
        if not path.startswith(("/sdcard/", "/storage/emulated/0/")):
            raise HostError("first milestone writes only into /sdcard")
        target = self.resolve(path, write=True, caller=caller)
        if target.is_symlink(): raise HostError("symlinks are not writable")
        return target

    def mkdir(self, path: str, caller: str) -> None:
        self._dest(path, caller).mkdir()  # no parent auto-create

    def touch(self, path: str, caller: str) -> None:
        with self._dest(path, caller).open("xb"): pass

    def rename(self, before: str, after: str, caller: str) -> None:
        old, new = self._dest(before, caller), self._dest(after, caller)
        if not old.exists() or new.exists() or old == new:
            raise HostError("source missing or destination already exists")
        old.rename(new)

    def delete(self, path: str, caller: str) -> None:
        target = self._dest(path, caller)
        target.rmdir() if target.is_dir() else target.unlink()  # nonempty dir denied

    def import_file(self, relative: str, dest: str, caller: str) -> None:
        source = self.imported(relative)
        target = self._dest(dest, caller)
        with source.open("rb") as inp, target.open("xb") as out:
            shutil.copyfileobj(inp, out, length=64 * 1024)

    def list(self, path: str) -> list[str]:
        self._parts(path)
        if path == "/":
            return ["cache/", "data/", "sdcard/", "storage/", "system/", "tmp/"]
        if path == "/storage": return ["emulated/"]
        if path == "/storage/emulated": return ["0/", "legacy/"]
        if path == "/data/media": return ["0/"]
        if path == "/data":
            return sorted(set(["media/"] + [p.name + ("/" if p.is_dir() else "")
                                               for p in (self.root / "data").iterdir()]))
        if path == "/system": return ["app/", "media/"]
        if path == "/system/app": return sorted(self.system_apps)
        if path == "/system/media": return ["audio/"]
        if path == "/system/media/audio": return ["ui/"]
        if path == "/system/media/audio/ui": return ["lowbattery.wav"]
        if path in ("/tmp", "/cache"):
            return sorted(key.split("/", 2)[-1] for key in self.ram_root
                          if key.startswith(path + "/"))
        target = self.resolve(path)
        if not target.is_dir(): raise HostError("not a guest folder")
        return sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())

    def temp_write(self, path: str, content: bytes) -> None:
        p = self._parts(path)
        if len(p) != 2 or p[0] not in ("tmp", "cache") or not isinstance(content, bytes):
            raise HostError("RAM writes only to /tmp or /cache direct files")
        size = len(content)
        if size > self.RAM_FILE_MAX or (sum(map(len, self.ram_root.values())) -
            len(self.ram_root.get(path, b"")) + size > self.RAM_TOTAL_MAX):
            raise HostError("RAM file/total limit exceeded")
        self.ram_root[path] = bytes(content)

    def temp_read(self, path: str) -> bytes:
        p = self._parts(path)
        if len(p) != 2 or p[0] not in ("tmp", "cache") or path not in self.ram_root:
            raise HostError("RAM file not found")
        return self.ram_root[path]

    def install(self, package: str) -> None:
        item = self.catalog.get(package)
        if not item or item["system"]:
            raise HostError("only catalogued non-system APKs may be installed")
        dest = self.root / "data/app" / item["name"]
        if dest.is_symlink() or dest.exists():
            raise HostError("package already installed or symlinked")
        with (self.apks / item["name"]).open("rb") as inp, dest.open("xb") as out:
            shutil.copyfileobj(inp, out, length=64 * 1024)
        (self.root / "data/data" / package).mkdir(parents=True, exist_ok=True)
        if package == "org.e63.dalvik.files":
            music = self.resolve("/sdcard/Music/music.wav", write=True, caller=package)
            if not music.exists():
                with zipfile.ZipFile(self.apks / item["name"]) as archive:
                    with music.open("xb") as out: out.write(archive.read("assets/music.wav"))

    def installed(self, package: str) -> bool:
        item = self.catalog.get(package)
        if not item: return False
        if item["system"]: return True
        dest = self.root / "data/app" / item["name"]
        source = self.apks / item["name"]
        if dest.is_symlink() or not dest.is_file() or not source.is_file():
            return False
        try:
            if dest.stat().st_size != source.stat().st_size: return False
            # A pre-existing/corrupted file is not an installed APK: don't show
            # false OPEN. _vm separately verifies its v1 signature and DEX.
            def digest(path: Path) -> bytes:
                checksum = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(64 * 1024), b""):
                        checksum.update(chunk)
                return checksum.digest()
            return digest(dest) == digest(source)
        except OSError:
            return False
