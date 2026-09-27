"""C99 executes ORIGINAL J2ME paint bytecode; PC host rasterizes its ops.

The C VM chooses colors, geometry, font/strings and draw order from classes.dex.
Pillow is an atomic Graphics/Font *device service*, not a screen adapter.
This harness still tests the original drawer body; full-screen RGB565 proofs
are in test_native_rgb565.py. No S60 backend or SIS.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops

from dalvik.midp_host import JObject
from dalvik.ui_vm import CANVAS, MIDLET, JavaMEUI

ROOT = Path(__file__).resolve().parents[1]
DEX = ROOT / "j2me/classes.dex"
APK = ROOT / "apks/Launcher.apk"
GRAPHICS = "Ljavax/microedition/lcdui/Graphics;"
FONT = "Ljavax/microedition/lcdui/Font;"
IMAGE = "Ljavax/microedition/lcdui/Image;"
STORE = "Landroid/j2me/edition/StoreState;"
# Boot host maps verified APK resources to handles. DEX selects the fields.
RESOURCE = {1: "/store.png", 2: "/settings.png", 3: "/files.png",
            4: "/nav_back.png", 5: "/nav_home.png", 6: "/nav_recent.png",
            7: "/wifi_status.png", 8: "/wall.png", 9: "/drawer.png",
            10: "/wifi.png", 11: "/settings_mini.png"}
PAINT_PROTO = "(Ljavax/microedition/lcdui/Graphics;)V"


class DexView(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("size", ctypes.c_size_t)] + [
        (name, ctypes.c_uint32) for name in (
            "strings_count strings_off types_count types_off protos_count protos_off "
            "fields_count fields_off methods_count methods_off classes_count "
            "classes_off data_off data_count").split()]


class DrawOp(ctypes.Structure):
    _fields_ = [("code", ctypes.c_int32), ("a", ctypes.c_int32),
                ("b", ctypes.c_int32), ("c", ctypes.c_int32),
                ("d", ctypes.c_int32), ("text", ctypes.c_char * 161)]


GAME = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int32,
                       ctypes.POINTER(ctypes.c_int32))
FONT_HEIGHT = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int32,
                              ctypes.POINTER(ctypes.c_int32))
FONT_WIDTH = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int32,
                             ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32))
IMAGE_BOUNDS = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int32,
                                ctypes.POINTER(ctypes.c_int32),
                                ctypes.POINTER(ctypes.c_int32))
COMMIT = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                         ctypes.POINTER(DrawOp), ctypes.c_uint32)
LOCAL_CLOCK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                             ctypes.POINTER(ctypes.c_int32),
                             ctypes.POINTER(ctypes.c_int32))


class PaintHost(ctypes.Structure):
    _fields_ = [("context", ctypes.c_void_p), ("height", FONT_HEIGHT),
                ("width", FONT_WIDTH), ("image_bounds", IMAGE_BOUNDS),
                ("commit", COMMIT), ("local_clock", LOCAL_CLOCK)]


class NativePaint:
    def __init__(self, lib, blob: bytes, ui: JavaMEUI, width: int, height: int):
        self.lib, self.ui = lib, ui
        self.width, self.height = width, height
        self.backing = ctypes.create_string_buffer(blob)
        self.view = DexView()
        if lib.e63_dex_open(self.backing, len(blob), ctypes.byref(self.view)):
            raise AssertionError("DEX preflight")

        @GAME
        def action(_, key, out):
            out[0] = 0
            return 0

        @FONT_HEIGHT
        def font_height(_, size, out):
            if self.fail_metrics:
                return 1
            out[0] = ui.host.font(size).size + 1
            return 0

        @FONT_WIDTH
        def font_width(_, size, text, out):
            if self.fail_metrics:
                return 1
            out[0] = int(ui.host.font(size).getlength(text.decode("ascii")))
            return 0

        @IMAGE_BOUNDS
        def image_bounds(_, resource_id, width_out, height_out):
            if self.fail_metrics or self.fail_image_bounds or resource_id not in self.images:
                return 1
            image = self.images[resource_id]
            width_out[0], height_out[0] = image.width, image.height
            return 0

        @COMMIT
        def commit(_, operations, count):
            try:
                if self.reject_commit:
                    return 1
                # Draw into a temporary surface: on failure, keep the old frame.
                graphics = ui.host.new_canvas()
                batch = []
                for operation in operations[:count]:
                    text = bytes(operation.text).split(b"\x00", 1)[0].decode("ascii")
                    batch.append((operation.code, operation.a, operation.b,
                                  operation.c, operation.d, text))
                    if operation.code == 1:
                        ui.host._draw("setColor", [graphics, operation.a])
                    elif operation.code == 2:
                        ui.host._draw("fillRect", [graphics, operation.a,
                                                     operation.b, operation.c,
                                                     operation.d])
                    elif operation.code == 3:
                        font = JObject(FONT, {"size": operation.a})
                        ui.host._draw("setFont", [graphics, font])
                    elif operation.code == 4:
                        ui.host._draw("drawString", [graphics, text,
                                                       operation.a, operation.b,
                                                       operation.c])
                    elif operation.code == 5:
                        image = JObject(IMAGE, {"image": self.images[operation.a]})
                        ui.host._draw("drawImage", [graphics, image,
                                                      operation.b, operation.c,
                                                      operation.d])
                    elif operation.code == 6:
                        ui.host._draw("drawRect", [graphics, operation.a,
                                                     operation.b, operation.c,
                                                     operation.d])
                    elif operation.code == 7:
                        ui.host._draw("drawLine", [graphics, operation.a,
                                                     operation.b, operation.c,
                                                     operation.d])
                    elif operation.code == 8:
                        ui.host._draw("setClip", [graphics, operation.a,
                                                   operation.b, operation.c,
                                                   operation.d])
                    elif operation.code == 9:
                        ui.host._draw("drawArc", [graphics, operation.a,
                                                   operation.b, operation.c,
                                                   operation.d, 0, 360])
                    else:
                        return 1
                self.frame = graphics.fields["surface"].convert("RGB")
                self.batch = batch
                self.commits += 1
                return 0
            except (ValueError, OSError, OverflowError, RuntimeError):
                return 1

        @LOCAL_CLOCK
        def local_clock(_, hour, minute):
            if self.fail_metrics:
                return 1
            now = datetime.fromtimestamp(ui.host.now_ms / 1000)
            hour[0], minute[0] = now.hour, now.minute
            return 0

        self.callbacks = (action, font_height, font_width, image_bounds,
                          commit, local_clock)
        self.images = {i: Image.open(BytesIO(ui.host.images[path])).convert("RGBA")
                       for i, path in RESOURCE.items()}
        self.host = PaintHost(None, font_height, font_width,
                              image_bounds, commit, local_clock)
        self.fail_metrics = False
        self.fail_image_bounds = False
        self.reject_commit = False
        self.frame: Image.Image | None = None
        self.batch: list[tuple] = []
        self.commits = 0
        self.vm = lib.e63_ui_new(ctypes.byref(self.view), action, None)
        if not self.vm:
            raise AssertionError("native VM allocation")
        if lib.e63_ui_set_viewport(self.vm, width, height) or \
           lib.e63_ui_set_paint_host(self.vm, ctypes.byref(self.host)):
            raise AssertionError("paint host attachment")
        self.midlet = self.object(MIDLET)
        self.canvas = self.object(CANVAS)
        self.store = self.object(STORE)
        self.graphics = self.host_object(GRAPHICS, 0)
        self.small = self.host_object(FONT, 8)
        self.medium = self.host_object(FONT, 0)
        self.large = self.host_object(FONT, 16)
        self.icons = {id: self.host_object(IMAGE, id) for id in RESOURCE}
        self.set_ref(CANVAS, "app", MIDLET, self.midlet)
        self.set_ref(MIDLET, "canvas", CANVAS, self.canvas)
        self.set_ref(CANVAS, "small", FONT, self.small)
        self.set_ref(CANVAS, "medium", FONT, self.medium)
        self.set_ref(CANVAS, "large", FONT, self.large)
        self.set_ref(CANVAS, "storeIcon", IMAGE, self.icons[1])
        self.set_ref(CANVAS, "settingsIcon", IMAGE, self.icons[2])
        self.set_ref(CANVAS, "fileIcon", IMAGE, self.icons[3])
        self.set_ref(CANVAS, "navBack", IMAGE, self.icons[4])
        self.set_ref(CANVAS, "navHome", IMAGE, self.icons[5])
        self.set_ref(CANVAS, "navRecent", IMAGE, self.icons[6])
        self.set_ref(CANVAS, "wifiStatus", IMAGE, self.icons[7])
        self.set_ref(CANVAS, "wall", IMAGE, self.icons[8])
        self.set_ref(CANVAS, "drawerIcon", IMAGE, self.icons[9])
        self.set_ref(CANVAS, "wifiIcon", IMAGE, self.icons[10])
        self.set_ref(CANVAS, "settingsMini", IMAGE, self.icons[11])
        self.set_ref(MIDLET, "store", STORE, self.store)
        self.selected = ctypes.c_uint32()
        if lib.e63_ui_int_array(self.vm, 18, ctypes.byref(self.selected)):
            raise AssertionError("selection array allocation")
        if lib.e63_ui_set_array(self.vm, self.midlet,
                               self.field(MIDLET, "selected", "[I"),
                               self.selected.value):
            raise AssertionError("selection array field")
        self.set_int(CANVAS, "w", "I", width)
        self.set_int(CANVAS, "h", "I", height)
        self.set_int(MIDLET, "widgetsTab", "Z", 1)

    def field(self, owner: str, name: str, kind: str):
        n = self.lib.e63_dex_field_id(ctypes.byref(self.view), owner.encode(),
                                      name.encode(), kind.encode())
        if n < 0:
            raise AssertionError(f"absent field {owner}->{name}:{kind}")
        return n

    def object(self, name: str):
        handle = ctypes.c_uint32()
        rc = self.lib.e63_ui_object(self.vm, name.encode(), ctypes.byref(handle))
        if rc:
            raise AssertionError(("guest object", name, rc))
        return handle.value

    def host_object(self, name: str, native_id: int):
        handle = ctypes.c_uint32()
        rc = self.lib.e63_ui_host_object(self.vm, name.encode(), native_id,
                                         ctypes.byref(handle))
        if rc:
            raise AssertionError(("host object", name, rc))
        return handle.value

    def set_ref(self, owner: str, name: str, kind: str, reference: int):
        receiver = {CANVAS: self.canvas, MIDLET: self.midlet, STORE: self.store}[owner]
        rc = self.lib.e63_ui_set_ref(self.vm, receiver,
                                     self.field(owner, name, kind), reference)
        if rc:
            raise AssertionError(("typed field ref", name, rc))

    def set_int(self, owner: str, name: str, kind: str, value: int):
        receiver = {CANVAS: self.canvas, MIDLET: self.midlet, STORE: self.store}[owner]
        rc = self.lib.e63_ui_set_int(self.vm, receiver,
                                     self.field(owner, name, kind), value)
        if rc:
            raise AssertionError(("typed field int", name, rc))

    def get_int(self, owner: str, name: str, kind: str):
        receiver = {CANVAS: self.canvas, MIDLET: self.midlet, STORE: self.store}[owner]
        result = ctypes.c_int32()
        rc = self.lib.e63_ui_get_int(self.vm, receiver,
                                     self.field(owner, name, kind),
                                     ctypes.byref(result))
        if rc:
            raise AssertionError(("typed field read", name, rc))
        return result.value

    def call(self, method: str = "paintAppDrawer"):
        return self.lib.e63_ui_call_ref(self.vm, self.canvas,
                                        method.encode(), PAINT_PROTO.encode(),
                                        self.graphics)

    def event(self, method: str, prototype: str, *parameters: int):
        params = (ctypes.c_int32 * len(parameters))(*parameters) if parameters else None
        output = ctypes.c_int32()
        return self.lib.e63_ui_call(self.vm, self.canvas, method.encode(),
                                    prototype.encode(), params, len(parameters),
                                    ctypes.byref(output))

    def close(self):
        if self.vm:
            self.lib.e63_ui_free(self.vm)
            self.vm = None


class NativeGuestPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("gcc")
        if not cc:
            raise unittest.SkipTest("GCC required for C99 guest painter")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.root = Path(cls.tmp.name)
        so = cls.root / "libui_paint.so"
        subprocess.run([cc, "-std=c99", "-O2", "-Wall", "-Wextra",
                        "-Werror", "-pedantic", "-shared", "-fPIC",
                        str(ROOT / "symbian/runtime/dex_preflight.c"),
                        str(ROOT / "symbian/runtime/ui_event_vm.c"),
                        "-o", str(so)], check=True)
        cls.lib = ctypes.CDLL(str(so))
        cls.lib.e63_dex_open.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.POINTER(DexView)]
        cls.lib.e63_dex_open.restype = ctypes.c_int
        cls.lib.e63_ui_new.argtypes = [ctypes.POINTER(DexView), GAME,
                                       ctypes.c_void_p]
        cls.lib.e63_ui_new.restype = ctypes.c_void_p
        for name, args in (
            ("e63_ui_free", [ctypes.c_void_p]),
            ("e63_ui_set_viewport", [ctypes.c_void_p, ctypes.c_uint16,
                                      ctypes.c_uint16]),
            ("e63_ui_set_paint_host", [ctypes.c_void_p, ctypes.POINTER(PaintHost)]),
            ("e63_ui_object", [ctypes.c_void_p, ctypes.c_char_p,
                               ctypes.POINTER(ctypes.c_uint32)]),
            ("e63_ui_host_object", [ctypes.c_void_p, ctypes.c_char_p,
                                    ctypes.c_int32, ctypes.POINTER(ctypes.c_uint32)]),
            ("e63_dex_field_id", [ctypes.POINTER(DexView), ctypes.c_char_p,
                                   ctypes.c_char_p, ctypes.c_char_p]),
            ("e63_ui_set_ref", [ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.c_uint32, ctypes.c_uint32]),
            ("e63_ui_int_array", [ctypes.c_void_p, ctypes.c_uint32,
                                   ctypes.POINTER(ctypes.c_uint32)]),
            ("e63_ui_set_array", [ctypes.c_void_p, ctypes.c_uint32,
                                   ctypes.c_uint32, ctypes.c_uint32]),
            ("e63_ui_array_set", [ctypes.c_void_p, ctypes.c_uint32,
                                   ctypes.c_uint32, ctypes.c_int32]),
            ("e63_ui_set_int", [ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.c_uint32, ctypes.c_int32]),
            ("e63_ui_get_int", [ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.c_uint32, ctypes.POINTER(ctypes.c_int32)]),
            ("e63_ui_call_ref", [ctypes.c_void_p, ctypes.c_uint32,
                                  ctypes.c_char_p, ctypes.c_char_p,
                                  ctypes.c_uint32]),
            ("e63_ui_call", [ctypes.c_void_p, ctypes.c_uint32,
                              ctypes.c_char_p, ctypes.c_char_p,
                              ctypes.POINTER(ctypes.c_int32), ctypes.c_uint32,
                              ctypes.POINTER(ctypes.c_int32)])):
            method = getattr(cls.lib, name)
            method.argtypes = args
            method.restype = None if name == "e63_ui_free" else ctypes.c_int
        cls.original = DEX.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compare(self, width=320, height=240, widgets=True, installed=False):
        label = "tab%d_install%d_%dx%d" % (widgets, installed, width, height)
        ui = JavaMEUI(APK, self.root / label, width, height)
        ui.tick(2100)
        ui.key(49)  # actual guest app drawer
        if widgets:
            ui.key(57)  # actual guest Widgets tab
        self.assertEqual(ui.app.fields[MIDLET + "->screen:I"], 14)
        self.assertEqual(bool(ui.app.fields[MIDLET + "->widgetsTab:Z"]), widgets)
        # Same synthetic package state on both VMs, set *before* guest paint.
        # The real INSTALL→OPEN flow has a separate end-to-end OS/VFS test.
        python_store = ui.app.fields[MIDLET + "->store:" + STORE]
        python_store.fields[STORE + "->installed:Z"] = int(installed)
        expected = Image.open(BytesIO(ui.png())).convert("RGB")
        native = NativePaint(self.lib, self.original, ui, width, height)
        native.set_int(MIDLET, "widgetsTab", "Z", int(widgets))
        native.set_int(STORE, "installed", "Z", int(installed))
        return ui, native, expected

    def test_drawer_widgets_body_matches_original_guest_pixels_at_two_sizes(self):
        for width, height in ((320, 240), (220, 180)):
            with self.subTest(width=width, height=height):
                ui, native, expected = self.compare(width, height)
                try:
                    self.assertEqual(native.call(), 0)
                    self.assertEqual(native.commits, 1)
                    self.assertGreaterEqual(len(native.batch), 10)
                    self.assertIn("No widgets installed", [o[5] for o in native.batch])
                    self.assertIn("Landroid/j2me/edition/E63Canvas;->paintAppDrawer"
                                  + PAINT_PROTO, ui.executed_methods)
                    region = (0, 18, width, height - 32)
                    diff = ImageChops.difference(native.frame.crop(region),
                                                 expected.crop(region))
                    self.assertIsNone(diff.getbbox(), "guest body differs at %s" % (region,))
                finally:
                    native.close()

    def test_installed_and_uninstalled_apps_drawer_uses_guest_images_and_labels(self):
        for width, height, installed in ((320, 240, False), (320, 240, True),
                                         (220, 180, False), (220, 180, True)):
            with self.subTest(width=width, installed=installed):
                ui, native, expected = self.compare(width, height, widgets=False,
                                                    installed=installed)
                try:
                    self.assertEqual(native.call(), 0)
                    ids = [o[1] for o in native.batch if o[0] == 5]
                    self.assertEqual(len(ids), 3 if installed else 2)
                    self.assertEqual(ids, ([3, 1, 2] if installed else [1, 2]))
                    self.assertEqual(native.commits, 1)
                    region = (0, 18, width, height - 32)
                    diff = ImageChops.difference(native.frame.crop(region),
                                                 expected.crop(region))
                    self.assertIsNone(diff.getbbox(),
                            "C guest paint != Python guest paint on apps %s" % (region,))
                finally:
                    native.close()

    def test_mutated_original_dex_literal_changes_native_graphics_not_host(self):
        ui, native, expected = self.compare()
        changed = bytearray(self.original)
        before, after = b"No widgets installed\x00", b"No widgets available\x00"
        self.assertEqual(len(before), len(after))
        self.assertEqual(changed.count(before), 1)
        offset = changed.index(before)
        changed[offset:offset+len(before)] = after
        changed[12:32] = hashlib.sha1(changed[32:]).digest()
        struct.pack_into("<I", changed, 8, zlib.adler32(changed[12:]) & 0xffffffff)
        mutated = NativePaint(self.lib, bytes(changed), ui, 320, 240)
        try:
            self.assertEqual(native.call(), 0)
            self.assertEqual(mutated.call(), 0)
            self.assertIn("No widgets available", [o[5] for o in mutated.batch])
            self.assertNotIn("No widgets available", [o[5] for o in native.batch])
            region = (0, 18, 320, 208)
            self.assertIsNotNone(ImageChops.difference(mutated.frame.crop(region),
                                                      expected.crop(region)).getbbox())
        finally:
            native.close()
            mutated.close()

    def test_paint_failure_discards_batch_and_restores_guest_fields(self):
        ui, native, _ = self.compare()
        try:
            native.fail_metrics = True  # after setColor/fillRect/text staging
            self.assertEqual(native.call(), -3)
            self.assertEqual(native.commits, 0)
            self.assertIsNone(native.frame)
            self.assertEqual(native.get_int(CANVAS, "w", "I"), 320)
            self.assertEqual(native.get_int(MIDLET, "widgetsTab", "Z"), 1)
            native.fail_metrics = False
            native.reject_commit = True  # host refuses an entire frame atomically
            self.assertEqual(native.call(), -3)
            self.assertEqual(native.commits, 0)
            native.reject_commit = False
            self.assertEqual(native.call(), 0)
            self.assertEqual(native.commits, 1)
            native.set_int(CANVAS, "w", "I", 201)
            native.set_int(CANVAS, "h", "I", 163)
            self.assertEqual(native.lib.e63_ui_call_ref(native.vm, native.canvas,
                b"paint", PAINT_PROTO.encode(), native.graphics), -3)
            # paint first writes w/h from getWidth/Height; the unsupported
            # setClip must undo these guest field writes and discard the batch.
            self.assertEqual(native.get_int(CANVAS, "w", "I"), 201)
            self.assertEqual(native.get_int(CANVAS, "h", "I"), 163)
            self.assertEqual(native.commits, 1)
        finally:
            native.close()

    def test_bad_image_metadata_fails_after_staging_without_partial_commit(self):
        _, native, _ = self.compare(widgets=False, installed=True)
        try:
            native.fail_image_bounds = True
            self.assertEqual(native.call(), -3)
            self.assertEqual(native.commits, 0)
            self.assertIsNone(native.frame)
            native.fail_image_bounds = False
            self.assertEqual(native.call(), 0)
            self.assertEqual(native.commits, 1)
            self.assertEqual([o[1] for o in native.batch if o[0] == 5],
                             [3, 1, 2])
        finally:
            native.close()

    def test_c99_cli_on_real_dex_with_address_and_undefined_sanitizers(self):
        exe = self.root / "paint_asan"
        subprocess.run([shutil.which("gcc"), "-std=c99", "-O1", "-g",
                        "-Wall", "-Wextra", "-Werror", "-pedantic",
                        "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
                        str(ROOT / "symbian/runtime/dex_preflight.c"),
                        str(ROOT / "symbian/runtime/ui_event_vm.c"),
                        str(ROOT / "symbian/runtime/ui_paint_cli.c"),
                        "-o", str(exe)], check=True)
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1")
        proof = subprocess.run([str(exe), str(DEX)], env=env,
                               capture_output=True, text=True, check=True)
        self.assertEqual(proof.stdout.count("original DEX drawer:"), 4)
        self.assertIn("font fault/atomic frame rejection: no partial commit",
                      proof.stdout)
        self.assertEqual(proof.stderr, "")

    def test_host_types_and_graphics_reference_are_restricted(self):
        ui, native, _ = self.compare()
        try:
            handle = ctypes.c_uint32()
            self.assertEqual(native.lib.e63_ui_host_object(native.vm,
                             b"Ljavax/microedition/lcdui/Form;", 0,
                             ctypes.byref(handle)), -3)
            self.assertEqual(native.lib.e63_ui_host_object(native.vm,
                             FONT.encode(), 123,
                             ctypes.byref(handle)), -3)
            self.assertEqual(native.lib.e63_ui_set_ref(native.vm, native.canvas,
                             native.field(CANVAS, "small", FONT),
                             native.graphics), -1)
            self.assertEqual(native.lib.e63_ui_call_ref(native.vm, native.canvas,
                             b"paintAppDrawer", PAINT_PROTO.encode(),
                             native.small), -1)
            self.assertEqual(native.commits, 0)
        finally:
            native.close()


if __name__ == "__main__":
    unittest.main()
