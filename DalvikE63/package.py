#!/usr/bin/env python3
"""Build a reproducible source/APK ZIP without debug keys or generated state."""
from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT.parent / "DalvikE63_Sorgenti_e_APK.zip"
TOP = {"README_IT.md", "ARCHITETTURA_IT.md", "PORTING_E63_STATO.md",
       "FEDELTA_ANDROID42_IT.md",
       "adapter_preview.py", "build.py", "package.py", "shell.py", "web_preview.py"}
DIRS = {"apks", "apps", "assets", "dalvik", "j2me", "symbian", "tests", "tools"}
IGNORED = {"__pycache__", "build", "state", "imports", ".git", "node_modules",
           ".cache", ".venv"}
IGNORED_EXT = {".pyc", ".jks", ".keystore", ".so", ".class", ".tmp"}


def included():
    for path in ROOT.rglob("*"):
        if not path.is_file(): continue
        relative = path.relative_to(ROOT)
        if any(bit in IGNORED or bit.startswith(".tmp") for bit in relative.parts): continue
        if path.suffix in IGNORED_EXT or path.name.startswith("."): continue
        if not (relative.parts[0] in DIRS or len(relative.parts)==1 and path.name in TOP):continue
        yield path, Path("DalvikE63") / relative


def main():
    files=sorted(included(),key=lambda pair:str(pair[1]))
    assert len(files)>=80 and all((ROOT / "apks" / f"{app}.apk") in
                                  [p for p,_ in files] for app in
                                  ("Launcher", "Settings", "Store", "SystemUI",
                                   "PackageInstaller", "FileManager"))
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=6,
                 allowZip64=True) as archive:
        for path,name in files:
            info=ZipInfo(str(name), date_time=(2026,9,26,0,0,0))
            info.compress_type=ZIP_DEFLATED
            info.external_attr=(0o100644 << 16)
            archive.writestr(info,path.read_bytes(),compress_type=ZIP_DEFLATED,
                             compresslevel=6)
    with ZipFile(OUTPUT) as archive:
        if archive.testzip():raise RuntimeError("archive CRC failed")
    print(f"{OUTPUT}: {len(files)} files, {OUTPUT.stat().st_size:,} bytes")
    print("SHA-256:",hashlib.sha256(OUTPUT.read_bytes()).hexdigest())


if __name__=="__main__":main()
