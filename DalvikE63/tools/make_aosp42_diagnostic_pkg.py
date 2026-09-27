#!/usr/bin/env python3
"""Create a SEPARATE, unreleased Symbian diagnostic .pkg for AOSP DEX.

No Android-complete claim: the app still denies Activity launch. The key '0'
only probes real Color.argb bytecode from authenticated on-disk AOSP framework
DEX. Package includes 10 built JARs, framework-res.apk, original six APKs,
and the 10 raw DEX caches + class index, all on persistent C:; /system is
read-only to guest code. Existing .pkg / SISX / historical release unchanged.
The same app UID means installing this package could replace an earlier 0.2
prototype ON THE PHONE: user must back up and consent separately.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.stage_android42_runtime import BOOT_ORDER, FILES, inspect

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "build/staged-android42-system"
ORIGINAL = ROOT / "symbian/android_java_app/e63android.pkg"
DIAGNOSTIC = ROOT / "symbian/android_java_app/e63android-aosp42-diagnostic.pkg"
PINS = ROOT / "symbian/android_java_app/framework_pins.h"
BOOT_PINS = ROOT / "symbian/android_java_app/boot_dex_pins.h"
PATTERN = re.compile(r'\{\s*"(?P<guest>/[^\"]+)",\s*"[^\"]+",\s*'
                     r'(?P<size>\d+)u,\s*\{(?P<sha>[^}]+)\}', re.S)


def pins(path: Path) -> dict[str, tuple[int, str]]:
    found = {}
    for record in PATTERN.finditer(path.read_text()):
        words = re.findall(r"0x([0-9a-f]{2})u", record.group("sha"))
        if len(words) != 32 or record.group("guest") in found:
            raise ValueError(f"invalid or duplicate native PIN record in {path}")
        found[record.group("guest")] = (int(record.group("size")), "".join(words))
    return found


def generate() -> Path:
    record = json.loads((STAGE / "candidate-runtime.json").read_text())
    if record["runtime_ready"] or record["bootclasspath_unique_classes"] < 10000:
        raise ValueError("staged artifacts are not the pinned 10-JAR candidate")
    jar_pins = pins(PINS)
    dex_pins = pins(BOOT_PINS)
    if len(jar_pins) != len(FILES) or len(dex_pins) != len(BOOT_ORDER) + 1:
        raise ValueError("candidate pin headers missing/mismatched")
    for name, need, kind in FILES:
        path = STAGE / "framework" / name
        size, digest = inspect(path, need)
        expected = (size, digest)
        if (record["files"][name] != {"bytes": size, "sha256": digest} or
                jar_pins.get("/system/framework/" + name) != expected):
            raise ValueError(f"{name}: /system pin does not match staged bytes")
    for name in (*[n + ".classes.dex" for n in BOOT_ORDER],
                 "boot-classes.idx"):
        path = STAGE / "bootdex" / name
        content = path.read_bytes()
        expected = (len(content), hashlib.sha256(content).hexdigest())
        if (record["bootdex"][name] != {"bytes": expected[0],
                                        "sha256": expected[1]} or
                dex_pins.get("/data/e63-bootdex/" + name) != expected):
            raise ValueError(f"{name}: /data pin does not match staged bytes")
    original = ORIGINAL.read_text()
    version = '# {"E63 Java Activity DEX"}, (0xE0B63E04), 0, 2, 0'
    if original.count(version) != 1 or '"images565.bin"' not in original:
        raise ValueError("historical development .pkg changed; refusing to modify")
    preamble = ("; UNRELEASED LOCAL DIAGNOSTIC — NOT AN ANDROID 4.2 PHONE.\n"
                "; All 10 AOSP boot DEX JARs + resources; key 0 probes only Color.argb.\n"
                "; Android Activity/JNI/Binder are ABSENT; old 0.2 files unchanged.\n"
                "; Same UID as 0.2 test app: do not install without phone backup.\n")
    source = preamble + original[original.index(version):]
    source = source.replace(version, '# {"AOSP 4.2 DEX Diagnostic (incomplete)"}, '
                                     '(0xE0B63E04), 0, 3, 0')
    for name, _, _ in FILES:
        source += (f'"../../build/staged-android42-system/framework/{name}" - '
                   f'"C:\\private\\E0B63E04\\system\\framework\\{name}"\n')
    for name in (*[n + ".classes.dex" for n in BOOT_ORDER],
                 "boot-classes.idx"):
        source += (f'"../../build/staged-android42-system/bootdex/{name}" - '
                   f'"C:\\private\\E0B63E04\\data\\e63-bootdex\\{name}"\n')
    DIAGNOSTIC.write_text(source)
    print(f"Diagnostic package only: {DIAGNOSTIC} ({len(FILES)+len(BOOT_ORDER)+1+10} payloads)")
    return DIAGNOSTIC


if __name__ == "__main__":
    generate()
