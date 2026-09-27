"""Real AOSP UI APKs + bounded native on-disk class lookup, no Activity run.

Generated candidates are under excluded build/: SKIP if not regenerated. The
unsigned APKs and host-native C tests do not establish working Nokia UI.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import ssl
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.test_aosp42_native_boot import BootIndex, BootClass, FileReader, CALLBACK
from tools.build_aosp42_ui_apks import (
    GUEST_APKS, PACKAGES, REQUIRED_CLASSES, REQUIRED_INTENTS, UI_APPS,
)
from tests.test_ui_manifest_axml import Match
from tools.stage_android42_runtime import BOOT_HEADER, BOOT_RECORD, dex_class_entries, executable_classes

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "build/staged-android42-system"
PIN = ROOT / "symbian/android_java_app/ui_apk_pins.h"


class UiDexSlice(ctypes.Structure):
    _fields_ = [("read_at", ctypes.c_void_p), ("context", ctypes.c_void_p),
                ("archive_bytes", ctypes.c_uint32),
                ("dex_offset", ctypes.c_uint32), ("dex_bytes", ctypes.c_uint32),
                ("manifest_offset", ctypes.c_uint32),
                ("manifest_compressed_bytes", ctypes.c_uint32),
                ("resources_offset", ctypes.c_uint32),
                ("resources_compressed_bytes", ctypes.c_uint32),
                ("manifest_compression", ctypes.c_uint16),
                ("resources_compression", ctypes.c_uint16)]


class SystemFile(ctypes.Structure):
    _fields_ = [("guest_path", ctypes.c_char_p),
                ("relative_on_c", ctypes.c_char_p),
                ("package_name", ctypes.c_char_p),
                ("bytes", ctypes.c_size_t),
                ("sha256", ctypes.POINTER(ctypes.c_uint8)),
                ("kind", ctypes.c_int)]


class Route(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_int), ("readonly", ctypes.c_uint8),
                ("relative", ctypes.c_char * 513)]


class Aosp42UiApkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = STAGE / "ui-app/candidate-ui.json"
        if not path.is_file() or not (STAGE / "ui-index/Settings.idx").is_file():
            raise unittest.SkipTest("excluded build/ lacks staged AOSP UI APKs and index")
        if not shutil.which("gcc"):
            raise unittest.SkipTest("host C99 compiler absent")
        cls.report = json.loads(path.read_text())
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        so = Path(cls.temp.name) / "real_ui_archive.so"
        subprocess.run(["gcc", "-std=c99", "-pedantic", "-Wall", "-Wextra",
                        "-Werror", "-fPIC", "-shared",
                        *map(str, [ROOT / "symbian/runtime" / name for name in
                                   ("ui_apk_archive.c", "ui_manifest_axml.c",
                                    "boot_classpath.c", "boot_method.c",
                                    "system_image.c",
                                    "vfs_mount.c", "apk_sha256.c")]),
                        "-o", str(so)], check=True)
        cls.lib = ctypes.CDLL(str(so))
        cls.open = cls.lib.e63_ui_apk_open
        cls.open.argtypes = [ctypes.POINTER(UiDexSlice), CALLBACK,
                             ctypes.c_void_p, ctypes.c_size_t]
        cls.open.restype = ctypes.c_int
        cls.idx_open = cls.lib.e63_boot_index_open
        cls.idx_open.argtypes = [ctypes.POINTER(BootIndex), CALLBACK,
                                 ctypes.c_void_p, ctypes.c_size_t]
        cls.idx_open.restype = ctypes.c_int
        cls.lookup = cls.lib.e63_boot_find_class
        cls.lookup.argtypes = [ctypes.POINTER(BootIndex), ctypes.c_char_p,
                               ctypes.POINTER(BootClass)]
        cls.lookup.restype = ctypes.c_int
        cls.confirm = cls.lib.e63_boot_confirm_class
        cls.confirm.argtypes = [ctypes.POINTER(BootClass), ctypes.c_char_p,
                                CALLBACK, ctypes.c_void_p, ctypes.c_size_t]
        cls.confirm.restype = ctypes.c_int
        cls.ui_read = CALLBACK(("e63_ui_dex_read_at", cls.lib))
        cls.axml_find = cls.lib.e63_ui_manifest_find
        cls.axml_find.argtypes = [CALLBACK, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint,
                                  ctypes.c_char_p, ctypes.c_char_p,
                                  ctypes.POINTER(Match)]
        cls.axml_find.restype = ctypes.c_int
        cls.call_static = cls.lib.e63_boot_call_static_int
        cls.call_static.argtypes = [ctypes.POINTER(BootClass), ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32),
            ctypes.c_uint, CALLBACK, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int32)]
        cls.call_static.restype = ctypes.c_int
        cls.find = cls.lib.e63_system_find
        cls.find.argtypes = [ctypes.c_char_p, ctypes.POINTER(SystemFile)]
        cls.find.restype = ctypes.c_int
        cls.path = cls.lib.e63_system_ui_app_path
        cls.path.argtypes = [ctypes.c_char_p]
        cls.path.restype = ctypes.c_char_p
        cls.legacy_path = cls.lib.e63_system_app_path
        cls.legacy_path.argtypes = [ctypes.c_char_p]
        cls.legacy_path.restype = ctypes.c_char_p
        cls.route = cls.lib.e63_route_guest_path
        cls.route.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                              ctypes.POINTER(Route)]
        cls.route.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_four_real_java_ui_apks_resources_code_and_manifest(self):
        self.assertEqual(self.report["tag"], "android-4.2.2_r1.2")
        self.assertEqual(set(self.report["ui_apks"]), set(UI_APPS))
        self.assertEqual(self.report["signed"], True)
        self.assertEqual(self.report["production_trust"], False)
        self.assertEqual(self.report["signature_scheme"],
                         "Android v1 SHA1withRSA, AOSP public development keys")
        self.assertEqual(self.report["android_runtime_ready"], False)
        self.assertEqual(self.report["activity_running_on_nokia"], False)
        self.assertIn("#define E63_UI_APK_PIN_COUNT 4u", PIN.read_text())
        for name in UI_APPS:
            with self.subTest(name=name):
                record = self.report["ui_apks"][name]
                apk = STAGE / "ui-app" / GUEST_APKS[name]
                raw = apk.read_bytes()
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                                 (record["apk_bytes"], record["apk_sha256"]))
                self.assertEqual(record["package_name"], PACKAGES[name])
                self.assertEqual(record["required_executable"],
                                 list(REQUIRED_CLASSES[name]))
                with zipfile.ZipFile(apk) as archive:
                    self.assertIsNone(archive.testzip())
                    contents = archive.namelist()
                    self.assertEqual(len(contents), len(set(contents)))
                    self.assertIn("AndroidManifest.xml", contents)
                    self.assertIn("resources.arsc", contents)
                    dex = archive.read("classes.dex")
                    self.assertEqual(archive.getinfo("classes.dex").compress_type, 0)
                    self.assertEqual((len(dex), hashlib.sha256(dex).hexdigest()),
                                     (record["dex_bytes"], record["dex_sha256"]))
                    if name == "SystemUI":
                        self.assertIn("res/raw/carousel.bc", contents)
                    classes = dex_class_entries(dex)
                    self.assertEqual(len(classes), record["dex_classes"])
                    self.assertTrue(set(REQUIRED_CLASSES[name]).issubset(
                        executable_classes(dex, classes)))
                    self.assertTrue({"META-INF/MANIFEST.MF", "META-INF/CERT.SF",
                                     "META-INF/CERT.RSA"}.issubset(contents))
                    key = "shared" if name == "Launcher2" else "platform"
                    self.assertEqual(record["aosp_development_certificate"], key)
                    block = archive.read("META-INF/CERT.RSA")
                    decoded = subprocess.run(["openssl", "pkcs7", "-inform", "DER",
                         "-print_certs"], input=block, capture_output=True,
                        check=True).stdout.decode("ascii")
                    certs = re.findall(
                        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
                        decoded, re.S)
                    self.assertEqual(len(certs), 1)
                    der = ssl.PEM_cert_to_DER_cert(certs[0])
                    source = ROOT / "build/aosp42-runtime-dependencies/build/"
                    source /= "target/product/security/" + key + ".x509.pem"
                    self.assertEqual(der, ssl.PEM_cert_to_DER_cert(source.read_text()))
                    self.assertEqual(hashlib.sha256(der).hexdigest(),
                                     record["certificate_sha256"])
                index = (STAGE / "ui-index" / (name + ".idx")).read_bytes()
                self.assertEqual(len(index), BOOT_HEADER.size+len(classes)*BOOT_RECORD.size)
                self.assertEqual(index[:8], b"E63BOOT2")
                self.assertEqual((len(index), hashlib.sha256(index).hexdigest()),
                                 (record["index_bytes"], record["index_sha256"]))
                self.assertEqual(struct.unpack_from("<I", index, 16)[0], len(classes))
                if (ROOT / "build/aosp42-host-tools/aapt").is_file():
                    tree = subprocess.run([str(ROOT / "build/aosp42-host-tools/aapt"),
                        "dump", "xmltree", str(apk), "AndroidManifest.xml"],
                        capture_output=True, text=True, check=True).stdout
                    self.assertIn('package="' + PACKAGES[name] + '"', tree)
                    if name == "Launcher2":
                        self.assertIn('="com.android.launcher2.Launcher"', tree)
                        self.assertIn('="android.intent.category.HOME"', tree)
                    elif name == "Settings":
                        self.assertIn('="android.settings.SETTINGS"', tree)
                    elif name == "PackageInstaller":
                        self.assertIn('=".PackageInstallerActivity"', tree)
                    else:
                        self.assertIn('E: service', tree)
                        self.assertIn('="SystemUIService"', tree)
                self.assertIn("C:\\private\\E0B63E04\\system\\app\\" +
                              GUEST_APKS[name],
                              (STAGE / "ui-app/ui-app.pkg-fragment").read_text())

    def test_real_launcher2_ui_helper_executes_dex_not_a_host_substitute(self):
        record = self.report["ui_apks"]["Launcher2"]
        path = STAGE / "ui-app/Launcher2.apk"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         record["apk_sha256"])
        apk = FileReader(path)
        index = FileReader(STAGE / "ui-index/Launcher2.idx")
        try:
            raw = UiDexSlice()
            self.assertEqual(self.open(ctypes.byref(raw), apk.cb, None,
                                       apk.size), 0)
            boot = BootIndex()
            self.assertEqual(self.idx_open(ctypes.byref(boot), index.cb, None,
                                           index.size), 0)
            where = BootClass()
            cls = b"Lcom/android/launcher2/Utilities;"
            self.assertEqual(self.lookup(ctypes.byref(boot), cls,
                                         ctypes.byref(where)), 0)
            self.assertEqual(where.dex_slot, 0)
            for n, expected in ((1, 1), (2, 2), (3, 4), (4, 4),
                                (5, 8), (9, 16), (16, 16), (33, 64)):
                with self.subTest(n=n):
                    param, value = ctypes.c_int32(n), ctypes.c_int32(0)
                    result = self.call_static(
                        ctypes.byref(where), cls, b"roundToPow2", b"(I)I",
                        ctypes.byref(param), 1, self.ui_read,
                        ctypes.byref(raw), raw.dex_bytes, ctypes.byref(value))
                    self.assertEqual(result, 0)
                    self.assertEqual(value.value, expected)
            value = ctypes.c_int32(123)
            param = ctypes.c_int32(33)
            self.assertEqual(self.call_static(
                ctypes.byref(where), cls, b"notAnAospMethod", b"(I)I",
                ctypes.byref(param), 1, self.ui_read,
                ctypes.byref(raw), raw.dex_bytes, ctypes.byref(value)), -3)
            self.assertEqual(value.value, 0)
            self.assertLessEqual(apk.max_request, 268)
            self.assertLess(apk.total_read, raw.dex_bytes + 500_000)
        finally:
            apk.close()
            index.close()
        source = (ROOT / "symbian/android_java_app/e63_ui_store.cpp").read_text()
        self.assertIn("E63UiStore::CallStaticInt", source)
        self.assertIn("e63_boot_call_static_int(", source)

    def test_native_axml_reader_matches_real_signed_aosp_components(self):
        for name in UI_APPS:
            with self.subTest(name=name):
                item = self.report["ui_apks"][name]
                axml_path = STAGE / "ui-manifest" / (name + ".axml")
                raw = axml_path.read_bytes()
                with zipfile.ZipFile(STAGE / "ui-app" / GUEST_APKS[name]) as z:
                    self.assertEqual(raw, z.read("AndroidManifest.xml"))
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                                 (item["manifest_bytes"], item["manifest_sha256"]))
                self.assertEqual(item["manifest_guest_path"],
                                 "/data/e63-uimanifest/" + name + ".axml")
                action, category = REQUIRED_INTENTS[name]
                self.assertEqual((item["intent_action"], item["intent_category"]),
                                 (action, category))
                reader = FileReader(axml_path)
                try:
                    result = Match()
                    def find(package=PACKAGES[name], descriptor=REQUIRED_CLASSES[name][0],
                             kind=int(name == "SystemUI"), act=action, cat=category):
                        return self.axml_find(
                            reader.cb, None, reader.size, package.encode(),
                            descriptor.encode(), kind,
                            act.encode() if act else None,
                            cat.encode() if cat else None,
                            ctypes.byref(result))
                    self.assertEqual(find(), 0)
                    self.assertGreater(result.line, 0)
                    self.assertEqual(result.is_service, int(name == "SystemUI"))
                    if action:
                        self.assertGreater(result.matching_filters, 0)
                    else:
                        self.assertEqual(result.matching_filters, 0)
                    self.assertEqual(find(descriptor="Lcom/example/Fake;"), -3)
                    if action:
                        self.assertEqual(find(cat="android.intent.category.FAKE"), -3)
                    self.assertLessEqual(reader.max_request, 128)
                    self.assertLess(reader.total_read, 600_000)
                finally:
                    reader.close()
        source = (ROOT / "symbian/android_java_app/e63_ui_store.cpp").read_text()
        self.assertIn("OpenManifest(aFs,*pin,axml)", source)
        self.assertIn("e63_ui_manifest_find(", source)
        self.assertIn("ui_manifest_axml.c",
                      (ROOT / "symbian/android_java_app/e63android.mmp").read_text())

    def test_native_random_access_to_real_activity_and_service_class_defs(self):
        for name in UI_APPS:
            with self.subTest(name=name):
                record = self.report["ui_apks"][name]
                apk = FileReader(STAGE / "ui-app" / GUEST_APKS[name])
                index = FileReader(STAGE / "ui-index" / (name + ".idx"))
                try:
                    raw = UiDexSlice()
                    self.assertEqual(self.open(ctypes.byref(raw), apk.cb,
                                               None, apk.size), 0)
                    self.assertEqual(raw.dex_bytes, record["dex_bytes"])
                    self.assertGreater(raw.manifest_compressed_bytes, 100)
                    self.assertGreater(raw.resources_compressed_bytes, 100)
                    boot = BootIndex()
                    self.assertEqual(self.idx_open(ctypes.byref(boot),index.cb,
                                                  None,index.size),0)
                    where = BootClass()
                    descriptor = REQUIRED_CLASSES[name][0].encode()
                    self.assertEqual(self.lookup(ctypes.byref(boot),descriptor,
                                                 ctypes.byref(where)),0)
                    self.assertEqual(where.dex_slot,0)
                    self.assertEqual(self.confirm(ctypes.byref(where),descriptor,
                                                  self.ui_read,ctypes.byref(raw),
                                                  raw.dex_bytes),0)
                    self.assertLessEqual(apk.max_request, 268)
                    self.assertLessEqual(index.max_request, 268)
                    self.assertLess(apk.total_read, raw.dex_bytes + 300_000)
                    self.assertLess(index.total_read, 64_000)
                    wrong = BootClass(0,where.class_def_index + 1)
                    self.assertEqual(self.confirm(ctypes.byref(wrong),descriptor,
                                                  self.ui_read,ctypes.byref(raw),
                                                  raw.dex_bytes),-2)
                finally:
                    apk.close()
                    index.close()

    def test_legacy_apks_unchanged_and_candidates_pinned_readonly(self):
        self.assertEqual(self.legacy_path(b"org.e63.dalvik.systemui"),
                         b"/system/app/SystemUI.apk")
        self.assertIsNone(self.path(b"org.e63.dalvik.systemui"))
        self.assertIsNone(self.legacy_path(b"com.android.systemui"))
        for name in UI_APPS:
            with self.subTest(name=name):
                record = self.report["ui_apks"][name]
                guest = record["guest_path"].encode()
                self.assertEqual(self.path(PACKAGES[name].encode()), guest)
                item = SystemFile()
                self.assertEqual(self.find(guest,ctypes.byref(item)),0)
                self.assertEqual(item.package_name, PACKAGES[name].encode())
                self.assertEqual(item.bytes,record["apk_bytes"])
                self.assertEqual(item.kind,1)
                self.assertEqual(ctypes.string_at(item.sha256,32),
                                 bytes.fromhex(record["apk_sha256"]))
                route = Route()
                self.assertEqual(self.route(guest,0,1,ctypes.byref(route)),0)
                self.assertEqual((route.kind,route.readonly),(2,1))
                self.assertEqual(self.route(guest,1,1,ctypes.byref(route)),-2)
                index = record["index_guest_path"].encode()
                self.assertEqual(self.route(index,1,1,ctypes.byref(route)),-2)
                self.assertEqual(self.route(index,1,3,ctypes.byref(route)),-2)
        self.assertNotEqual(self.find(b"/system/app/Unknown.apk",
                                      ctypes.byref(SystemFile())),0)

    def test_native_zip_rejects_truncated_and_changed_dex_without_loading_whole_apk(self):
        apk = STAGE / "ui-app/AOSP42PackageInstaller.apk"
        data = apk.read_bytes()
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            path = Path(tmp) / "bad.apk"
            for kind, changed, status in (
                ("truncated",data[:-11],-3),
                ("bad crc",self._alter_stored_dex(data),-5),
            ):
                with self.subTest(kind=kind):
                    path.write_bytes(changed)
                    file = FileReader(path)
                    try:
                        found = UiDexSlice()
                        self.assertEqual(self.open(ctypes.byref(found),file.cb,
                                                   None,file.size), status)
                        self.assertEqual(found.dex_bytes, 0)
                    finally:
                        file.close()
            path.write_bytes(data)
            with zipfile.ZipFile(path,"a") as archive:
                # Independently mutable file, never alters staged AOSP APK.
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore",UserWarning)
                    archive.writestr("classes.dex",b"not genuine dex",
                                     compress_type=zipfile.ZIP_STORED)
            file = FileReader(path)
            try:
                self.assertEqual(self.open(ctypes.byref(UiDexSlice()),file.cb,
                                           None,file.size),-2)
            finally:
                file.close()

    @staticmethod
    def _alter_stored_dex(raw: bytes) -> bytes:
        with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
            info = archive.getinfo("classes.dex")
            local = info.header_offset
            name = struct.unpack_from("<H",raw,local+26)[0]
            extra = struct.unpack_from("<H",raw,local+28)[0]
            at = local+30+name+extra
        changed=bytearray(raw)
        changed[at+100] ^= 1
        return bytes(changed)


if __name__ == "__main__":
    unittest.main()
