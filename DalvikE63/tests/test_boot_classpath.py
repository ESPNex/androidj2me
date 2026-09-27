"""End-phase host tests for a class-DEFINITION index; never an E63/VM test.

All constructed DEX inputs in this module are SYNTHETIC metadata fixtures,
NOT Android 4.2 runtime binaries and NOT a way to generate a release SISX.
"""
from __future__ import annotations

import ctypes
import hashlib
import shutil
import struct
import subprocess
import tempfile
import unittest
import warnings
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

from tools import stage_android42_runtime as stage

ROOT = Path(__file__).resolve().parents[1]


class BootIndex(ctypes.Structure):
    _fields_ = [("context", ctypes.c_void_p), ("read_at", ctypes.c_void_p),
                ("class_count", ctypes.c_uint32), ("total_bytes", ctypes.c_uint32)]


class BootClass(ctypes.Structure):
    _fields_ = [("dex_slot", ctypes.c_uint32),
                ("class_def_index", ctypes.c_uint32)]


CALLBACK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                            ctypes.c_uint32, ctypes.c_void_p, ctypes.c_size_t)


def make_dex(names: list[str]) -> bytes:
    """Synthetic checksummed DEX with trivial methods (never Android code)."""
    names = sorted(names)
    n = len(names)
    assert n
    strings = ["<init>", *names, "V"]
    strings_at = 112
    types_at = strings_at + len(strings) * 4
    proto_at = types_at + (n + 1) * 4
    methods_at = proto_at + 12
    classes_at = methods_at + n * 8
    data_at = classes_at + n * 32
    raw = bytearray(data_at)
    section = bytearray()
    for i, text in enumerate(strings):
        encoded = text.encode("ascii")
        assert len(encoded) < 128
        struct.pack_into("<I", raw, strings_at + i * 4, data_at + len(section))
        section.extend(bytes((len(encoded),)) + encoded + b"\x00")
    for i in range(n + 1):
        struct.pack_into("<I", raw, types_at + i * 4, i + 1)
    struct.pack_into("<III", raw, proto_at, n + 1, n, 0)
    code_offsets = []
    for i in range(n):
        while len(section) % 4:
            section.append(0)
        code_offsets.append(data_at + len(section))
        section.extend(struct.pack("<HHHHIIH", 1, 1, 0, 0, 0, 1, 0x000e))
        struct.pack_into("<HHI", raw, methods_at + i * 8, i, 0, 0)
        struct.pack_into("<I", raw, classes_at + i * 32, i)
        struct.pack_into("<I", raw, classes_at + i * 32 + 4, 1)
        struct.pack_into("<I", raw, classes_at + i * 32 + 8, 0xffffffff)
        struct.pack_into("<I", raw, classes_at + i * 32 + 16, 0xffffffff)
    for i, code_off in enumerate(code_offsets):
        struct.pack_into("<I", raw, classes_at + i * 32 + 24,
                         data_at + len(section))
        # class_data: 0 fields, 1 direct method, no virtual methods.
        section.extend(b"\x00\x00\x01\x00" + _uleb(i) + b"\x01" +
                       _uleb(code_off))
    raw.extend(section)
    raw[:8] = b"dex\n035\x00"
    for offset, value in ((32, len(raw)), (36, 112), (40, 0x12345678),
                          (56, len(strings)), (60, strings_at),
                          (64, n + 1), (68, types_at),
                          (72, 1), (76, proto_at),
                          (88, n), (92, methods_at),
                          (96, n), (100, classes_at),
                          (104, len(section)), (108, data_at)):
        struct.pack_into("<I", raw, offset, value)
    raw[12:32] = hashlib.sha1(raw[32:]).digest()
    struct.pack_into("<I", raw, 8, zlib.adler32(raw[12:]) & 0xffffffff)
    return bytes(raw)


def _uleb(value: int) -> bytes:
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


class Reader:
    def __init__(self, content: bytes, fail: bool = False):
        self.content = content
        self.fail = fail
        self.requests: list[tuple[int, int]] = []
        self.cb = CALLBACK(self.read)

    def read(self, context, offset, destination, length):
        self.requests.append((offset, length))
        if self.fail or offset + length > len(self.content):
            return 0
        ctypes.memmove(destination, self.content[offset:offset + length], length)
        return 1


class BootClasspathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("gcc")
        if not cc:
            raise unittest.SkipTest("native C99 toolchain required")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        dll = Path(cls.temp.name) / "boot_classpath.so"
        subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-pedantic", "-fPIC", "-shared",
                        str(ROOT / "symbian/runtime/boot_classpath.c"),
                        "-o", str(dll)], check=True)
        lib = ctypes.CDLL(str(dll))
        cls.open = lib.e63_boot_index_open
        cls.open.argtypes = [ctypes.POINTER(BootIndex), CALLBACK,
                             ctypes.c_void_p, ctypes.c_size_t]
        cls.open.restype = ctypes.c_int
        cls.find = lib.e63_boot_find_class
        cls.find.argtypes = [ctypes.POINTER(BootIndex), ctypes.c_char_p,
                             ctypes.POINTER(BootClass)]
        cls.find.restype = ctypes.c_int
        cls.confirm = lib.e63_boot_confirm_class
        cls.confirm.argtypes = [ctypes.POINTER(BootClass), ctypes.c_char_p,
                                CALLBACK, ctypes.c_void_p, ctypes.c_size_t]
        cls.confirm.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def image() -> tuple[dict[str, bytes], dict[str, list[str]], bytes]:
        defs = {
            "core.jar": ["Ljava/lang/Object;", "Ldup/Shared;"],
            "core-junit.jar": ["Ljunit/framework/TestCase;"],
            "bouncycastle.jar": [
                "Lcom/android/org/bouncycastle/jce/provider/BouncyCastleProvider;"],
            "ext.jar": ["Ldup/Shared;",
                        "Lorg/apache/http/impl/client/DefaultHttpClient;"],
            "framework.jar": ["Landroid/app/Activity;", "Landroid/os/ServiceManager;"],
            "telephony-common.jar": ["Lcom/android/internal/telephony/PhoneBase;"],
            "mms-common.jar": ["Lcom/google/android/mms/pdu/PduParser;"],
            "android.policy.jar": ["Lcom/android/internal/policy/impl/PhoneWindow;"],
            "services.jar": ["Lcom/android/server/SystemServer;"],
            "apache-xml.jar": [
                "Lorg/apache/xalan/processor/TransformerFactoryImpl;"],
        }
        dex = {name: make_dex(classes) for name, classes in defs.items()}
        tables = {name: stage.dex_class_entries(payload) for name, payload in dex.items()}
        index, shadows = stage.boot_index(tables)
        assert shadows == 1
        return dex, tables, index

    def test_sorted_first_wins_and_confirm_real_disk_class_defs(self):
        dex, tables, binary = self.image()
        index_reader = Reader(binary)
        view = BootIndex()
        self.assertEqual(self.open(ctypes.byref(view), index_reader.cb, None,
                                   len(binary)), 0)
        self.assertEqual(view.class_count, 12)
        for expected_slot, name in enumerate(stage.BOOT_ORDER):
            for class_idx, descriptor in enumerate(tables[name]):
                found = BootClass()
                self.assertEqual(self.find(ctypes.byref(view), descriptor.encode(),
                                           ctypes.byref(found)), 0)
                self.assertEqual(found.dex_slot, 0 if descriptor == "Ldup/Shared;"
                                 else expected_slot)
                source = dex[stage.BOOT_ORDER[found.dex_slot]]
                raw = Reader(source)
                self.assertEqual(self.confirm(ctypes.byref(found), descriptor.encode(),
                                              raw.cb, None, len(source)), 0)
                self.assertLessEqual(max(length for _, length in raw.requests), 268)
        missing = BootClass(5, 7)
        self.assertEqual(self.find(ctypes.byref(view), b"Lnone/Absent;",
                                   ctypes.byref(missing)), -3)
        self.assertEqual((missing.dex_slot, missing.class_def_index), (0, 0))
        self.assertLessEqual(len(index_reader.requests), 1 + 12 * 4)
        self.assertTrue(all(length <= 268 for _, length in index_reader.requests))

    def test_project_compiled_dex_metadata_without_claiming_android_vm(self):
        # This is the *real compiled* J2ME project's DEX, not framework.jar.
        # It exercises the native on-disk metadata path beyond fake fixtures.
        payload = (ROOT / "j2me/classes.dex").read_bytes()
        names = stage.dex_class_entries(payload)
        owner = "Landroid/j2me/edition/E63Midlet;"
        self.assertIn(owner, names)
        self.assertIn(owner, stage.executable_classes(payload, names))
        position = BootClass(0, names.index(owner))
        reader = Reader(payload)
        self.assertEqual(self.confirm(ctypes.byref(position), owner.encode(),
                                      reader.cb, None, len(payload)), 0)
        self.assertLessEqual(max(size for _, size in reader.requests), 268)

    def test_reject_truncated_or_corrupt_index_and_io(self):
        _, _, payload = self.image()
        for data in (payload[:-1], b"NOTMAGIC" + payload[8:],
                     payload[:16] + struct.pack("<I", 50001) + payload[20:]):
            with self.subTest(data=data[:20]):
                view = BootIndex()
                reader = Reader(data)
                self.assertNotEqual(self.open(ctypes.byref(view), reader.cb, None,
                                              len(data)), 0)
                self.assertEqual(view.class_count, 0)
        reader = Reader(payload, fail=True)
        self.assertEqual(self.open(ctypes.byref(BootIndex()), reader.cb,
                                   None, len(payload)), -4)
        # Rewriting a record without changing the header isn't an auth check:
        # RFile adapter must hash the whole pinned index before calling open.
        data = bytearray(payload)
        first = stage.BOOT_HEADER.size
        struct.pack_into("<I", data, first + 256, 10)  # impossible DEX slot
        corrupt = Reader(bytes(data))
        view = BootIndex()
        self.assertEqual(self.open(ctypes.byref(view), corrupt.cb, None, len(data)), 0)
        result = BootClass()
        self.assertEqual(self.find(ctypes.byref(view), b"Landroid/app/Activity;",
                                   ctypes.byref(result)), -2)

    def test_dex_confirmation_rejects_tampering_and_wrong_index(self):
        dex, _, _ = self.image()
        payload = dex["core.jar"]
        reader = Reader(payload)
        self.assertEqual(self.confirm(ctypes.byref(BootClass(0, 1)),
                                      b"Ljava/lang/Object;", reader.cb,
                                      None, len(payload)), 0)
        self.assertEqual(self.confirm(ctypes.byref(BootClass(0, 0)),
                                      b"Ljava/lang/Object;", reader.cb,
                                      None, len(payload)), -2)
        changed = bytearray(payload)
        changed[0] ^= 1
        other = Reader(bytes(changed))
        self.assertEqual(self.confirm(ctypes.byref(BootClass(0, 1)),
                                      b"Ljava/lang/Object;", other.cb,
                                      None, len(payload)), -2)
        reader.fail = True
        self.assertEqual(self.confirm(ctypes.byref(BootClass(0, 1)),
                                      b"Ljava/lang/Object;", reader.cb,
                                      None, len(payload)), -4)
        self.assertEqual(self.confirm(ctypes.byref(BootClass(10, 0)),
                                      b"Ljava/lang/Object;", reader.cb,
                                      None, len(payload)), -1)

    def test_max_index_is_bounded_and_binary_search_is_logarithmic(self):
        tables = {name: [f"Lboot/S{slot}/{i:05d};" for i in range(5000)]
                  for slot, name in enumerate(stage.BOOT_ORDER)}
        binary, shadows = stage.boot_index(tables)
        self.assertEqual(shadows, 0)
        self.assertEqual(len(binary), 24 + 50000 * 268)
        reader = Reader(binary)
        view = BootIndex()
        self.assertEqual(self.open(ctypes.byref(view), reader.cb, None,
                                   len(binary)), 0)
        found = BootClass()
        self.assertEqual(self.find(ctypes.byref(view), b"Lboot/S4/04999;",
                                   ctypes.byref(found)), 0)
        self.assertEqual((found.dex_slot, found.class_def_index), (4, 4999))
        self.assertLessEqual(len(reader.requests), 18)
        self.assertLessEqual(max(size for _, size in reader.requests), 268)

    def test_staging_synthetic_fixture_still_marks_runtime_not_ready(self):
        dex, _, _ = self.image()
        base = Path(self.temp.name) / "fake-local-build"
        base.mkdir()
        for filename, content in dex.items():
            with zipfile.ZipFile(base / filename, "w", zipfile.ZIP_DEFLATED) as jar:
                jar.writestr("classes.dex", content)
        with zipfile.ZipFile(base / "framework-res.apk", "w") as apk:
            apk.writestr("AndroidManifest.xml", b"synthetic test")
            apk.writestr("resources.arsc", b"synthetic test")
        temp_stage = Path(self.temp.name) / "isolated-staging"
        overrides = {"STAGE": temp_stage, "OUT": temp_stage / "framework",
                     "BOOT_OUT": temp_stage / "bootdex",
                     "HEADER": temp_stage / "framework_pins.h",
                     "BOOT_PINS": temp_stage / "boot_dex_pins.h"}
        with patch.multiple(stage, **overrides):
            record = stage.stage(base)
        self.assertFalse(record["runtime_ready"])
        self.assertTrue(record["source_provenance_not_verified"])
        self.assertEqual(record["bootclasspath_unique_classes"], 12)
        self.assertEqual(record["shadowed_class_definitions"], 1)
        self.assertIn("#define E63_BOOT_DEX_PIN_COUNT 10u",
                      overrides["BOOT_PINS"].read_text())
        self.assertIn("#define E63_FRAMEWORK_PIN_COUNT 11u",
                      overrides["HEADER"].read_text())
        for filename in stage.BOOT_ORDER:
            extracted = (temp_stage / "bootdex" /
                         (filename + ".classes.dex")).read_bytes()
            self.assertEqual(extracted, dex[filename])
            self.assertEqual(record["bootdex"][filename + ".classes.dex"]["sha256"],
                             hashlib.sha256(extracted).hexdigest())
        self.assertEqual((temp_stage / "bootdex/boot-classes.idx").read_bytes(),
                         self.image()[2])
        self.assertNotIn("framework.pkg-fragment",
                         (ROOT / "symbian/android_java_app/e63android.pkg").read_text())
        # Synthetic staging must never replace the independently generated
        # ten-classpath candidate pins in the Symbian source tree.
        self.assertIn("#define E63_BOOT_DEX_PIN_COUNT 10u",
                      (ROOT / "symbian/android_java_app/boot_dex_pins.h").read_text())

    def test_refuses_corrupt_and_compile_only_inputs(self):
        raw = bytearray(make_dex(["Ljava/lang/Object;"]))
        raw[-2] ^= 1  # SHA-1 and Adler32 no longer valid
        with self.assertRaisesRegex(ValueError, "checksum|signature"):
            stage.dex_class_entries(bytes(raw))
        with self.assertRaisesRegex(ValueError, "MUTF-8|descriptor"):
            stage.dex_class_entries(make_dex(["Lbad/[A;"]))
        jar = Path(self.temp.name) / "empty.jar"
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("android/app/Activity.class", b"only SDK stubs")
        with self.assertRaisesRegex(ValueError, "DEX"):
            stage.inspect(jar, ("Landroid/app/Activity;",))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(jar, "w") as z:
                z.writestr("classes.dex", make_dex(["Ljava/lang/Object;"]))
                z.writestr("classes.dex", make_dex(["Ljava/lang/Object;"]))
        with self.assertRaisesRegex(ValueError, "duplicate ZIP"):
            stage.inspect(jar, ())
        no_code = bytearray(make_dex(["Ljava/lang/Object;"]))
        struct.pack_into("<I", no_code, struct.unpack_from("<I", no_code, 100)[0] + 24, 0)
        no_code[12:32] = hashlib.sha1(no_code[32:]).digest()
        struct.pack_into("<I", no_code, 8, zlib.adler32(no_code[12:]) & 0xffffffff)
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("classes.dex", no_code)
        with self.assertRaisesRegex(ValueError, "method CODE"):
            stage.inspect(jar, ("Ljava/lang/Object;",))


if __name__ == "__main__": 
    unittest.main()
