#!/usr/bin/env python3
"""Pinned, allowlisted AOSP 4.2.2 runtime/build dependency SOURCES only.

The owner separately authorized the repositories indispensable to a real
framework after initially authorizing just frameworks/base. This fetches an
explicit allowlist of projects at the same AOSP tag, NOT a repo manifest or
all Android.
They remain inside excluded build/; they are not runtime binaries, cannot be
rebuilt for Symbian just by invoking this script, and are not redistributed.
Do not extend this allowlist without checking necessity and authorization.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "build/aosp42-runtime-dependencies"
TAG = "android-4.2.2_r1.2"
# Direct Google Git tag objects and peeled commits. Never use floating HEAD.
PROJECTS = {
    "dalvik": ("platform/dalvik", "9393f5ac8ff2b52cc2e9f352d1d60cb89cc82c33", "cbac7aed2621a0d51ecddf89af0b3c4a110a17df"),
    "libcore": ("platform/libcore", "45cb6cca3ab7cba602518e38be9b19abc1c3ca16", "cc55503ccef76a3b443b1dba3a2f05049b2b34f4"),
    "bionic": ("platform/bionic", "c5ad87d494451fbce2d669d5d4b8c17237102a60", "5115d4348ee720be3db77ae54a06c492049e5ea3"),
    "frameworks-native": ("platform/frameworks/native", "d9cb52f2b16081ece4f9811650f34b5b6107de6f", "529cb9ed9c5d62d5b270cdd650380ae116382143"),
    "system-core": ("platform/system/core", "7b05de30ecfed0c224a70c85c7c4c9a58bc81728", "4f247d753a8865cd16292ff0b720b72c28049786"),
    "build": ("platform/build", "023aa2aae3bc277d2df38590290bb909676e7ed8", "b225d8b17ee61f0cfe4fb14e7153826183872b00"),
    "libnativehelper": ("platform/libnativehelper", "e56639dbc09322d8ab34b3c33b227fb37995890b", "73d3c2e3ed100f1d0ccc08a9675844bf8a0848fa"),
    "icu4c": ("platform/external/icu4c", "73a887b6c340e6b6a568b32f60ac52e45f2944f9", "7c2b59472f5086b12884891153b07ab11726fb99"),
    "zlib": ("platform/external/zlib", "a8ade547acdf7291977b4eb1ea17f125f1037db2", "2d5094f0ebcb01fb9f11952d776945b090d89cf0"),
    "expat": ("platform/external/expat", "9b83cc0295fdb36cb8ced78bef77f6be6bddb53b", "bb9f3f74212ef523ff693cba9d782575ebba7418"),
    "bouncycastle": ("platform/external/bouncycastle", "2e9e8acce00adcff933dcda3a52a107e533d4976", "e0c8f22188026985f304bc28da6fb41d3bffb517"),
    "telephony-common": ("platform/frameworks/opt/telephony", "1fc5b76bd2b7f63c395799f68731cbc519c7a4e3", "f08c4c89622ddcbc4ed9315fe6b399941dad4939"),
    "openssl": ("platform/external/openssl", "71c6973fd62d15a34060d8650801dcfb24db8f2f", "ba352abc91bee1349bbdcbababd38e954e2020c7"),
    "skia": ("platform/external/skia", "3d74a50ee4a20586b8615c96da9090c2597582d0", "7cd90d4eecdba0f40a36945749d40df95d6d641b"),
    # Required by AOSP build/core/dex_preopt.mk's TEN bootclasspath JARs.
    # ext.jar is assembled from these four projects by frameworks/base/Android.mk.
    "nist-sip": ("platform/external/nist-sip", "9cac60cc160c80dcaac4539c956da8d55b9a2f18", "b23dbfce7ea84c39cea75b612868a5832cb9af2b"),
    "apache-http": ("platform/external/apache-http", "1df3fae4910ec6d921a0ec6bad65925c9e005dad", "3be157fc74e12c82abfa92ee804a35dfb68f4410"),
    "tagsoup": ("platform/external/tagsoup", "7e0b3139bec7f777d42ffda4301f61f9fc9cf646", "68c2ec9e0acdb3214b7fb91dbab8c9fab8736817"),
    "libphonenumber": ("platform/external/libphonenumber", "eaacb07c8c7c5e92af16297842626e3e3b59e6c4", "bf5d9756fe9b13f5b2e0696c62949cea77396687"),
    "junit": ("platform/external/junit", "da0efc69b17c1b0a70f7f5d182953d083b116995", "f4e7f982bdd63feb52e5d63e7a5605d5a7f8df36"),
    "apache-xml": ("platform/external/apache-xml", "98aecc37a53941c0ca951928e42ed7657a3cb9bc", "66ca8092e7de32f4e4c5a3feac68e1c736601f0a"),
    "mms-common": ("platform/frameworks/opt/mms", "5b533b76fe69457a3dcedd9f7ba34bfdb4524634", "b43774ad8fe7855acb2b23837003b44cebabdc73"),
}


def command(*args: str, cwd: Path = ROOT, timeout: int = 400) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True,
                            timeout=timeout, check=True)
    return result.stdout.strip()


def acquire(name: str, project: str, tag_object: str, commit: str) -> dict:
    location = DEST / name
    url = f"https://android.googlesource.com/{project}.git"
    if not (location / ".git").is_dir():
        command("git", "clone", "--depth=1", "--filter=blob:none",
                "--single-branch", "--branch", TAG, url, str(location))
    origin = command("git", "remote", "get-url", "origin", cwd=location)
    head = command("git", "rev-parse", "HEAD", cwd=location)
    tag = command("git", "rev-parse", f"refs/tags/{TAG}", cwd=location)
    peeled = command("git", "rev-parse", f"refs/tags/{TAG}^{{}}", cwd=location)
    official = command("git", "ls-remote", url,
                       f"refs/tags/{TAG}", f"refs/tags/{TAG}^{{}}")
    expect = {f"{tag_object}\trefs/tags/{TAG}",
              f"{commit}\trefs/tags/{TAG}^{{}}"}
    if origin != url or head != commit or tag != tag_object or peeled != commit \
            or set(official.splitlines()) != expect:
        raise ValueError(f"{name}: upstream tag/commit differs; abort")
    if command("git", "status", "--porcelain", cwd=location):
        raise ValueError(f"{name}: local checkout changed; abort")
    count = len(command("git", "ls-files", cwd=location).splitlines())
    return {"project": project, "remote": url, "tag_object": tag_object,
            "commit": commit, "local_path": str(location), "tracked_files": count}


def bootstrap() -> dict:
    DEST.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, (project, tag_object, commit) in PROJECTS.items():
        result[name] = acquire(name, project, tag_object, commit)
        print(f"{name}: {result[name]['tracked_files']} files @ {commit[:12]}", flush=True)
    record = {"tag": TAG,
              "scope": f"{len(PROJECTS)} named dependency repositories only, NOT all AOSP",
              "release_ready": False, "tag_signatures_verified": False,
              "repositories": result}
    (DEST / "provenance.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


if __name__ == "__main__":
    bootstrap()
