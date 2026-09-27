#!/usr/bin/env python3
"""Prepare MIDP-scale graphics strictly from the user's original Swing project.

Original labels, colours and imagery remain unchanged. Only resizing/cropping
needed for the E63's 320x240 Canvas is performed. No generated substitutes.
"""
from pathlib import Path
from PIL import Image, ImageOps
import shutil

ORIGINAL = Path(__file__).resolve().parents[2] / "progetto_originale/Android J2ME Edition/src/android/j2me/edition"
RES = Path(__file__).resolve().parents[1] / "res"
RES.mkdir(parents=True, exist_ok=True)


def save(name, src, size, crop=None):
    image = Image.open(ORIGINAL / src)
    if crop is not None:
        image = image.crop(crop)
    image = image.convert("RGBA" if image.mode == "RGBA" else "RGB")
    image = image.resize(size, Image.Resampling.LANCZOS)
    image.save(RES / name, "PNG", optimize=True)


# Same background and splash as the desktop original, with the canvas filled
# (the Swing version accidentally left a white band along its bottom edge).
wall = ImageOps.fit(Image.open(ORIGINAL / "homewallpaper.png").convert("RGB"),
                    (320, 240), method=Image.Resampling.LANCZOS)
wall.save(RES / "wall.png", "PNG", optimize=True)
save("boot.png", "boot.png", (320, 240))

# Original graphics and shapes at about 70% of the Swing UI size. This keeps
# the blue/grey styling instead of the unrelated green-card theme.
for output, source, dimensions in (
    ("store.png", "playstore.png", (34, 33)),
    ("files.png", "filemanager_home.png", (34, 33)),
    ("store_app.png", "filemanager.png", (56, 57)),
    ("settings.png", "Settings.png", (34, 33)),
    ("settings_mini.png", "Settings_mini.png", (32, 28)),
    ("folder.png", "folder.png", (25, 21)),
    ("music.png", "musicfile_icon.png", (32, 31)),
    ("wifi.png", "wifi.png", (32, 28)),
    ("wifi_status.png", "wifi_statusbar.png", (13, 10)),
    ("warning.png", "battery_alert_icon.png", (40, 37)),
    ("account.png", "account_icon.png", (21, 20)),
    ("logo.png", "GooglePlayLogo.png", (103, 21)),
    ("next.png", "nextButton.png", (29, 33)),
    ("icon.png", "Phone.png", (32, 31)),
):
    save(output, source, dimensions)

# Swing placed the 512x250 source image inside a 460x116 label, vertically
# centred: reproducing exactly the visible crop prevents losing the logo/text.
save("banner.png", "filemanagerbanner.jpg", (320, 80), (0, 67, 512, 183))
save("banner_short.png", "filemanagerbanner.jpg", (320, 58), (0, 67, 512, 183))
save("banner_narrow.png", "filemanagerbanner.jpg", (176, 60), (0, 67, 512, 183))

# The original black navigation bar contains three grey icons. Cropping each
# lets MIDP position them proportionally when the Canvas is shorter or narrower.
for name, crop in (
    ("nav_back.png", (80, 18, 118, 42)),
    ("nav_home.png", (206, 16, 248, 42)),
    ("nav_recent.png", (336, 18, 376, 42)),
):
    save(name, "navbar.png", (29, 19), crop)

shutil.copy2(ORIGINAL / "lowbattery.wav", RES / "lowbattery.wav")
shutil.copy2(ORIGINAL / "Disfigure - Blank (NCS Release).wav", RES / "music.wav")
print("Original project assets prepared for Nokia E63:")
for entry in sorted(RES.iterdir()):
    print("  %-18s %8d bytes" % (entry.name, entry.stat().st_size))
