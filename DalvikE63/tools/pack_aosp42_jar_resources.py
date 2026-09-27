#!/usr/bin/env python3
"""Add AOSP 4.2 Java resources to locally built DEX JARs (never SDK stubs).

Matches the LOCAL_JAVA_RESOURCE_DIRS / LOCAL_JAVA_RESOURCE_FILES selections in
libcore/JavaLibrary.mk, frameworks/base/Android.mk, apache-xml/Android.mk.
Only intermediates under build/ are modified; old APKs, SISX and JARs remain
untouched. Regenerate the C: pins after modifying an archive.
"""
from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "build/aosp-frameworks-base-4.2.2/repo"
DEPS = ROOT / "build/aosp42-runtime-dependencies"
OUTPUT = ROOT / "build/aosp42-framework-build"
IGNORED = {"package.html", "overview.html", ".DS_Store"}


def resources(module: str) -> dict[str, Path]:
    if module == "core":
        libcore = DEPS / "libcore"
        locations = sorted(p for p in libcore.glob("*/src/main/*")
                           if p.is_dir() and p.name in ("java", "resources"))
    elif module == "ext":
        locations = [DEPS / "libphonenumber/java/src"]
    elif module == "apache-xml":
        locations = [DEPS / "apache-xml/src/main/java"]
    elif module == "framework":
        locations = [BASE]
    else:
        raise ValueError(f"no AOSP Java resource selection for {module}")
    answer: dict[str, Path] = {}
    for folder in locations:
        if not folder.is_dir():
            raise FileNotFoundError(folder)
        files = ([BASE / "preloaded-classes"] if module == "framework" else
                 sorted(p for p in folder.rglob("*") if p.is_file()))
        for path in files:
            name = path.relative_to(folder).as_posix()
            if (name.endswith(".java") or path.name in IGNORED or
                    path.name.endswith(".swp") or path.name.endswith("~")):
                continue
            if name in answer:
                raise ValueError(f"duplicate AOSP Java resource {name}")
            answer[name] = path
    if not answer:
        raise ValueError(f"missing AOSP resources for {module}")
    return answer


def pack(module: str, output: Path = OUTPUT) -> int:
    source = output / f"{module}.jar"
    files = resources(module)
    if not source.is_file():
        raise FileNotFoundError(source)
    temp = source.with_name(source.name + ".resources-tmp")
    try:
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(temp, "w") as new:
            names = original.namelist()
            if "classes.dex" not in names or len(names) != len(set(names)):
                raise ValueError("expected unique entries and real classes.dex")
            if original.getinfo("classes.dex").file_size < 112:
                raise ValueError("empty classes.dex")
            if (set(names) - {"META-INF/MANIFEST.MF", "classes.dex"} -
                    set(files)):
                raise ValueError("JAR contains unexpected entries; refusing overwrite")
            for name in names:
                if name in files:
                    continue  # idempotent replacement; not a duplicate ZIP entry
                new.writestr(original.getinfo(name), original.read(name))
            for name, path in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                new.writestr(info, path.read_bytes(), compresslevel=9)
        os.replace(temp, source)
    finally:
        temp.unlink(missing_ok=True)
    return len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", nargs="*",
                        choices=("core", "ext", "apache-xml", "framework"))
    args = parser.parse_args()
    for module_name in (args.modules or ("core", "ext", "apache-xml", "framework")):
        print(f"{module_name}.jar: {pack(module_name)} AOSP resources")
