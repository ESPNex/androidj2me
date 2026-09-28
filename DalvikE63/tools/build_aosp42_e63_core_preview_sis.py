#!/usr/bin/env python3
"""Build a distinct <20,000,000-byte modular E63 AOSP core preview.

Real 4.2 boot JAR/DEX bytes come from the SHA-pinned public v0.6 asset;
Symbian EXE/resources are cross-compiled from the current source with the
E63_CORE_PREVIEW macro in an isolated, disposable build/ source tree.
No original .mmp, v0.2 SISX/JAR, v0.6 Release, licensed SDK, key or APK is
modified/repacked. The older six shim APKs and all optional Android UI/
resources are *absent*, not replaced or pretended to work. The JNI/Binder
and DEX diagnostics remain, but NO Activity, UI or Android boot can run.
This is NOT evidence of installability on a real Nokia E63.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_aosp42_diagnostic_sis import BASE, SDK, run
from tools.make_aosp42_e63_core_pkg import APP, WORK, generate
from tools.verify_symbian_sis import extract, verify

OUTPUT = ROOT / "release/experiments/e63android-aosp42-core-preview.sisx"
LIMIT = 20_000_000  # decimal MB, stricter than 20 MiB


def stage_sources() -> Path:
    """Enable the size-specific native branch WITHOUT changing the full app."""
    source = WORK / "source"
    app = source / "android_java_app"
    if source.exists():
        shutil.rmtree(source)
    app.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP, app)
    for name in ("runtime", "compat"):
        (source / name).symlink_to(ROOT / "symbian" / name,
                                   target_is_directory=True)
    mmp = app / "e63android.mmp"
    old = mmp.read_text()
    needle = "CAPABILITY      NONE\n"
    if old.count(needle) != 1 or "E63_CORE_PREVIEW" in old:
        raise ValueError("unexpected Symbian MMP; do not modify historic app")
    mmp.write_text(old.replace(needle,needle + "MACRO           E63_CORE_PREVIEW\n"))
    if "#ifdef E63_CORE_PREVIEW" not in (app / "e63android_app.cpp").read_text():
        raise ValueError("native core must fail closed without old UI APKs")
    return app


def build(output: Path = OUTPUT) -> Path:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"preserved signed SISX exists: {output}; "
                              "use --output under build/ for a new local signing run")
    pkg = generate()
    for path in (SDK / "epoc32/include/e32base.h",
                 BASE / "csl-gcc/bin/arm-none-symbianelf-gcc",
                 BASE / "csl-gcc/bin/signsis"):
        if not path.is_file():
            raise FileNotFoundError(f"local, personally licensed S60 SDK absent: {path}")
    WORK.mkdir(parents=True, exist_ok=True)
    app = stage_sources()
    run([str(BASE / "gnupoc/bin/bldmake"), "bldfiles"],
        WORK / "bldmake.log", cwd=app)
    exe = SDK / "epoc32/release/gcce/urel/e63android.exe"
    exe.unlink(missing_ok=True)  # do not accept a stale v0.6 executable
    run([str(BASE / "gnupoc/bin/abld"), "build", "gcce", "urel"],
        WORK / "abld.log", cwd=app)
    if not exe.is_file() or exe.stat().st_size < 1000:
        raise ValueError("GCCE did not produce a new ARM Symbian core executable")
    shutil.copyfile(exe, WORK / "e63android.exe")
    private = WORK / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    key, cert = private / "core.key.pem", private / "core.cert.pem"
    if not key.is_file() or not cert.is_file():
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
             "-nodes", "-sha1", "-days", "730", "-subj",
             "/CN=E63 AOSP Core Size Preview/O=Not Android",
             "-keyout", str(key), "-out", str(cert)],
            WORK / "local-signing.log", cwd=ROOT)
        key.chmod(0o600)
    unsigned = WORK / "e63android-aosp42-core-preview-unsigned.sis"
    signed = WORK / "e63android-aosp42-core-preview.sisx"
    # The package's source paths are relative to the original app folder;
    # this folder remains unmodified, apart from a separate new .pkg file.
    run([str(BASE / "gnupoc/bin/makesis"), pkg.name, str(unsigned)],
        WORK / "makesis.log", cwd=APP)
    run([str(BASE / "gnupoc/bin/signsis"), str(unsigned), str(signed),
         str(cert), str(key)], WORK / "signsis.log", cwd=ROOT)
    run([str(BASE / "gnupoc/bin/signsis"), "-o", str(signed)],
        WORK / "signsis-info.log", cwd=ROOT)
    verify("e63android-core-preview", signed, SDK)
    payload = extract(signed, core_preview=True)
    if (len(payload) != 24 or payload[0] != exe.read_bytes() or
            signed.stat().st_size >= LIMIT):
        raise ValueError("modular core failed size or executable integrity gate")
    # Only copy the fully verified result to the requested location; never
    # overwrite a previously signed deliverable with a fresh ephemeral key.
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(signed, output)
    if hashlib.sha256(output.read_bytes()).digest() != \
            hashlib.sha256(signed.read_bytes()).digest():
        output.unlink(missing_ok=True)
        raise ValueError("copied SISX differs from verified signed SISX")
    print(f"MODULAR AOSP CORE PREVIEW, NOT ANDROID UI/OS: {output}")
    print(f"SISX: {output.stat().st_size:,} bytes (<20,000,000); installed payload: "
          f"{sum(map(len, payload)):,} bytes")
    print(f"SHA-256: {hashlib.sha256(output.read_bytes()).hexdigest()}")
    print("Same UID and a NEW self-signed key: do not install over 0.2/v0.6 "
          "without a full phone backup. No hardware run has been performed.")
    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT,
                        help="distinct SISX destination; never overwrite")
    args = parser.parse_args()
    build(args.output)
