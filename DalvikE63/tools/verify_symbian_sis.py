#!/usr/bin/env python3
"""Independent bounded extractor/checker of local Symbian 9 SISX files.

Validates exact EXE/resources/MIDP or six Android Java APKs; in the separate
32-payload AOSP DEX diagnostic mode it also validates all ten JARs, compiled
resources, ten extracted DEX files and class index against the C pin headers.
A SEPARATE 40-payload UI diagnostic checks four signed APKs and indexes;
two distinct 44-payload AXML/object diagnostics and a separate JNI/Binder
preview check four manifest caches. None is an E63/Android hardware test.
Checks S60 FP1 prerequisites, NOT the cryptographic SIS signature or E63 run.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_SIS = 12 * 1024 * 1024
MAX_PAYLOAD = 8 * 1024 * 1024
MAX_DIAGNOSTIC_SIS = 96 * 1024 * 1024
MAX_DIAGNOSTIC_PAYLOAD = 32 * 1024 * 1024


def fields(blob: bytes):
    offset = 0
    while offset < len(blob):
        if offset + 8 > len(blob):
            raise ValueError("truncated SIS TLV")
        tag, length = struct.unpack_from("<II", blob, offset)
        offset += 8
        if length > len(blob) - offset:
            raise ValueError("SIS field exceeds data")
        yield tag, blob[offset:offset + length]
        offset += (length + 3) & ~3
    if offset != len(blob):
        raise ValueError("SIS padding exceeds data")


def array_items(blob: bytes, expected_type: int):
    if len(blob) < 4 or struct.unpack_from("<I", blob)[0] != expected_type:
        raise ValueError("wrong SIS array element type")
    pos = 4
    while pos < len(blob):
        if pos + 4 > len(blob):
            raise ValueError("truncated SIS array")
        n = struct.unpack_from("<I", blob, pos)[0]
        pos += 4
        if n > len(blob) - pos:
            raise ValueError("SIS array item exceeds data")
        yield blob[pos:pos + n]
        pos += (n + 3) & ~3
    if pos != len(blob):
        raise ValueError("SIS array padding exceeds data")


def one_field(blob: bytes, wanted: int) -> bytes:
    matches = [content for tag, content in fields(blob) if tag == wanted]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one SIS field type {wanted}")
    return matches[0]


def unpack_compressed(blob: bytes, limit: int = MAX_PAYLOAD) -> bytes:
    if len(blob) < 12:
        raise ValueError("invalid SISCompressed")
    algorithm, length = struct.unpack_from("<IQ", blob)
    if length > limit:
        raise ValueError("decoded SIS payload too large")
    if algorithm == 0:
        decoded = blob[12:]
    elif algorithm == 1:
        dec = zlib.decompressobj()
        decoded = dec.decompress(blob[12:], limit + 1)
        if not dec.eof or dec.unused_data or dec.unconsumed_tail:
            raise ValueError("invalid SIS deflate stream")
    else:
        raise ValueError("unsupported SIS compression")
    if len(decoded) != length:
        raise ValueError("SIS decoded length mismatch")
    return decoded


def extract(sisx: Path, diagnostic: bool = False,
            ui_diagnostic: bool = False,
            axml_diagnostic: bool = False,
            object_diagnostic: bool = False) -> list[bytes]:
    raw = sisx.read_bytes()
    if ui_diagnostic or axml_diagnostic or object_diagnostic:
        diagnostic = True
    limit = MAX_DIAGNOSTIC_SIS if diagnostic else MAX_SIS
    if not (16 < len(raw) <= limit):
        raise ValueError("unexpected SISX length")
    if struct.unpack_from("<I", raw)[0] != 0x10201A7A:
        raise ValueError("not Symbian SIS9")
    contents = one_field(raw[16:], 12)
    data = one_field(contents, 30)
    units = list(array_items(one_field(data, 2), 31))
    if len(units) != 1:
        raise ValueError("expected one SIS data unit")
    file_data = list(array_items(one_field(units[0], 2), 32))
    counts = (44,) if axml_diagnostic or object_diagnostic else \
             (40,) if ui_diagnostic else (32,) if diagnostic else (4, 5, 10)
    if len(file_data) not in counts:
        raise ValueError("unexpected number of packaged files")
    payload_limit = MAX_DIAGNOSTIC_PAYLOAD if diagnostic else MAX_PAYLOAD
    return [unpack_compressed(one_field(item, 3), payload_limit)
            for item in file_data]


def platform_ids(sisx: Path, diagnostic: bool = False) -> list[int]:
    """Read SIS9 Controller/Prerequisites/Dependencies, NOT raw byte matches.

    Missing platform prerequisites produce an installer warning on a Nokia E63;
    they are distinct from EXE capabilities and from the package UID.
    """
    raw = sisx.read_bytes()
    limit = MAX_DIAGNOSTIC_SIS if diagnostic else MAX_SIS
    if not (16 < len(raw) <= limit) or struct.unpack_from("<I", raw)[0] != 0x10201A7A:
        raise ValueError("not a bounded Symbian SIS9")
    contents = one_field(raw[16:], 12)
    controller = one_field(unpack_compressed(one_field(contents, 3)), 13)
    prerequisites = one_field(controller, 17)
    arrays = [value for tag, value in fields(prerequisites) if tag == 2]
    if len(arrays) != 2:
        raise ValueError("expected target-device and package dependencies")
    # SISPrerequisites: the FIRST array is target devices, the second is
    # mandatory install dependencies. Merely spotting the UID elsewhere in
    # the SIS cannot establish that Installer will recognize this handset.
    if list(array_items(arrays[1], 18)):
        raise ValueError("unexpected mandatory package dependencies")
    ids = []
    for dependency in array_items(arrays[0], 18):
        uid = one_field(dependency, 9)
        if len(uid) != 4:
            raise ValueError("invalid SIS target-device UID")
        ids.append(struct.unpack("<I", uid)[0])
    return ids


def verify(app: str, sisx: Path, sdk: Path):
    ui_diagnostic = app == "e63android-ui-diagnostic"
    axml_diagnostic = app in ("e63android-ui-axml-diagnostic",
                              "e63android-jni-binder-preview")
    object_diagnostic = app == "e63android-object-diagnostic"
    diagnostic = app in ("e63android-diagnostic",
                         "e63android-ui-diagnostic",
                         "e63android-ui-axml-diagnostic",
                         "e63android-object-diagnostic",
                         "e63android-jni-binder-preview")
    ids = platform_ids(sisx, diagnostic=diagnostic)
    if ids != [0x102032BE]:
        raise ValueError(f"missing unique E63 S60 3rd FP1 dependency: got {ids!r}")
    files = extract(sisx, diagnostic=diagnostic,
                    ui_diagnostic=ui_diagnostic,
                    axml_diagnostic=axml_diagnostic,
                    object_diagnostic=object_diagnostic)
    base = sdk / "epoc32"
    exe = base / "release/gcce/urel" / (
        "e63android.exe" if diagnostic else f"{app}.exe")
    if ui_diagnostic or axml_diagnostic or object_diagnostic:
        # Independently built candidates must each retain their OWN EXE:
        # GnuPoc overwrites the SDK's single e63android.exe on every build.
        saved = ("aosp42-object-diagnostic" if object_diagnostic else
                 "aosp42-jni-binder-preview" if app==
                      "e63android-jni-binder-preview" else
                 "aosp42-ui-axml-diagnostic" if axml_diagnostic else
                 "aosp42-ui-diagnostic")
        frozen = ROOT / "build" / saved / "e63android.exe"
        if frozen.is_file():
            exe = frozen
    expected = [exe]
    if app == "e63os":
        expected.extend([base / "data/z/resource/apps/e63os.rsc",
                         base / "data/z/private/10003a3f/import/apps/e63os_reg.rsc",
                         ROOT / "j2me/classes.dex",
                         ROOT / "symbian/resources/e63assets.bin"])
    elif app == "e63bridge":
        expected.extend([base / "release/gcce/urel/e63bridge_launch.exe",
                         base / "data/z/resource/apps/e63bridge_launch.rsc",
                         base / "data/z/private/10003a3f/import/apps/e63bridge_launch_reg.rsc"])
    elif app in ("e63android", "e63android-diagnostic",
                 "e63android-ui-diagnostic",
                 "e63android-ui-axml-diagnostic",
                 "e63android-object-diagnostic",
                 "e63android-jni-binder-preview"):
        expected.extend([base / "data/z/resource/apps/e63android.rsc",
                         base / "data/z/private/10003a3f/import/apps/e63android_reg.rsc"])
        expected.extend(ROOT / "apks_android" / name for name in (
            "Launcher.apk", "Settings.apk", "Store.apk", "SystemUI.apk",
            "PackageInstaller.apk", "FileManager.apk"))
        expected.append(ROOT / "symbian/android_java_app/images565.bin")
        if diagnostic:
            from tools.stage_android42_runtime import BOOT_ORDER, FILES
            from tools.make_aosp42_diagnostic_pkg import generate
            generate()  # re-check each SHA-256 against every generated C pin
            staged = ROOT / "build/staged-android42-system"
            expected.extend(staged / "framework" / name
                            for name, _, _ in FILES)
            expected.extend(staged / "bootdex" / name
                            for name in (*[p + ".classes.dex" for p in BOOT_ORDER],
                                         "boot-classes.idx"))
            if ui_diagnostic or axml_diagnostic or object_diagnostic:
                from tools.make_aosp42_ui_diagnostic_pkg import validate
                from tools.build_aosp42_ui_apks import GUEST_APKS, UI_APPS
                validate()  # recheck APK, class index, AXML cache, C pins
                for name in UI_APPS:
                    expected.append(staged / "ui-app" / GUEST_APKS[name])
                    expected.append(staged / "ui-index" / (name + ".idx"))
                if axml_diagnostic or object_diagnostic:
                    expected.extend(staged / "ui-manifest" / (name + ".axml")
                                    for name in UI_APPS)
    else:
        raise ValueError("unrecognized Symbian app")
    if len(files) != len(expected):
        raise ValueError(f"expected {len(expected)} payloads, got {len(files)}")
    for index, (actual, source) in enumerate(zip(files, expected)):
        if actual != source.read_bytes():
            raise ValueError(f"SIS payload #{index} differs from {source}")
    print(f"{app}.sisx: FP1 platform dependency 0x{ids[0]:08X}, {len(files)} files "
          "byte-identical to GCCE EXE and project inputs; no phone/signature validation")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("app", choices=("e63os", "e63bridge", "e63android",
                                      "e63android-diagnostic",
                                      "e63android-ui-diagnostic",
                                      "e63android-ui-axml-diagnostic",
                                      "e63android-object-diagnostic"))
    cli.add_argument("sisx", type=Path)
    cli.add_argument("--sdk", type=Path,
                     default=Path(os.environ.get("EPOCROOT", "")))
    args = cli.parse_args()
    if not (args.sdk / "epoc32").is_dir():
        cli.error("set EPOCROOT to your personal S60 FP1 SDK path, or use --sdk")
    verify(args.app, args.sisx, args.sdk)
