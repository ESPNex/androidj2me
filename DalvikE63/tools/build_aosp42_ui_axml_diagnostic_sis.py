#!/usr/bin/env python3
"""Cross-build a NEW 44-payload Nokia AOSP AXML/DEX diagnostic SISX.

The 32-/40-payload experimental SISX files and all historical 0.2 releases
are untouched. This only diagnoses authentic package declarations and class
metadata; it does not start an Activity/Service, render Android Views, or
establish E63 hardware compatibility. A full Android 4.2 VM remains absent.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_aosp42_diagnostic_sis import BASE, SDK, run
from tools.make_aosp42_ui_axml_diagnostic_pkg import generate
from tools.verify_symbian_sis import verify

OUT = ROOT / "build/aosp42-ui-axml-diagnostic"


def build() -> Path:
    pkg = generate()  # 44 input payloads; checks source APK, index + AXML pins
    for path in (SDK / "epoc32/include/e32base.h",
                 BASE / "csl-gcc/bin/arm-none-symbianelf-gcc",
                 BASE / "csl-gcc/bin/signsis"):
        if not path.is_file():
            raise FileNotFoundError(f"local, licensed Nokia toolchain absent: {path}")
    OUT.mkdir(parents=True, exist_ok=True)
    run([str(BASE / "gnupoc/bin/bldmake"), "bldfiles"], OUT / "bldmake.log")
    exe = SDK / "epoc32/release/gcce/urel/e63android.exe"
    exe.unlink(missing_ok=True)  # do not accept a stale target executable
    run([str(BASE / "gnupoc/bin/abld"), "build", "gcce", "urel"],
        OUT / "abld.log")
    if not exe.is_file() or exe.stat().st_size < 1000:
        raise ValueError("no newly GCCE-crossbuilt AXML diagnostic EXE")
    shutil.copyfile(exe, OUT / "e63android.exe")
    private = OUT / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    key = private / "ui-axml-diagnostic.key.pem"
    cert = private / "ui-axml-diagnostic.cert.pem"
    if not key.is_file() or not cert.is_file():
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-sha1", "-days", "730", "-subj",
             "/CN=E63 AOSP UI AXML Diagnostic Local Only/O=Not Android",
             "-keyout", str(key), "-out", str(cert)],
            OUT / "local-signing.log", cwd=ROOT)
        key.chmod(0o600)
    unsigned = OUT / "e63android-aosp42-ui-axml-diagnostic-unsigned.sis"
    signed = OUT / "e63android-aosp42-ui-axml-diagnostic.sisx"
    run([str(BASE / "gnupoc/bin/makesis"), pkg.name, str(unsigned)],
        OUT / "makesis.log")
    run([str(BASE / "gnupoc/bin/signsis"), str(unsigned), str(signed),
         str(cert), str(key)], OUT / "signsis.log")
    run([str(BASE / "gnupoc/bin/signsis"), "-o", str(signed)],
        OUT / "signsis-info.log")
    verify("e63android-ui-axml-diagnostic", signed, SDK)
    print(f"UNRELEASED LOCAL AOSP UI AXML DIAGNOSTIC: {signed}")
    print(f"{signed.stat().st_size} bytes; SHA-256 "
          f"{hashlib.sha256(signed.read_bytes()).hexdigest()}")
    print("BACK UP Nokia before opt-in install: same UID as 0.2, large C: "
          "payloads; no Android Activity, UI or hardware execution demonstrated.")
    return signed


if __name__ == "__main__":
    build()
