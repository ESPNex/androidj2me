#!/usr/bin/env python3
"""Crossbuild/sign the SEPARATE, non-release 0.6 object-DEX diagnostic.

This proves neither installer success on the E63 nor any Android Activity/UI.
The Nokia SDK is locally licensed only, under excluded build/. The output
must NOT overwrite the preserved original Java/J2ME/0.2 release or test SISX.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_aosp42_diagnostic_sis import BASE, SDK, run
from tools.make_aosp42_object_diagnostic_pkg import generate
from tools.verify_symbian_sis import verify

OUT = ROOT / "build/aosp42-object-diagnostic"


def build() -> Path:
    pkg = generate()  # verifies all 44 original pinned source payloads
    for path in (SDK / "epoc32/include/e32base.h",
                 BASE / "csl-gcc/bin/arm-none-symbianelf-gcc",
                 BASE / "csl-gcc/bin/signsis"):
        if not path.is_file():
            raise FileNotFoundError(f"personal Nokia FP1 toolchain missing: {path}")
    OUT.mkdir(parents=True, exist_ok=True)
    run([str(BASE / "gnupoc/bin/bldmake"), "bldfiles"], OUT / "bldmake.log")
    exe = SDK / "epoc32/release/gcce/urel/e63android.exe"
    exe.unlink(missing_ok=True)  # never package a stale compiler result
    run([str(BASE / "gnupoc/bin/abld"), "build", "gcce", "urel"],
        OUT / "abld.log")
    if not exe.is_file() or exe.stat().st_size < 1000:
        raise ValueError("no fresh GCCE-crossbuilt native object VM EXE")
    shutil.copyfile(exe, OUT / "e63android.exe")
    private = OUT / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    key = private / "object-diagnostic.key.pem"
    cert = private / "object-diagnostic.cert.pem"
    if not key.is_file() or not cert.is_file():
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-sha1", "-days", "730", "-subj",
             "/CN=E63 AOSP Object DEX Diagnostic Local Only/O=Not Android",
             "-keyout", str(key), "-out", str(cert)],
            OUT / "local-signing.log", cwd=ROOT)
        key.chmod(0o600)
    unsigned = OUT / "e63android-aosp42-object-diagnostic-unsigned.sis"
    signed = OUT / "e63android-aosp42-object-diagnostic.sisx"
    run([str(BASE / "gnupoc/bin/makesis"), pkg.name, str(unsigned)],
        OUT / "makesis.log")
    run([str(BASE / "gnupoc/bin/signsis"), str(unsigned), str(signed),
         str(cert), str(key)], OUT / "signsis.log")
    run([str(BASE / "gnupoc/bin/signsis"), "-o", str(signed)],
        OUT / "signsis-info.log")
    verify("e63android-object-diagnostic", signed, SDK)
    print(f"UNRELEASED/UNTESTED AOSP OBJECT DEX DIAGNOSTIC: {signed}")
    print(f"{signed.stat().st_size} bytes; SHA-256 "
          f"{hashlib.sha256(signed.read_bytes()).hexdigest()}")
    print("Nokia test NOT performed; no Activity/View/runtime/Android OS claim.")
    return signed


if __name__ == "__main__":
    build()
