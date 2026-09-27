#!/usr/bin/env python3
"""Cross-compile/sign an UNRELEASED Symbian AOSP DEX diagnostic, not Android.

Isolated from tools/build_symbian_java_apks.sh (which correctly refuses a
misleading 0.2/Android release while Activity dispatcher is absent). Requires
Nokia SDK/GnuPoc/GCCE previously installed LOCALLY under excluded
build/toolchains/ after license acceptance; never redistributes those tools.
Override the location with SYMBIAN_TOOLCHAINS if installed elsewhere.
Verifies all 32 payloads against the generated native C pins after signing.
Even a successful GCCE crossbuild + SISX verification is NOT a phone test.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.make_aosp42_diagnostic_pkg import generate
from tools.verify_symbian_sis import verify

BASE = Path(os.environ.get("SYMBIAN_TOOLCHAINS", str(ROOT / "build/toolchains")))
SDK = BASE / "s60-fp1/sdk"
STAGE = ROOT / "build/aosp42-diagnostic"
APP = ROOT / "symbian/android_java_app"


def run(args: list[str], log: Path, cwd: Path = APP) -> None:
    environment = dict(os.environ, EPOCROOT=str(SDK) + "/")
    environment["PATH"] = str(BASE / "gnupoc/bin") + os.pathsep + environment["PATH"]
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        result = subprocess.run(args, cwd=cwd, env=environment,
                                stdout=stream, stderr=subprocess.STDOUT)
    text = log.read_text(errors="replace")
    if (result.returncode or re.search(
            r"(?i)(?:\berror:|\bError\s+[0-9]|No rule to make target|undefined reference)",
            text)):
        raise RuntimeError(f"{args[0]} failed ({result.returncode}):\n" +
                           "\n".join(text.splitlines()[-90:]))


def build() -> Path:
    pkg = generate()  # verifies SHA-256 for 11 system + 11 /data files
    for path in (SDK / "epoc32/include/e32base.h",
                 BASE / "csl-gcc/bin/arm-none-symbianelf-gcc",
                 BASE / "csl-gcc/bin/signsis"):
        if not path.is_file():
            raise FileNotFoundError(f"local licensed FP1 toolchain absent: {path}")
    STAGE.mkdir(parents=True, exist_ok=True)
    run([str(BASE / "gnupoc/bin/bldmake"), "bldfiles"],
        STAGE / "bldmake.log")
    exe = SDK / "epoc32/release/gcce/urel/e63android.exe"
    exe.unlink(missing_ok=True)  # never accept a stale ARM executable
    run([str(BASE / "gnupoc/bin/abld"), "build", "gcce", "urel"],
        STAGE / "abld.log")
    if not exe.is_file() or exe.stat().st_size < 1000:
        raise ValueError("GCCE produced no new native E32 diagnostic executable")
    private = STAGE / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    key = private / "diagnostic.key.pem"
    cert = private / "diagnostic.cert.pem"
    if not key.is_file() or not cert.is_file():
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-sha1", "-days", "730", "-subj",
             "/CN=E63 AOSP DEX Diagnostic Local Only/O=Not Android",
             "-keyout", str(key), "-out", str(cert)],
            STAGE / "local-signing.log", cwd=ROOT)
        key.chmod(0o600)
    unsigned = STAGE / "e63android-aosp42-diagnostic-unsigned.sis"
    signed = STAGE / "e63android-aosp42-diagnostic.sisx"
    run([str(BASE / "gnupoc/bin/makesis"), pkg.name, str(unsigned)],
        STAGE / "makesis.log")
    run([str(BASE / "gnupoc/bin/signsis"), str(unsigned), str(signed),
         str(cert), str(key)], STAGE / "signsis.log")
    run([str(BASE / "gnupoc/bin/signsis"), "-o", str(signed)],
        STAGE / "signsis-info.log")
    verify("e63android-diagnostic", signed, SDK)
    digest = hashlib.sha256(signed.read_bytes()).hexdigest()
    print(f"UNRELEASED LOCAL AOSP DEX DIAGNOSTIC: {signed}")
    print(f"{signed.stat().st_size} bytes; SHA-256 {digest}")
    print("No real Nokia E63 run or Android Activity/VM/OS is implied.")
    return signed


if __name__ == "__main__":
    build()
