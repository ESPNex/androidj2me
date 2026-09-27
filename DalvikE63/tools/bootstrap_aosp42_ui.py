#!/usr/bin/env python3
"""Acquire ONLY the Android 4.2 system UI packages necessary for this port.

Launcher2 supplies the real HOME Activity, Settings supplies the platform
settings Activity and PackageInstaller handles real Android APK installation.
SystemUI source is already inside the separately pinned frameworks/base tree.
The six further sources are ONLY its or these apps' declared Java build
libraries (frameworks/ex, frameworks/support, guava, jsr305) and RenderScript
compile-time headers (frameworks/rs, external/clang). The latter are sparse.
No full AOSP tree or optional Google/third-party UI is checked out. All large
repositories live under excluded build/. This is SOURCE, not UI execution.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "build/aosp42-ui-dependencies"
TAG = "android-4.2.2_r1.2"
REPOSITORIES = {
    "Launcher2": ("platform/packages/apps/Launcher2",
                  "c6b1e34fe6007735a81045f08b1161aea1a8d259",
                  "002c25eede2a33a5378c16c5bb9165179783e729"),
    "Settings": ("platform/packages/apps/Settings",
                 "a326cb7420db5d1111a2d9a636e24bc307c8c81d",
                 "29a4eb7a33da12a957b3305138ada69140d8ab75"),
    "PackageInstaller": ("platform/packages/apps/PackageInstaller",
                         "b44c0912870c341177ae8a11022eb10ad4749a8e",
                         "8c61b898160c77798d72840fb990476ccfcb9eaf"),
    # AOSP Android.mk dependencies used by Launcher2/SystemUI/Settings.
    "frameworks-ex": ("platform/frameworks/ex",
                      "b09e9261e47adfea7535ac1b279bd95a49d6da76",
                      "a918fec5a1dc028e9b04a71d0e37ee1bab6caa61"),
    "frameworks-support": ("platform/frameworks/support",
                           "43bfb2e093267cee85ebf61351e5ef13b1d189be",
                           "0bb301ec35dcaf2ea9c2010790d7eadb1918b8cb"),
    "guava": ("platform/external/guava",
              "baa7bf444659d77c6f832a672c81e654a3539610",
              "515370823799decea74751ff3a78b80e44e71219"),
    "jsr305": ("platform/external/jsr305",
               "e2e0294edcfc124a0d2bc3c30213ba37e46b2f77",
               "5c7719ffff2b6b6acfde07b0e41c08224f443a7b"),
    "frameworks-rs": ("platform/frameworks/rs",
                      "5239f7ba5b68760afaaed9bd2180fb74fbcd6c5d",
                      "36f07d854de88949d632f77bffab322ffa826bcc"),
    "external-clang": ("platform/external/clang",
                       "fb6934b7c7760bcd71be5b6f0e1b4bf6bb2886a5",
                       "210d8aa7162e928d81d3f284b5ca7bc6bb3a9ba7"),
}
SPARSE = {"frameworks-rs": ("scriptc",),
          "external-clang": ("lib/Headers",)}


def command(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                          text=True, timeout=300).stdout.strip()


def acquire() -> dict:
    DEST.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, (project, tag_object, commit) in REPOSITORIES.items():
        url = f"https://android.googlesource.com/{project}.git"
        location = DEST / name
        if not (location / ".git").is_dir():
            options = ("--no-checkout",) if name in SPARSE else ()
            command("git", "clone", "--depth=1", "--filter=blob:none",
                    "--single-branch", "--branch", TAG, *options, url,
                    str(location))
            if name in SPARSE:
                command("git", "sparse-checkout", "set", "--cone",
                        *SPARSE[name], cwd=location)
                command("git", "checkout", "--detach", commit, cwd=location)
        if (command("git", "remote", "get-url", "origin", cwd=location) != url or
                command("git", "rev-parse", "HEAD", cwd=location) != commit or
                command("git", "rev-parse", f"refs/tags/{TAG}", cwd=location) != tag_object or
                command("git", "rev-parse", f"refs/tags/{TAG}^{{}}", cwd=location) != commit or
                command("git", "status", "--porcelain", cwd=location)):
            raise ValueError(f"{name}: tag/commit/source modified")
        remote = command("git", "ls-remote", url, f"refs/tags/{TAG}",
                         f"refs/tags/{TAG}^{{}}")
        if set(remote.splitlines()) != {f"{tag_object}\trefs/tags/{TAG}",
                                           f"{commit}\trefs/tags/{TAG}^{{}}"}:
            raise ValueError(f"{name}: official AOSP tag moved")
        result[name] = {"project": project, "tag_object": tag_object,
                        "commit": commit, "local_path": str(location)}
        print(f"{name}: {commit[:12]} at official AOSP {TAG}", flush=True)
    record = {"tag": TAG, "repositories": result,
              "scope": "three UI packages, four Java libraries, two sparse RS headers", 
              "running_ui": False, "tag_gpg_verified": False}
    (DEST / "provenance.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


if __name__ == "__main__":
    acquire()
