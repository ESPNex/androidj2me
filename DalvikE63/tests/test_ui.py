"""End-to-end proof: the UI is painted and navigated by original J2ME DEX.

No source-level screen adapter or hardcoded HTML is used for these screenshots.
The host supplies only graphics/input/storage services and PackageInstaller.
"""
import ctypes
import hashlib
import json
import shutil
import socketserver
import struct
import subprocess
import threading
import sys
import tempfile
import unittest
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

from PIL import Image

from dalvik.dex_j2me import J2MEDex
from dalvik.ids import FILES
from dalvik.ui_vm import CANVAS, MIDLET, JavaMEUI, UIVMError
from web_preview import OSPreview

ROOT = Path(__file__).resolve().parents[1]
APK = ROOT / "apks/Launcher.apk"
SCREEN = MIDLET + "->screen:I"


class OriginalJ2MEUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.base = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ui(self, name):
        return JavaMEUI(APK, self.base / name)

    @staticmethod
    def texts(ui):
        return [str(c[1]) for c in ui.host.draw_calls if c[0] == "drawString"]

    @staticmethod
    def press(ui, *keys):
        for key in keys: ui.key(key)

    def test_converted_midlet_paints_real_boot_home_and_settings(self):
        ui = self.ui("screens")
        boot = ui.png()
        self.assertEqual(Image.open(BytesIO(boot)).size, (320, 240))
        self.assertEqual(ui.app.fields[SCREEN], 0)
        ui.tick(2100)  # actually executes E63Midlet.tickLoop DEX
        self.assertEqual(ui.app.fields[SCREEN], 1)
        home = ui.png()
        self.assertNotEqual(boot, home)
        self.assertIn("No service", self.texts(ui))
        self.assertIn("Play Store", self.texts(ui))
        self.press(ui, -2, -7)  # Canvas.keyPressed -> Midlet.move/activate
        self.assertEqual(ui.app.fields[SCREEN], 2)
        settings = ui.png()
        self.assertIn("SIS Bridge (loopback)", self.texts(ui))
        self.assertNotEqual(home, settings)
        ui.key(-7)  # toggle Wi-Fi, original Midlet.activate
        self.assertEqual(ui.app.fields[MIDLET+"->wifiOn:Z"], 1)
        self.assertTrue((self.base / "screens/c_drive/private/e63os/rms/j2me_rms.json").is_file())

    def test_guest_navigation_drives_real_os_apk_installer(self):
        ui = self.ui("install")
        ui.tick(2100)
        self.press(ui, -2, -7, -7, -6, -7)  # settings Wi-Fi -> login
        self.assertEqual(ui.app.fields[SCREEN], 4)
        self.press(ui, -2, -2, -7, -2, -7, -7)  # login -> Store card -> INSTALL
        self.assertEqual(ui.app.fields[SCREEN], 6)
        self.assertFalse(ui.packages.installed(FILES))
        ui.tick(1700)
        self.assertGreater(ui.app.fields[MIDLET+"->installPercent:I"], 0)
        ui.tick(2300)  # actual guest tickLoop calls StoreState.finishInstall
        self.assertTrue(ui.packages.installed(FILES))  # separate APK's DEX installed in PC OS VFS
        self.assertTrue((self.base / "install/c_drive/private/e63os/data/app/FileManager.apk").is_file())
        ui.key(-7)  # original J2ME OPEN navigates FileManager
        self.assertEqual(ui.app.fields[SCREEN], 8)
        file_image = ui.png()
        self.assertIn("File Manager", " ".join(self.texts(ui)))
        self.press(ui, -7, -2, -7)  # Android folder -> Android/data -> SystemUI error
        self.assertEqual(ui.app.fields[SCREEN], 11)
        error_image = ui.png()
        self.assertNotEqual(file_image, error_image)
        self.assertIn("Unfortunately", " ".join(self.texts(ui)))
        restarted=self.ui("install")
        restarted.tick(2100)
        self.assertTrue(restarted.packages.installed(FILES))
        self.assertEqual(restarted.app.fields[MIDLET+"->store:Landroid/j2me/edition/StoreState;"].
                         fields["Landroid/j2me/edition/StoreState;->installed:Z"],1)
        restarted.png()
        self.assertIn("File Manager", " ".join(self.texts(restarted)))

    def test_original_midlet_native_textfield_triggers_guest_command(self):
        ui = self.ui("forms")
        ui.tick(2100)
        self.press(ui, -2, -7, -7, -6, -7)
        ui.key(-7)  # original startEditing(EDIT_EMAIL), native MIDP Form
        self.assertEqual(ui.host.current.desc, "Ljavax/microedition/lcdui/Form;")
        ui.form_action("person@example.com")
        self.assertEqual(ui.app.fields[MIDLET+"->emailDraft:Ljava/lang/String;"],
                         "person@example.com")
        self.press(ui, -2, -2, -7)
        self.assertEqual(ui.app.fields[SCREEN], 5)
        ui.key(-7)
        ui.form_action("file manager")
        self.assertEqual(ui.app.fields[MIDLET+"->oneResult:Z"], 1)
        self.assertEqual(ui.app.fields[MIDLET+"->query:Ljava/lang/String;"], "file manager")

    def test_original_bridgeclient_dex_to_compiled_c_core_and_guest_catches_errors(self):
        gcc=shutil.which("gcc")
        if not gcc:self.skipTest("gcc needed for real C bridge protocol")
        so=self.base / "bridge-core.so"
        subprocess.run([gcc,"-std=c99","-Wall","-Wextra","-Werror","-fPIC","-shared",
                        str(ROOT / "symbian/bridge_protocol.c"),"-o",str(so)],check=True)
        core=ctypes.CDLL(str(so)).e63_reply
        core.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_char_p,
                       ctypes.c_void_p,ctypes.c_size_t]
        core.restype=ctypes.c_int
        frames=[]
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                frame=b""
                while not frame.endswith(b"\n") and len(frame)<96:
                    data=self.request.recv(1)
                    if not data:break
                    frame+=data
                frames.append(frame)
                reply=ctypes.create_string_buffer(96)
                n=core(ctypes.create_string_buffer(frame),len(frame),b"123456",
                       reply,len(reply))
                self.request.sendall(reply.raw[:abs(n)])
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address=True
        server=Server(("127.0.0.1",27463),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        try:
            for suffix,pin,expected in (("ok","123456","SIS bridge: PONG"),
                                        ("deny","111111","Unavailable: java.io.IOException")):
                ui=self.ui("bridge_"+suffix)
                ui.tick(2100)
                self.press(ui,-2,-7,-2,-2,-7)  # guest Settings -> SIS Bridge Form
                self.assertEqual(ui.host.current.desc,"Ljavax/microedition/lcdui/Form;")
                ui.form_action(pin)
                status=ui.app.fields[MIDLET+"->bridgeStatusItem:Ljavax/microedition/lcdui/StringItem;"]
                self.assertEqual(status.fields["text"],expected)
                self.assertIn("Landroid/j2me/edition/BridgeClient;->ping(Ljava/lang/String;)Ljava/lang/String;",
                              ui.executed_methods)
                self.assertIn("Landroid/j2me/edition/E63Midlet$2;->run()V",ui.executed_methods)
            self.assertEqual(frames,[b"E63BRIDGE/1\tAUTH\t123456\tPING\n",
                                     b"E63BRIDGE/1\tAUTH\t111111\tPING\n"])
        finally:
            server.shutdown();server.server_close();worker.join(timeout=3)
        ui=self.ui("bridge_missing")
        ui.tick(2100)
        self.press(ui,-2,-7,-2,-2,-7)
        ui.form_action("123456")
        status=ui.app.fields[MIDLET+"->bridgeStatusItem:Ljavax/microedition/lcdui/StringItem;"]
        self.assertEqual(status.fields["text"],"Unavailable: java.io.IOException")

    def test_status_clock_and_battery_are_vertically_aligned_in_guest_pixels(self):
        ui = self.ui("status_alignment")
        ui.tick(2100)
        for battery in (-1, 35):
            with self.subTest(battery=battery):
                ui.app.fields[MIDLET + "->battery:I"] = battery
                picture = Image.open(BytesIO(ui.png())).convert("RGB")
                clock = ui.run(MIDLET + "->clock()Ljava/lang/String;", [ui.app])
                draws = [call for call in ui.host.draw_calls
                         if call[0] == "drawString" and call[1] == clock
                         and call[3] < 18]
                self.assertEqual(len(draws), 1)
                clock_x, clock_y = draws[0][2:4]
                self.assertEqual(clock_y, 5)  # centred beside the 11px battery
                battery_y = [y for y in range(18)
                             for x in range(clock_x - 45, clock_x - 2)
                             if picture.getpixel((x, y)) == (153, 153, 153)]
                clock_y_pixels = [y for y in range(18)
                                  for x in range(clock_x, 320)
                                  if (lambda rgb: rgb[1] > 85 and rgb[2] > 140
                                      and rgb[2] > rgb[1] * 1.25)(picture.getpixel((x, y)))]
                self.assertTrue(battery_y and clock_y_pixels)
                # Compare doubled centres, avoiding float rounding and varying
                # glyph widths across the clock's minute digits.
                self.assertLessEqual(abs((min(battery_y) + max(battery_y)) -
                                         (min(clock_y_pixels) + max(clock_y_pixels))), 2)

    def test_search_lens_is_round_and_quick_tiles_match_the_panel_backdrop(self):
        ui = self.ui("search_circle_and_quick_panel")
        ui.tick(2100)
        home = Image.open(BytesIO(ui.png())).convert("RGB")
        self.assertIn(("drawArc", 22, 31, 11, 11, 0, 360), ui.host.draw_calls)
        self.assertEqual(home.getpixel((22, 31)), (217, 221, 224))  # no square corner
        self.assertEqual(home.getpixel((27, 31)), (85, 94, 99))   # curved outline
        ui.pointer(260, 7)
        self.assertEqual(ui.app.fields[SCREEN], 16)
        for enabled in (False, True):
            with self.subTest(wifi_enabled=enabled):
                panel = Image.open(BytesIO(ui.png())).convert("RGB")
                backdrop = panel.getpixel((8, 75))
                self.assertEqual(backdrop, (16, 16, 16))
                for point in ((20, 75), (170, 75), (20, 145), (170, 145)):
                    self.assertEqual(panel.getpixel(point), backdrop, point)
                if not enabled:
                    ui.pointer(71, 87)  # guest changes demo flag/focus, not radio
                    self.assertEqual(ui.app.fields[MIDLET + "->wifiOn:Z"], 1)

    def test_android42_style_surfaces_are_painted_and_navigated_by_guest_dex(self):
        ui = self.ui("jelly_bean_surfaces")
        ui.tick(2100)
        home = Image.open(BytesIO(ui.png())).convert("RGB")
        self.assertEqual(home.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(home.getpixel((5, 220)), (0, 0, 0))
        self.assertIn("Search apps", self.texts(ui))
        self.assertIn("Apps", self.texts(ui))
        ui.pointer(50, 37)  # launcher search opens the local app tray
        self.assertEqual(ui.app.fields[SCREEN], 14)
        ui.png()
        self.assertIn("WIDGETS", self.texts(ui))
        self.assertIn("Play Store", self.texts(ui))
        ui.key(57)  # Widgets tab is empty, not a fabricated app catalog
        ui.png()
        self.assertIn("No widgets installed", self.texts(ui))
        ui.key(49)
        ui.key(-6)
        self.assertEqual(ui.app.fields[SCREEN], 1)
        ui.pointer(24, 8)  # left status tap -> empty notifications shade
        self.assertEqual(ui.app.fields[SCREEN], 15)
        ui.png()
        self.assertIn("No notifications", self.texts(ui))
        ui.pointer(155, 182)  # button in guest Canvas -> quick settings
        self.assertEqual(ui.app.fields[SCREEN], 16)
        ui.png()
        self.assertIn("demo OFF", self.texts(ui))
        self.assertIn("Unknown", self.texts(ui))
        self.assertEqual(ui.app.fields[MIDLET+"->battery:I"], -1)
        ui.pointer(71, 87)  # toggle local Store Wi-Fi switch (not Nokia radio)
        self.assertEqual(ui.app.fields[MIDLET+"->wifiOn:Z"], 1)
        ui.pointer(160, 221)
        self.assertEqual(ui.app.fields[SCREEN], 1)
        ui.pointer(264, 8)  # right status tap -> quick settings
        self.assertEqual(ui.app.fields[SCREEN], 16)
        ui.pointer(241, 87)  # Settings tile
        self.assertEqual(ui.app.fields[SCREEN], 2)
        ui.pointer(275, 222)  # third Android nav button -> Recent screens
        self.assertEqual(ui.app.fields[SCREEN], 17)
        ui.png()
        self.assertIn("Recent screens", self.texts(ui))
        self.assertIn("Local guest history", self.texts(ui))
        ui.key(-6)  # physical left softkey remains Back
        self.assertEqual(ui.app.fields[SCREEN], 2)
        for name in ("paintHome", "paintAppDrawer", "paintNotifications",
                     "paintQuickSettings", "paintRecents", "pointerPressed"):
            self.assertTrue(any("E63Canvas;->"+name+"(" in ref
                                for ref in ui.executed_methods), name)

    def test_guest_clock_option_changes_only_displayed_time(self):
        ui = self.ui("local_display_clock")
        ui.tick(2100)
        reference = ui.host.now_ms
        before = ui.run(MIDLET+"->clock()Ljava/lang/String;", [ui.app])
        ui.key(-2); ui.key(-7)  # Settings
        ui.key(-2); ui.key(-7)  # Display clock +1 hour checkbox
        self.assertEqual(ui.app.fields[MIDLET+"->adjustClock:Z"], 1)
        ui.host.now_ms = reference  # compare with the same underlying device time
        after = ui.run(MIDLET+"->clock()Ljava/lang/String;", [ui.app])
        self.assertEqual(after[3:], before[3:])
        self.assertEqual(int(after[:2]), (int(before[:2]) + 1) % 24)

    def test_touch_install_open_and_installed_app_tray(self):
        ui = self.ui("jelly_bean_touch_install")
        ui.tick(2100)
        ui.pointer(276, 7)   # quick settings
        ui.pointer(71, 86)   # turn on local demo Store switch
        ui.pointer(160, 220) # Home
        ui.pointer(70, 169)  # Store dock shortcut
        self.assertEqual(ui.app.fields[SCREEN], 4)  # optional local login
        login = Image.open(BytesIO(ui.png())).convert("RGB")
        self.assertEqual(login.getpixel((0, 0)), (0, 0, 0))
        ui.pointer(280, 183) # continue without sending any credentials
        self.assertEqual(ui.app.fields[SCREEN], 5)
        store = Image.open(BytesIO(ui.png())).convert("RGB")
        self.assertEqual(store.getpixel((0, 0)), (0, 0, 0))
        ui.pointer(50, 132)  # Store card -> FileManager app
        self.assertEqual(ui.app.fields[SCREEN], 6)
        ui.pointer(50, 190)  # INSTALL button
        self.assertFalse(ui.packages.installed(FILES))
        ui.tick(4000)        # original guest timer + real PC APK install
        self.assertTrue(ui.packages.installed(FILES))
        ui.png()
        self.assertIn("OPEN", self.texts(ui))
        ui.pointer(50, 190)  # OPEN
        self.assertEqual(ui.app.fields[SCREEN], 8)
        files = Image.open(BytesIO(ui.png())).convert("RGB")
        self.assertEqual(files.getpixel((0, 0)), (0, 0, 0))
        ui.pointer(160, 220) # Home shortcut, installed File Manager visible
        ui.key(49)           # numeric shortcut opens app tray on Nokia
        self.assertEqual(ui.app.fields[SCREEN], 14)
        ui.png()
        self.assertIn("File Manager", self.texts(ui))
        ui.pointer(48, 109)
        self.assertEqual(ui.app.fields[SCREEN], 8)

    def test_mutating_original_classes_dex_changes_actual_pixels(self):
        src = self.ui("baseline")
        src.tick(2100)
        original = src.png()
        self.assertIn("Play Store", self.texts(src))
        with zipfile.ZipFile(APK) as z:
            members = {n: z.read(n) for n in z.namelist()}
        code = bytearray(members["classes.dex"])
        self.assertEqual(code.count(b"Play Store\x00"), 1)
        pos = code.index(b"Play Store\x00")
        code[pos:pos+10] = b"Play Space"
        code[12:32] = hashlib.sha1(code[32:]).digest()
        struct.pack_into("<I", code, 8, zlib.adler32(code[12:]) & 0xffffffff)
        self.assertIn("Play Space", J2MEDex(bytes(code)).strings)
        members["classes.dex"] = bytes(code)
        altered_apk = self.base / "mutated.apk"
        with zipfile.ZipFile(altered_apk, "w") as z:
            for name, data in members.items(): z.writestr(name, data)
        # Intentional bypass ONLY for this mutation test; production checks v1 signature.
        changed = JavaMEUI(altered_apk, self.base / "mutated", check_signature=False)
        changed.tick(2100)
        image = changed.png()
        self.assertIn("Play Space", self.texts(changed))
        self.assertNotIn("Play Store", self.texts(changed))
        self.assertNotEqual(original, image)
        with self.assertRaises(UIVMError):
            JavaMEUI(altered_apk, self.base / "reject_tamper")

    def test_web_preview_is_only_terminal_not_adapter_screen(self):
        preview = OSPreview(self.base / "web")
        html = preview.html().decode("utf-8")
        self.assertIn('src="/screen.png"', html)
        self.assertIn("E63Canvas", html)
        self.assertNotIn("Apps - File Manager - LardeXWare", html)
        preview.action({"type":["key"],"code":["-7"]})
        self.assertEqual(preview.ui.app.fields[SCREEN], 1)
        self.assertTrue(preview.ui.png().startswith(b"\x89PNG"))

    def test_preview_controls_only_forward_jelly_bean_input_to_guest(self):
        preview = OSPreview(self.base / "jelly_bean_preview")
        preview.action({"type": ["key"], "code": ["-7"]})
        preview.action({"type": ["key"], "code": ["49"]})
        self.assertEqual(preview.ui.app.fields[SCREEN], 14)
        self.assertIn(b"Notifiche", preview.html())
        self.assertTrue(preview.ui.png().startswith(b"\x89PNG"))
        preview.action({"type": ["key"], "code": ["57"]})
        preview.ui.png()
        self.assertIn("No widgets installed", self.texts(preview.ui))

    def test_runtime_does_not_import_guest_adapter_sources(self):
        result = subprocess.run([sys.executable, "-c",
            "import sys,pathlib; from dalvik.ui_vm import JavaMEUI; "
            "u=JavaMEUI(pathlib.Path('apks/Launcher.apk'),pathlib.Path('build/isolation-ui')); "
            "u.tick(2100); u.png(); assert 'apps.specs' not in sys.modules"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__": unittest.main()
