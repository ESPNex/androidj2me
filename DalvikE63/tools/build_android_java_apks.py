#!/usr/bin/env python3
"""Build SIX genuine Android Activity APKs with per-APK javac+D8 code/assets.

New, separate track: does not overwrite apks/ (MIDP guest), SISX or old JAR.
Compile against binary Android 4.2.2 API-17 stubs, NOT AOSP sources. The
signed APKs have no generated DexWriter/Python screen adapters or copy of the
MIDlet. A bounded interpreter on PC executes their own Java Program DEX;
Android's framework bytecode is *not* executed by the E63 subset VM.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import sign
from dalvik.apk_program import load_apk
from dalvik.axml_reader import inspect
from dalvik.dex_j2me import J2MEDex
from tools.get_android_api17 import DEST as ANDROID, check as check_android
from tools.get_d8 import DEST as D8, check as check_d8
from tools.pack_android_resources import package_android
from tools.make_android_java_images import pack_images

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "android_java/src"
BUILD = ROOT / "build/android_java"
OUT = ROOT / "apks_android"
PERMISSIONS = ("android.permission.READ_EXTERNAL_STORAGE",
               "android.permission.WRITE_EXTERNAL_STORAGE")


@dataclass(frozen=True)
class App:
    slug: str
    label: str
    system: bool
    assets: tuple[str, ...]
    permissions: tuple[str, ...] = ()

    @property
    def package(self): return "org.e63.dalvik." + self.slug

    @property
    def apk_name(self):
        return {"files":"FileManager", "systemui":"SystemUI",
                "packageinstaller":"PackageInstaller"}.get(self.slug,
                         self.slug.capitalize()) + ".apk"


# Installer comes after FileManager: its own asset is the exact signed APK it
# requests Android's system installer to install with user confirmation.
APPS = (
    App("files", "File Manager", False, ("files.png", "lowbattery.wav", "music.wav"), PERMISSIONS),
    App("settings", "Settings", True, ("settings.png",)),
    App("store", "Dalvik Store", True, ("store.png", "banner.png")),
    App("systemui", "SystemUI (simulated)", True, ("warning.png", "lowbattery.wav")),
    App("launcher", "Android J2ME Edition", True, ("wall.png",)),
    App("packageinstaller", "Package Installer", True,
        ("files.png", "packages/FileManager.apk"), PERMISSIONS),
)


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def invoke(command: list[str]):
    result = subprocess.run(command, text=True, capture_output=True, cwd=ROOT)
    if result.returncode:
        raise RuntimeError(f"command failed: {command!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def compile_java(app: App) -> bytes:
    classes = BUILD / app.slug / "classes"
    output = BUILD / app.slug / "dex"
    shutil.rmtree(classes, ignore_errors=True)
    shutil.rmtree(output, ignore_errors=True)
    classes.mkdir(parents=True)
    output.mkdir(parents=True)
    java_files = [SRC / "org/e63/dalvik/runtime/Host.java",
                  SRC / "org/e63/dalvik/runtime/GuestActivity.java",
                  SRC / "org/e63/dalvik" / app.slug / "Main.java",
                  SRC / "org/e63/dalvik" / app.slug / "Program.java"]
    for file in java_files:
        if not file.is_file(): raise FileNotFoundError(file)
    invoke(["javac", "-source", "7", "-target", "7", "-g:none",
            "-bootclasspath", str(ANDROID), "-d", str(classes),
            *map(str, java_files)])
    compiled = sorted(str(path) for path in classes.rglob("*.class"))
    if len(compiled) < 4 or len(compiled) > 20:
        raise RuntimeError("expected Activity/Program/Host Java classfiles")
    invoke(["java", "-cp", str(D8), "com.android.tools.r8.D8",
            "--release", "--no-desugaring", "--min-api", "17",
            "--lib", str(ANDROID), "--output", str(output), *compiled])
    dex = (output / "classes.dex").read_bytes()
    j = J2MEDex(dex)
    required = {"L" + app.package.replace(".", "/") + "/" + name + ";"
                for name in ("Main", "Program")}
    if not required.issubset(j.classes):
        raise RuntimeError("D8 did not compile the Java Activity and Program")
    return dex


def assets_for(app: App, stage: Path) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for name in app.assets:
        if name == "packages/FileManager.apk":
            source = stage / "FileManager.apk"
        else:
            source = ROOT / "assets" / name
        if not source.is_file() or source.stat().st_size > 12 * 1024 * 1024:
            raise FileNotFoundError("missing/oversized per-APK asset: " + str(source))
        sources[name] = source
    return sources


def write_native_pins(registry: list[dict], stage: Path,
                      image_pack: bytes) -> None:
    """Authenticate exact built-in APK bytes before the E63 C99 ZIP/DEX VM.

    This is a fixed per-build SHA-256 allowlist, NOT generic Android APK
    signer verification. The C: adapter must reject any other APK/update.
    """
    def c_string(value: str) -> str:
        return json.dumps(value, ensure_ascii=True)

    lines = ["/* Generated by tools/build_android_java_apks.py. Do not edit.",
             " * Complete signed APK SHA-256 pins, plus asset ownership from the",
             " * per-package build manifest. These authenticate ONLY exact bundled",
             " * builds; they are not an Android certificate trust store. */",
             "#ifndef E63_ANDROID_JAVA_APK_PINS_H",
             "#define E63_ANDROID_JAVA_APK_PINS_H",
             "#include <stddef.h>", "#include <stdint.h>",
             "#define E63_PIN_COUNT 6u",
             "typedef struct E63PinnedApk {",
             "    const char *filename, *package_name, *program;",
             "    size_t length;", "    uint8_t sha256[32];",
             "    const char *const *assets; unsigned asset_count;",
             "} E63PinnedApk;"]
    for number, app in enumerate(registry):
        assets = sorted(app["assets"])
        lines.append("static const char *const e63_pin_assets_%d[] = {%s};" %
                     (number, ", ".join(c_string(asset) for asset in assets)))
    lines.append("static const E63PinnedApk e63_apk_pins[E63_PIN_COUNT] = {")
    for number, app in enumerate(registry):
        content = (stage / app["name"]).read_bytes()
        digest = hashlib.sha256(content).digest()
        hex_bytes = ",".join("0x%02xu" % item for item in digest)
        lines.append("    { %s, %s, %s, %du, { %s }, e63_pin_assets_%d, %du }," %
                     (c_string(app["name"]), c_string(app["package"]),
                      c_string(app["class"]), len(content), hex_bytes,
                      number, len(app["assets"])))
    lines += ["};", "/* Exact RGB565 preview pack built only from PNGs in the pinned APKs. */"]
    image_bytes = ",".join("0x%02xu" % item for item in hashlib.sha256(image_pack).digest())
    lines += ["static const uint8_t e63_apk_images_sha256[32] = { " +
              image_bytes + " };", "#endif", ""]
    destination = ROOT / "symbian/android_java_app/apk_pins.h"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="ascii")


def build_all() -> list[dict]:
    if not check_d8(D8):
        raise RuntimeError("run python3 tools/get_d8.py (pinned D8 binary)")
    if not check_android():
        raise RuntimeError("run python3 tools/get_android_api17.py (binary API-17 compile stubs)")
    if not shutil.which("javac") or not shutil.which("java") or not shutil.which("aapt"):
        raise RuntimeError("JDK javac+java and Android aapt required")
    BUILD.mkdir(parents=True, exist_ok=True)
    stage = BUILD / "stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    registry = []
    for app in APPS:
        dex = compile_java(app)
        assets = assets_for(app, stage)
        index = {name: {"size": source.stat().st_size,
                        "sha256": digest(source.read_bytes())}
                 for name, source in sorted(assets.items())}
        unsigned = package_android(app, dex, assets, index, ROOT, BUILD, ANDROID)
        dest = stage / app.apk_name
        shutil.copyfile(unsigned, dest)
        sign(dest)
        with ZipFile(dest) as zipf:
            info = inspect(zipf.read("AndroidManifest.xml"))
            if (info.package, info.main_class, info.permissions) != (
                    app.package, app.package + ".Main", app.permissions):
                raise RuntimeError("aapt manifest lacks expected Activity/permissions")
            for wav in (n for n in assets if n.endswith(".wav")):
                if zipf.getinfo("assets/" + wav).compress_type != 0:
                    raise RuntimeError("audio asset must be stored for Android MediaPlayer")
        # Independent Android packaging tool, not our XML parser alone.
        badge = invoke(["aapt", "dump", "badging", str(dest)])
        if (f"package: name='{app.package}'" not in badge or
                f"launchable-activity: name='{app.package}.Main'" not in badge or
                f"application-label:'{app.label}'" not in badge):
            raise RuntimeError("aapt cannot recognize a labeled installable Activity")
        cat = {"name": app.apk_name, "package": app.package,
               "entry": app.package + ".Main",
               "class": "L" + app.package.replace(".", "/") + "/Program;",
               "system": app.system, "dex_sha256": digest(dex),
               "assets": index, "java_sources": {
                   str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted([
                       SRC / "org/e63/dalvik/runtime/Host.java",
                       SRC / "org/e63/dalvik/runtime/GuestActivity.java",
                       SRC / "org/e63/dalvik" / app.slug / "Main.java",
                       SRC / "org/e63/dalvik" / app.slug / "Program.java"])}}
        checked = load_apk(dest, expected=cat)
        if checked.class_desc != cat["class"]:
            raise RuntimeError("signed APK lost its Java Program")
        registry.append(cat)
        print(f"{app.apk_name}: {dest.stat().st_size:,} bytes, "
              f"{len(dex):,}-byte D8 Activity/Program DEX, "
              f"{len(assets)} package-specific assets; Android v1 debug signature")
    total = sum((stage / app.apk_name).stat().st_size for app in APPS)
    if total > 10 * 1024 * 1024:
        raise RuntimeError("new six-APK delivery exceeds 10 MiB budget")
    OUT.mkdir(exist_ok=True)
    for app in APPS:
        shutil.copyfile(stage / app.apk_name, OUT / app.apk_name)
    (OUT / "catalog.json").write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    image_pack = pack_images(registry, stage)
    image_path = ROOT / "symbian/android_java_app/images565.bin"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(image_pack)
    write_native_pins(registry, stage, image_pack)
    print(f"{len(APPS)} Android Java APKs staged in {OUT}, {total / 1024**2:.2f} MiB. "
          "No Android device/emulator or Nokia E63 test was performed.")
    return registry


if __name__ == "__main__":
    build_all()
