#!/usr/bin/env python3
"""Reproduce ONLY the host tools needed for the authorized AOSP 4.2 build.

Downloads pinned AOSP tag artifacts (aapt/aidl/llvm-rs-cc, ECJ, jarjar) and a SHA-256
pinned JDK 8 into excluded build/. Compiles dx from the already bootstrapped,
pinned platform/dalvik source; it never downloads a full AOSP checkout.
The 32-bit AOSP aapt/aidl require LOCAL system libraries on 64-bit Debian:
  sudo apt-get install libc6-i386 lib32stdc++6 lib32z1
This script does not install software system-wide or redistribute an SDK.
"""
from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "build/aosp42-host-tools"
TAG = "android-4.2.2_r1.2"
JDK_FILE = "OpenJDK8U-jdk_x64_linux_hotspot_8u504b01.tar.gz"
JDK_URL = ("https://github.com/adoptium/temurin8-binaries/releases/download/"
           "jdk8u504-b01/" + JDK_FILE)
# Each SHA is from the current, locally verified AOSP tag object or
# Adoptium's published package checksum. SHA checking remains mandatory.
FILES = {
    "ecj-aosp42.jar": (
        f"https://android.googlesource.com/platform/prebuilts/misc/+/{TAG}/common/ecj/ecj.jar?format=TEXT",
        "3ae73ce5aada048553bae0e541f285ccb1a1784344b2f113d472f5136942ea3f", True),
    "jarjar-aosp42.jar": (
        f"https://android.googlesource.com/platform/prebuilts/misc/+/{TAG}/common/jarjar/jarjar-1.0rc8.jar?format=TEXT",
        "afdd7e963aa52ef03a3dfc98916b58375e2b1356f6d7ea565a82d8c544eb28cf", True),
    "aapt": (
        f"https://android.googlesource.com/platform/prebuilts/sdk/+/{TAG}/tools/linux/aapt?format=TEXT",
        "cbe9af7af23a4497da554c03cce6b31b556ade4f6284325a624f72fd104e71e4", True),
    "aidl": (
        f"https://android.googlesource.com/platform/prebuilts/sdk/+/{TAG}/tools/linux/aidl?format=TEXT",
        "36fdafb6725dec00b2f1edba90fed283a81c9c5687fc2e893c6e38fcd1916b5a", True),
    "llvm-rs-cc": (
        f"https://android.googlesource.com/platform/prebuilts/sdk/+/{TAG}/tools/linux/llvm-rs-cc?format=TEXT",
        "540d68b4d9039f2eea79048a5227aa9f449a82668e2c4239b2ae36d972c0099a", True),
    JDK_FILE: (JDK_URL,
               "9c70e102f527ac674ac2fe9c7d47b9a04e2d19842ba5ab8e9b33f368bbadfaea", False),
}


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def fetch(name: str) -> Path:
    url, expected, b64 = FILES[name]
    DEST.mkdir(parents=True, exist_ok=True)
    path = DEST / name
    if path.is_file() and sha256(path) == expected:
        return path
    if path.exists():
        raise ValueError(f"existing {path} has an unexpected SHA-256")
    temp = path.with_suffix(path.suffix + ".partial")
    # Gitiles intermittently returns 503 specifically to Python urllib's
    # default User-Agent; curl's retry/resume semantics work reliably here.
    try:
        subprocess.run(["curl", "--fail", "--silent", "--show-error",
                        "--location", "--retry", "5", "--retry-delay", "2",
                        "--max-time", "180", "-o", str(temp), url], check=True)
        if b64:
            payload = base64.b64decode(temp.read_bytes(), validate=True)
            if hashlib.sha256(payload).hexdigest() != expected:
                raise ValueError(f"upstream SHA-256 mismatch: {name}")
            path.write_bytes(payload)
        else:
            if sha256(temp) != expected:
                raise ValueError(f"upstream SHA-256 mismatch: {name}")
            os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    if name in ("aapt", "aidl", "llvm-rs-cc"):
        path.chmod(0o755)
    print(f"verified {name}: {expected}", flush=True)
    return path


def jdk() -> Path:
    package = fetch(JDK_FILE)
    installed = DEST / "jdk8"
    binary = installed / "bin/javac"
    if binary.is_file():
        version = subprocess.check_output([str(binary), "-version"],
                                          stderr=subprocess.STDOUT, text=True)
        if "1.8.0_504" not in version:
            raise ValueError("unexpected local JDK 8 version")
        return binary
    with tempfile.TemporaryDirectory(prefix="jdk-unpack-", dir=DEST) as tmp:
        root = Path(tmp)
        with tarfile.open(package) as archive:
            for item in archive.getmembers():
                parts = Path(item.name).parts
                if (not parts or any(part == ".." for part in parts) or
                        Path(item.name).is_absolute()):
                    raise ValueError("unsafe JDK tarball path")
            try:
                archive.extractall(root, filter="data")
            except TypeError:  # Python 3.10/3.11 without extraction filters
                archive.extractall(root)
        matches = [p for p in root.iterdir() if (p / "bin/javac").is_file()]
        if len(matches) != 1:
            raise ValueError("JDK tarball missing a unique javac")
        os.replace(matches[0], installed)
    return binary


def build_dx(javac: Path) -> Path:
    src = ROOT / "build/aosp42-runtime-dependencies/dalvik/dx/src"
    source_files = sorted(src.rglob("*.java"))
    if not source_files or len(source_files) < 300:
        raise ValueError("pinned AOSP platform/dalvik dx sources not bootstrapped")
    out = DEST / "dx.jar"
    if out.is_file() and zipfile_ok(out):
        return out
    classes = DEST / "dx-classes"
    classes.mkdir(parents=True, exist_ok=True)
    sources = DEST / "dx-sources.list"
    sources.write_text("\n".join(str(p) for p in source_files) + "\n")
    subprocess.run([str(javac), "-source", "7", "-target", "7",
                    "-encoding", "UTF-8", "-d", str(classes),
                    "@" + str(sources)], check=True, cwd=ROOT)
    subprocess.run([str(javac.parent / "jar"), "cf", str(out), "-C",
                    str(classes), "."], check=True, cwd=ROOT)
    if not zipfile_ok(out):
        raise ValueError("built dx.jar lacks AOSP dx Main.class")
    print(f"compiled AOSP dx from {len(source_files)} Java sources", flush=True)
    return out


def zipfile_ok(path: Path) -> bool:
    import zipfile
    with zipfile.ZipFile(path) as archive:
        return "com/android/dx/command/Main.class" in archive.namelist()


if __name__ == "__main__":
    compiler = jdk()
    for name in ("ecj-aosp42.jar", "jarjar-aosp42.jar", "aapt", "aidl", "llvm-rs-cc"):
        fetch(name)
    build_dx(compiler)
    print("AOSP host tools available under build/ (not an E63 or Android runtime)")
