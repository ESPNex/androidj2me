#!/usr/bin/env python3
"""Capture the signed Launcher.apk's guest-DEX Canvas, NOT a host-made UI.

The PC host implements only MIDP drawing/input primitives. Labels around the
screenshots are added afterward for documentation; all 320x240 screen pixels
come from E63Canvas.paint(Graphics) in the converted classes.dex.
"""
from __future__ import annotations

import sys
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dalvik.ui_vm import JavaMEUI, MIDLET  # noqa: E402
SCREEN = MIDLET + "->screen:I"
DEST = ROOT / "assets/preview_android42.png"


def main() -> None:
    (ROOT / "build").mkdir(exist_ok=True)
    frames: list[tuple[str, Image.Image]] = []
    with tempfile.TemporaryDirectory(dir=ROOT / "build") as state:
        ui = JavaMEUI(ROOT / "apks/Launcher.apk", Path(state))

        def shot(label: str, expected: int) -> None:
            actual = ui.app.fields[SCREEN]
            if actual != expected:
                raise RuntimeError(f"{label}: guest screen {actual}, expected {expected}")
            pic = Image.open(BytesIO(ui.png())).convert("RGB")
            if pic.size != (320, 240):
                raise RuntimeError("not the E63's 320x240 guest viewport")
            frames.append((label, pic))

        ui.tick(2100)
        shot("01  Home / dock", 1)
        ui.key(49)
        shot("02  Application tray", 14)
        ui.key(35)
        ui.key(51)
        shot("03  Notifications", 15)
        ui.key(-7)
        shot("04  Quick settings", 16)
        ui.pointer(240, 86)
        shot("05  Settings", 2)
        ui.key(-7)  # Local Store switch; not a real Nokia Wi-Fi toggle.
        ui.key(-6)
        ui.key(-7)
        if ui.app.fields[SCREEN] != 4:
            raise RuntimeError("offline local account form not reached")
        ui.key(-2); ui.key(-2); ui.key(-7)
        shot("06  Play Store", 5)
        ui.key(-2); ui.key(-7)
        if ui.app.fields[SCREEN] != 6:
            raise RuntimeError("Store card not reached")
        ui.key(-7); ui.tick(4000)
        shot("07  INSTALL to OPEN", 6)
        ui.key(-7)
        shot("08  File Manager", 8)
        ui.key(35); ui.pointer(280, 222)
        shot("09  Recent screens", 17)

    # The grid/labels are documentation only, never part of the runtime screen.
    gap, label_h, cols = 12, 27, 3
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (gap + cols * (320 + gap),
                              gap + rows * (240 + label_h + gap)), (20, 24, 29))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    for i, (label, pic) in enumerate(frames):
        x = gap + (i % cols) * (320 + gap)
        y = gap + (i // cols) * (240 + label_h + gap)
        draw.text((x + 3, y + 4), label, font=font, fill=(225, 232, 239))
        sheet.paste(pic, (x, y + label_h))
    DEST.parent.mkdir(exist_ok=True)
    sheet.save(DEST, optimize=True)
    print(f"{DEST}: {len(frames)} guest-DEX frames, {sheet.width}x{sheet.height}")


if __name__ == "__main__":
    main()
