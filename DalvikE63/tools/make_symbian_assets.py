#!/usr/bin/env python3
"""Build bounded, offline E63 image/font resources from the existing APK.

Only original J2ME PNGs from the signed Launcher APK and DejaVuSans glyph
masks are exported. The SCREEN, TEXT and GEOMETRY still come from the guest
E63Canvas.paint Dalvik bytecode. The pack has no Nokia SDK content.
"""
from __future__ import annotations

import hashlib
import io
import struct
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
APK = ROOT / "apks/Launcher.apk"
JAR = ROOT / "j2me/Android_J2ME_E63_Bridge.jar"
DEX = ROOT / "j2me/classes.dex"
OUTPUT = ROOT / "symbian/resources/e63assets.bin"
FONT_FILE = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
MAGIC = b"E63RSC01"
IMAGE_NAMES = (
    "store.png", "settings.png", "files.png", "nav_back.png",
    "nav_home.png", "nav_recent.png", "wifi_status.png", "wall.png",
    "drawer.png", "wifi.png", "settings_mini.png",
)
FONTS = {8: 11, 0: 13, 16: 17}
IMAGE_FMT = "<IIIII"  # ID, width, height, RGBA offset, byte count
GLYPH_FMT = "<IIIIIiiIII"  # font, text length, advance, mask w/h, left/top, text/mask offsets and byte count


def dex_literals(blob: bytes) -> set[str]:
    count, ids_off = struct.unpack_from("<II", blob, 0x38)
    labels: set[str] = set()
    for index in range(count):
        offset = struct.unpack_from("<I", blob, ids_off + 4 * index)[0]
        while blob[offset] & 0x80:
            offset += 1
        offset += 1  # last ULEB byte of the UTF-16 unit count
        end = blob.index(b"\0", offset)
        item = blob[offset:end]
        if (1 <= len(item) <= 64 and all(32 <= c < 127 for c in item)
                and b"/" not in item and b";" not in item):
            labels.add(item.decode("ascii"))
    # A clock value is returned by the ORIGINAL guest E63Midlet.clock() bytecode,
    # not by this file; the strings here are merely an offline font cache.
    labels.update(f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in range(60))
    labels.update(f"{level}%" for level in range(101))
    labels.update(chr(code) for code in range(32, 127))
    labels.update({"?", "...", ""})
    return labels


def build() -> tuple[int, int, int, str]:
    if not FONT_FILE.is_file():
        raise FileNotFoundError(f"Missing DejaVu Sans; install fonts-dejavu-core: {FONT_FILE}")
    source = DEX.read_bytes()
    with ZipFile(APK) as apk, ZipFile(JAR) as jar:
        if apk.read("classes.dex") != source:
            raise ValueError("Launcher APK DEX differs from the original J2ME DEX")
        images = []
        for number, name in enumerate(IMAGE_NAMES, 1):
            png = apk.read("assets/j2me/" + name)
            if png != jar.read(name):
                raise ValueError(f"APK asset differs from the original J2ME PNG: {name}")
            with Image.open(io.BytesIO(png)) as image:
                rgba = image.convert("RGBA")
                if not (0 < rgba.width <= 512 and 0 < rgba.height <= 512):
                    raise ValueError(f"bad bounded image: {name}")
                images.append((number, rgba.width, rgba.height, rgba.tobytes()))

    labels = sorted(dex_literals(source))
    glyphs = []
    for font_id, point in sorted(FONTS.items()):
        face = ImageFont.truetype(str(FONT_FILE), point)
        for text in labels:
            left, top, right, bottom = face.getbbox(text, anchor="lt")
            width, height = right - left, bottom - top
            if width < 0 or height < 0 or width > 4096 or height > 512:
                raise ValueError(f"invalid glyph bounds: {text!r}")
            coverage = Image.new("L", (max(1, width), max(1, height)), 0)
            if text:
                ImageDraw.Draw(coverage).text((-left, -top), text, font=face,
                                              fill=255, anchor="lt")
            advance = int(face.getlength(text))
            glyphs.append((font_id, text.encode("ascii"), advance, width,
                           height, left, top, coverage.tobytes()))

    # Offsets are absolute and little endian. Native code checks every offset,
    # dimension and multiplication before returning pointers to the renderer.
    header_len = 20 + len(images) * struct.calcsize(IMAGE_FMT) + len(glyphs) * struct.calcsize(GLYPH_FMT)
    data = bytearray()
    image_records = bytearray()
    glyph_records = bytearray()
    for number, width, height, rgba in images:
        offset = header_len + len(data)
        image_records.extend(struct.pack(IMAGE_FMT, number, width, height, offset, len(rgba)))
        data.extend(rgba)
    for font_id, text, advance, width, height, left, top, mask in glyphs:
        text_off = header_len + len(data)
        data.extend(text)
        mask_off = header_len + len(data)
        data.extend(mask)
        glyph_records.extend(struct.pack(GLYPH_FMT, font_id, len(text), advance,
                                         width, height, left, top, text_off,
                                         mask_off, len(mask)))
    total = header_len + len(data)
    if total >= 8 * 1024 * 1024 or len(glyphs) > 8000:
        raise ValueError(f"pack exceeds 8 MiB/8000 glyphs limit: {total}, {len(glyphs)}")
    payload = (struct.pack("<8sIII", MAGIC, len(images), len(glyphs), total)
               + image_records + glyph_records + data)
    assert len(payload) == total
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(payload)
    return len(images), len(glyphs), total, hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    count, glyphs, length, digest = build()
    print(f"{OUTPUT}: {count} original APK PNGs, {glyphs} offline font masks, {length} bytes")
    print("SHA-256:", digest)
