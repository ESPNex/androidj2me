"""Small RGB565 pack of ONLY each signed Android Java APK's own PNG assets.

The E63 source target does not have a PNG decoder yet. Its UI can show a
predecoded, pinned RGB565 thumbnail only after the Java Program DEX selects
an image AND the active, SHA-256-pinned APK owns that asset. This pack is NOT
a copy of every asset in each APK; no cross-package asset access is granted.
"""
from __future__ import annotations

import hashlib
import io
import struct
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

MAGIC = b"E63I5651"
HEADER_SIZE = 16
ENTRY = struct.Struct("<64s80sHHII")
PACK_LIMIT = 1024 * 1024


def pack_images(registry: list[dict], apks: Path) -> bytes:
    entries: list[tuple[str,str,int,int,bytes]] = []
    for app in registry:
        with ZipFile(apks / app["name"]) as archive:
            for name, checked in sorted(app["assets"].items()):
                if not name.endswith(".png"):
                    continue
                payload = archive.read("assets/" + name)
                if (len(payload) != checked["size"] or
                    hashlib.sha256(payload).hexdigest() != checked["sha256"]):
                    raise ValueError("APK PNG differs from owned asset catalog: " + name)
                with Image.open(io.BytesIO(payload)) as image:
                    if not (0 < image.width <= 512 and 0 < image.height <= 512):
                        raise ValueError("oversized PNG: " + name)
                    rgba = image.convert("RGBA")
                    backdrop = Image.new("RGBA", rgba.size, (16,16,16,255))
                    backdrop.alpha_composite(rgba)
                    rgb = backdrop.convert("RGB").tobytes()
                    pix = bytearray()
                    for i in range(0,len(rgb),3):
                        red,green,blue=rgb[i:i+3]
                        pixel = ((red>>3)<<11) | ((green>>2)<<5) | (blue>>3)
                        pix.extend(struct.pack("<H",pixel))
                    entries.append((app["package"],name,image.width,image.height,bytes(pix)))
    entries.sort(key=lambda row:(row[0],row[1]))
    if not entries or len(entries)>24:
        raise ValueError("expected 1..24 per-APK preview images")
    offset = HEADER_SIZE+len(entries)*ENTRY.size
    records=bytearray(); pixels=bytearray()
    for package,name,width,height,data in entries:
        package_bytes=package.encode("ascii")
        name_bytes=name.encode("ascii")
        if len(package_bytes)>=64 or len(name_bytes)>=80:
            raise ValueError("image name too long")
        records.extend(ENTRY.pack(package_bytes,name_bytes,width,height,
                                  offset+len(pixels),len(data)))
        pixels.extend(data)
    size=offset+len(pixels)
    if size>PACK_LIMIT:
        raise ValueError("RGB565 E63 images exceed 1 MiB")
    result=struct.pack("<8sII",MAGIC,len(entries),size)+records+pixels
    assert len(result)==size
    return bytes(result)
