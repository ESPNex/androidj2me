#!/usr/bin/env python3
"""Fetch only the binary API-17 android.jar needed to compile Java Activities.

SDK platform archive URL/SHA-1/size come from Google's repository2-1.xml
(platforms;android-17, revision 3); only android.jar is extracted under
build/tools/ (excluded from snapshots). No AOSP sources or emulator images.
Use of the SDK is subject to Google's SDK license; do not redistribute the jar.
"""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from zipfile import ZipFile

DEST = Path(__file__).resolve().parents[1] / "build/tools/android-17.jar"
SHA256 = "2bf921bd5efce9e4b2966a394d8b9b332e548fa30df7a158e029c7fa823dd799"
ARCHIVE = "https://dl.google.com/android/repository/android-17_r03.zip"
ARCHIVE_SIZE = 57_030_216
ARCHIVE_SHA1 = "dbe14101c06e6cdb34e300393e64e64f8c92168a"
MEMBER = "android-4.2.2/android.jar"


def check() -> bool:
    return DEST.is_file() and hashlib.sha256(DEST.read_bytes()).hexdigest() == SHA256


def download() -> Path:
    if check(): return DEST
    DEST.parent.mkdir(parents=True, exist_ok=True)
    archive = DEST.with_suffix(".platform.zip")
    try:
        sha = hashlib.sha1()
        total = 0
        with urllib.request.urlopen(ARCHIVE, timeout=60) as src, archive.open("wb") as out:
            for block in iter(lambda: src.read(128 * 1024), b""):
                total += len(block)
                if total > ARCHIVE_SIZE: raise ValueError("oversized API-17 archive")
                sha.update(block)
                out.write(block)
        if total != ARCHIVE_SIZE or sha.hexdigest() != ARCHIVE_SHA1:
            raise ValueError("API-17 platform download differs from Google repository metadata")
        with ZipFile(archive) as zf:
            names = [name for name in zf.namelist() if name.endswith("android.jar")]
            if names != [MEMBER]: raise ValueError("wrong API-17 jar layout")
            member = zf.getinfo(MEMBER)
            if not 0 < member.file_size < 30_000_000: raise ValueError("oversized API-17 jar")
            with zf.open(member) as src, DEST.open("wb") as out:
                for block in iter(lambda: src.read(128 * 1024), b""):
                    out.write(block)
        if not check(): raise ValueError("API-17 jar hash mismatch")
        return DEST
    finally:
        archive.unlink(missing_ok=True)
        if not check(): DEST.unlink(missing_ok=True)


if __name__ == "__main__":
    print("Verified binary API-17 compile stubs:", download())
