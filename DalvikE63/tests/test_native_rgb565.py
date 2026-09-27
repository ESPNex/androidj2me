"""Portable C99 RGB565 renderer of ORIGINAL guest Canvas.paint DEX.

Seven complete scenes (including guest status/nav and battery) are pixel-tested
against the same guest DEX run in the Python VM at two sizes. Font/PNG resource
callbacks use Pillow and APK images, not host UI layout. No Symbian Window
Server, hardware evidence, complete MIDP lifecycle, all screens or SIS.
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

from PIL import Image, ImageDraw

from dalvik.ui_vm import MIDLET
from dalvik.ui_vm import CANVAS
from dalvik.dex_j2me import J2MEDex
import test_native_ui_paint as harness
from test_native_ui_paint import COMMIT, DrawOp, PaintHost, RESOURCE, ROOT, STORE


class RgbaResource(ctypes.Structure):
    _fields_ = [("pixels", ctypes.c_void_p), ("size", ctypes.c_size_t),
                ("stride", ctypes.c_uint32), ("width", ctypes.c_int32),
                ("height", ctypes.c_int32)]


class GlyphResource(ctypes.Structure):
    _fields_ = [("alpha", ctypes.c_void_p), ("size", ctypes.c_size_t),
                ("stride", ctypes.c_uint32), ("width", ctypes.c_int32),
                ("height", ctypes.c_int32), ("left", ctypes.c_int32),
                ("top", ctypes.c_int32)]


IMAGE_RGBA = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                             ctypes.c_int32, ctypes.POINTER(RgbaResource))
GLYPH_MASK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                             ctypes.c_int32, ctypes.c_char_p,
                             ctypes.POINTER(GlyphResource))


class Resources(ctypes.Structure):
    _fields_ = [("context", ctypes.c_void_p), ("image_rgba", IMAGE_RGBA),
                ("text_mask", GLYPH_MASK)]


class NativeFrame:
    """Test resource adapter; raster/atomic frame ownership stays with C."""
    def __init__(self, lib, native, ui, width, height):
        self.lib, self.native, self.ui = lib, native, ui
        self.width, self.height = width, height
        self.fail_image = False
        self.fail_text = False
        self.bad_mask_stride = False
        self.pinned: dict[tuple, ctypes.Array] = {}

        @IMAGE_RGBA
        def image(_, resource_id, out):
            if self.fail_image or resource_id not in RESOURCE:
                return 1
            try:
                picture = Image.open(BytesIO(ui.host.images[RESOURCE[resource_id]]))
                picture = picture.convert("RGBA")
                raw = picture.tobytes()
                pinned = ctypes.create_string_buffer(raw)
                self.pinned[("image", resource_id)] = pinned
                out[0] = RgbaResource(ctypes.addressof(pinned), len(raw),
                                       picture.width * 4, picture.width,
                                       picture.height)
                return 0
            except (OSError, ValueError, KeyError):
                return 1

        @GLYPH_MASK
        def glyph(_, size, raw_text, out):
            if self.fail_text:
                return 1
            try:
                label = raw_text.decode("ascii")
                font = ui.host.font(size)
                left, top, right, bottom = font.getbbox(label, anchor="lt")
                w, h = right - left, bottom - top
                mask = Image.new("L", (max(1, w), max(1, h)), 0)
                ImageDraw.Draw(mask).text((-left, -top), label, font=font,
                                          fill=255, anchor="lt")
                raw = mask.tobytes()
                pinned = ctypes.create_string_buffer(raw)
                self.pinned[("font", size, label)] = pinned
                out[0] = GlyphResource(ctypes.addressof(pinned), len(raw),
                                       0 if self.bad_mask_stride else mask.width,
                                       w, h, left, top)
                return 0
            except (UnicodeError, OSError, ValueError):
                return 1

        self.callbacks = (image, glyph)
        self.resources = Resources(None, image, glyph)
        self.handle = lib.e63_rgb565_new(width, height,
                                          ctypes.byref(self.resources))
        if not self.handle:
            raise AssertionError("bounded C99 RGB565 allocation failed")

        @COMMIT
        def commit(_, ops, count):
            return lib.e63_rgb565_commit(self.handle, ops, count)

        self.commit_callback = commit
        self.paint_host = PaintHost(None, native.callbacks[1],
                                    native.callbacks[2], native.callbacks[3],
                                    commit, native.callbacks[5])
        if native.lib.e63_ui_set_paint_host(native.vm,
                                           ctypes.byref(self.paint_host)):
            raise AssertionError("C renderer attachment")

    def pixels(self):
        raw = self.lib.e63_rgb565_pixels(self.handle)
        return list(raw[:self.width * self.height])

    def frames(self):
        return self.lib.e63_rgb565_frames(self.handle)

    def close(self):
        if self.handle:
            self.lib.e63_rgb565_free(self.handle)
            self.handle = None


def quantize_rgb565(image: Image.Image, region):
    left, top, right, bottom = region
    rgb = image.convert("RGB").load()
    result = []
    for y in range(top, bottom):
        for x in range(left, right):
            r, g, b = rgb[x, y]
            result.append((r >> 3) << 11 | (g >> 2) << 5 | (b >> 3))
    return result


class NativeRgb565Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("gcc"):
            raise unittest.SkipTest("GCC required for C99 RGB565 proof")
        harness.NativeGuestPaintTests.setUpClass()
        cls.guest = harness.NativeGuestPaintTests()
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.base = Path(cls.tmp.name)
        shared = cls.base / "librgb565.so"
        subprocess.run([shutil.which("gcc"), "-std=c99", "-O2",
                        "-Wall", "-Wextra", "-Werror", "-pedantic",
                        "-fPIC", "-shared",
                        str(ROOT / "symbian/runtime/rgb565_painter.c"),
                        "-o", str(shared)], check=True)
        cls.lib = ctypes.CDLL(str(shared))
        cls.lib.e63_rgb565_new.argtypes = [ctypes.c_uint16, ctypes.c_uint16,
                                           ctypes.POINTER(Resources)]
        cls.lib.e63_rgb565_new.restype = ctypes.c_void_p
        cls.lib.e63_rgb565_free.argtypes = [ctypes.c_void_p]
        cls.lib.e63_rgb565_free.restype = None
        cls.lib.e63_rgb565_commit.argtypes = [ctypes.c_void_p,
                                               ctypes.POINTER(DrawOp),
                                               ctypes.c_uint32]
        cls.lib.e63_rgb565_commit.restype = ctypes.c_int
        cls.lib.e63_rgb565_pixels.argtypes = [ctypes.c_void_p]
        cls.lib.e63_rgb565_pixels.restype = ctypes.POINTER(ctypes.c_uint16)
        cls.lib.e63_rgb565_frames.argtypes = [ctypes.c_void_p]
        cls.lib.e63_rgb565_frames.restype = ctypes.c_uint32

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        harness.NativeGuestPaintTests.tearDownClass()

    def scene(self, width=320, height=240, widgets=False, installed=False):
        ui, native, expected = self.guest.compare(width, height, widgets,
                                                   installed)
        try:
            frame = NativeFrame(self.lib, native, ui, width, height)
        except Exception:
            native.close()
            raise
        return native, frame, expected

    def full_scene(self, width=320, height=240, screen=14, *,
                   battery=-1, wifi=False, adjust=False, widgets=False,
                   installed=False):
        native, frame, _ = self.scene(width, height, widgets, installed)
        ui = native.ui
        ui.host.now_ms = int(datetime(2020, 1, 1, 9, 7).timestamp() * 1000)
        for name, typ, datum in (("screen", "I", screen),
                                 ("battery", "I", battery),
                                 ("wifiOn", "Z", int(wifi)),
                                 ("adjustClock", "Z", int(adjust)),
                                 ("recentsOrigin", "I", ui.app.fields[
                                     MIDLET + "->recentsOrigin:I"]),
                                 ("recentScreen", "I", ui.app.fields[
                                     MIDLET + "->recentScreen:I"])):
            ui.app.fields[MIDLET + "->" + name + ":" + typ] = datum
            native.set_int(MIDLET, name, typ, datum)
        expected = Image.open(BytesIO(ui.png())).convert("RGB")
        return native, frame, expected

    def test_full_canvas_paints_seven_guest_screens_pixel_identically(self):
        # Original E63Canvas.paint chooses the screen and runs paintStatus,
        # batteryPercent, paintNav and the selected body in ONE atomic frame.
        conditions = ((1, False, False, -1, False, False),
                      (1, False, True, 20, True, True),
                      (14, False, False, 100, True, False),
                      (14, False, True, 0, True, True),
                      (14, True, False, -1, False, False),
                      (10, False, False, -1, False, False),
                      (13, False, True, 20, True, True),
                      (15, False, False, 57, False, False),
                      (16, False, False, 100, True, True),
                      (17, False, False, -1, False, False))
        for width, height in ((320, 240), (220, 180)):
            for screen, widgets, installed, battery, wifi, adjust in conditions:
                with self.subTest(size=(width, height), screen=screen,
                                  widgets=widgets, installed=installed,
                                  battery=battery, wifi=wifi, adjust=adjust):
                    native, frame, expected = self.full_scene(
                        width, height, screen, battery=battery, wifi=wifi,
                        adjust=adjust, widgets=widgets, installed=installed)
                    try:
                        self.assertEqual(native.call("paint"), 0)
                        self.assertEqual(frame.frames(), 1)
                        self.assertEqual(frame.pixels(),
                                         quantize_rgb565(expected,
                                                         (0, 0, width, height)))
                        self.assertEqual(native.get_int(CANVAS, "w", "I"), width)
                        self.assertEqual(native.get_int(CANVAS, "h", "I"), height)
                    finally:
                        native.close()
                        frame.close()

    def test_guest_input_to_screen_state_to_full_rgb565_roundtrip(self):
        native, frame, _ = self.full_scene(screen=1, battery=57, wifi=True)
        try:
            ui = native.ui
            for key in (49, 57):  # guest Home -> Apps -> Widgets
                ui.key(key)
                self.assertEqual(native.event("keyPressed", "(I)V", key), 0)
                self.assertEqual(native.get_int(MIDLET, "screen", "I"),
                                 ui.app.fields[MIDLET + "->screen:I"])
                self.assertEqual(native.get_int(MIDLET, "widgetsTab", "Z"),
                                 ui.app.fields[MIDLET + "->widgetsTab:Z"])
                expected = Image.open(BytesIO(ui.png())).convert("RGB")
                self.assertEqual(native.call("paint"), 0)
                self.assertEqual(frame.pixels(),
                                 quantize_rgb565(expected, (0, 0, 320, 240)))
            ui.pointer(160, 220)  # guest bottom Home button
            self.assertEqual(native.event("pointerPressed", "(II)V",
                                          160, 220), 0)
            self.assertEqual(native.get_int(MIDLET, "screen", "I"), 1)
            expected = Image.open(BytesIO(ui.png())).convert("RGB")
            self.assertEqual(native.call("paint"), 0)
            self.assertEqual(frame.frames(), 3)
            self.assertEqual(frame.pixels(),
                             quantize_rgb565(expected, (0, 0, 320, 240)))
        finally:
            native.close()
            frame.close()

    def test_status_bar_narrow_fallback_is_chosen_by_guest(self):
        native, frame, expected = self.full_scene(100, 115, screen=14,
                                                   battery=86, wifi=True)
        try:
            self.assertEqual(native.call("paintStatus"), 0)
            self.assertEqual(frame.frames(), 1)
            front = frame.pixels()
            status = front[:100 * 18]
            self.assertEqual(status,
                             quantize_rgb565(expected, (0, 0, 100, 18)))
            self.assertTrue(all(pixel == 0 for pixel in front[100 * 18:]))
        finally:
            native.close()
            frame.close()

    def test_battery_glyph_changes_when_original_clinit_dex_changes(self):
        native, frame, expected = self.full_scene(screen=14, battery=20)
        parsed = J2MEDex(harness.DEX.read_bytes())
        clinit = parsed.methods[CANVAS + "-><clinit>()V"]
        glyph_byte = clinit.code_off + 16 + 2 * (112 + 4)
        changed = bytearray(harness.DEX.read_bytes())
        self.assertEqual(changed[glyph_byte], 7)  # first bitmap byte for '0'
        changed[glyph_byte] = 1
        changed[12:32] = hashlib.sha1(changed[32:]).digest()
        struct.pack_into("<I", changed, 8,
                         zlib.adler32(changed[12:]) & 0xffffffff)
        mutated = harness.NativePaint(self.guest.lib, bytes(changed),
                                      native.ui, 320, 240)
        mutant_frame = NativeFrame(self.lib, mutated, native.ui, 320, 240)
        try:
            mutated.set_int(MIDLET, "screen", "I", 14)
            mutated.set_int(MIDLET, "battery", "I", 20)
            mutated.set_int(MIDLET, "widgetsTab", "Z", 0)
            self.assertEqual(native.call("paint"), 0)
            self.assertEqual(mutated.call("paint"), 0)
            original_pixels = quantize_rgb565(expected, (0, 0, 320, 240))
            self.assertEqual(frame.pixels(), original_pixels)
            altered = mutant_frame.pixels()
            changed_positions = [i for i, (a, b) in enumerate(
                zip(altered, original_pixels)) if a != b]
            self.assertGreater(len(changed_positions), 0)
            self.assertTrue(all(i // 320 < 18 for i in changed_positions))
        finally:
            native.close()
            frame.close()
            mutated.close()
            mutant_frame.close()

    def test_full_frame_failure_and_many_repaints_are_atomic_and_bounded(self):
        native, frame, _ = self.full_scene(screen=1, installed=True)
        try:
            self.assertEqual(native.call("paint"), 0)
            self.assertEqual(frame.frames(), 1)
            previous = frame.pixels()
            native.set_int(MIDLET, "screen", "I", 15)
            frame.fail_image = True  # notifications/clock succeeded; nav failed
            self.assertEqual(native.call("paint"), -3)
            self.assertEqual(frame.frames(), 1)
            self.assertEqual(frame.pixels(), previous)
            frame.fail_image = False
            frame.fail_text = True
            self.assertEqual(native.call("paint"), -3)
            self.assertEqual(frame.frames(), 1)
            self.assertEqual(frame.pixels(), previous)
            frame.fail_text = False
            native.set_int(MIDLET, "screen", "I", 2)  # Settings is not ported
            self.assertEqual(native.call("paint"), -3)
            self.assertEqual(frame.frames(), 1)
            self.assertEqual(frame.pixels(), previous)
            native.set_int(MIDLET, "screen", "I", 16)
            # Each clock/percent call allocates managed StringBuffers and
            # strings; 36 full frames exceed the bounded heap if they leak.
            for _ in range(36):
                self.assertEqual(native.call("paint"), 0)
            self.assertEqual(frame.frames(), 37)
            self.assertNotEqual(frame.pixels(), previous)
        finally:
            native.close()
            frame.close()

    def test_native_rgb565_pixels_match_python_guest_quantized_at_two_sizes(self):
        for width, height in ((320, 240), (220, 180)):
            for widgets, installed in ((False, False), (False, True), (True, False)):
                with self.subTest(size=(width, height), widgets=widgets,
                                  installed=installed):
                    native, frame, expected = self.scene(width, height,
                                                          widgets, installed)
                    try:
                        self.assertEqual(native.call(), 0)
                        self.assertEqual(frame.frames(), 1)
                        region = (0, 18, width, height - 32)
                        actual = frame.pixels()
                        body = [actual[y * width + x]
                                for y in range(region[1], region[3])
                                for x in range(region[0], region[2])]
                        self.assertEqual(body, quantize_rgb565(expected, region))
                        self.assertEqual(actual[0], 0)  # status/nav NOT C-painted
                        self.assertEqual(actual[-1], 0)
                    finally:
                        native.close()
                        frame.close()

    def test_original_guest_nav_raster_matches_status_bar_independent_bottom(self):
        # The original Canvas.paintNav DEX, not a C screen drawing shortcut.
        for width, height in ((320, 240), (220, 180)):
            with self.subTest(size=(width, height)):
                native, frame, expected = self.scene(width, height)
                try:
                    self.assertEqual(native.call("paintNav"), 0)
                    self.assertEqual(frame.frames(), 1)
                    actual = frame.pixels()
                    region = (0, height - 32, width, height)
                    bottom = actual[(height - 32) * width:]
                    self.assertEqual(bottom, quantize_rgb565(expected, region))
                    self.assertGreater(sum(bool(pixel) for pixel in bottom), 500)
                    self.assertEqual(actual[0], 0)
                finally:
                    native.close()
                    frame.close()

    def test_raster_or_guest_fault_cannot_publish_partial_frame(self):
        native, frame, _ = self.scene(widgets=True)
        try:
            self.assertEqual(native.call(), 0)
            before = frame.pixels()
            self.assertEqual(frame.frames(), 1)
            native.set_int(MIDLET, "widgetsTab", "Z", 0)
            native.set_int(STORE, "installed", "Z", 1)
            frame.fail_image = True  # fault after background/text was staged
            self.assertEqual(native.call(), -3)
            self.assertEqual(frame.frames(), 1)
            self.assertEqual(frame.pixels(), before)
            frame.fail_image = False
            frame.fail_text = True
            self.assertEqual(native.call(), -3)
            self.assertEqual(frame.frames(), 1)
            self.assertEqual(frame.pixels(), before)
            frame.fail_text = False
            self.assertEqual(native.call(), 0)
            self.assertEqual(frame.frames(), 2)
            self.assertNotEqual(frame.pixels(), before)
        finally:
            native.close()
            frame.close()

    def test_raster_rejects_invalid_resource_geometry_anchor_and_budget(self):
        native, frame, _ = self.scene(widgets=True)
        try:
            frame.bad_mask_stride = True
            self.assertEqual(native.call(), -3)
            self.assertEqual(frame.frames(), 0)
            self.assertTrue(all(pixel == 0 for pixel in frame.pixels()))
            frame.bad_mask_stride = False
            ops = (DrawOp * 3)()
            ops[0].code, ops[0].a = 1, 0xabcdef
            ops[1].code, ops[1].a, ops[1].b, ops[1].c, ops[1].d = (
                2, 0, 18, 320, 100)
            ops[2].code = 99
            self.assertEqual(self.lib.e63_rgb565_commit(frame.handle, ops, 3), 1)
            self.assertEqual(self.lib.e63_rgb565_commit(frame.handle, ops, 257), 1)
            self.assertEqual(frame.frames(), 0)
            ops[2].code, ops[2].a, ops[2].b, ops[2].c, ops[2].d = (
                5, 1, 5, 6, 0)  # image anchor 0 is unsupported
            self.assertEqual(self.lib.e63_rgb565_commit(frame.handle, ops, 3), 1)
            ops[2].code, ops[2].a, ops[2].b, ops[2].c, ops[2].d = (
                7, -2147483648, 0, 2147483647, 0)
            self.assertEqual(self.lib.e63_rgb565_commit(frame.handle, ops, 3), 1)
            ops[2].code, ops[2].a, ops[2].b, ops[2].c, ops[2].d = (
                8, 0, 0, 319, 240)  # no silently ignored partial clip
            self.assertEqual(self.lib.e63_rgb565_commit(frame.handle, ops, 3), 1)
            ops[2].code, ops[2].a, ops[2].b, ops[2].c, ops[2].d = (
                9, 0, 0, 0, 11)  # no zero-sized full arc
            self.assertEqual(self.lib.e63_rgb565_commit(frame.handle, ops, 3), 1)
            self.assertTrue(all(pixel == 0 for pixel in frame.pixels()))
            self.assertEqual(frame.frames(), 0)
            self.assertEqual(native.call(), 0)  # clean commit after rejects
            self.assertEqual(frame.frames(), 1)
        finally:
            native.close()
            frame.close()

    def test_standalone_full_dex_to_rgb565_to_mock_device_under_sanitizers(self):
        exe = self.base / "ui_full_frame_asan"
        subprocess.run([shutil.which("gcc"), "-std=c99", "-O1", "-g",
                        "-Wall", "-Wextra", "-Werror", "-pedantic",
                        "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
                        str(ROOT / "symbian/runtime/dex_preflight.c"),
                        str(ROOT / "symbian/runtime/ui_event_vm.c"),
                        str(ROOT / "symbian/runtime/rgb565_painter.c"),
                        str(ROOT / "symbian/runtime/ui_full_frame_cli.c"),
                        "-o", str(exe)], check=True)
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1")
        result = subprocess.run([str(exe), str(harness.DEX)],
                                capture_output=True, text=True,
                                env=env, check=True)
        self.assertIn("7 complete RGB565 frames + 3 guest-input frames,",
                      result.stdout)
        self.assertIn("mock device present OK", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_rgb565_c_only_cli_runs_under_address_and_undefined_sanitizers(self):
        exe = self.base / "rgb565_asan"
        subprocess.run([shutil.which("gcc"), "-std=c99", "-O1", "-g",
                        "-Wall", "-Wextra", "-Werror", "-pedantic",
                        "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
                        str(ROOT / "symbian/runtime/rgb565_painter.c"),
                        str(ROOT / "symbian/runtime/rgb565_cli.c"),
                        "-o", str(exe)], check=True)
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1")
        result = subprocess.run([str(exe)], capture_output=True, text=True,
                                env=env, check=True)
        self.assertIn("C99 RGB565: pixels and atomic rollback OK", result.stdout)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
