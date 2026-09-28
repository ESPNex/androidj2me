#!/usr/bin/env python3
"""Prepare the *small* E63 boot/JNI/Binder preview from pinned AOSP bytes.

The public, previously signed 44-payload v0.6 SISX is only a byte-for-byte
transport for real, independently SHA-pinned AOSP boot JARs and DEX/index.
The original sources and their reproducible AOSP build scripts remain intact.
This base intentionally has NO old shim APK, framework-res.apk, Launcher2,
Settings, SystemUI or other UI APK. Those are *future optional modules*, not
something that silently works without an Activity manager and Java Views.
No full AOSP clone, SDK redistributions, private keys or physical partitions.
"""
from __future__ import annotations

import hashlib
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.make_aosp42_diagnostic_pkg import pins
from tools.stage_android42_runtime import BOOT_ORDER, FILES
from tools.verify_symbian_sis import extract, platform_ids

OLD_SHA = "4c9a312e19789c394e072825f7b9e95a82efbaa9c6dfcd0bd30cf6a033db55ff"
OLD_SIZE = 55_379_048
URL = ("https://github.com/ESPNex/androidj2me/releases/download/"
       "v0.6-preview/e63android-aosp42-jni-binder-preview.sisx")
STAGE = ROOT / "build/staged-android42-system"
WORK = ROOT / "build/aosp42-e63-core-preview"
APP = ROOT / "symbian/android_java_app"
OLD_PKG = APP / "e63android-aosp42-jni-binder-preview.pkg"
NEW_PKG = APP / "e63android-aosp42-core-preview.pkg"
BOOT_JARS = tuple(name for name, _, kind in FILES if kind == 2)
BOOT_FILES = tuple(name + ".classes.dex" for name in BOOT_ORDER) + (
    "boot-classes.idx",)
assert len(BOOT_JARS) == 10 and len(BOOT_FILES) == 11


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_reference(path: Path | None = None) -> Path:
    """Fetch only the exact public asset, never trust a floating build output."""
    if path is None:
        WORK.mkdir(parents=True, exist_ok=True)
        path = WORK / "original-v06.sisx"
        if not path.is_file() or path.stat().st_size != OLD_SIZE or \
                sha256(path.read_bytes()) != OLD_SHA:
            path.unlink(missing_ok=True)
            partial = path.with_suffix(".partial")
            try:
                request = urllib.request.Request(URL, headers={
                    "User-Agent": "E63-core-preview-pinned-payload-stager"})
                with urllib.request.urlopen(request, timeout=90) as stream, \
                        partial.open("wb") as output:
                    size = 0
                    while block := stream.read(1024 * 1024):
                        size += len(block)
                        if size > OLD_SIZE:
                            raise ValueError("remote SISX is larger than pinned release")
                        output.write(block)
                if size != OLD_SIZE or sha256(partial.read_bytes()) != OLD_SHA:
                    raise ValueError("downloaded v0.6 asset does not match its SHA-256")
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
    path = path.resolve()
    if path.stat().st_size != OLD_SIZE or sha256(path.read_bytes()) != OLD_SHA:
        raise ValueError("expected exact public v0.6 SISX, not an arbitrary APK/JAR")
    return path


def _expected() -> tuple[list[tuple[int, Path, tuple[int, str]]], list[str]]:
    original = OLD_PKG.read_text()
    header = '# {"AOSP 4.2 JNI Binder IPC Preview (no Activities)"}, (0xE0B63E04), 0, 6, 0'
    if original.count(header) != 1:
        raise ValueError("original v0.6 package header has changed")
    rows = [line for line in original.splitlines() if line.startswith('"')]
    if len(rows) != 44 or any(not re.fullmatch(r'"[^"]+" - "[^"]+"', row)
                              for row in rows):
        raise ValueError("unexpected v0.6 package payload layout")
    if not (rows[0].endswith('"!:\\sys\\bin\\e63android.exe"') and
            rows[1].endswith('"!:\\resource\\apps\\e63android.rsc"') and
            rows[2].endswith('"!:\\private\\10003a3f\\import\\apps\\e63android_reg.rsc"')):
        raise ValueError("unexpected Symbian executable/registration entries")
    framework = pins(APP / "framework_pins.h")
    boot = pins(APP / "boot_dex_pins.h")
    if len(framework) != 11 or len(boot) != 11:
        raise ValueError("candidate AOSP pin headers changed")
    expected: list[tuple[int, Path, tuple[int, str]]] = []
    for index, name in enumerate(BOOT_JARS, start=10):
        target = STAGE / "framework" / name
        guest = "/system/framework/" + name
        if rows[index] != (f'"../../build/staged-android42-system/framework/{name}"'
                           f' - "C:\\private\\E0B63E04\\system\\framework\\{name}"'):
            raise ValueError(f"boot JAR entry mismatch: {name}")
        expected.append((index, target, framework[guest]))
    for index, name in enumerate(BOOT_FILES, start=21):
        target = STAGE / "bootdex" / name
        guest = "/data/e63-bootdex/" + name
        if rows[index] != (f'"../../build/staged-android42-system/bootdex/{name}"'
                           f' - "C:\\private\\E0B63E04\\data\\e63-bootdex\\{name}"'):
            raise ValueError(f"boot DEX entry mismatch: {name}")
        expected.append((index, target, boot[guest]))
    return expected, rows


def generate(reference: Path | None = None) -> Path:
    base = get_reference(reference)
    expected, rows = _expected()
    if platform_ids(base, diagnostic=True) != [0x102032BE]:
        raise ValueError("v0.6 did not target S60 FP1")
    files = extract(base, diagnostic=True, axml_diagnostic=True)
    if len(files) != 44:
        raise ValueError("v0.6 has an unexpected number of files")
    for index, target, (length, digest) in expected:
        data = files[index]
        if len(data) != length or sha256(data) != digest:
            raise ValueError(f"untrusted boot payload at offset {index}: {target.name}")
    # All 21 bytestrings matched separately compiled AOSP pins. Never stage
    # any of the old six APKs, heavy framework-res or four UI APKs in base.
    for index, target, _ in expected:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != files[index]:
            target.write_bytes(files[index])
    original = OLD_PKG.read_text()
    header = '# {"AOSP 4.2 JNI Binder IPC Preview (no Activities)"}, (0xE0B63E04), 0, 6, 0'
    new = '# {"E63 AOSP Core DEX JNI Binder (no Android UI)"}, (0xE0B63E04), 0, 7, 0'
    preamble = ("; EXPERIMENTAL MODULAR CORE: not a booted Android system.\n"
                "; ONLY genuine AOSP 4.2 boot JARs + pinned DEX/index and\n"
                "; native Symbian DEX/JNI/Binder broker. No old shim APK,\n"
                "; framework-res, Launcher2, Settings or SystemUI in base.\n"
                "; C: contains guest /system (read-only) and /data;\n"
                "; /dev/binder is a virtual IPC endpoint, not disk storage.\n"
                "; SAME SID as Java 0.2/v0.6; backup before installing.\n")
    content = preamble + new + "\n" + original.split(header + "\n", 1)[1]
    original_rows = set(rows)
    stripped = [line for line in content.splitlines()
                if line not in original_rows or line in (rows[:3] + [rows[i] for i, _, _ in expected])]
    new_rows = [line for line in stripped if line.startswith('"')]
    if len(new_rows) != 24 or new_rows != rows[:3] + rows[10:20] + rows[21:32]:
        raise ValueError("a UI/legacy payload slipped into modular base")
    NEW_PKG.write_text("\n".join(stripped) + "\n")
    print("Staged 10 authentic AOSP boot JARs and 11 pinned DEX/index files")
    print(f"Created modular Symbian .pkg: {NEW_PKG} ({len(new_rows)} payloads)")
    return NEW_PKG


if __name__ == "__main__":
    import argparse
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--reference", type=Path, help="offline exact v0.6 SISX")
    args = cli.parse_args()
    generate(args.reference)
