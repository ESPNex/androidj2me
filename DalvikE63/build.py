#!/usr/bin/env python3
"""Build signed APKs containing the actual D8-converted Java ME classes.

classes.dex: complete compiled J2ME code, built with the *pinned binary* D8.
classes2.dex: small per-app DEX adapter interpreted by the host sandbox VM.
No AOSP checkout; D8 is only obtained separately with explicit consent.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from apps.specs import programs
from dalvik.assembler import DexWriter
from dalvik.axml import manifest
from dalvik.axml_reader import inspect
from dalvik.dex import Dex
from dalvik.dex_j2me import J2MEDex
from dalvik.ids import LAUNCHER
from dalvik.store_j2me import J2MEStoreState
from dalvik.tools import jdk_tool
from tools.get_d8 import DEST as D8_JAR, check as check_d8

HERE = Path(__file__).resolve().parent
OUT = HERE / "apks"
BUILD = HERE / "build"  # generated keystore, excluded from persisted snapshots
KEYSTORE = BUILD / "debug.jks"
DEBUG_PASSWORD = "dalvik-e63-local-only"


def sign(apk: Path) -> None:
    keytool, jarsigner = jdk_tool("keytool"), jdk_tool("jarsigner")
    if not keytool or not jarsigner:
        raise SystemExit("JDK keytool+jarsigner required; refuse to output unsigned APKs")
    if not KEYSTORE.is_file():
        subprocess.run([keytool, "-genkeypair", "-noprompt", "-alias", "dalvik-e63-debug",
                        "-keyalg", "RSA", "-keysize", "2048", "-validity", "3650",
                        "-dname", "CN=Dalvik E63 Debug, O=Local Prototype, C=IT",
                        "-keystore", str(KEYSTORE), "-storetype", "JKS",
                        "-storepass", DEBUG_PASSWORD, "-keypass", DEBUG_PASSWORD],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run([jarsigner, "-keystore", str(KEYSTORE), "-storepass", DEBUG_PASSWORD,
                    "-keypass", DEBUG_PASSWORD, "-digestalg", "SHA-256",
                    "-sigalg", "SHA256withRSA", str(apk), "dalvik-e63-debug"],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check = subprocess.run([jarsigner, "-verify", str(apk)], check=True,
                           capture_output=True, text=True)
    if "jar verified." not in check.stdout:
        raise RuntimeError("jarsigner did not verify " + str(apk))


def converted_j2me() -> tuple[bytes, J2MEDex, str]:
    base = HERE / "j2me"
    jar = base / "Android_J2ME_E63_Bridge.jar"
    frozen = base / "classes.dex"
    provenance_path = base / "source_provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    sha = lambda data: hashlib.sha256(data).hexdigest()
    source_files = sorted([*base.glob("src/**/*.java"), *base.glob("res/*"),
                           base / "MANIFEST.MF"])
    current = {str(p.relative_to(base)): sha(p.read_bytes()) for p in source_files}
    if (provenance.get("schema") != 1 or current != provenance.get("files")
            or sha(jar.read_bytes()) != provenance.get("jar_sha256")):
        raise RuntimeError("J2ME sources/JAR differ from provenance: run j2me/build_j2me.sh")
    if check_d8(D8_JAR):
        java = jdk_tool("java")
        if not java: raise RuntimeError("JDK java not available for D8")
        output = BUILD / "j2me/d8"
        output.mkdir(parents=True, exist_ok=True)
        cmd = [java, "-cp", str(D8_JAR), "com.android.tools.r8.D8",
               "--min-api", "17", "--no-desugaring", "--output", str(output), str(jar)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("D8 failed: " + result.stdout + result.stderr)
        dex = (output / "classes.dex").read_bytes()
        if not frozen.is_file() or frozen.read_bytes() != dex:
            frozen.write_bytes(dex)
        provenance["dex_sha256"] = sha(dex)
        provenance["converter"] = "com.android.tools.r8.D8 8.0.40 --min-api 17 --no-desugaring"
        provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    else:
        if not frozen.is_file() or sha(frozen.read_bytes()) != provenance.get("dex_sha256"):
            raise RuntimeError("pinned D8 binary absent and no validated prebuilt J2ME DEX")
        dex = frozen.read_bytes()
        print("Pinned D8 absent: using source-verified precompiled J2ME classes.dex")
    with zipfile.ZipFile(jar) as archive:
        expected = {"L" + name[:-6] + ";" for name in archive.namelist()
                    if name.endswith(".class")}
    converted = J2MEDex(dex)
    if set(converted.classes) != expected or len(expected) < 7 or \
       not all("Landroid/j2me/edition/" in c for c in expected):
        raise RuntimeError("converted J2ME classes differ from original classfiles")
    model = J2MEStoreState(converted, False)
    if (model.activate(), model.activate()) != (1, 3):
        raise RuntimeError("original J2ME StoreState does not implement INSTALL / WAIT")
    model.finish_install()
    if not model.is_installed() or model.activate() != 2:
        raise RuntimeError("original J2ME StoreState does not implement OPEN")
    return dex, converted, sha(dex)


def build_all() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    j2me_dex, j2me_index, j2me_sha = converted_j2me()
    registry = []
    apps = programs()
    if len({a.apk_name for a in apps}) != len(apps):
        raise ValueError("duplicate APK name")
    for app in apps:
        adapter = DexWriter(app).build()
        parsed = Dex(adapter)  # validate per-app adapter before packaging/signing
        expected = {app.class_desc + "->" + m.name + m.proto for m in app.methods}
        if expected != set(parsed.codes):
            raise ValueError("DEX methods lost during assembly")
        # The OS launcher must enter the actual converted J2ME MIDlet, not
        # the older per-screen adapter class kept for service diagnostics.
        entry = "android.j2me.edition.E63Midlet" if app.package == LAUNCHER else app.main_name
        xml = manifest(app.package, app.label, entry)
        info = inspect(xml)
        if (info.package, info.main_class, info.min_sdk, info.target_sdk) != \
           (app.package, entry, 17, 17):
            raise ValueError("invalid binary manifest")
        dest = OUT / app.apk_name
        unsigned = BUILD / (app.apk_name + ".unsigned")
        with zipfile.ZipFile(unsigned, "w", allowZip64=False) as zipf:
            zipf.writestr("AndroidManifest.xml", xml,
                          compress_type=zipfile.ZIP_STORED)
            zipf.writestr("classes.dex", j2me_dex, compress_type=zipfile.ZIP_STORED)
            zipf.writestr("classes2.dex", adapter, compress_type=zipfile.ZIP_STORED)
            zipf.write(HERE / "j2me/source_provenance.json", "assets/j2me-provenance.json",
                       compress_type=zipfile.ZIP_DEFLATED)
            # The converted MIDlet's Canvas loads images using absolute J2ME
            # resource names. Give each APK the actual pixel assets so its
            # classes.dex can draw without reaching into the source directory.
            with zipfile.ZipFile(HERE / "j2me/Android_J2ME_E63_Bridge.jar") as midlet:
                for resource in sorted(midlet.namelist()):
                    if "/" not in resource and (resource.endswith(".png") or
                        resource == "lowbattery.wav" or
                        resource == "music.wav" and app.package in ("org.e63.dalvik.launcher",
                                                                  "org.e63.dalvik.files")):
                        zipf.writestr("assets/j2me/" + resource, midlet.read(resource),
                                      compress_type=zipfile.ZIP_DEFLATED)
            for archive_name, file_path in sorted((app.assets or {}).items()):
                source = HERE / file_path
                if not source.is_file(): raise FileNotFoundError(source)
                zipf.write(source, archive_name, compress_type=zipfile.ZIP_DEFLATED)
        shutil.copyfile(unsigned, dest)
        sign(dest)
        registry.append({"name": app.apk_name, "package": app.package,
                         "class": app.class_desc, "entry": entry, "system": app.system,
                         "j2me_dex_sha256": j2me_sha,
                         "j2me_classes": len(j2me_index.classes),
                         "j2me_methods": len(j2me_index.methods),
                         "adapter_sha256": hashlib.sha256(adapter).hexdigest(),
                         "methods": sorted(m.name + m.proto for m in app.methods)})
        print(f"{dest.relative_to(HERE)}: {dest.stat().st_size:,} bytes, "
              f"{len(j2me_dex):,}-byte J2ME classes.dex + {len(adapter):,}-byte "
              f"adapter classes2.dex, v1 signed")
    (OUT / "catalog.json").write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
    print("APK build/DEX parse/JDK signature verification succeeded (not tested on Android 4.2).")


if __name__ == "__main__":
    build_all()
