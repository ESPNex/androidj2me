#!/usr/bin/env python3
"""Add four SHA-pinned genuine AAPT manifest caches to the 40-payload UI test.

This is a NEW, unreleased 44-file package (version 0.5), leaving the original
40-file UI SISX/PKG, 32-file DEX diagnostic, historical APKs and 0.2 intact.
The on-device 4-key diagnoses AOSP Launcher2 HOME declaration and class_def;
it cannot launch an Android Activity or draw an Android View.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_aosp42_ui_apks import UI_APPS
from tools.make_aosp42_ui_diagnostic_pkg import generate as old_ui, validate

PKG = ROOT / "symbian/android_java_app/e63android-aosp42-ui-axml-diagnostic.pkg"


def generate() -> Path:
    old = old_ui()  # exact original 40-file contents, and all staged SHA pins
    validate()  # byte-identical signed-APK -> on-disk AXML cache derivation
    text = old.read_text()
    version = '# {"AOSP 4.2 UI DEX Diagnostic (no Activities)"}, (0xE0B63E04), 0, 4, 0'
    newer = '# {"AOSP 4.2 UI AXML Diagnostic (no Activities)"}, (0xE0B63E04), 0, 5, 0'
    if text.count(version) != 1 or text.count("e63-uiindex") != 4:
        raise ValueError("old UI diagnostic package/payload count changed")
    contents = ("; UNRELEASED 44-file AOSP UI metadata diagnostic.\n"
                "; Four real APKs, four index files and four byte-identical\n"
                "; SHA-pinned AAPT binary manifests cached under /data.\n"
                "; Key 4 verifies HOME/DEX metadata; NO Android Activity/UI.\n"
                "; Same Nokia UID as 0.2: backup and free C: space required.\n" +
                text.replace(version, newer))
    for name in UI_APPS:
        contents += (f'"../../build/staged-android42-system/ui-manifest/{name}.axml" - '
                     f'"C:\\private\\E0B63E04\\data\\e63-uimanifest\\{name}.axml"\n')
    PKG.write_text(contents)
    print(f"AXML UI diagnostic only: {PKG} (44 payloads, NO Android UI)")
    return PKG


if __name__ == "__main__":
    generate()
