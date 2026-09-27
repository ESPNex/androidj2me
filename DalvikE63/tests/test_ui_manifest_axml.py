"""Host-only bounds/semantics tests for Nokia's compiled-manifest reader.

Synthetic AXML covers adversarial cases; the separate test_aosp42_ui_apks uses
original AOSP signed APK AXML when excluded build/ was regenerated. Neither
suite starts an Android Activity or tests the physical E63.
"""
from __future__ import annotations

import ctypes
import hashlib
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_aosp42_native_boot import CALLBACK, FileReader

ROOT = Path(__file__).resolve().parents[1]
NO = 0xffffffff
ANDROID_URI = "http://schemas.android.com/apk/res/android"
PACKAGE = "com.example.demo"
CLASS = "Lcom/example/demo/Home;"
ACTION = "android.intent.action.MAIN"
HOME = "android.intent.category.HOME"


class Match(ctypes.Structure):
    _fields_ = [("line", ctypes.c_uint32),
                ("matching_filters", ctypes.c_uint32),
                ("is_service", ctypes.c_uint)]


class ManifestBuilder:
    def __init__(self):
        self.names: list[str] = []
        self.nodes: list[bytes] = []

    def name(self, value: str) -> int:
        if value not in self.names:
            self.names.append(value)
        return self.names.index(value)

    def node(self, kind: int, data: bytes, line: int = 1) -> None:
        self.nodes.append(struct.pack("<HHIII", kind, 16, len(data)+16,
                                      line, NO) + data)

    def namespace(self, start: bool) -> None:
        self.node(0x100 if start else 0x101,
                  struct.pack("<II", self.name("android"),
                              self.name(ANDROID_URI)))

    def attr(self, value: str, name: str, *, android: bool = True) -> bytes:
        return struct.pack("<IIIHBBI",
                           self.name(ANDROID_URI) if android else NO,
                           self.name(name), self.name(value), 8, 0, 3,
                           self.name(value))

    def enabled_false(self) -> bytes:
        return struct.pack("<IIIHBBI", self.name(ANDROID_URI),
                           self.name("enabled"), NO, 8, 0, 0x12, 0)

    def start(self, name: str, attrs: tuple[bytes, ...] = (),
              line: int = 1) -> None:
        ext = struct.pack("<IIHHHHHH", NO, self.name(name), 20, 20,
                          len(attrs), 0, 0, 0)
        self.node(0x102, ext+b"".join(attrs), line=line)

    def end(self, name: str) -> None:
        self.node(0x103, struct.pack("<II", NO, self.name(name)))

    def serialize(self) -> bytes:
        strings = bytearray()
        offsets = []
        for value in self.names:
            offsets.append(len(strings))
            strings.extend(struct.pack("<H", len(value)))
            strings.extend(value.encode("utf-16le"))
            strings.extend(b"\x00\x00")
        strings.extend(b"\x00"*((-len(strings)) % 4))
        count = len(self.names)
        pool_len = 28 + count*4 + len(strings)
        pool = struct.pack("<HHIIIIII", 1, 28, pool_len, count, 0, 0,
                           28+count*4, 0)
        pool += b"".join(struct.pack("<I", item) for item in offsets)+strings
        body = pool + b"".join(self.nodes)
        return struct.pack("<HHI", 3, 8, len(body)+8)+body


def fixture(*, split_filter: bool = False, duplicate: bool = False,
            disabled: bool = False, service: bool = False) -> bytes:
    m = ManifestBuilder()
    m.namespace(True)
    m.start("manifest", (m.attr(PACKAGE, "package", android=False),))
    m.start("application")
    component = "service" if service else "activity"
    attrs = (m.attr(".Home", "name"),) + (
        (m.enabled_false(),) if disabled else ())
    m.start(component, attrs, line=42)
    if not service:
        m.start("intent-filter")
        m.start("action", (m.attr(ACTION, "name"),))
        m.end("action")
        if not split_filter:
            m.start("category", (m.attr(HOME, "name"),))
            m.end("category")
        m.end("intent-filter")
        if split_filter:
            m.start("intent-filter")
            m.start("category", (m.attr(HOME, "name"),))
            m.end("category")
            m.end("intent-filter")
    m.end(component)
    if duplicate:
        m.start(component, (m.attr(".Home", "name"),))
        m.end(component)
    m.end("application")
    m.end("manifest")
    m.namespace(False)
    return m.serialize()


class AxmlNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "build").mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        lib = Path(cls.temp.name) / "axml_reader.so"
        subprocess.run(["gcc", "-std=c99", "-pedantic", "-Wall", "-Wextra",
                        "-Werror", "-fPIC", "-shared",
                        str(ROOT / "symbian/runtime/ui_manifest_axml.c"),
                        "-o", str(lib)], check=True)
        cls.find = ctypes.CDLL(str(lib)).e63_ui_manifest_find
        cls.find.argtypes = [CALLBACK, ctypes.c_void_p, ctypes.c_size_t,
                             ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint,
                             ctypes.c_char_p, ctypes.c_char_p,
                             ctypes.POINTER(Match)]
        cls.find.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def query(self, raw: bytes, *, package: str = PACKAGE, descriptor: str = CLASS,
              is_service: int = 0, action: str | None = ACTION,
              category: str | None = HOME) -> tuple[int, Match]:
        path = Path(self.temp.name) / "input.axml"
        path.write_bytes(raw)
        file = FileReader(path)
        try:
            output = Match(0xaaaaaaaa, 0xbbbbbbbb, 0xcccccccc)
            status = self.find(file.cb, None, len(raw), package.encode(),
                               descriptor.encode(), is_service,
                               action.encode() if action else None,
                               category.encode() if category else None,
                               ctypes.byref(output))
            self.assertLessEqual(file.max_request, 128)
            return status, output
        finally:
            file.close()

    def test_byte_identical_real_aosp_axml_fixtures_survive_build_cleanup(self):
        from tools.make_aosp42_ui_diagnostic_pkg import parse_header
        pins = parse_header()
        examples = {
            "Launcher2": ("com.android.launcher",
                          "Lcom/android/launcher2/Launcher;", 0, 71, 1),
            "Settings": ("com.android.settings",
                         "Lcom/android/settings/Settings;", 0, 76, 1),
            "PackageInstaller": ("com.android.packageinstaller",
                                 "Lcom/android/packageinstaller/PackageInstallerActivity;",
                                 0, 17, 2),
            "SystemUI": ("com.android.systemui",
                         "Lcom/android/systemui/SystemUIService;", 1, 77, 0),
        }
        for name, (pkg, descriptor, kind, line, filters) in examples.items():
            with self.subTest(name=name):
                raw = (ROOT / "tests/fixtures/aosp42_axml" /
                       (name + ".axml")).read_bytes()
                pin = pins[pkg]
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                                 (pin[14], pin[15]))
                status, out = self.query(raw, package=pkg, descriptor=descriptor,
                                         is_service=kind, action=pin[16],
                                         category=pin[17])
                self.assertEqual(status, 0)
                self.assertEqual((out.line, out.matching_filters, out.is_service),
                                 (line, filters, kind))

    def test_declared_activity_and_single_intent_filter(self):
        status, out = self.query(fixture())
        self.assertEqual(status, 0)
        self.assertEqual((out.line, out.matching_filters, out.is_service),
                         (42, 1, 0))

    def test_service_has_no_home_activity_intent(self):
        status, out = self.query(fixture(service=True), is_service=1,
                                 action=None, category=None)
        self.assertEqual(status, 0)
        self.assertEqual((out.line, out.matching_filters, out.is_service),
                         (42, 0, 1))
        self.assertEqual(self.query(fixture(service=True))[0], -3)

    def test_wrong_package_class_intent_or_cross_filter_fail_closed(self):
        for change in ({"package": "com.elsewhere"},
                       {"descriptor": "Lcom/example/demo/Fake;"},
                       {"category": "android.intent.category.LAUNCHER"}):
            with self.subTest(change=change):
                code, out = self.query(fixture(), **change)
                self.assertEqual(code, -3)
                self.assertEqual((out.line, out.matching_filters,
                                  out.is_service), (0, 0, 0))
        code, out = self.query(fixture(split_filter=True))
        self.assertEqual(code, -3, "category in a different filter must not match")
        self.assertEqual(out.matching_filters, 0)
        self.assertEqual(self.query(fixture(disabled=True))[0], -3)

    def test_duplicate_component_and_corrupt_or_truncated_chunks(self):
        self.assertEqual(self.query(fixture(duplicate=True))[0], -2)
        good = fixture()
        self.assertEqual(self.query(good[:-1])[0], -2)
        bad = bytearray(good)
        struct.pack_into("<I", bad, 8+28+4, 0xffffffff)  # URI string
        self.assertEqual(self.query(bytes(bad))[0], -2)
        utf8 = bytearray(good)
        struct.pack_into("<I", utf8, 8+16, 0x100)
        self.assertEqual(self.query(bytes(utf8))[0], -5)
        broken = bytearray(good)
        struct.pack_into("<I", broken, 4, 0xffffffff)
        self.assertEqual(self.query(bytes(broken))[0], -2)


if __name__ == "__main__":
    unittest.main()
