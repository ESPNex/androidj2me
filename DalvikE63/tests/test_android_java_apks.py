"""True javac/D8 per-app Android Activities plus two bounded DEX interpreters.

AAPT/Java compilation and PC VM execution do NOT claim Android/E63 hardware.
The legacy MIDlet/SISX remain independently tested by the earlier test files.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import warnings
import zipfile
import zlib
from pathlib import Path

from android_shell import AndroidShell
from dalvik.apk_program import APKProgramError, load_apk
from dalvik.axml_reader import inspect
from dalvik.assembler import HOST
from dalvik.dex_j2me import J2MEDex, J2MEDexError
from dalvik.host import HostError
from dalvik.ids import FILES, LAUNCHER, SETTINGS, STORE, SYSTEMUI, INSTALLER
from dalvik.vm import VM, VMError
from tools.build_android_java_apks import APPS, compile_java, digest
from tools.get_android_api17 import check as check_android
from tools.get_d8 import DEST as D8, check as check_d8
from tools.make_android_java_images import pack_images
from tools.verify_symbian_sis import extract as extract_sis, platform_ids

ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / "apks_android"


class AndroidJavaAPKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.base = Path(cls.tmp.name)
        cls.catalog = json.loads((NEW / "catalog.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def shell(self, name): return AndroidShell(state=self.base / name)

    def test_six_installable_activity_apks_with_distinct_java_dex(self):
        self.assertEqual(len(self.catalog), 6)
        seen = set()
        for row in self.catalog:
            path = NEW / row["name"]
            dex = load_apk(path, expected=row)
            self.assertNotIn(row["dex_sha256"], seen)
            seen.add(row["dex_sha256"])
            self.assertEqual(dex.package, row["package"])
            self.assertIn(dex.class_desc + "->onStart()V", dex.codes)
            self.assertIn(dex.class_desc + "->onSelect(I)V", dex.codes)
            self.assertIn(dex.class_desc + "->onCommand(ILjava/lang/String;Ljava/lang/String;)V",
                          dex.codes)
            self.assertIn("Lorg/e63/dalvik/runtime/Host;", dex.classes)
            self.assertNotIn("Landroid/j2me/edition/E63Canvas;", dex.classes)
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                self.assertIn("resources.arsc", names)
                self.assertIn("res/drawable/icon.png", names)
                self.assertNotIn("classes2.dex", names)
                info = inspect(archive.read("AndroidManifest.xml"))
                self.assertEqual((info.main_class, info.min_sdk, info.target_sdk),
                                 (row["entry"], 17, 17))
                self.assertEqual(info.permissions,
                    ("android.permission.READ_EXTERNAL_STORAGE",
                     "android.permission.WRITE_EXTERNAL_STORAGE") if row["package"] in
                    (FILES, INSTALLER) else ())
                if shutil.which("jarsigner"):
                    r = subprocess.run(["jarsigner", "-verify", str(path)],
                                       capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn("jar verified.", r.stdout)
                if shutil.which("aapt"):
                    r = subprocess.run(["aapt", "dump", "badging", str(path)],
                                       capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn("application-label:'", r.stdout)
                    self.assertIn("launchable-activity: name='"+row["entry"]+"'",r.stdout)
        # Preserve the previously hardware-tested branch, never silently
        # overwrite its SISX/D8 guest entry when changing Android APKs.
        with zipfile.ZipFile(ROOT / "apks/Launcher.apk") as old:
            self.assertIn("Landroid/j2me/edition/E63Canvas;",
                          J2MEDex(old.read("classes.dex")).classes)

    def test_per_apk_assets_and_bundled_installer_are_real_not_everything(self):
        expected = {
            "Launcher.apk": {"wall.png"},
            "Settings.apk": {"settings.png"},
            "Store.apk": {"store.png", "banner.png"},
            "SystemUI.apk": {"warning.png", "lowbattery.wav"},
            "FileManager.apk": {"files.png", "lowbattery.wav", "music.wav"},
            "PackageInstaller.apk": {"files.png", "packages/FileManager.apk"},
        }
        for name, wanted in expected.items():
            with self.subTest(apk=name), zipfile.ZipFile(NEW / name) as z:
                owned = set(json.loads(z.read("assets/e63-assets.json")))
                self.assertEqual(owned, wanted)
                self.assertEqual({f"assets/{x}" for x in wanted},
                    {n for n in z.namelist() if n.startswith("assets/") and
                     n != "assets/e63-assets.json"})
                for asset in wanted:
                    if asset.endswith(".wav"):
                        self.assertEqual(z.getinfo("assets/" + asset).compress_type,
                                         zipfile.ZIP_STORED)
        with zipfile.ZipFile(NEW / "PackageInstaller.apk") as installer:
            bundled = installer.read("assets/packages/FileManager.apk")
        self.assertEqual(bundled, (NEW / "FileManager.apk").read_bytes())

    def test_actual_java_dex_drives_settings_store_install_files_error(self):
        sh = self.shell("complete")
        self.assertEqual(sh.active, LAUNCHER)
        self.assertIn("[own APK asset] wall.png", sh.text())
        self.assertNotIn("  2. File Manager", sh.text())
        sh.select(1)
        self.assertEqual(sh.active, SETTINGS)
        self.assertIn("Wi-Fi preview: OFF", sh.text())
        sh.select(0)
        self.assertIn("Wi-Fi preview: ON", sh.text())
        sh.home(); sh.select(0)
        self.assertEqual(sh.active, STORE)
        sh.command("search", "FILE MAN")
        self.assertIn("1 result found", sh.text())
        sh.command("search", "maps")
        self.assertIn("No results", sh.text())
        sh.select(0)
        self.assertEqual(sh.active, INSTALLER)
        self.assertIn("INSTALL", sh.text())
        sh.select(0)
        self.assertIn("OPEN", sh.text())
        self.assertTrue(sh.vfs.installed(FILES))
        sh.select(0)
        self.assertEqual(sh.active, FILES)
        imported = sh.import_root / "notes.txt"
        imported.write_text("data", encoding="utf-8")
        sh.command("mkdir", "/sdcard/DCIM/Trips")
        sh.command("touch", "/sdcard/DCIM/Trips/empty.txt")
        sh.command("rename", "/sdcard/DCIM/Trips/empty.txt",
                   "/sdcard/DCIM/Trips/new.txt")
        sh.command("delete", "/sdcard/DCIM/Trips/new.txt")
        sh.command("import", "notes.txt", "/sdcard/Download/notes.txt")
        self.assertEqual((sh.vfs.media / "Download/notes.txt").read_text(), "data")
        sh.command("wav", "/sdcard/Music/music.wav")
        self.assertIn("WAV OK", sh.text())
        sh.select(0)
        self.assertEqual(sh.active, SYSTEMUI)
        self.assertIn("[SIMULATED DIALOG]", sh.text())
        sh.select(1)
        self.assertIn("WAV OK", sh.text())
        sh.home()
        self.assertIn("  2. File Manager", sh.text())

    def test_assets_are_restricted_to_the_owning_signed_apk(self):
        sh = self.shell("scope")
        sh.host.current = LAUNCHER
        with self.assertRaises(HostError):
            sh.host.call(HOST + "->image(Ljava/lang/String;)V", ("warning.png",))
        sh.host.call(HOST + "->image(Ljava/lang/String;)V", ("wall.png",))
        self.assertIn(("image", "wall.png"), sh.host.events)
        sh.host.current = SETTINGS
        with self.assertRaises(HostError):
            sh.host.call(HOST + "->image(Ljava/lang/String;)V", ("wall.png",))

    def test_java_source_rebuild_changes_the_dex_and_is_reproducible(self):
        for row in self.catalog:
            for filename, expected in row["java_sources"].items():
                self.assertEqual(digest((ROOT / filename).read_bytes()), expected)
        if not (check_android() and check_d8(D8) and shutil.which("javac")):
            self.skipTest("API-17 binary stubs, pinned D8 and javac needed to recompile")
        settings = next(a for a in APPS if a.slug == "settings")
        dex_bytes = compile_java(settings)
        row = next(r for r in self.catalog if r["package"] == SETTINGS)
        self.assertEqual(digest(dex_bytes), row["dex_sha256"])

    def test_mutating_compiled_java_literal_changes_vm_output(self):
        base = load_apk(NEW / "Settings.apk")
        raw = bytearray(base.blob)
        self.assertEqual(raw.count(b"Settings\x00"), 1)
        offset = raw.index(b"Settings\x00")
        raw[offset:offset+8] = b"SettinGs"
        raw[12:32] = hashlib.sha1(raw[32:]).digest()
        struct.pack_into("<I", raw, 8, zlib.adler32(raw[12:]) & 0xffffffff)
        j = J2MEDex(bytes(raw))
        updated = dataclasses.replace(base, blob=bytes(raw), strings=j.strings,
            codes={ref: j.code_for(ref) for ref in base.codes})
        sh = self.shell("mutate")
        sh._vm(SETTINGS)  # register Settings' verified per-APK asset allowlist
        sh.host.current = SETTINGS
        sh.host.events = []
        VM(updated, sh.host).call("onStart", "()V")
        self.assertIn(("title", "SettinGs"), sh.host.events)
        self.assertNotIn(("title", "Settings"), sh.host.events)

    def test_malformed_zip_asset_dex_or_opcode_fail_closed(self):
        original = NEW / "Settings.apk"
        def rewrite(path, *, mutate=None, duplicate=False):
            with zipfile.ZipFile(original) as src:
                entries = [(info.filename, src.read(info), info.compress_type)
                           for info in src.infolist()]
            with zipfile.ZipFile(path, "w") as dst:
                for name, payload, compression in entries:
                    if name == mutate:
                        payload = payload[:-1] + bytes([payload[-1] ^ 1])
                    dst.writestr(name, payload, compress_type=compression)
                if duplicate:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        dst.writestr("classes.dex", next(payload for name,payload,_
                                                         in entries if name == "classes.dex"))
        for which in ("assets/settings.png", "classes.dex"):
            p = self.base / ("modified-" + which.replace("/", "-"))
            rewrite(p, mutate=which)
            with self.assertRaises((APKProgramError, J2MEDexError)):
                load_apk(p)
        p = self.base / "duplicate.apk"
        rewrite(p, duplicate=True)
        with self.assertRaises(APKProgramError): load_apk(p)
        p = load_apk(original)
        words = p.codes[p.class_desc + "->onStart()V"].words
        changed = dataclasses.replace(p, codes={**p.codes,
            p.class_desc + "->onStart()V": dataclasses.replace(
                p.codes[p.class_desc + "->onStart()V"], words=(0x00ff, *words[1:]))})
        sh = self.shell("bad-op")
        with self.assertRaises(VMError): VM(changed, sh.host).call("onStart", "()V")


class NativeAndroidJavaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("gcc")
        if not cc: raise unittest.SkipTest("GCC needed for native C99 APK Java VM")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.base = Path(cls.tmp.name)
        cls.cli = cls.base / "apk_java_cli"
        sources = [ROOT / "symbian/runtime" / name for name in (
            "dex_preflight.c", "apk_dex_loader.c", "apk_java_vm.c", "apk_java_cli.c")]
        subprocess.run([cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-pedantic", *map(str, sources), "-o", str(cls.cli)], check=True)
        cls.bridge_cli = cls.base / "apk_android_cli"
        bridge_sources = [ROOT / "symbian/runtime" / name for name in (
            "dex_preflight.c", "apk_dex_loader.c", "apk_java_vm.c",
            "apk_activity_vm.c", "apk_sha256.c", "apk_java_runtime.c",
            "apk_android_bridge.c",
            "vfs_mount.c", "apk_android_cli.c")]
        subprocess.run([cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-pedantic", *map(str, bridge_sources),
                        "-o", str(cls.bridge_cli)], check=True)
        cls.image_cli = cls.base / "apk_image_cli"
        image_sources = [ROOT / "symbian/runtime" / name for name in (
            "apk_sha256.c", "apk_image_pack.c", "apk_image_cli.c")]
        subprocess.run([cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-pedantic", *map(str, image_sources),
                        "-o", str(cls.image_cli)], check=True)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def call(self, apk, entry, *args):
        info = next(row for row in json.loads((NEW / "catalog.json").read_text())
                    if row["name"] == apk)
        return subprocess.run([str(self.cli), str(NEW / apk), info["class"],
                               entry, *map(str, args)], capture_output=True, text=True)

    def test_c99_vm_reads_all_six_primary_dex_directly_from_real_apks(self):
        expected = {
            "Launcher.apk": ("TITLE: Android J2ME Edition", "IMAGE: wall.png"),
            "Settings.apk": ("TITLE: Settings", "IMAGE: settings.png"),
            "Store.apk": ("TITLE: Store - local preview", "IMAGE: banner.png"),
            "SystemUI.apk": ("TITLE: SystemUI - simulated error", "IMAGE: warning.png"),
            "PackageInstaller.apk": ("TITLE: Package Installer", "IMAGE: files.png"),
            "FileManager.apk": ("TITLE: File Manager", "IMAGE: files.png")}
        for apk, texts in expected.items():
            with self.subTest(apk=apk):
                result = self.call(apk, "onStart")
                self.assertEqual(result.returncode, 0, result.stderr)
                for text in texts: self.assertIn(text, result.stdout)
        self.assertIn("OPEN: org.e63.dalvik.settings",
                      self.call("Launcher.apk", "onSelect", 1).stdout)
        self.assertIn("SETFLAG: wifi_demo=1",
                      self.call("Settings.apk", "onSelect", 0).stdout)
        self.assertIn("TEXT: 1 result found: File Manager",
                      self.call("Store.apk", "onCommand", 1, "FILE MAN", "").stdout)
        self.assertIn("INSTALL REQUEST: org.e63.dalvik.files",
                      self.call("PackageInstaller.apk", "onSelect", 0).stdout)

    def pinned(self, name, entry="onStart", *params, path=None):
        package = next(row["package"] for row in json.loads((NEW / "catalog.json").read_text())
                       if row["name"] == name)
        return subprocess.run([str(self.bridge_cli), "--run",
                               str(path or NEW / name), package, entry,
                               *map(str, params)], capture_output=True, text=True)

    def test_native_activity_dex_lifecycle_unicode_and_guest_choose(self):
        def guest(name, event="onStart", *parameters):
            package = next(row["package"] for row in
                           json.loads((NEW / "catalog.json").read_text())
                           if row["name"] == name)
            return subprocess.run([str(self.bridge_cli), "--activity",
                                   str(NEW / name), package, event,
                                   *map(str, parameters)],
                                  capture_output=True, text=True)
        for item in json.loads((NEW / "catalog.json").read_text()):
            with self.subTest(name=item["name"]):
                result = guest(item["name"])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("ACTIVITY_DEX: constructed=1 created=1 "
                              "started=1 resumed=1 resumedOnce=1", result.stdout)
                self.assertIn("TITLE:", result.stdout)
                with zipfile.ZipFile(NEW / item["name"]) as archive:
                    dex = J2MEDex(archive.read("classes.dex"))
                descriptor = "L" + item["package"].replace(".", "/") + "/Main;"
                for key in (descriptor + "-><init>()V",
                            descriptor + "->showProgram()V",
                            "Lorg/e63/dalvik/runtime/GuestActivity;->onCreate(Landroid/os/Bundle;)V",
                            "Lorg/e63/dalvik/runtime/GuestActivity;->onResume()V"):
                    self.assertGreater(dex.methods[key].code_off, 0)
        store = guest("Store.apk")
        self.assertIn("Catalogo locale: città · café ☕ 😀", store.stdout)
        self.assertIn("NEXT: org.e63.dalvik.store",
                      guest("Launcher.apk", "onSelect", 0).stdout)
        self.assertIn("Wi-Fi preview: ON",
                      guest("Settings.apk", "onSelect", 0).stdout)
        # Only GuestActivity.choose() performs this conditional redraw.
        self.assertIn("Wi-Fi preview: OFF",
                      self.pinned("Settings.apk", "onSelect", 0).stdout)
        self.assertIn("resumedOnce=1", guest("Settings.apk", "onResume").stdout)
        self.assertIn("TEXT: No results found.",
                      guest("Store.apk", "onCommand", 1, "città", "").stdout)
        denied = guest("Store.apk", "onSelect", 60)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("invalid Java Program input", denied.stderr)
        malformed = subprocess.run([
            str(self.bridge_cli).encode(), b"--activity",
            str(NEW / "Store.apk").encode(), STORE.encode(), b"onCommand",
            b"1", b"\xed\xa0\xbd", b""], capture_output=True)
        self.assertNotEqual(malformed.returncode, 0)
        self.assertIn(b"invalid Java Program input", malformed.stderr)

    def test_native_exact_whole_apk_sha256_pin_and_own_asset_screen(self):
        for text in ("", "abc", "a"*1000):
            checksum = subprocess.check_output([str(self.bridge_cli), "--sha", text],
                                               text=True).strip()
            self.assertEqual(checksum, hashlib.sha256(text.encode()).hexdigest())
        for item in json.loads((NEW / "catalog.json").read_text()):
            with self.subTest(apk=item["name"]):
                output = self.pinned(item["name"])
                self.assertEqual(output.returncode, 0, output.stderr)
                self.assertIn("PIN_OK: " + item["package"], output.stdout)
                own = {line[len("IMAGE: "):] for line in output.stdout.splitlines()
                       if line.startswith("IMAGE: ")}
                self.assertLessEqual(own, set(item["assets"]))
        source = NEW / "Settings.apk"
        tampered = self.base / "tampered-signed-entry.apk"
        raw = bytearray(source.read_bytes())
        raw[-36] ^= 1  # outside classes.dex: CRC alone could not authenticate it
        tampered.write_bytes(raw)
        checked = self.pinned("Settings.apk", path=tampered)
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("not an exact built-in SHA-256 pin", checked.stderr)
        wrong_package = subprocess.run([str(self.bridge_cli), "--run", str(source),
                                        "org.e63.dalvik.store", "onStart"],
                                       capture_output=True, text=True)
        self.assertNotEqual(wrong_package.returncode, 0)
        self.assertIn("not an exact built-in SHA-256 pin", wrong_package.stderr)

    def test_per_package_image_pack_is_exact_and_pinned(self):
        images = ROOT / "symbian/android_java_app/images565.bin"
        records = json.loads((NEW / "catalog.json").read_text())
        self.assertEqual(pack_images(records, NEW), images.read_bytes())
        for item in records:
            for name in item["assets"]:
                if not name.endswith(".png"): continue
                r = subprocess.run([str(self.image_cli), str(images),
                                    item["package"], name],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("IMAGE: " + item["package"] + " " + name, r.stdout)
        denied = subprocess.run([str(self.image_cli), str(images),
                                 "org.e63.dalvik.launcher", "warning.png"],
                                capture_output=True, text=True)
        self.assertNotEqual(denied.returncode, 0)
        modified = self.base / "changed-images565.bin"
        blob = bytearray(images.read_bytes()); blob[-1] ^= 1
        modified.write_bytes(blob)
        denied = subprocess.run([str(self.image_cli), str(modified),
                                 "org.e63.dalvik.launcher", "wall.png"],
                                capture_output=True, text=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("image pack pin/format invalid", denied.stderr)

    def test_native_java_screen_events_and_safe_service_denials(self):
        self.assertIn("NEXT: org.e63.dalvik.store",
                      self.pinned("Launcher.apk", "onSelect", 0).stdout)
        self.assertIn("NEXT: org.e63.dalvik.settings",
                      self.pinned("Launcher.apk", "onSelect", 1).stdout)
        self.assertIn("TEXT: 1 result found: File Manager",
                      self.pinned("Store.apk", "onCommand", 1,
                                  " FILE MAN ", "").stdout)
        self.assertIn("TEXT: No results found.",
                      self.pinned("Store.apk", "onCommand", 1,
                                  "maps", "").stdout)
        install = self.pinned("PackageInstaller.apk", "onSelect", 0)
        self.assertEqual(install.returncode, 0, install.stderr)
        self.assertIn("Installation/enable unavailable", install.stdout)
        self.assertNotIn("OPTION: 0 OPEN", install.stdout)
        bad_index = self.pinned("Store.apk", "onSelect", 5)
        self.assertNotEqual(bad_index.returncode, 0)
        self.assertIn("invalid Java Program input", bad_index.stderr)
        bad_query = self.pinned("Store.apk", "onCommand", 1,
                                "A"*513, "")
        self.assertNotEqual(bad_query.returncode, 0)
        self.assertIn("invalid Java Program input", bad_query.stderr)

    def test_separate_symbian_target_references_actual_full_apks(self):
        app = ROOT / "symbian/android_java_app"
        mmp = (app / "e63android.mmp").read_text()
        pkg = (app / "e63android.pkg").read_text()
        source = (app / "e63android_app.cpp").read_text()
        for name in ("apk_dex_loader", "apk_java_vm", "apk_sha256",
                     "apk_java_runtime", "apk_android_bridge", "apk_image_pack"):
            self.assertIn(name + ".c", mmp)
        for name in ("Launcher", "Settings", "Store", "SystemUI",
                     "PackageInstaller", "FileManager"):
            self.assertIn("../../apks_android/" + name + ".apk", pkg)
        self.assertIn('"images565.bin"', pkg)
        self.assertIn("e63_session_open(&verified", source)
        # The preserved 0.2 SISX still contains the old interpreter, while
        # current (unreleased) source MUST NOT silently fall back to its shim.
        self.assertIn("StrictActivityEvent(&verified", source)
        self.assertIn("e63_android_activity_event_framework(", source)
        self.assertNotIn("e63_android_activity_event(&verified", source)
        self.assertIn("system_image.c", mmp)
        self.assertIn("e63_system_store.cpp", mmp)
        self.assertIn('"onCreate",0,0u)', source)
        self.assertIn('"onResume",0,0u)', source)
        self.assertIn("e63_file_services.cpp", mmp)
        self.assertIn("EStdKeyDevice0", source)
        self.assertIn("BuildThumbsL();", source)
        self.assertNotIn("e63android.mmp", (ROOT / "symbian/bld.inf").read_text())

    def test_native_crc_and_method_whitelist_fail_closed(self):
        source = NEW / "Settings.apk"
        modified = self.base / "bitflip.apk"
        raw = bytearray(source.read_bytes())
        with zipfile.ZipFile(source) as z:
            entry = z.getinfo("classes.dex")
            off = entry.header_offset + 30 + len(entry.filename.encode("utf-8")) + len(entry.extra)
            self.assertEqual(raw[off:off+8], b"dex\n035\x00")
            raw[off+30] ^= 1  # no CRC update -> reject before DEX interpreter
        modified.write_bytes(raw)
        info = next(row for row in json.loads((NEW / "catalog.json").read_text())
                    if row["name"] == "Settings.apk")
        checked = subprocess.run([str(self.cli), str(modified), info["class"], "onStart"],
                                 capture_output=True, text=True)
        self.assertNotEqual(checked.returncode, 0)
        forged = self.call("Settings.apk", "onPause")
        self.assertNotEqual(forged.returncode, 0)


class SignedSymbianJavaReleaseTests(unittest.TestCase):
    def test_frozen_preview_is_preserved_byte_for_byte(self):
        """The previous 0.1 release is historic, not the current APK inputs."""
        sis = ROOT / "release/e63android-0.1-java-apk-preview.sisx"
        self.assertEqual(hashlib.sha256(sis.read_bytes()).hexdigest(),
                         "21dba7be85b6f662328d0e7b16727df2044498e9a746eaebdacf7073ffab8977")
        self.assertEqual(platform_ids(sis), [0x102032BE])
        payloads = extract_sis(sis)
        self.assertEqual(len(payloads), 10)
        self.assertGreater(len(payloads[0]), 30_000)
        self.assertEqual(struct.unpack_from("<III", payloads[0]),
                         (0x1000007A, 0x100039CE, 0xE0B63E04))
        self.assertTrue(all(entry[:2] == b"PK" for entry in payloads[3:9]))
        self.assertNotEqual(payloads[3], (NEW / "Launcher.apk").read_bytes())

    def test_activity_unicode_native_release_contains_current_six_apks(self):
        """Payload/pin checks are NOT a hardware run or external SIS signing audit."""
        sis = ROOT / "release/e63android-0.2-activity-unicode-services-test.sisx"
        self.assertEqual(platform_ids(sis), [0x102032BE])
        payloads = extract_sis(sis)
        self.assertEqual(len(payloads), 10)
        exe, ui_rsc, reg_rsc, *data = payloads
        self.assertGreater(len(exe), 30_000)
        self.assertEqual(struct.unpack_from("<III", exe),
                         (0x1000007A, 0x100039CE, 0xE0B63E04))
        self.assertGreater(len(ui_rsc), 0)
        self.assertGreater(len(reg_rsc), 0)
        self.assertEqual(data[:-1], [(NEW / name).read_bytes() for name in (
            "Launcher.apk", "Settings.apk", "Store.apk", "SystemUI.apk",
            "PackageInstaller.apk", "FileManager.apk")])
        self.assertEqual(data[-1],
                         (ROOT / "symbian/android_java_app/images565.bin").read_bytes())



if __name__ == "__main__": unittest.main()
