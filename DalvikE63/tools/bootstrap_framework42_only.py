#!/usr/bin/env python3
"""Acquire ONLY AOSP frameworks/base 4.2.2 source at a pinned commit.

The owner authorized framework-source downloads, not a full AOSP checkout.
The pinned annotated AOSP release tag can be checked against the official
Android Git remote. This script supports a shallow, blob-filtered sparse
checkout or --full-base (ALL files in this ONE frameworks/base repository)
under excluded build/. It does NOT download other AOSP projects: only the
separately authorized indispensable repositories are acquired by
bootstrap_android42_dependencies.py. Sources by themselves are not runtime
JARs; build_aosp42_bootclasspath.py compiles a local candidate.

This is a bootstrap/provenance operation, NOT a runtime test or SIS build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = "android-4.2.2_r1.2"
ANNOTATED_TAG = "4eb8c7c365258ac40fced748db4bb914b07a8679"
COMMIT = "763ef60466ac752a3031719fb86b08486c9946b1"
REMOTE = "https://android.googlesource.com/platform/frameworks/base.git"
MIRROR = "https://github.com/aosp-mirror/platform_frameworks_base.git"
DEST = ROOT / "build/aosp-frameworks-base-4.2.2"
REPO = DEST / "repo"
PATHS = (
    "Android.mk", "NOTICE", "MODULE_LICENSE_APACHE2", "preloaded-classes",
    "core/java", "core/jni", "core/res",
    "services/java", "services/jni", "policy",
    "packages/SystemUI", "graphics/java", "media/java",
    "media/mca/effect/java", "media/mca/filterfw/java",
    "media/mca/filterpacks/java", "location/java", "drm/java",
    "opengl/java", "sax/java", "wifi/java", "keystore/java",
    "icu4j/java", "voip/java", "telephony/java", "libs", "include",
    "native", "tools/aidl", "tools/aapt",
)
REQUIRED = (
    "core/java/android/app/Activity.java",
    "core/java/android/app/ActivityThread.java",
    "core/java/android/content/Context.java",
    "core/java/android/os/ServiceManager.java",
    "services/java/com/android/server/am/ActivityManagerService.java",
    "services/java/com/android/server/SystemServer.java",
)


def run(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(args, cwd=cwd, check=True, text=True,
                          capture_output=True).stdout.strip()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bootstrap(full_base: bool = False) -> dict:
    DEST.mkdir(parents=True, exist_ok=True)
    if not (REPO / ".git").is_dir():
        run("git", "clone", "--depth=1", "--filter=blob:none", "--sparse",
            "--single-branch", "--branch", TAG, "--no-checkout", REMOTE,
            str(REPO))
    source_remote = run("git", "remote", "get-url", "origin", cwd=REPO)
    if source_remote not in (REMOTE, MIRROR):
        raise ValueError("unexpected source remote")
    if (run("git", "rev-parse", f"refs/tags/{TAG}", cwd=REPO) != ANNOTATED_TAG or
            run("git", "rev-parse", f"refs/tags/{TAG}^{{}}", cwd=REPO) != COMMIT or
            run("git", "rev-parse", "HEAD", cwd=REPO) != COMMIT):
        raise ValueError("the annotated tag object/commit moved; refusing new sources")
    official = run("git", "ls-remote", REMOTE,
                   f"refs/tags/{TAG}", f"refs/tags/{TAG}^{{}}")
    expected = {f"{ANNOTATED_TAG}\trefs/tags/{TAG}",
                f"{COMMIT}\trefs/tags/{TAG}^{{}}"}
    if set(official.splitlines()) != expected:
        raise ValueError("official upstream tag/commit differs from checkout")
    if full_base:
        # This expands ONLY the selected frameworks/base repository, not AOSP.
        run("git", "sparse-checkout", "disable", cwd=REPO)
    else:
        run("git", "sparse-checkout", "set", "--no-cone", *PATHS, cwd=REPO)
    run("git", "checkout", "--detach", COMMIT, cwd=REPO)
    if run("git", "status", "--porcelain", cwd=REPO):
        raise ValueError("source mirror has uncommitted changes")
    paths = {}
    for name in REQUIRED:
        path = REPO / name
        if not path.is_file():
            raise ValueError(f"missing framework source {name}")
        paths[name] = sha(path)
    # The annotated tag and peeled commit were retrieved from the AOSP mirror.
    # Their signature has NOT been verified with an independent GPG trust key.
    record = {
        "scope": ("FULL frameworks/base repo ONLY; NO other AOSP projects" if full_base
                  else "SPARSE frameworks/base ONLY; NO other AOSP projects"),
        "tag": TAG, "annotated_tag_sha": ANNOTATED_TAG,
        "commit": COMMIT, "remote": source_remote,
        "independently_checked_official_remote": REMOTE,
        "paths": ["ALL files in frameworks/base"] if full_base else list(PATHS),
        "required_sha256": paths,
        "tag_signature_verified": False, "runtime_jar_produced": False,
        "location": str(REPO),
    }
    (DEST / "provenance.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-base", action="store_true",
                        help="Check out every file of frameworks/base only")
    args = parser.parse_args()
    print(json.dumps(bootstrap(full_base=args.full_base), indent=2))
