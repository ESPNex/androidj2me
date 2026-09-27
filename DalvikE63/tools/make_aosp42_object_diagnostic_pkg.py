#!/usr/bin/env python3
"""Unreleased 0.6 SIS9 package for genuinely interpreted AOSP constructors.

Reuses SHA-checked 44 exact AOSP UI/boot payloads of 0.5, but creates a NEW
name/version and package file. Preserves all historical 0.2 and test SISX.
Keys 1/2/6-9 report diagnostic native text, NOT Java View rendering.
"""
from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.make_aosp42_ui_axml_diagnostic_pkg import generate as axml_generate

PKG = ROOT / "symbian/android_java_app/e63android-aosp42-object-diagnostic.pkg"
OLD = '# {"AOSP 4.2 UI AXML Diagnostic (no Activities)"}, (0xE0B63E04), 0, 5, 0'
NEW = '# {"AOSP 4.2 DEX Objects (NO Android UI)"}, (0xE0B63E04), 0, 6, 0'


def generate() -> Path:
    previous = axml_generate()  # recheck APK/JAR/DEX/index/AXML pinned inputs
    raw = previous.read_text()
    if raw.count(OLD) != 1 or raw.count("e63-uimanifest") != 4:
        raise ValueError("0.5 package's 44 AOSP file inputs changed")
    PKG.write_text(
        "; UNRELEASED Nokia 0.6 native AOSP OBJECT diagnostic, NOT Android.\n"
        "; Keys 1/2/6-9 run genuine Launcher2/core DEX object methods.\n"
        "; Only signed development-key APKs; no Activity, View/JNI/Binder.\n"
        "; Same Symbian UID as 0.2: voluntary install requires BACKUP/free C:.\n"
        + raw.replace(OLD, NEW))
    print(f"Object DEX diagnostic only: {PKG} (44 payloads, NO Android UI)")
    return PKG


if __name__ == "__main__":
    generate()
