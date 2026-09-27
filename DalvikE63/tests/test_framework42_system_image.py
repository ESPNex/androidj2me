"""Deferred final-phase checks for C:-backed read-only /system.

Prepared during framework integration; intentionally not executed yet at the
owner's request to perform the full test suite at the END. Host GCC results
will never be mistaken for an E63 hardware or Android-framework run.
"""
from __future__ import annotations

import ctypes
import hashlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.stage_android42_runtime import inspect as inspect_runtime_archive

ROOT = Path(__file__).resolve().parents[1]


class File(ctypes.Structure):
    _fields_ = [("guest_path", ctypes.c_char_p),
                ("relative_on_c", ctypes.c_char_p),
                ("package_name", ctypes.c_char_p),
                ("bytes", ctypes.c_size_t),
                ("sha256", ctypes.POINTER(ctypes.c_uint8)),
                ("kind", ctypes.c_int)]


class HashContext(ctypes.Structure):
    _fields_ = [("state", ctypes.c_uint32 * 8),
                ("pending", ctypes.c_uint8 * 64),
                ("pending_length", ctypes.c_size_t),
                ("total_length", ctypes.c_uint64)]


class SystemImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("gcc")
        if not cc:
            raise unittest.SkipTest("native C99 toolchain required")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        lib = Path(cls.temp.name) / "system_image.so"
        subprocess.run([cc, "-std=c99", "-pedantic", "-Wall", "-Wextra", "-Werror",
                        "-fPIC", "-shared", *map(str, (
                            ROOT / "symbian/runtime/system_image.c",
                            ROOT / "symbian/runtime/vfs_mount.c",
                            ROOT / "symbian/runtime/apk_sha256.c")),
                        "-o", str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.find = cls.lib.e63_system_find
        cls.find.argtypes = [ctypes.c_char_p, ctypes.POINTER(File)]
        cls.find.restype = ctypes.c_int
        cls.app = cls.lib.e63_system_app_path
        cls.app.argtypes = [ctypes.c_char_p]
        cls.app.restype = ctypes.c_char_p
        cls.verify = cls.lib.e63_system_verify
        cls.verify.argtypes = [ctypes.POINTER(File), ctypes.c_void_p, ctypes.c_size_t]
        cls.verify.restype = ctypes.c_int
        cls.hash_init = cls.lib.e63_sha256_init
        cls.hash_init.argtypes = [ctypes.POINTER(HashContext)]
        cls.hash_update = cls.lib.e63_sha256_update
        cls.hash_update.argtypes = [ctypes.POINTER(HashContext),
                                    ctypes.c_void_p, ctypes.c_size_t]
        cls.hash_final = cls.lib.e63_sha256_final
        cls.hash_final.argtypes = [ctypes.POINTER(HashContext), ctypes.c_void_p]
        class Route(ctypes.Structure):
            _fields_ = [("kind", ctypes.c_int), ("readonly", ctypes.c_uint8),
                        ("relative", ctypes.c_char * 513)]
        cls.Route = Route
        cls.route = cls.lib.e63_route_guest_path
        cls.route.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                              ctypes.POINTER(Route)]
        cls.route.restype = ctypes.c_int
        cls.gate = Path(cls.temp.name) / "framework42_gate_probe"
        sources = [ROOT / "symbian/runtime" / name for name in (
            "dex_preflight.c", "apk_dex_loader.c", "apk_java_vm.c",
            "apk_activity_vm.c", "apk_sha256.c", "apk_java_runtime.c",
            "apk_android_bridge.c", "vfs_mount.c")]
        subprocess.run([cc, "-std=c99", "-pedantic", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "symbian/runtime"),
                        str(ROOT / "tests/framework42_gate_probe.c"),
                        *map(str, sources), "-o", str(cls.gate)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_six_pinned_apps_are_on_persistent_c_and_read_only(self):
        pkg = (ROOT / "symbian/android_java_app/e63android.pkg").read_text()
        for package, filename in (
            ("org.e63.dalvik.launcher", "Launcher.apk"),
            ("org.e63.dalvik.settings", "Settings.apk"),
            ("org.e63.dalvik.store", "Store.apk"),
            ("org.e63.dalvik.systemui", "SystemUI.apk"),
            ("org.e63.dalvik.packageinstaller", "PackageInstaller.apk"),
            ("org.e63.dalvik.files", "FileManager.apk"),
        ):
            with self.subTest(filename=filename):
                guest = f"/system/app/{filename}".encode()
                self.assertEqual(self.app(package.encode()), guest)
                item = File()
                self.assertEqual(self.find(guest, ctypes.byref(item)), 0)
                self.assertEqual(item.kind, 1)
                self.assertEqual(item.relative_on_c,
                                 f"system\\app\\{filename}".encode())
                self.assertIn(f'C:\\private\\E0B63E04\\system\\app\\{filename}', pkg)
                data = (ROOT / "apks_android" / filename).read_bytes()
                self.assertEqual(item.bytes, len(data))
                self.assertEqual(ctypes.string_at(item.sha256, 32),
                                 hashlib.sha256(data).digest())
                buf = ctypes.create_string_buffer(data)
                self.assertEqual(self.verify(ctypes.byref(item), buf, len(data)), 0)
                tampered = bytearray(data)
                tampered[-1] ^= 1
                buf = ctypes.create_string_buffer(bytes(tampered))
                self.assertEqual(self.verify(ctypes.byref(item), buf, len(data)), -3)
                route = self.Route()
                self.assertEqual(self.route(guest, 0, 1, ctypes.byref(route)), 0)
                self.assertEqual((route.kind, route.readonly), (2, 1))
                self.assertEqual(self.route(guest, 1, 1, ctypes.byref(route)), -2)

    def test_framework_candidate_pins_are_read_only_not_a_running_system(self):
        self.assertIn("#define E63_FRAMEWORK_PIN_COUNT 11u",
                      (ROOT / "symbian/android_java_app/framework_pins.h").read_text())
        boot = ("core.jar", "core-junit.jar", "bouncycastle.jar", "ext.jar",
                "framework.jar", "telephony-common.jar", "mms-common.jar",
                "android.policy.jar", "services.jar", "apache-xml.jar")
        root = ROOT / "build/staged-android42-system/framework"
        for name in (*boot, "framework-res.apk"):
            with self.subTest(name=name):
                route = self.Route()
                path = f"/system/framework/{name}".encode()
                self.assertEqual(self.route(path, 0, 1, ctypes.byref(route)), 0)
                self.assertEqual(self.route(path, 1, 1, ctypes.byref(route)), -2)
                pinned = File()
                self.assertEqual(self.find(path, ctypes.byref(pinned)), 0)
                self.assertEqual(pinned.kind, 3 if name.endswith(".apk") else 2)
                self.assertEqual(pinned.relative_on_c,
                                 f"system\\framework\\{name}".encode())
                # The checkout/build directory is intentionally ephemeral:
                # headers survive without claiming a file is on the E63.
                if (root / name).is_file():
                    data = (root / name).read_bytes()
                    self.assertEqual(pinned.bytes, len(data))
                    self.assertEqual(ctypes.string_at(pinned.sha256, 32),
                                     hashlib.sha256(data).digest())
        if (root / "framework.jar").is_file():
            pinned = File()
            self.assertEqual(self.find(b"/system/framework/framework.jar",
                                       ctypes.byref(pinned)), 0)
            data = (root / "framework.jar").read_bytes()
            self.assertEqual(self.verify(ctypes.byref(pinned),
                                         ctypes.create_string_buffer(data), len(data)), 0)
            bad = bytearray(data)
            bad[-1] ^= 1
            self.assertEqual(self.verify(ctypes.byref(pinned),
                                         ctypes.create_string_buffer(bytes(bad)),
                                         len(bad)), -3)
        for path in (b"/system/framework/../../data/secret",
                     b"/system/app/Unknown.apk", b"/system/framework/android.jar"):
            self.assertNotEqual(self.find(path, ctypes.byref(File())), 0)

    def test_strict_activity_gate_cannot_fallback_to_old_shim(self):
        subprocess.run([str(self.gate)], check=True)
        app = (ROOT / "symbian/android_java_app/e63android_app.cpp").read_text()
        self.assertIn("e63_android_activity_event_framework(", app)
        self.assertNotIn("e63_android_activity_event(", app)
        self.assertGreaterEqual(app.count("StrictActivityEvent("), 8)

    def test_sdk_stub_jar_cannot_be_staged_as_framework_runtime(self):
        jar = Path(self.temp.name) / "android.jar"
        with zipfile.ZipFile(jar, "w") as archive:
            archive.writestr("android/app/Activity.class", b"compile-only stub")
        with self.assertRaisesRegex(ValueError, "DEX"):
            inspect_runtime_archive(jar, ("Landroid/app/Activity;",))

    def test_streaming_system_hash_matches_sha256_for_all_padding_boundaries(self):
        for length in (0, 1, 55, 56, 63, 64, 65, 123, 128, 1000, 1024 * 1024):
            data = bytes(i % 251 for i in range(length))
            context = HashContext()
            result = (ctypes.c_uint8 * 32)()
            self.hash_init(ctypes.byref(context))
            for start in range(0, length, 37):
                chunk = data[start:start + 37]
                self.hash_update(ctypes.byref(context),
                                 ctypes.create_string_buffer(chunk), len(chunk))
            self.hash_final(ctypes.byref(context), result)
            self.assertEqual(bytes(result), hashlib.sha256(data).digest())


if __name__ == "__main__":
    unittest.main()
