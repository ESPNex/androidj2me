"""Offline proofs for the native E63 pack; no phone or emulator is exercised.

The compiled Symbian host reads the same binary pack layout. Here the desktop
VM and raster receive ONLY resources decoded from that pre-generated pack,
then all pixels are compared with the independent Python guest reference.
"""
from __future__ import annotations

import ctypes
import struct
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont

import test_native_rgb565 as frames
from test_native_ui_paint import (COMMIT, FONT_HEIGHT, FONT_WIDTH, IMAGE_BOUNDS,
                                  PaintHost, RESOURCE, ROOT)

PACK = ROOT / "symbian/resources/e63assets.bin"
IM_FMT = "<IIIII"
GL_FMT = "<IIIIIiiIII"


class Pack:
    def __init__(self):
        self.raw = PACK.read_bytes()
        self.pinned = ctypes.create_string_buffer(self.raw)
        magic, image_count, glyph_count, size = struct.unpack_from("<8sIII", self.raw)
        assert magic == b"E63RSC01" and image_count == 11 and 0 < glyph_count < 8000
        assert len(self.raw) == size
        table_end = 20 + 20 * image_count + 40 * glyph_count
        self.images = {}
        self.glyphs = {}
        for i in range(image_count):
            ident, w, h, offset, n = struct.unpack_from(IM_FMT, self.raw, 20 + 20 * i)
            assert ident == i + 1 and 0 < w <= 512 and 0 < h <= 512
            assert n == w * h * 4 and table_end <= offset <= size - n
            self.images[ident] = (w, h, offset, n)
        for i in range(glyph_count):
            loc = 20 + 20 * image_count + 40 * i
            (font, text_len, advance, w, h, left, top,
             text_off, mask_off, mask_len) = struct.unpack_from(GL_FMT, self.raw, loc)
            assert font in (0, 8, 16) and 0 <= text_len <= 160
            assert table_end <= text_off <= size - text_len
            assert table_end <= mask_off <= size - mask_len
            assert mask_len == max(1, w) * max(1, h)
            text = self.raw[text_off:text_off + text_len].decode("ascii")
            assert (font, text) not in self.glyphs
            self.glyphs[(font, text)] = (advance, w, h, left, top, mask_off, mask_len)
        assert len(self.glyphs) == glyph_count
        assert list(self.glyphs) == sorted(self.glyphs), "native binary-search ordering"

    def pin(self, offset):
        return ctypes.addressof(self.pinned) + offset


class SymbianResourcePackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = Pack()
        frames.NativeRgb565Tests.setUpClass()
        cls.proof = frames.NativeRgb565Tests()

    @classmethod
    def tearDownClass(cls):
        frames.NativeRgb565Tests.tearDownClass()

    def test_images_are_original_launcher_apk_j2me_pngs(self):
        with ZipFile(ROOT / "apks/Launcher.apk") as archive:
            self.assertEqual(archive.read("classes.dex"),
                             (ROOT / "j2me/classes.dex").read_bytes())
            for index, path in RESOURCE.items():
                img = Image.open(BytesIO(archive.read("assets/j2me" + path))).convert("RGBA")
                w, h, offset, n = self.pack.images[index]
                self.assertEqual((w, h), img.size)
                self.assertEqual(self.pack.raw[offset:offset+n], img.tobytes())

    def test_masks_and_metrics_are_from_same_pillow_font_as_pc_reference(self):
        for point, font_id, sample in ((11,8,"09:07"), (13,0,"QUICK SETTINGS"),
                                       (17,16,"No notifications"),
                                       (11,8,"100%"), (11,8,"No service")):
            with self.subTest(sample=sample):
                font = ImageFont.truetype("DejaVuSans.ttf", point)
                left, top, right, bottom = font.getbbox(sample, anchor="lt")
                advance, w, h, x, y, offset, n = self.pack.glyphs[(font_id, sample)]
                self.assertEqual((w, h, x, y, advance),
                                 (right-left, bottom-top, left, top,
                                  int(font.getlength(sample))))
                mask = Image.new("L",(max(1,w),max(1,h)),0)
                ImageDraw.Draw(mask).text((-left,-top),sample,
                                          font=font,fill=255,anchor="lt")
                self.assertEqual(self.pack.raw[offset:offset+n], mask.tobytes())

    def test_seven_guest_screens_raster_identical_with_only_packed_resources(self):
        pack = self.pack
        scenarios = ((1,False,False,-1,False,False),
                     (1,False,True,20,True,True),
                     (14,False,False,100,True,False),
                     (14,False,True,0,True,True),
                     (14,True,False,-1,False,False),
                     (10,False,False,-1,False,False),
                     (13,False,True,20,True,True),
                     (15,False,False,57,False,False),
                     (16,False,False,100,True,True),
                     (17,False,False,-1,False,False))
        for screen,widgets,installed,battery,wifi,adjust in scenarios:
            with self.subTest(screen=screen,widgets=widgets,installed=installed,
                              battery=battery,wifi=wifi,adjust=adjust):
                native, frame, expected = self.proof.full_scene(
                    320,240,screen=screen,battery=battery,wifi=wifi,
                    adjust=adjust,widgets=widgets,installed=installed)
                problems = []
                lib = self.proof.lib
                raster = None
                try:
                    @frames.IMAGE_RGBA
                    def image(_, image_id, out):
                        if image_id not in pack.images: problems.append(("image",image_id)); return 1
                        w,h,offset,n = pack.images[image_id]
                        out[0] = frames.RgbaResource(pack.pin(offset),n,w*4,w,h)
                        return 0

                    @frames.GLYPH_MASK
                    def mask(_, font, label, out):
                        key = (font, label.decode("ascii"))
                        if key not in pack.glyphs: problems.append(("mask",key)); return 1
                        advance,w,h,left,top,offset,n = pack.glyphs[key]
                        out[0] = frames.GlyphResource(pack.pin(offset),n,max(1,w),
                                                      w,h,left,top)
                        return 0

                    @FONT_HEIGHT
                    def height(_,font,out):
                        if font not in (0,8,16): return 1
                        out[0] = {0:14,8:12,16:18}[font]
                        return 0

                    @FONT_WIDTH
                    def width(_,font,label,out):
                        key = (font,label.decode("ascii"))
                        if key not in pack.glyphs: problems.append(("width",key)); return 1
                        out[0] = pack.glyphs[key][0]
                        return 0

                    @IMAGE_BOUNDS
                    def bounds(_,image_id,w,h):
                        if image_id not in pack.images: return 1
                        w[0],h[0] = pack.images[image_id][:2]
                        return 0

                    resources = frames.Resources(None,image,mask)
                    raster = lib.e63_rgb565_new(320,240,ctypes.byref(resources))
                    self.assertTrue(raster)
                    @COMMIT
                    def commit(_,ops,count):
                        return lib.e63_rgb565_commit(raster,ops,count)

                    host = PaintHost(None,height,width,bounds,commit,native.callbacks[5])
                    self.assertEqual(native.lib.e63_ui_set_paint_host(native.vm,
                                        ctypes.byref(host)),0)
                    self.assertEqual(native.call("paint"),0,problems)
                    self.assertEqual(problems,[])
                    self.assertEqual(list(lib.e63_rgb565_pixels(raster)[:320*240]),
                                     frames.quantize_rgb565(expected,(0,0,320,240)))
                finally:
                    if raster: lib.e63_rgb565_free(raster)
                    native.close();frame.close()


if __name__ == "__main__": unittest.main()
