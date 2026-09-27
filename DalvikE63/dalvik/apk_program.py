"""Bounded APK container loader for real javac+D8 Java Activity packages.

Read the DEX *inside the APK*, index each real class with J2MEDex, then expose
only its own static Program entry points to the subset interpreter. Main and
Host contain actual Android Java bytecode for Android devices; this loader
never pretends that Android's framework is present on E63. The asset allowlist
is per APK, never a shared copy of the MIDlet's whole resource directory.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .axml_reader import inspect
from .dex_j2me import J2MEDex


class APKProgramError(ValueError):
    pass


@dataclass(frozen=True)
class ProgramDex:
    # The small register VM consumes these same attributes as its legacy Dex.
    blob: bytes
    class_desc: str
    codes: dict
    strings: list[str]
    method_refs: list[str]
    assets: dict[str, dict]
    package: str
    activity: str
    classes: frozenset[str]


def _bounded_entry(name: str) -> bool:
    return (bool(name) and len(name) <= 160 and not name.startswith("/") and
            "\\" not in name and "\x00" not in name and
            all(part not in ("", ".", "..") for part in name.split("/")))


def load_apk(path: Path, *, expected: dict | None = None) -> ProgramDex:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise APKProgramError("missing or oversized Java APK")
    try:
        with zipfile.ZipFile(path) as apk:
            entries = apk.infolist()
            names = [e.filename for e in entries]
            if (len(entries) > 100 or len(names) != len(set(names)) or
                    not all(_bounded_entry(name) for name in names) or
                    any(e.is_dir() or e.file_size > 12 * 1024 * 1024 or
                        e.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        for e in entries) or
                    sum(e.file_size for e in entries) > 20 * 1024 * 1024):
                raise APKProgramError("unexpected, duplicate or oversized APK entries")
            if (names.count("AndroidManifest.xml") != 1 or
                    names.count("classes.dex") != 1 or
                    any(name.startswith("classes") and name.endswith(".dex") and
                        name != "classes.dex" for name in names) or
                    names.count("assets/e63-assets.json") != 1):
                raise APKProgramError("Android Activity APK lacks its single primary DEX")
            if apk.testzip() is not None:
                raise APKProgramError("APK ZIP CRC mismatch")
            info = inspect(apk.read("AndroidManifest.xml"))
            if (not info.package.startswith("org.e63.dalvik.") or
                    info.main_class != info.package + ".Main" or
                    info.min_sdk != 17 or info.target_sdk != 17):
                raise APKProgramError("APK manifest entry/API level differs from requested Activity")
            blob = apk.read("classes.dex")
            dex = J2MEDex(blob)
            main = "L" + info.package.replace(".", "/") + "/Main;"
            program = "L" + info.package.replace(".", "/") + "/Program;"
            base = "Lorg/e63/dalvik/runtime/GuestActivity;"
            host = "Lorg/e63/dalvik/runtime/Host;"
            if (dex.classes.get(main) != base or
                    dex.classes.get(base) != "Landroid/app/Activity;" or
                    host not in dex.classes or program not in dex.classes):
                raise APKProgramError("manifest Activity/Java Program class not in DEX")
            methods = ("onStart()V", "onSelect(I)V",
                       "onCommand(ILjava/lang/String;Ljava/lang/String;)V")
            for method in methods:
                ref = program + "->" + method
                entry = dex.methods.get(ref)
                if entry is None or not entry.code_off or entry.flags & 0x9 != 0x9:
                    raise APKProgramError("missing executable static Java entry: " + ref)
            # Only allowlisted static code can enter this VM. Constructors,
            # lifecycle methods and Android framework calls fail closed here.
            codes = {ref: dex.code_for(ref) for ref, method in dex.methods.items()
                     if ref.startswith(program + "->") and method.code_off and
                     method.flags & 0x9 == 0x9}
            try:
                declared = json.loads(apk.read("assets/e63-assets.json"))
            except (ValueError, UnicodeError) as exc:
                raise APKProgramError("bad per-APK asset index") from exc
            if (not isinstance(declared, dict) or len(declared) > 24 or
                    any(not isinstance(name, str) or not _bounded_entry(name) or
                            not isinstance(data, dict) or set(data) != {"size", "sha256"} or
                            not isinstance(data["size"], int) or data["size"] < 0 or
                            not isinstance(data["sha256"], str) or len(data["sha256"]) != 64
                            for name, data in declared.items())):
                raise APKProgramError("invalid per-APK asset index")
            assets = {name: "assets/" + name for name in declared}
            if set(assets.values()) != {n for n in names if n.startswith("assets/")
                                      and n != "assets/e63-assets.json"}:
                raise APKProgramError("APK assets not owned/listed by this package")
            for name, location in assets.items():
                data = apk.read(location)
                if (len(data) != declared[name]["size"] or
                        hashlib.sha256(data).hexdigest() != declared[name]["sha256"]):
                    raise APKProgramError("APK asset hash mismatch: " + name)
            if expected is not None and (
                    expected.get("package") != info.package or
                    expected.get("entry") != info.main_class or
                    expected.get("class") != program or
                    expected.get("dex_sha256") != hashlib.sha256(blob).hexdigest() or
                    expected.get("assets") != declared):
                raise APKProgramError("APK differs from the signed-build catalog")
            return ProgramDex(blob, program, codes, dex.strings, dex.method_refs,
                              declared, info.package, info.main_class,
                              frozenset(dex.classes))
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise APKProgramError("cannot read bounded Java APK") from exc
