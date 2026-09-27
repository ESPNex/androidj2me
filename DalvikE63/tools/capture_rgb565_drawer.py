#!/usr/bin/env python3
"""Visual PC proof of C99 RGB565 pixel compositing from guest drawer DEX.

Only y=18..208 is guest-painted by C99 here. Font coverage and decoded icon
bytes are device resources supplied by the same signed APK/Pillow test shim;
C99 owns raster coordinates, clipping, blending, framebuffer and atomic swap.
This is NOT a complete Canvas.paint or Symbian/Android/E63 screenshot.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from test_native_rgb565 import NativeRgb565Tests, quantize_rgb565  # noqa: E402

DEST = ROOT / "assets/preview_rgb565_pc.png"


def expand565(color: int) -> tuple[int, int, int]:
    return (((color >> 11) & 31) * 255 // 31,
            ((color >> 5) & 63) * 255 // 63,
            (color & 31) * 255 // 31)


def main() -> None:
    NativeRgb565Tests.setUpClass()
    try:
        guest = NativeRgb565Tests()
        conditions = (("Apps / before install", False, False),
                      ("Apps / after install", False, True),
                      ("Widgets / empty", True, False))
        gap, width, body_h = 14, 320, 190
        top, row = 96, body_h + 42
        sheet = Image.new("RGB", (gap + 2 * (width + gap), top + 3 * row),
                          (20, 24, 29))
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 13)
        except OSError:
            font = ImageFont.load_default()
        draw.text((gap, 5), "Drawer crop: original guest DEX, RGB565 native PC raster",
                  fill=(225, 233, 241), font=font)
        draw.text((gap, 27), "Left: C99 framebuffer. Right: Python guest quantized to RGB565.",
                  fill=(164, 191, 212), font=font)
        draw.text((gap, 48), "Assets and glyph masks: PC host; no full paint, S60 or SIS.",
                  fill=(164, 191, 212), font=font)
        for index, (title, widgets, installed) in enumerate(conditions):
            native, frame, expected = guest.scene(widgets=widgets, installed=installed)
            try:
                if native.call() != 0:
                    raise RuntimeError("C99 guest draw/raster failed for " + title)
                region = (0, 18, width, 208)
                actual = frame.pixels()
                left565 = [actual[y * width + x]
                           for y in range(region[1], region[3])
                           for x in range(width)]
                right565 = quantize_rgb565(expected, region)
                if left565 != right565:
                    raise RuntimeError("C99/Python RGB565 differs: " + title)
                left = Image.new("RGB", (width, body_h))
                left.putdata([expand565(color) for color in left565])
                right = Image.new("RGB", (width, body_h))
                right.putdata([expand565(color) for color in right565])
                y = top + index * row
                draw.text((gap, y - 19), title + "  |  C99/Python: identical RGB565 pixels",
                          fill=(211, 224, 233), font=font)
                sheet.paste(left, (gap, y))
                sheet.paste(right, (gap * 2 + width, y))
            finally:
                native.close()
                frame.close()
        DEST.parent.mkdir(exist_ok=True)
        sheet.save(DEST, optimize=True)
        print(f"{DEST}: three C99 RGB565 crops, pixel parity proven")
    finally:
        NativeRgb565Tests.tearDownClass()


if __name__ == "__main__":
    main()
