"""PC-only gates for REAL AOSP 4.2.2 bytecode read from pinned on-disk DEX.

This is not a Nokia E63 execution, complete Dalvik VM, Activity or Android
boot test. If excluded build/ is absent in a later workspace snapshot, the
real-artifact cases SKIP rather than substituting synthetic Android code.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.stage_android42_runtime import BOOT_ORDER, FILES, dex_class_entries, inspect

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / "build/staged-android42-system"
INDEX = STAGED / "bootdex/boot-classes.idx"
DEX = STAGED / "bootdex/framework.jar.classes.dex"


class BootIndex(ctypes.Structure):
    _fields_ = [("context", ctypes.c_void_p), ("read_at", ctypes.c_void_p),
                ("class_count", ctypes.c_uint32), ("total_bytes", ctypes.c_uint32)]


class BootClass(ctypes.Structure):
    _fields_ = [("dex_slot", ctypes.c_uint32),
                ("class_def_index", ctypes.c_uint32)]


CALLBACK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                            ctypes.c_void_p, ctypes.c_size_t)


class FileReader:
    def __init__(self, path: Path):
        self.file = path.open("rb")
        self.size = os.fstat(self.file.fileno()).st_size
        self.max_request = self.total_read = 0
        self.cb = CALLBACK(self.read)

    def read(self, context, offset, destination, length):
        self.max_request = max(self.max_request, length)
        self.total_read += length
        data = os.pread(self.file.fileno(), length, offset)
        if len(data) != length:
            return 0
        ctypes.memmove(destination, data, length)
        return 1

    def close(self):
        self.file.close()


class AospRealBootMethodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not INDEX.is_file() or not DEX.is_file():
            raise unittest.SkipTest("excluded build/ lacks staged, local-built AOSP JARs")
        gcc = shutil.which("gcc")
        if not gcc:
            raise unittest.SkipTest("host gcc unavailable")
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        lib = Path(cls.temp.name) / "native_boot_method.so"
        subprocess.run([gcc, "-std=c99", "-pedantic", "-Wall", "-Wextra",
                        "-Werror", "-fPIC", "-shared",
                        str(ROOT / "symbian/runtime/boot_classpath.c"),
                        str(ROOT / "symbian/runtime/boot_method.c"),
                        "-o", str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.lib.e63_boot_index_open.argtypes = [ctypes.POINTER(BootIndex),
                                                CALLBACK, ctypes.c_void_p,
                                                ctypes.c_size_t]
        cls.lib.e63_boot_index_open.restype = ctypes.c_int
        cls.lib.e63_boot_find_class.argtypes = [ctypes.POINTER(BootIndex),
                                                ctypes.c_char_p,
                                                ctypes.POINTER(BootClass)]
        cls.lib.e63_boot_find_class.restype = ctypes.c_int
        cls.lib.e63_boot_call_static_int.argtypes = [
            ctypes.POINTER(BootClass), ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32), ctypes.c_uint,
            CALLBACK, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int32)]
        cls.lib.e63_boot_call_static_int.restype = ctypes.c_int
        cls.manifest = json.loads((STAGED / "candidate-runtime.json").read_text())
        for name in ("framework.jar", "framework.jar.classes.dex",
                     "boot-classes.idx"):
            metadata = (cls.manifest["files"] if name == "framework.jar" else
                        cls.manifest["bootdex"])[name]
            path = ((STAGED / "framework") if name == "framework.jar" else
                    (STAGED / "bootdex")) / name
            if (path.stat().st_size != metadata["bytes"] or
                    hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]):
                raise AssertionError(f"staged AOSP candidate SHA mismatch: {path}")
        cls.index = FileReader(INDEX)
        cls.dex = FileReader(DEX)
        cls.view = BootIndex()
        rc = cls.lib.e63_boot_index_open(ctypes.byref(cls.view), cls.index.cb,
                                         None, cls.index.size)
        if rc != 0:
            raise AssertionError("AOSP boot index could not be opened")
        cls.color = BootClass()
        rc = cls.lib.e63_boot_find_class(ctypes.byref(cls.view),
                 b"Landroid/graphics/Color;", ctypes.byref(cls.color))
        if rc != 0 or cls.color.dex_slot != 4:
            raise AssertionError("real Color DEX class not in AOSP framework slot")
        cls.math = BootClass()
        rc = cls.lib.e63_boot_find_class(ctypes.byref(cls.view),
                 b"Landroid/util/MathUtils;", ctypes.byref(cls.math))
        if rc != 0 or cls.math.dex_slot != 4:
            raise AssertionError("real MathUtils DEX class not in AOSP framework slot")

    @classmethod
    def tearDownClass(cls):
        cls.index.close()
        cls.dex.close()
        cls.temp.cleanup()

    @classmethod
    def call(cls, name: str, proto: bytes, arguments: list[int],
             location: BootClass | None = None,
             descriptor: bytes = b"Landroid/graphics/Color;") -> tuple[int, int]:
        arr = (ctypes.c_int32 * len(arguments))(*arguments)
        result = ctypes.c_int32(0x77777777)
        status = cls.lib.e63_boot_call_static_int(
            ctypes.byref(location or cls.color), descriptor, name.encode(),
            proto, arr, len(arguments), cls.dex.cb, None, cls.dex.size,
            ctypes.byref(result))
        return status, result.value

    def test_native_execution_from_on_disk_aosp_framework_bytes(self):
        samples = (
            ("argb", b"(IIII)I", [255, 31, 96, 224], 0xff1f60e0),
            ("rgb", b"(III)I", [31, 96, 224], 0xff1f60e0),
            ("alpha", b"(I)I", [0xff1f60e0], 255),
            ("red", b"(I)I", [0xff1f60e0], 31),
            ("green", b"(I)I", [0xff1f60e0], 96),
            ("blue", b"(I)I", [0xff1f60e0], 224),
        )
        for name, prototype, args, expected in samples:
            with self.subTest(name=name):
                status, result = self.call(name, prototype, args)
                self.assertEqual(status, 0)
                self.assertEqual(result & 0xffffffff, expected)
        self.assertEqual(self.view.class_count,
                         self.manifest["bootclasspath_unique_classes"])
        self.assertGreaterEqual(self.view.class_count, 11_000)
        self.assertLessEqual(self.dex.max_request, 268)
        self.assertLess(self.dex.total_read, 64 * 1024)
        self.assertLessEqual(self.index.max_request, 268)
        self.assertGreater(self.dex.size, 8 * 1024 * 1024)

    def test_real_aosp_branch_bytecode_from_pinned_framework(self):
        for amount, low, high, expected in (
            (-99, 0, 10, 0), (5, 0, 10, 5), (99, 0, 10, 10),
            (-1, -5, 4, -1), (0, 0, 0, 0)):
            with self.subTest(amount=amount):
                result = self.call("constrain", b"(III)I", [amount, low, high],
                                   self.math, b"Landroid/util/MathUtils;")
                self.assertEqual(result, (0, expected))

    def test_cannot_forge_owner_or_call_a_different_prototype(self):
        status, result = self.call("argb", b"(I)I", [0])
        self.assertEqual((status, result), (-3, 0))
        status, result = self.call("argb", b"(Ljava/lang/String;)I", [0])
        self.assertEqual((status, result), (-1, 0))
        wrong = BootClass(4, self.color.class_def_index + 1)
        status, result = self.call("argb", b"(IIII)I",
                                   [255, 31, 96, 224], wrong)
        self.assertEqual((status, result), (-2, 0))
        status, result = self.call("argb", b"(IIII)I",
                                   [255, 31, 96, 224],
                                   descriptor=b"Landroid/app/Activity;")
        self.assertEqual((status, result), (-2, 0))
        self.assertLessEqual(self.dex.max_request, 268)

    def test_ten_jar_index_and_aosp_resources_are_real_and_in_order(self):
        self.assertEqual(len(BOOT_ORDER), 10)
        self.assertEqual(len(FILES), 11)
        # Derive the canonical count from CURRENT clean-build DEX class_def
        # rows; an earlier incremental host build reported one extra class.
        # Do not freeze that accidental 11,730 into a runtime correctness test.
        actual_count = 0
        for name in BOOT_ORDER:
            with zipfile.ZipFile(STAGED / "framework" / name) as jar:
                actual_count += len(dex_class_entries(jar.read("classes.dex")))
        self.assertGreaterEqual(actual_count, 11_000)
        self.assertEqual(self.manifest["bootclasspath_unique_classes"], actual_count)
        self.assertEqual(self.view.class_count, actual_count)
        self.assertEqual(self.manifest["shadowed_class_definitions"], 0)
        for name, needed, kind in FILES:
            with self.subTest(name=name):
                path = STAGED / "framework" / name
                length, sha = inspect(path, needed)
                self.assertEqual((length, sha),
                                 (self.manifest["files"][name]["bytes"],
                                  self.manifest["files"][name]["sha256"]))
                with zipfile.ZipFile(path) as archive:
                    self.assertIsNone(archive.testzip())
                    if kind == 2:
                        dex = archive.read("classes.dex")
                        self.assertEqual(dex[:8], b"dex\n035\x00")
                        self.assertEqual(hashlib.sha256(dex).hexdigest(),
                                         self.manifest["bootdex"][
                                             name + ".classes.dex"]["sha256"])
        with zipfile.ZipFile(STAGED / "framework/framework-res.apk") as archive:
            self.assertIn("assets/webkit/incognito_mode_start_page.html",
                          archive.namelist())
        with zipfile.ZipFile(STAGED / "framework/framework.jar") as archive:
            self.assertIn("preloaded-classes", archive.namelist())
        with zipfile.ZipFile(STAGED / "framework/ext.jar") as archive:
            self.assertIn("com/android/i18n/phonenumbers/data/PhoneNumberMetadataProto_IT",
                          archive.namelist())
        with zipfile.ZipFile(STAGED / "framework/apache-xml.jar") as archive:
            self.assertIn("org/apache/xml/serializer/Encodings.properties",
                          archive.namelist())


if __name__ == "__main__":
    unittest.main()
