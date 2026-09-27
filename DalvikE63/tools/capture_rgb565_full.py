#!/usr/bin/env python3
"""Full-frame PC proof: original Canvas.paint DEX -> C99 RGB565 framebuffer.

The DEX owns the selected screen and BOTH bars. Only decoded APK PNGs, font
masks/metrics and deterministic local time come from PC resource callbacks.
The right-hand reference is the same original guest DEX run by the independent
Python interpreter, quantized to RGB565. This is not a Nokia screenshot/SIS.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from test_native_rgb565 import NativeRgb565Tests, quantize_rgb565  # noqa: E402

DEST = ROOT / "assets/preview_rgb565_full_pc.png"


def expand565(color: int) -> tuple[int, int, int]:
    return (((color >> 11) & 31) * 255 // 31,
            ((color >> 5) & 63) * 255 // 63,
            (color & 31) * 255 // 31)


def main() -> None:
    NativeRgb565Tests.setUpClass()
    try:
        fixture = NativeRgb565Tests()
        width, height, gap, top, row = 320, 240, 14, 106, 278
        conditions = (
            ("Home / installata / Wi-Fi / batteria 20%", 1,
             dict(installed=True, battery=20, wifi=True, adjust=True)),
            ("Apps / prima di INSTALL / batteria 100%", 14,
             dict(battery=100, wifi=True)),
            ("Notifiche / batteria sconosciuta", 15,
             dict(battery=-1)),
            ("Quick Settings / Wi-Fi / batteria 57%", 16,
             dict(battery=57, wifi=True, adjust=True)),
        )
        sheet = Image.new("RGB", (gap + 2 * (width + gap),
                                   top + len(conditions) * row),
                          (20, 24, 29))
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 13)
        except OSError:
            font = ImageFont.load_default()
        draw.text((gap, 5), "Canvas.paint DEX originale -> RGB565 C99, frame PC completo",
                  fill=(230, 239, 246), font=font)
        draw.text((gap, 28), "Sinistra: VM+raster C99  |  Destra: guest Python quantizzato",
                  fill=(169, 202, 226), font=font)
        draw.text((gap, 49), "PNG, glifi e orario: callback PC. Stato e UI dal DEX.",
                  fill=(169, 202, 226), font=font)
        draw.text((gap, 70), "Non e' uno screenshot E63: nessun SDK, SIS o test hardware.",
                  fill=(169, 202, 226), font=font)
        for index, (label, screen, kwargs) in enumerate(conditions):
            native, frame, expected = fixture.full_scene(
                width, height, screen=screen, **kwargs)
            try:
                if native.call("paint") != 0 or frame.frames() != 1:
                    raise RuntimeError("C99 full guest frame failed for " + label)
                actual565 = frame.pixels()
                reference565 = quantize_rgb565(expected, (0, 0, width, height))
                if actual565 != reference565:
                    raise RuntimeError("Pixel parity failed for " + label)
                left = Image.new("RGB", (width, height))
                left.putdata([expand565(color) for color in actual565])
                right = Image.new("RGB", (width, height))
                right.putdata([expand565(color) for color in reference565])
                y = top + index * row
                draw.text((gap, y - 22), label + "  |  ogni pixel RGB565 coincide",
                          fill=(211, 224, 233), font=font)
                sheet.paste(left, (gap, y))
                sheet.paste(right, (2 * gap + width, y))
            finally:
                native.close()
                frame.close()
        DEST.parent.mkdir(exist_ok=True)
        sheet.save(DEST, optimize=True)
        print(f"{DEST}: {len(conditions)} full-frame C99/Python RGB565 pairs,"
              " pixel-identical on PC")
    finally:
        NativeRgb565Tests.tearDownClass()


if __name__ == "__main__":
    main()
