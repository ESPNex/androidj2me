#!/usr/bin/env python3
"""Stage a C:-backed *candidate* Android 4.2 bootclasspath from LOCAL builds.

No downloads, SDK android.jar stubs, repackaged APKs or source-only jars.
Require DEX-035/036 class definitions AND actual method code in all ten
AOSP boot JARs; pin each whole archive, extract byte-identical raw DEX to /data/e63-bootdex,
and pin a sorted, on-disk class-def index. None of this is a Dalvik VM or a
usable Android system. In particular, source/tag provenance is NOT verified.
Only run after a real LOCAL runtime build, with a separate provenance check:
  python3 tools/stage_android42_runtime.py /path/to/local/runtime/framework
The generated .pkg fragment is intentionally NOT part of any released SISX.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "build/staged-android42-system"
OUT = STAGE / "framework"
BOOT_OUT = STAGE / "bootdex"
HEADER = ROOT / "symbian/android_java_app/framework_pins.h"
BOOT_PINS = ROOT / "symbian/android_java_app/boot_dex_pins.h"
# Exact AOSP 4.2.2 build/core/dex_preopt.mk DEXPREOPT_BOOT_JARS order.
# Do not omit core-junit/bouncycastle/telephony/mms/apache-xml as before.
FILES = (
    ("core.jar", ("Ljava/lang/Object;",), 2),
    ("core-junit.jar", ("Ljunit/framework/TestCase;",), 2),
    ("bouncycastle.jar", ("Lcom/android/org/bouncycastle/jce/provider/BouncyCastleProvider;",), 2),
    # HttpClient is an interface with no code_item; check an implementation.
    ("ext.jar", ("Lorg/apache/http/impl/client/DefaultHttpClient;",), 2),
    ("framework.jar", ("Landroid/app/Activity;", "Landroid/os/ServiceManager;"), 2),
    ("telephony-common.jar", ("Lcom/android/internal/telephony/PhoneBase;",), 2),
    ("mms-common.jar", ("Lcom/google/android/mms/pdu/PduParser;",), 2),
    ("android.policy.jar", ("Lcom/android/internal/policy/impl/PhoneWindow;",), 2),
    ("services.jar", ("Lcom/android/server/SystemServer;",), 2),
    ("apache-xml.jar", ("Lorg/apache/xalan/processor/TransformerFactoryImpl;",), 2),
    ("framework-res.apk", (), 3),
)
MAX_FILE = 100 * 1024 * 1024
MAX_DEX = 32 * 1024 * 1024  # symbian/runtime/dex_preflight.h
MAX_RESOURCE = 70 * 1024 * 1024
BOOT_MAGIC = b"E63BOOT2"
BOOT_RECORD = struct.Struct("<256sIII")  # descriptor, DEX slot, class_def index, length
BOOT_HEADER = struct.Struct("<8sIIII")  # magic, version, row bytes, count, reserved
BOOT_MAX_CLASSES = 50_000
BOOT_MAX_BYTES = 16 * 1024 * 1024
BOOT_ORDER = tuple(filename for filename, _, kind in FILES if kind == 2)


def u32(data: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(data):
        raise ValueError("truncated DEX reference")
    return struct.unpack_from("<I", data, off)[0]


def descriptor(data: bytes, string_index: int) -> str:
    strings, off = u32(data, 56), u32(data, 60)
    if string_index >= strings or off + strings * 4 > len(data):
        raise ValueError("invalid DEX strings")
    at = u32(data, off + string_index * 4)
    for _ in range(5):  # bounded ULEB128 for declared UTF-16 length
        if at >= len(data):
            raise ValueError("invalid DEX string length")
        b = data[at]
        at += 1
        if b < 128:
            break
    else:
        raise ValueError("DEX length overflow")
    end = data.find(b"\x00", at, min(at + 256, len(data)))
    if end < 0:
        raise ValueError("DEX class descriptor exceeds native index capacity")
    raw = data[at:end]
    # The bounded native lookup compares raw descriptor bytes. Reject (rather
    # than silently replace) names requiring a future MUTF-8 aware index.
    if (len(raw) < 3 or len(raw) >= 256 or raw[0:1] != b"L" or
            raw[-1:] != b";" or b";" in raw[1:-1] or
            any(c < 33 or c > 126 for c in raw) or b"[" in raw):
        raise ValueError("non-ASCII or invalid class descriptor; MUTF-8 index needed")
    return raw.decode("ascii")


def dex_class_entries(data: bytes) -> list[str]:
    """Full ordered class_def table: list index is the real DEX class_def index."""
    if (len(data) < 112 or len(data) > MAX_DEX or
            data[:8] not in (b"dex\n035\x00", b"dex\n036\x00") or
            u32(data, 32) != len(data) or u32(data, 36) != 112 or
            u32(data, 40) != 0x12345678):
        raise ValueError("not a bounded Android 4.2 DEX-035/036 runtime image")
    if hashlib.sha1(data[32:]).digest() != data[12:32] or \
            zlib.adler32(data[12:]) != u32(data, 8):
        raise ValueError("DEX signature or checksum failed")
    types, type_off = u32(data, 64), u32(data, 68)
    classes, class_off = u32(data, 96), u32(data, 100)
    if (types == 0 or classes == 0 or classes > 10_000 or
            type_off + 4 * types > len(data) or
            class_off + 32 * classes > len(data)):
        raise ValueError("invalid or empty DEX class table")
    found: list[str] = []
    seen: set[str] = set()
    # AOSP dx emits class_defs in dependency/topological order, NOT in
    # class_idx order. Their physical row position is the class_def index.
    for idx in range(classes):
        type_idx = u32(data, class_off + 32 * idx)
        if type_idx >= types:
            raise ValueError("invalid DEX class_def type index")
        name = descriptor(data, u32(data, type_off + 4 * type_idx))
        if name in seen:
            raise ValueError("duplicate DEX class definition")
        seen.add(name)
        found.append(name)
    return found


def defined_classes(data: bytes) -> set[str]:
    return set(dex_class_entries(data))


def uleb128(data: bytes, off: int) -> tuple[int, int]:
    value = 0
    for step in range(5):
        if off >= len(data):
            raise ValueError("truncated DEX class_data ULEB128")
        byte = data[off]
        off += 1
        if step == 4 and byte > 15:
            raise ValueError("overflow in DEX class_data ULEB128")
        value |= (byte & 0x7f) << (step * 7)
        if byte < 128:
            return value, off
    raise ValueError("overflow in DEX class_data ULEB128")


def executable_classes(data: bytes, classes: list[str]) -> set[str]:
    """Check class_data method_id/code_item references, not only DEX names.

    This is an offline structural check, NOT a bytecode verifier, provenance
    certificate, Android build verification or replacement for Dalvik.
    """
    method_count, method_off = u32(data, 88), u32(data, 92)
    field_count, field_off = u32(data, 80), u32(data, 84)
    class_off = u32(data, 100)
    data_at, data_size = u32(data, 108), u32(data, 104)
    if (method_count == 0 or method_off < 112 or method_off % 4 != 0 or
            method_off + method_count * 8 > len(data) or
            data_at < 112 or data_size == 0 or data_at + data_size > len(data) or
            (field_count and (field_off < 112 or field_off % 4 != 0 or
                              field_off + field_count * 8 > len(data)))):
        raise ValueError("DEX lacks executable method/field tables")
    result: set[str] = set()
    for class_def, name in enumerate(classes):
        row = class_off + class_def * 32
        owning_type = u32(data, row)
        class_data = u32(data, row + 24)
        if not class_data:
            continue
        if class_data < data_at or class_data >= data_at + data_size:
            raise ValueError("DEX class_data outside data section")
        at = class_data
        lengths = []
        for _ in range(4):
            count, at = uleb128(data, at)
            lengths.append(count)
        if (lengths[0] + lengths[1] > field_count or
                lengths[2] + lengths[3] > method_count):
            raise ValueError("DEX class_data exceeds method/field table")
        for count in lengths[:2]:
            field_idx = 0
            for _ in range(count):
                delta, at = uleb128(data, at)
                _, at = uleb128(data, at)  # access_flags
                field_idx += delta
                if field_idx >= field_count:
                    raise ValueError("DEX class_data field index out of range")
        for count in lengths[2:]:
            method_idx = 0
            for _ in range(count):
                delta, at = uleb128(data, at)
                _, at = uleb128(data, at)  # access_flags
                code_off, at = uleb128(data, at)
                method_idx += delta
                if (method_idx >= method_count or
                        struct.unpack_from("<H", data,
                                           method_off + method_idx * 8)[0] != owning_type):
                    raise ValueError("DEX method_id owner mismatch")
                if code_off:
                    if (code_off < data_at or code_off % 4 != 0 or
                            code_off + 16 > data_at + data_size or
                            code_off + 16 + 2 * u32(data, code_off + 12) >
                                data_at + data_size or
                            u32(data, code_off + 12) == 0):
                        raise ValueError("DEX code_item outside data section")
                    result.add(name)
        if at > data_at + data_size:
            raise ValueError("DEX class_data is truncated")
    return result


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_with_dex(path: Path, needed: tuple[str, ...]) -> tuple[int, str, bytes | None, list[str]]:
    size = path.stat().st_size
    if size < 112 or size > MAX_FILE:
        raise ValueError(f"out-of-bounds archive: {path}")
    digest = file_sha256(path)
    dex = None
    classes: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate ZIP entries: {path}")
        if path.suffix == ".jar":
            if "classes.dex" not in names:
                raise ValueError(f"no bounded executable DEX: {path}")
            info = archive.getinfo("classes.dex")
            if (not 112 <= info.file_size <= MAX_DEX or
                    info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ValueError(f"no bounded executable DEX: {path}")
            dex = archive.read(info)  # offline PC staging; bounded before extraction
            classes = dex_class_entries(dex)
            if not set(needed).issubset(classes):
                raise ValueError(f"expected framework CLASS DEFINITION absent: {path}")
            executable = executable_classes(dex, classes)
            if not executable or not set(needed).issubset(executable):
                raise ValueError(f"required DEX method CODE absent: {path}")
        elif path.suffix == ".apk":
            if "resources.arsc" not in names or "AndroidManifest.xml" not in names:
                raise ValueError(f"not a compiled resources APK: {path}")
            info = archive.getinfo("resources.arsc")
            if not 8 < info.file_size <= MAX_RESOURCE:
                raise ValueError(f"not a bounded resources APK: {path}")
        else:
            raise ValueError(f"unexpected archive type: {path}")
    return size, digest, dex, classes


def inspect(path: Path, needed: tuple[str, ...]) -> tuple[int, str]:
    """Compatibility entry for the original fail-closed archive check."""
    size, digest, _, _ = inspect_with_dex(path, needed)
    return size, digest


def boot_index(dex_classes: dict[str, list[str]]) -> tuple[bytes, int]:
    # Dalvik's original bootclasspath is ordered: the FIRST class_def wins.
    if set(dex_classes) != set(BOOT_ORDER):
        raise ValueError("ten runtime DEX files required for AOSP bootclasspath")
    first: dict[str, tuple[int, int]] = {}
    duplicates = 0
    for slot, filename in enumerate(BOOT_ORDER):
        for class_def, name in enumerate(dex_classes[filename]):
            if name in first:
                duplicates += 1
            else:
                first[name] = slot, class_def
    if not 0 < len(first) <= BOOT_MAX_CLASSES:
        raise ValueError("boot index class count out of bounds")
    rows = bytearray(BOOT_HEADER.pack(BOOT_MAGIC, 2, BOOT_RECORD.size,
                                      len(first), 0))
    for name in sorted(first):  # ASCII descriptor order equals native byte order
        slot, class_def = first[name]
        raw = name.encode("ascii")
        if len(raw) >= 256 or class_def >= 10_000:
            raise ValueError("boot descriptor or class_def exceeds native bound")
        rows.extend(BOOT_RECORD.pack(raw, slot, class_def, len(raw)))
    if len(rows) > BOOT_MAX_BYTES:
        raise ValueError("boot index exceeds bounded native maximum")
    return bytes(rows), duplicates


def _c_pin(path: str, relative: str, size: int, digest: str, kind: int | None = None) -> str:
    sha = ",".join(f"0x{digest[n:n+2]}u" for n in range(0, 64, 2))
    tail = f", {kind}u" if kind is not None else ""
    return (f'    {{ "{path}", "{relative.replace(chr(92), chr(92)*2)}", '
            f'{size}u, {{{sha}}}{tail} }},')


def _write_header(path: Path, lines: list[str]) -> None:
    temporary = path.with_suffix(".new")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.replace(path)


def stage(source: Path) -> dict:
    if not source.is_dir() or source.resolve() == OUT.resolve():
        raise ValueError("provide an existing LOCAL runtime framework directory")
    pins: list[tuple[str, int, str, int]] = []
    dex_payloads: dict[str, bytes] = {}
    dex_tables: dict[str, list[str]] = {}
    # Validate every supplied input before writing a candidate manifest.
    for filename, expected_classes, kind in FILES:
        file = source / filename
        if not file.is_file():
            raise ValueError(f"missing required built runtime archive: {file}")
        length, digest, dex, classes = inspect_with_dex(file, expected_classes)
        pins.append((filename, length, digest, kind))
        if dex is not None:
            dex_payloads[filename] = dex
            dex_tables[filename] = classes
    index, duplicates = boot_index(dex_tables)
    OUT.mkdir(parents=True, exist_ok=True)
    BOOT_OUT.mkdir(parents=True, exist_ok=True)
    for filename, length, digest, _ in pins:
        copy = OUT / filename
        shutil.copyfile(source / filename, copy)
        if copy.stat().st_size != length or file_sha256(copy) != digest:
            raise ValueError(f"source/copy changed during staging: {filename}")
        if filename in dex_payloads:
            with zipfile.ZipFile(copy) as archive:
                if archive.read("classes.dex") != dex_payloads[filename]:
                    raise ValueError(f"DEX changed after archive pinning: {filename}")
    boot_files = []
    for filename in BOOT_ORDER:
        dex = dex_payloads[filename]
        cache_name = filename + ".classes.dex"
        (BOOT_OUT / cache_name).write_bytes(dex)
        boot_files.append((cache_name, len(dex), hashlib.sha256(dex).hexdigest()))
    (BOOT_OUT / "boot-classes.idx").write_bytes(index)
    index_pin = ("boot-classes.idx", len(index), hashlib.sha256(index).hexdigest())
    framework_header = [
        "/* Candidate LOCAL archives. Not a certified or executable Android runtime. */",
        "#ifndef E63_FRAMEWORK_PINS_H", "#define E63_FRAMEWORK_PINS_H",
        "#include <stddef.h>", "#include <stdint.h>",
        "typedef struct E63FrameworkPin {",
        "    const char *guest_path; const char *relative_on_c;",
        "    size_t length; uint8_t sha256[32]; unsigned kind;",
        "} E63FrameworkPin;",
        f"#define E63_FRAMEWORK_PIN_COUNT {len(pins)}u",
        "static const E63FrameworkPin e63_framework_pins[] = {",
    ]
    for filename, length, digest, kind in pins:
        framework_header.append(_c_pin(f"/system/framework/{filename}",
                                       f"system\\framework\\{filename}",
                                       length, digest, kind))
    framework_header += ["};", "#endif"]
    boot_header = [
        "/* Pinned raw DEX cache and index from LOCAL jars; no VM or SISX. */",
        "#ifndef E63_BOOT_DEX_PINS_H", "#define E63_BOOT_DEX_PINS_H",
        "#include <stddef.h>", "#include <stdint.h>",
        "typedef struct E63BootFilePin {",
        "    const char *guest_path; const char *relative_on_c;",
        "    size_t length; uint8_t sha256[32];",
        "} E63BootFilePin;",
        f"#define E63_BOOT_DEX_PIN_COUNT {len(boot_files)}u",
        "static const E63BootFilePin e63_boot_dex_pins[] = {",
    ]
    for filename, length, digest in boot_files:
        boot_header.append(_c_pin(f"/data/e63-bootdex/{filename}",
                                   f"data\\e63-bootdex\\{filename}",
                                   length, digest))
    boot_header += ["};", "static const E63BootFilePin e63_boot_index_pin ="]
    boot_header.append(_c_pin("/data/e63-bootdex/boot-classes.idx",
                               "data\\e63-bootdex\\boot-classes.idx",
                               index_pin[1], index_pin[2]).strip().rstrip(",") + ";")
    boot_header += ["#endif"]
    # Last: publish pins only after all payloads and their digests exist.
    _write_header(HEADER, framework_header)
    _write_header(BOOT_PINS, boot_header)
    fragment = STAGE / "framework.pkg-fragment"
    entries = ([(f"framework/{n}", f"system\\framework\\{n}") for n, _, _, _ in pins] +
               [(f"bootdex/{n}", f"data\\e63-bootdex\\{n}")
                for n, _, _ in [*boot_files, index_pin]])
    fragment.write_text("; DO NOT include: Android VM, JNI, Binder and services missing.\n" +
                        "\n".join(f'"../../build/staged-android42-system/{src}" - '
                                   f'"C:\\private\\E0B63E04\\{dst}"'
                                   for src, dst in entries) + "\n")
    record = {"runtime_ready": False, "source_provenance_not_verified": True,
              "stage": str(STAGE), "package_fragment_not_included": str(fragment),
              "files": {n: {"bytes": size, "sha256": digest} for n, size, digest, _ in pins},
              "bootdex": {n: {"bytes": size, "sha256": digest}
                          for n, size, digest in [*boot_files, index_pin]},
              "bootclasspath_unique_classes": struct.unpack_from("<I", index, 16)[0],
              "shadowed_class_definitions": duplicates}
    (STAGE / "candidate-runtime.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("local_runtime_framework", type=Path)
    args = parser.parse_args()
    print(json.dumps(stage(args.local_runtime_framework), indent=2))
