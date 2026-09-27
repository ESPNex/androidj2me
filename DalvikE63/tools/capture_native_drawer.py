#!/usr/bin/env python3
"""PC proof: C99 interprets guest paintAppDrawer and Pillow draws its ops.

Two columns crop the *drawer body only* (y=18..208): full-screen Canvas.paint
and any Symbian rasterizer are NOT implemented in C. This script reuses the
same typed host harness as the pixel-parity tests to avoid a second UI backend.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_native_ui_paint import NativeGuestPaintTests  # noqa: E402

DEST = ROOT / "assets/preview_c99_drawer_pc.png"


def main() -> None:
    NativeGuestPaintTests.setUpClass()
    try:
        suite = NativeGuestPaintTests()
        conditions = (("Apps / before install", False, False),
                      ("Apps / after install", False, True),
                      ("Widgets / empty", True, False))
        gap, width, body_h = 14, 320, 190
        top, row = 95, body_h + 42
        sheet = Image.new("RGB", (gap + 2 * (width + gap), top + 3 * row),
                          (20, 24, 29))
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 13)
        except OSError:
            font = ImageFont.load_default()
        draw.text((gap, 5), "App drawer body - original DEX on two PC interpreters",
                  fill=(228, 235, 241), font=font)
        draw.text((gap, 27), "Left: C99 guest + atomic Pillow host. Right: Python guest + Pillow host.",
                  fill=(166, 189, 208), font=font)
        draw.text((gap, 48), "Only y=18..208; not full paint, Android 4.2, or Nokia output.",
                  fill=(166, 189, 208), font=font)
        for index, (title, widgets, installed) in enumerate(conditions):
            _, native, expected = suite.compare(widgets=widgets, installed=installed)
            try:
                status = native.call()
                if status:
                    raise RuntimeError("native DEX paint failed: %d" % status)
                region = (0, 18, width, 208)
                left = native.frame.crop(region)
                right = expected.crop(region)
                if ImageChops.difference(left, right).getbbox():
                    raise RuntimeError("guest pixel parity failed for " + title)
                y = top + index * row
                draw.text((gap, y - 19), f"{title}  |  {len(native.batch)} guest draw ops  |  equal pixels",
                          fill=(211, 224, 233), font=font)
                sheet.paste(left, (gap, y))
                sheet.paste(right, (gap * 2 + width, y))
            finally:
                native.close()
        DEST.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(DEST, optimize=True)
        print(f"{DEST}: 3 drawer bodies, byte-for-byte equal RGB pixels")
    finally:
        NativeGuestPaintTests.tearDownClass()


if __name__ == "__main__":
    main()
