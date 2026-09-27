import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from apps.specs import FILES, INSTALLER, LAUNCHER, SETTINGS, STORE, SYSTEMUI, programs
from build import HERE, jdk_tool
from dalvik.assembler import DexWriter, HOST
from dalvik.axml import manifest
from dalvik.axml_reader import inspect, AXMLError
from dalvik.dex import Dex, DexError
from dalvik.dex_j2me import J2MEDex, J2MEDexError
from dalvik.store_j2me import J2MEStoreState, CLASS as STORE_CLASS
from dalvik.host import HostError
from dalvik.vm import VM, VMError
from shell import DesktopShell
from adapter_preview import WebState


class DalvikTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["python3", str(HERE / "build.py")], cwd=HERE, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cls.tmp = tempfile.TemporaryDirectory(dir=HERE / "build")
        cls.base = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def shell(self, name: str):
        location = self.base / name
        if location.exists(): shutil.rmtree(location)
        return DesktopShell(state=location, import_root=location / "nokia_imports")

    def install_files(self, shell):
        shell.select(0)  # Store
        self.assertEqual(shell.active, STORE)
        shell.select(0)  # original J2ME StoreState.activate -> PackageInstaller
        self.assertEqual(shell.active, INSTALLER)
        self.assertTrue(shell.host.store_state.is_installing())
        self.assertIn("INSTALL", shell.text())
        shell.select(0)  # install + real J2ME StoreState.finishInstall
        self.assertIn("OPEN", shell.text())
        self.assertTrue(shell.host.store_state.is_installed())
        shell.select(0)
        self.assertEqual(shell.active, FILES)

    def test_signed_real_zip_axml_and_dex(self):
        signer = jdk_tool("jarsigner")
        for app in programs():
            with self.subTest(apk=app.apk_name):
                apk = HERE / "apks" / app.apk_name
                self.assertTrue(apk.is_file())
                with zipfile.ZipFile(apk) as z:
                    self.assertEqual(z.namelist().count("classes.dex"), 1)
                    self.assertEqual(z.namelist().count("classes2.dex"), 1)
                    original = J2MEDex(z.read("classes.dex"))
                    self.assertIn("Landroid/j2me/edition/E63Midlet;", original.classes)
                    self.assertIn("Landroid/j2me/edition/E63Canvas;", original.classes)
                    self.assertIn("Landroid/j2me/edition/BridgeClient;", original.classes)
                    for method in (
                        STORE_CLASS + "->activate()I",
                        "Landroid/j2me/edition/E63Midlet;->startApp()V",
                        "Landroid/j2me/edition/E63Midlet;->activate()V",
                        "Landroid/j2me/edition/E63Canvas;->paintSettings(Ljavax/microedition/lcdui/Graphics;)V",
                        "Landroid/j2me/edition/BridgeClient;->ping(Ljava/lang/String;)Ljava/lang/String;",
                    ):
                        self.assertIn(method, original.methods)
                        self.assertGreater(original.methods[method].code_off, 0)
                    self.assertEqual(len(original.classes), 9)
                    axml = z.read("AndroidManifest.xml")
                    self.assertEqual(struct.unpack_from("<HHI", axml), (3, 8, len(axml)))
                    info = inspect(axml)
                    self.assertEqual(info.package, app.package)
                    self.assertEqual(info.main_class,
                                     "android.j2me.edition.E63Midlet" if app.package == LAUNCHER
                                     else app.main_name)
                    self.assertEqual((info.min_sdk, info.target_sdk), (17, 17))
                    self.assertTrue(any(p.startswith("META-INF/") and p.endswith(".RSA")
                                        for p in z.namelist()))
                    dx = Dex(z.read("classes2.dex"))
                    self.assertEqual(dx.class_desc, app.class_desc)
                    self.assertIn(app.class_desc + "->onStart()V", dx.codes)
                check = subprocess.run([signer, "-verify", str(apk)], capture_output=True, text=True)
                self.assertEqual(check.returncode, 0)
                self.assertIn("jar verified.", check.stdout)
        self.assertIn("Unfortunately, the process com.android.systemui has stopped.",
                      Dex(zipfile.ZipFile(HERE / "apks/SystemUI.apk").read("classes2.dex")).strings)
        self.assertNotIn(b"<?xml", zipfile.ZipFile(HERE / "apks/Launcher.apk").read("AndroidManifest.xml"))

    def test_bytecode_dispatch_navigation_and_search(self):
        shell = self.shell("navigation")
        self.assertEqual(shell.active, LAUNCHER)
        self.assertNotIn("  2. File Manager", shell.text())
        shell.select(0)
        shell.command("search", "FILE MAN")
        self.assertIn("1 result found", shell.text())
        shell.command("search", "maps")
        self.assertIn("No results found.", shell.text())
        shell.select(0)
        shell.select(0)
        self.assertIn("OPEN", shell.text())
        shell.select(0)
        self.assertEqual(shell.active, FILES)
        shell.select(0)
        self.assertEqual(shell.active, SYSTEMUI)
        self.assertIn("[SIMULATED DIALOG]", shell.text())
        shell.select(1)
        self.assertIn("WAV OK:", shell.text())
        shell.select(0)
        self.assertEqual(shell.active, LAUNCHER)
        self.assertIn("  2. File Manager", shell.text())
        self.assertTrue(shell.vfs.installed(FILES))

    def test_persist_flags_data_and_volatile_ram_root(self):
        shell = self.shell("reboot")
        shell.select(1)
        shell.select(0)
        self.assertIn("Wi-Fi preview: ON", shell.text())
        shell.vfs.temp_write("/tmp/session", b"ephemeral")
        shell.home()
        self.install_files(shell)
        shell.command("touch", "/sdcard/Download/test.txt")
        self.assertIn("touch: OK", shell.text())
        restarted = DesktopShell(state=shell.state, import_root=shell.import_root)
        self.assertEqual(restarted.vfs.ram_root, {})
        self.assertTrue((restarted.vfs.media / "Download/test.txt").is_file())
        self.assertTrue(restarted.vfs.installed(FILES))
        restarted.select(1)
        self.assertIn("Wi-Fi preview: ON", restarted.text())

    def test_crud_import_and_mount_boundary(self):
        shell = self.shell("crud")
        self.install_files(shell)
        incoming = shell.import_root / "notes.txt"
        incoming.write_text("nokia-notes", encoding="utf-8")
        shell.command("mkdir", "/sdcard/DCIM/Trips")
        self.assertIn("mkdir: OK", shell.text())
        shell.command("touch", "/sdcard/DCIM/Trips/empty.txt")
        shell.command("rename", "/sdcard/DCIM/Trips/empty.txt", "/sdcard/DCIM/Trips/renamed.txt")
        self.assertTrue((shell.vfs.media / "DCIM/Trips/renamed.txt").exists())
        shell.command("delete", "/sdcard/DCIM/Trips/renamed.txt")
        self.assertFalse((shell.vfs.media / "DCIM/Trips/renamed.txt").exists())
        shell.command("import", "notes.txt", "/sdcard/Download/imported.txt")
        self.assertIn("import_file: OK", shell.text())
        self.assertEqual((shell.vfs.media / "Download/imported.txt").read_text(),
                         incoming.read_text())
        shell.command("import", "notes.txt", "/sdcard/Download/imported.txt")
        self.assertIn("import_file:", shell.text())
        self.assertNotIn("import_file: OK", shell.text())
        self.assertEqual(incoming.read_text(), "nokia-notes")
        with self.assertRaises(HostError): shell.vfs.resolve("/sdcard/../../etc/passwd")
        with self.assertRaises(HostError): shell.vfs.resolve("/system/media/hijack", write=True, caller=FILES)
        with self.assertRaises(HostError): shell.vfs.imported("../build.py")
        outside = self.base / "external"
        outside.mkdir()
        (shell.vfs.media / "Download/escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HostError):
            shell.vfs.touch("/sdcard/Download/escape/evil.txt", FILES)
        shell.command("wav", "/sdcard/Music/music.wav")
        self.assertIn("WAV OK:", shell.text())

    def test_real_midlet_classfiles_converted_not_embedded_as_inert_assets(self):
        port = HERE / "j2me"
        jar = port / "Android_J2ME_E63_Bridge.jar"
        meta = json.loads((port / "source_provenance.json").read_text())
        self.assertEqual(hashlib.sha256(jar.read_bytes()).hexdigest(), meta["jar_sha256"])
        for relative, expected in meta["files"].items():
            self.assertEqual(hashlib.sha256((port / relative).read_bytes()).hexdigest(), expected)
        with zipfile.ZipFile(jar) as z:
            expected_classes = {"L" + name[:-6] + ";" for name in z.namelist()
                                if name.endswith(".class")}
        self.assertIn("Landroid/j2me/edition/E63Canvas;", expected_classes)
        for app in programs():
            with zipfile.ZipFile(HERE / "apks" / app.apk_name) as z:
                d = z.read("classes.dex")
                self.assertEqual(set(J2MEDex(d).classes), expected_classes)
                self.assertEqual(hashlib.sha256(d).hexdigest(), meta["dex_sha256"])
                self.assertNotIn("assets/j2me.jar", z.namelist())

    def test_mutating_translated_j2me_method_changes_store_behavior(self):
        original = bytearray((HERE / "j2me/classes.dex").read_bytes())
        dex = J2MEDex(bytes(original))
        ref = STORE_CLASS + "->activate()I"
        method = dex.methods[ref]
        code = dex.code_for(ref)
        # Change the original OPEN_APP=2 branch to WAIT=3, not a Python stub.
        index = code.words.index(0x2012)
        struct.pack_into("<H", original, method.code_off + 16 + index * 2, 0x3012)
        original[12:32] = hashlib.sha1(original[32:]).digest()
        struct.pack_into("<I", original, 8, zlib.adler32(original[12:]) & 0xffffffff)
        actual = J2MEStoreState(dex, True)
        altered = J2MEStoreState(J2MEDex(bytes(original)), True)
        self.assertEqual(actual.activate(), 2)
        self.assertEqual(altered.activate(), 3)

    def test_corruption_and_unknown_instruction_fail_closed(self):
        original = zipfile.ZipFile(HERE / "apks/Settings.apk").read("classes2.dex")
        bad = bytearray(original)
        bad[-5] ^= 1
        with self.assertRaises(DexError): Dex(bytes(bad))
        j2me = bytearray(zipfile.ZipFile(HERE / "apks/Settings.apk").read("classes.dex"))
        j2me[-5] ^= 1
        with self.assertRaises(J2MEDexError): J2MEDex(bytes(j2me))
        xml = bytearray(zipfile.ZipFile(HERE / "apks/Settings.apk").read("AndroidManifest.xml"))
        xml[4:8] = b"\x00\x00\x00\x00"
        with self.assertRaises(AXMLError): inspect(bytes(xml))
        sample = Dex(original)
        key = sample.class_desc + "->onStart()V"
        sample.codes[key].words = (0xFF,)
        shell = self.shell("fail_closed")
        with self.assertRaises(VMError): VM(sample, shell.host).call("onStart", "()V")
        with self.assertRaises(HostError): shell.host.call(HOST + "->root()V", ())

    def test_runtime_does_not_import_guest_build_sources(self):
        result = subprocess.run(["python3", "-c",
                                 "import sys, shell; assert 'apps.specs' not in sys.modules; "
                                 "s=shell.DesktopShell(state=__import__('pathlib').Path('build/isolation')); "
                                 "assert 'apps.specs' not in sys.modules"],
                                cwd=HERE, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_graphical_host_preview_uses_dex_events(self):
        location = self.base / "visual"
        app = WebState(location)
        self.assertIn("width:320px;height:240px", app.html())
        self.assertIn("data:image/png;base64,", app.html())
        app.action({"type": ["select"], "index": ["3"]})
        self.assertEqual(app.shell.active, SYSTEMUI)
        self.assertIn("Unfortunately, the process com.android.systemui has stopped.", app.html())
        self.assertIn("class=\"dialog\"", app.html())
        app.action({"type": ["home"]})
        self.assertEqual(app.shell.active, LAUNCHER)

    def test_generated_instructions_are_behavior_not_python_stub(self):
        app = programs()[0]
        original = Dex(DexWriter(app).build())
        changed = False
        for index, op in enumerate(app.methods[0].asm.ops):
            if op == ("string", 0, "Launcher"):
                app.methods[0].asm.ops[index] = ("string", 0, "Custom Guest Home")
                changed = True
                break
        self.assertTrue(changed)
        modified = Dex(DexWriter(app).build())
        self.assertNotEqual(original.blob, modified.blob)
        shell = self.shell("bytecode_change")
        host = shell.host
        host.current = LAUNCHER
        host.events = []
        VM(modified, host).call("onStart", "()V")
        self.assertIn(("title", "Custom Guest Home"), host.events)
        self.assertNotIn(("title", "Launcher"), host.events)


if __name__ == "__main__":
    unittest.main()
