#!/usr/bin/env python3
"""Compile four genuine AOSP 4.2.2_r1.2 system UI *candidates* locally.

Consumes ONLY the independently pinned sources/host tools already acquired by
bootstrap_framework42_only.py, bootstrap_android42_dependencies.py,
bootstrap_aosp42_ui.py and bootstrap_aosp42_host_tools.py. Builds AOSP Java,
AOSP static libraries, SystemUI carousel RenderScript, AOSP resources and DEX.
Signs v1 APKs with AOSP build/ public DEVELOPMENT platform/shared test keys
using SignApk compiled from pinned AOSP sources, not production device keys.
No replacement Java Activity, fake UI or precompiled third-party Android JAR.

The APKs are out-of-tree builds: NOT a complete Android product build, not
production-trusted, and NOT proof of any Activity running on Nokia.
AOSP's historical prebuilt llvm-rs-cc supports target API 16, not 17: the
carousel is compiled from original .rs with target 16 and this discrepancy is
recorded. Only excluded build/ receives APKs and generated large artifacts.
No existing 0.2 APK, SISX, JAR, release, or packaged diagnostic is overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import ssl
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.bootstrap_aosp42_ui import REPOSITORIES, DEST as UI, TAG
from tools.bootstrap_aosp42_host_tools import FILES as TOOL_FILES, DEST as HOST, sha256
from tools.aosp42_eventlog_tags import generate as logtags
from tools.stage_android42_runtime import (
    BOOT_HEADER, BOOT_MAGIC, BOOT_RECORD, dex_class_entries,
    executable_classes, inspect,
)

BASE = ROOT / "build/aosp-frameworks-base-4.2.2/repo"
FMW = ROOT / "build/aosp42-framework-build"
OUT = ROOT / "build/aosp42-ui-build"
STAGE = ROOT / "build/staged-android42-system/ui-app"
INDEX_STAGE = ROOT / "build/staged-android42-system/ui-index"
MANIFEST_STAGE = ROOT / "build/staged-android42-system/ui-manifest"
HEADER = ROOT / "symbian/android_java_app/ui_apk_pins.h"
JDK = HOST / "jdk8/bin/java"
ECJ = HOST / "ecj-aosp42.jar"
AAPT = HOST / "aapt"
DX = HOST / "dx.jar"
RS = HOST / "llvm-rs-cc"
JAVAC = HOST / "jdk8/bin/javac"
JAR = HOST / "jdk8/bin/jar"
SIGNTOOLS = HOST / "signapk"
SIGN_JAR = SIGNTOOLS / "aosp42-signapk-host.jar"
DEVKEYS = ROOT / "build/aosp42-runtime-dependencies/build/target/product/security"
BOUNCY = ROOT / "build/aosp42-runtime-dependencies/bouncycastle"
CORE = FMW / "core-classes"
FRAMEWORK = FMW / "framework/classes"
UI_APPS = ("Launcher2", "Settings", "PackageInstaller", "SystemUI")
# Extra filename segment keeps the legacy 0.2 APKs and simulated SystemUI
# intact while allowing genuine 4.2 package identities side-by-side.
GUEST_APKS = {"Launcher2": "Launcher2.apk",
              "Settings": "AOSP42Settings.apk",
              "PackageInstaller": "AOSP42PackageInstaller.apk",
              "SystemUI": "AOSP42SystemUI.apk"}
PACKAGES = {"Launcher2": "com.android.launcher",
            "Settings": "com.android.settings",
            "PackageInstaller": "com.android.packageinstaller",
            "SystemUI": "com.android.systemui"}
COMPONENT_TYPE = {"Launcher2": "activity", "Settings": "activity",
                  "PackageInstaller": "activity", "SystemUI": "service"}
# Paired requirements from the REAL AOSP 4.2 manifests, not simulated actions.
# The native AXML reader requires both entries in the SAME intent-filter.
REQUIRED_INTENTS = {
    "Launcher2": ("android.intent.action.MAIN", "android.intent.category.HOME"),
    "Settings": ("android.settings.SETTINGS", "android.intent.category.LAUNCHER"),
    "PackageInstaller": ("android.intent.action.INSTALL_PACKAGE",
                         "android.intent.category.DEFAULT"),
    "SystemUI": (None, None),  # A service; not an Activity or HOME intent.
}
SYSTEM_UI = BASE / "packages/SystemUI"
# AOSP Android.mk LOCAL_STATIC_JAVA_LIBRARIES (in original declared order).
STATIC = {
    "Launcher2": ("android-common", "android-support-v13", "android-support-v4"),
    "Settings": ("guava", "android-support-v4", "jsr305"),
    "PackageInstaller": ("android-support-v4",),
    "SystemUI": ("android-common-carousel",),
}
REQUIRED_CLASSES = {
    "Launcher2": ("Lcom/android/launcher2/Launcher;",),
    "Settings": ("Lcom/android/settings/Settings;",),
    "PackageInstaller": ("Lcom/android/packageinstaller/PackageInstallerActivity;",),
    "SystemUI": ("Lcom/android/systemui/SystemUIService;",),
}


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def files(path: Path) -> list[Path]:
    if not path.is_dir():
        raise FileNotFoundError(path)
    return sorted(path.rglob("*.java"))


def run(cmd: list[str], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        result = subprocess.run(cmd, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise RuntimeError(f"{cmd[0]} failed ({result.returncode}), {log}:\n" +
                           "\n".join(log.read_text(errors="replace").splitlines()[-85:]))


def validate() -> dict[str, str]:
    from tools.bootstrap_framework42_only import COMMIT as BASE_COMMIT
    from tools.bootstrap_android42_dependencies import PROJECTS as BOOT_REPOS
    repos = {"frameworks/base": (BASE, BASE_COMMIT)}
    repos.update({name: (UI / name, pins[2])
                  for name, pins in REPOSITORIES.items()})
    repos.update({name: (ROOT / "build/aosp42-runtime-dependencies" / name,
                         BOOT_REPOS[name][2]) for name in ("build", "bouncycastle")})
    for name, (location, commit) in repos.items():
        if not (location / ".git").is_dir():
            raise FileNotFoundError(f"missing AOSP UI repository {name}")
        head = subprocess.check_output(["git", "-C", str(location), "rev-parse",
                                        "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(location), "status",
                                         "--porcelain"], text=True).strip()
        if head != commit or dirty:
            raise ValueError(f"wrong/modified AOSP UI repository {name}")
    for name, (_, expected, _) in TOOL_FILES.items():
        if not (HOST / name).is_file() or sha256(HOST / name) != expected:
            raise ValueError(f"missing/modified SHA-pinned host tool {name}")
    if not (JDK.is_file() and DX.is_file() and CORE.is_dir() and FRAMEWORK.is_dir()):
        raise FileNotFoundError("compile and stage 10 boot JARs first")
    manifest = json.loads((FMW / "local-build-provenance.json").read_text())
    if manifest["tag"] != TAG or manifest["android_runtime_ready"]:
        raise ValueError("untrusted boot build provenance")
    for name, record in manifest["artifacts"].items():
        size, _ = inspect(FMW / name, ())
        if size != record["bytes"] or sha256(FMW / name) != record["sha256"]:
            raise ValueError(f"framework artifact changed: {name}")
    return {name: commit for name, (_, commit) in repos.items()}


def ecj(name: str, source_files: list[Path], dependencies: tuple[Path, ...]) -> Path:
    if not source_files or len(source_files) != len(set(source_files)):
        raise ValueError(f"empty or repeated sources: {name}")
    out = OUT / name
    classes = out / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    listing = out / "sources.list"
    listing.write_text("\n".join(relative(path) for path in source_files) + "\n")
    cp = tuple(relative(p) for p in (FRAMEWORK, *dependencies))
    run([str(JDK), "-Xmx1250m", "-XX:+UseSerialGC", "-jar", str(ECJ),
         "-6", "-nowarn", "-maxProblems", "120", "-encoding", "UTF-8",
         "-bootclasspath", relative(CORE), "-classpath", ":".join(cp),
         "-d", relative(classes), "@" + relative(listing)], out / "ecj.log")
    count = sum(1 for _ in classes.rglob("*.class"))
    if not count:
        raise ValueError(f"{name}: ECJ produced no bytecode")
    print(f"{name}: {count} AOSP Java classes", flush=True)
    return classes


def render_carousel() -> Path:
    source = UI / "frameworks-ex/carousel/java/com/android/ex/carousel/carousel.rs"
    out = OUT / "android-common-carousel"
    gen = out / "generated"
    raw = out / "renderscript-res/raw"
    gen.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    # AOSP tag's pinned prebuilt host tool has max API 16 (NOT 17).
    run([str(RS), "-o", relative(raw), "-java-reflection-path-base",
         relative(gen), "-target-api", "16", "-I",
         relative(UI / "external-clang/lib/Headers"), "-I",
         relative(UI / "frameworks-rs/scriptc"), relative(source)],
        out / "llvm-rs-cc.log")
    if not (raw / "carousel.bc").is_file() or len(files(gen)) != 4:
        raise ValueError("genuine RenderScript carousel output incomplete")
    print("SystemUI carousel: source .rs -> genuine bitcode and four Java bindings "
          "(API 16 host compiler)", flush=True)
    return out / "renderscript-res"


def resources(name: str, *, rs_res: Path | None = None) -> Path:
    src = SYSTEM_UI if name == "SystemUI" else UI / name
    out = OUT / name
    gen = out / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    args = [str(AAPT), "package", "-f", "-m", "-M",
            relative(src / "AndroidManifest.xml")]
    if rs_res is not None:
        args += ["-S", relative(rs_res)]
    args += ["-S", relative(src / "res"), "-I",
             relative(FMW / "framework-res.apk")]
    if (src / "assets").is_dir():
        args += ["-A", relative(src / "assets")]
    args += ["-J", relative(gen), "-F", relative(out / "resources.ap_")]
    run(args, out / "aapt.log")
    pkg = {"Launcher2": "com/android/launcher", "Settings": "com/android/settings",
           "PackageInstaller": "com/android/packageinstaller",
           "SystemUI": "com/android/systemui"}[name]
    if not (gen / pkg / "R.java").is_file():
        raise ValueError(f"AOSP aapt did not generate {name} R.java")
    print(f"{name}: AOSP compiled resources/AndroidManifest.xml", flush=True)
    return out / "resources.ap_"


def java6_guava_sources() -> list[Path]:
    """Strip only @Override on abstract Object members in ephemeral copies.

    Historic ECJ -6 disallows @Override when interfaces redeclare Object's
    equals/hashCode/toString. Source-retention annotations do NOT change any
    DEX API or code. AOSP git sources remain unchanged and the EXACT allowed
    files/counts are checked against the tag. Includes nested subinterfaces.
    """
    original = UI / "guava/guava/src"
    sources = files(original)
    allowed = {
        "com/google/common/base/Function.java": 1,
        "com/google/common/base/Predicate.java": 1,
        "com/google/common/collect/Constraint.java": 1,
        "com/google/common/collect/ListMultimap.java": 1,
        "com/google/common/collect/MapConstraint.java": 1,
        "com/google/common/collect/MapDifference.java": 4,
        "com/google/common/collect/Multimap.java": 2,
        "com/google/common/collect/Multiset.java": 6,
        "com/google/common/collect/SetMultimap.java": 1,
        "com/google/common/collect/Table.java": 4,
    }
    pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)@Override(?P<gap>[ \t]*\n[ \t]*|[ \t]+)"
        r"(?=(?://[^\n]*\n[ \t]*)*(?:boolean\s+equals\([^\n]*\)|int\s+hashCode\(\)|"
        r"String\s+toString\(\))\s*;)"
    )
    actual: dict[str, int] = {}
    for idx, source in enumerate(sources):
        src = source.relative_to(original).as_posix()
        text = source.read_text()
        patched, count = pattern.subn(lambda m: m.group("indent"), text)
        if not count:
            continue
        actual[src] = count
        dest = OUT / "guava/compat-source" / src
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(patched)
        sources[idx] = dest
    if actual != allowed:
        raise ValueError(f"Guava source/tag or Java 6 compat list changed: {actual}")
    print("Guava: 22 transient SOURCE-only @Override removals for ECJ -6 "
          "(AOSP tree unchanged)", flush=True)
    return sources


def build_static(rs_res: Path) -> dict[str, Path]:
    output: dict[str, Path] = {}
    output["jsr305"] = ecj("jsr305", files(UI / "jsr305/ri/src/main/java"), ())
    output["guava"] = ecj("guava", java6_guava_sources(),
                            (output["jsr305"],))
    output["android-support-v4"] = ecj("android-support-v4",
        files(UI / "frameworks-support/v4/eclair") +
        files(UI / "frameworks-support/v4/froyo") +
        files(UI / "frameworks-support/v4/gingerbread") +
        files(UI / "frameworks-support/v4/honeycomb") +
        files(UI / "frameworks-support/v4/honeycomb_mr2") +
        files(UI / "frameworks-support/v4/ics") +
        files(UI / "frameworks-support/v4/ics-mr1") +
        files(UI / "frameworks-support/v4/jellybean") +
        files(UI / "frameworks-support/v4/jellybean-mr1") +
        files(UI / "frameworks-support/v4/java"), ())
    output["android-support-v13"] = ecj("android-support-v13",
        files(UI / "frameworks-support/v13/ics") +
        files(UI / "frameworks-support/v13/ics-mr1") +
        files(UI / "frameworks-support/v13/java"),
        (output["android-support-v4"],))
    source = UI / "frameworks-ex/common/java"
    generated = OUT / "android-common/logtags-generated/com/android/common/EventLogTags.java"
    logtags(source / "com/android/common/GoogleLogTags.logtags", generated)
    output["android-common"] = ecj("android-common",
        files(source) + [generated], ())
    output["android-common-carousel"] = ecj("android-common-carousel",
        files(UI / "frameworks-ex/carousel/java") +
        files(OUT / "android-common-carousel/generated"), ())
    if not (rs_res / "raw/carousel.bc").is_file():
        raise ValueError("SystemUI carousel bitcode missing")
    return output


def build_aosp_signapk() -> None:
    """Compile the tag's SignApk + BouncyCastle's ORIGINAL host RI selection.

    Device BouncyCastle uses OpenSSLDigest JNI and cannot sign on a host.
    AOSP Android.mk selects the other original BouncyCastle digest class for
    bouncycastle-host. Do not transplant the Android device library here.
    """
    bc = BOUNCY / "bcprov/src/main/java"
    sources = [p for p in files(bc) if p.name not in
               ("AndroidDigestFactoryOpenSSL.java", "OpenSSLDigest.java")]
    if len(sources) != 559 or not (bc / "org/bouncycastle/crypto/digests/"
                                 "AndroidDigestFactoryBouncyCastle.java").is_file():
        raise ValueError("AOSP BouncyCastle host build-source selection changed")
    for key in ("platform", "shared"):
        if not (DEVKEYS / (key + ".pk8")).is_file() or not (
                DEVKEYS / (key + ".x509.pem")).is_file():
            raise FileNotFoundError("AOSP public development test keys absent")
    classes = SIGNTOOLS / "classes"
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(parents=True)
    src_list = SIGNTOOLS / "bcprov-sources.list"
    src_list.write_text("\n".join(relative(p) for p in sources) + "\n")
    run([str(JAVAC), "-J-Xmx1200m", "-source", "7", "-target", "7",
         "-encoding", "UTF-8", "-d", relative(classes),
         "@" + relative(src_list)], SIGNTOOLS / "bcprov.log")
    pkix = files(BOUNCY / "bcpkix/src/main/java")
    sign = ROOT / "build/aosp42-runtime-dependencies/build/tools/signapk/SignApk.java"
    if len(pkix) != 65 or not sign.is_file():
        raise ValueError("AOSP host SignApk/bcpkix sources changed")
    src_list.write_text("\n".join(relative(p) for p in [*pkix, sign]) + "\n")
    run([str(JAVAC), "-J-Xmx1100m", "-source", "7", "-target", "7",
         "-encoding", "UTF-8", "-cp", relative(classes),
         "-d", relative(classes), "@" + relative(src_list)],
        SIGNTOOLS / "signapk-javac.log")
    SIGN_JAR.unlink(missing_ok=True)
    run([str(JAR), "cf", relative(SIGN_JAR), "-C", relative(classes), "."],
        SIGNTOOLS / "jar.log")
    with zipfile.ZipFile(SIGN_JAR) as jar:
        if ("com/android/signapk/SignApk.class" not in jar.namelist() or
            "org/bouncycastle/crypto/digests/AndroidDigestFactoryBouncyCastle.class"
            not in jar.namelist() or
            "org/bouncycastle/crypto/digests/AndroidDigestFactoryOpenSSL.class"
            in jar.namelist()):
            raise ValueError("host SignApk contains device OpenSSL or missing RI classes")
    # AOSP 4.2's SHA1withRSA v1 was standard then; present-day Temurin 8
    # DISABLES SHA-1 for jarsigner. This local verification-only override
    # tests historical v1 integrity, never relaxes system security settings.
    (SIGNTOOLS / "jarsigner-compat.security").write_text(
        "jdk.jar.disabledAlgorithms=MD2, MD5, RSA keySize < 1024\n")
    print("AOSP host SignApk/bcprov/bcpkix compiled; public DEV keys only", flush=True)


def dev_certificate(name: str, apk: Path) -> str:
    signed = zipfile.ZipFile(apk)
    with signed:
        try:
            block = signed.read("META-INF/CERT.RSA")
        except KeyError as exc:
            raise ValueError(f"missing {name} Android v1 signature") from exc
    extracted = subprocess.run(["openssl", "pkcs7", "-inform", "DER",
                                "-print_certs"], input=block, capture_output=True,
                               check=True).stdout.decode("ascii")
    matches = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
                         extracted, flags=re.S)
    if len(matches) != 1:
        raise ValueError("expected exactly one AOSP test signing certificate")
    actual = ssl.PEM_cert_to_DER_cert(matches[0])
    expected = ssl.PEM_cert_to_DER_cert(
        (DEVKEYS / (name + ".x509.pem")).read_text())
    if actual != expected:
        raise ValueError("APK not signed by selected AOSP development key")
    return hashlib.sha256(expected).hexdigest()


def sign_apk(name: str, unsigned: Path, apk: Path) -> tuple[str, str]:
    cert = "shared" if name == "Launcher2" else "platform"
    run([str(JDK), "-Xmx900m", "-XX:+UseSerialGC", "-cp", str(SIGN_JAR),
         "com.android.signapk.SignApk", str(DEVKEYS / (cert + ".x509.pem")),
         str(DEVKEYS / (cert + ".pk8")), relative(unsigned), relative(apk)],
        OUT / name / "signapk.log")
    compat = SIGNTOOLS / "jarsigner-compat.security"
    run([str(HOST / "jdk8/bin/jarsigner"),
         "-J-Djava.security.properties=" + str(compat), "-verify", "-verbose",
         str(apk)], OUT / name / "jarsigner.log")
    output = (OUT / name / "jarsigner.log").read_text()
    if "jar verified." not in output or not re.search(
            r"(?m)^sm\s+\d+.*classes\.dex$", output):
        raise ValueError(f"AOSP testkey v1 signature did not verify: {name}")
    return cert, dev_certificate(cert, apk)


def make_apk(name: str, support: dict[str, Path], resource_zip: Path) -> dict:
    src = SYSTEM_UI if name == "SystemUI" else UI / name
    out = OUT / name
    source_files = files(src / "src") + files(out / "generated")
    deps = tuple(support[key] for key in STATIC[name])
    # These Android.mk LOCAL_JAVA_LIBRARIES are on the bootclasspath, not
    # duplicated as static code inside application DEX.
    cp = deps + tuple(FMW / key / "classes" for key in
                       ("telephony-common", "services", "ext", "mms-common",
                        "bouncycastle"))
    classes = ecj(name, source_files, cp)
    dex = out / "classes.dex"
    run([str(JDK), "-Xmx1250m", "-XX:+UseSerialGC", "-cp", str(DX),
         "com.android.dx.command.Main", "--dex", "--num-threads=1",
         "--output=" + relative(dex), relative(classes),
         *(relative(dep) for dep in deps)], out / "dx.log")
    data = dex.read_bytes()
    classes_list = dex_class_entries(data)
    executable = executable_classes(data, classes_list)
    if not set(REQUIRED_CLASSES[name]).issubset(executable):
        raise ValueError(f"{name}: Activity/Service DEX method code missing")
    unsigned = out / (name + "-unsigned.apk")
    apk = out / (name + ".apk")
    # ZIP_STORED primary DEX: the native file reader validates CRC32 without
    # decompression. SignApk keeps the STORED method and its byte-identical DEX.
    shutil.copyfile(resource_zip, unsigned)
    with zipfile.ZipFile(unsigned, "a") as archive:
        archive.writestr("classes.dex", data, compress_type=zipfile.ZIP_STORED)
    cert, cert_sha = sign_apk(name, unsigned, apk)
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if (len(names) != len(set(names)) or "AndroidManifest.xml" not in names or
            "resources.arsc" not in names or archive.read("classes.dex") != data or
            archive.getinfo("classes.dex").compress_type != zipfile.ZIP_STORED or
            not {"META-INF/MANIFEST.MF", "META-INF/CERT.SF",
                 "META-INF/CERT.RSA"}.issubset(names) or archive.testzip()):
            raise ValueError(f"{name}: incomplete/invalid AOSP v1-signed APK")
    print(f"{name}: {len(classes_list)} DEX classes, {len(data)} DEX bytes, "
          f"{apk.stat().st_size} APK bytes (AOSP {cert} DEVELOPMENT key)", flush=True)
    return {"apk": apk, "dex": dex, "dex_classes": len(classes_list),
            "required_executable": list(REQUIRED_CLASSES[name]),
            "apk_sha256": sha256(apk), "dex_sha256": hashlib.sha256(data).hexdigest(),
            "apk_bytes": apk.stat().st_size, "dex_bytes": len(data),
            "aosp_development_certificate": cert,
            "certificate_sha256": cert_sha}


def ui_class_index(name: str, dex: Path) -> dict:
    """Per-package E63BOOT2 class index, slot ZERO = this APK's stored DEX.

    This reuses only the existing small on-disk binary-search index format.
    It never inserts app classes into the ten-archive bootclasspath, and a
    native lookup MUST re-confirm the class_def in the SHA-pinned APK.
    """
    data = dex.read_bytes()
    classes = dex_class_entries(data)
    rows = bytearray(BOOT_HEADER.pack(BOOT_MAGIC, 2, BOOT_RECORD.size,
                                      len(classes), 0))
    if not 0 < len(classes) < 10000:
        raise ValueError("UI class index out of bounds")
    for pos, descriptor in sorted(enumerate(classes), key=lambda row: row[1]):
        raw = descriptor.encode("ascii")
        if len(raw) >= 256:
            raise ValueError("UI descriptor too long")
        rows.extend(BOOT_RECORD.pack(raw, 0, pos, len(raw)))
    target = INDEX_STAGE / (name + ".idx")
    target.write_bytes(rows)
    if len(rows) != BOOT_HEADER.size + len(classes) * BOOT_RECORD.size:
        raise ValueError("bad UI class index encoding")
    return {"index_bytes": len(rows), "index_sha256": sha256(target)}


def stage_compiled_manifest(name: str, apk: Path) -> dict:
    """Preserve EXACT decompressed AAPT AXML bytes as a small /data cache.

    Nokia's ezlib 1.1.3 documents only positive windowBits and does not
    promise raw ZIP deflate. The on-device parser can instead read the copied
    bytes at offsets, after authenticating BOTH original whole APK and this
    independently SHA-pinned cache. No full APK/manifest is held in RAM.
    """
    with zipfile.ZipFile(apk) as archive:
        info = archive.getinfo("AndroidManifest.xml")
        if (not 40 <= info.file_size <= 128 * 1024 or
                info.compress_type not in (zipfile.ZIP_DEFLATED,
                                           zipfile.ZIP_STORED)):
            raise ValueError(f"unsupported AndroidManifest.xml: {name}")
        raw = archive.read(info)
    if len(raw) != info.file_size or raw[:4] != b"\x03\x00\x08\x00" or \
            int.from_bytes(raw[4:8], "little") != len(raw):
        raise ValueError(f"not bounded AAPT binary XML: {name}")
    MANIFEST_STAGE.mkdir(parents=True, exist_ok=True)
    cached = MANIFEST_STAGE / (name + ".axml")
    cached.write_bytes(raw)
    if cached.read_bytes() != raw:
        raise ValueError("AXML staging changed")
    return {"manifest_guest_path": "/data/e63-uimanifest/" + name + ".axml",
            "manifest_relative_on_c": "data\\e63-uimanifest\\" + name + ".axml",
            "manifest_bytes": len(raw),
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "intent_action": REQUIRED_INTENTS[name][0],
            "intent_category": REQUIRED_INTENTS[name][1]}


def _bytes(digest: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid UI SHA-256 pin")
    return "{" + ",".join(f"0x{digest[i:i+2]}u" for i in range(0, 64, 2)) + "}"


def _literal(value: str | None) -> str:
    if value is None:
        return "0"  # GCCE's C header on Symbian does not expose NULL here.
    if not re.fullmatch(r"[A-Za-z0-9_.]+", value):
        raise ValueError("invalid Android intent pin")
    return f'"{value}"'


def pin_header(manifests: dict[str, dict]) -> None:
    lines = [
        "/* Unreleased AOSP UI CANDIDATES: indexes/classes, NOT running Activities.",
        " * Built from pinned 4.2.2_r1.2 sources. Never overwrite 0.2 APK pins. */",
        "#ifndef E63_UI_APK_PINS_H", "#define E63_UI_APK_PINS_H",
        "#include <stdint.h>", "#include <stddef.h>",
        "typedef struct E63UiApkPin {",
        "    const char *package_name, *guest_path, *relative_on_c;",
        "    size_t apk_bytes; uint8_t apk_sha256[32];",
        "    const char *index_guest_path, *index_relative_on_c;",
        "    size_t index_bytes; uint8_t index_sha256[32];",
        "    const char *component; unsigned is_service;",
        "    size_t dex_bytes; uint8_t dex_sha256[32];",
        "    const char *manifest_guest_path, *manifest_relative_on_c;",
        "    size_t manifest_bytes; uint8_t manifest_sha256[32];",
        "    const char *intent_action, *intent_category;",
        "} E63UiApkPin;", 
        f"#define E63_UI_APK_PIN_COUNT {len(manifests)}u",
        "static const E63UiApkPin e63_ui_apk_pins[] = {",
    ]
    for name in UI_APPS:
        record = manifests[name]
        lines.append("    { " + ", ".join((
            f'"{record["package_name"]}"',
            f'"{record["guest_path"]}"',
            f'"{record["relative_on_c"].replace(chr(92), chr(92)*2)}"',
            f'{record["apk_bytes"]}u', _bytes(record["apk_sha256"]),
            f'"{record["index_guest_path"]}"',
            f'"{record["index_relative_on_c"].replace(chr(92), chr(92)*2)}"',
            f'{record["index_bytes"]}u', _bytes(record["index_sha256"]),
            f'"{record["required_executable"][0]}"',
            f'{int(record["component_type"] == "service")}u',
            f'{record["dex_bytes"]}u', _bytes(record["dex_sha256"]),
            f'"{record["manifest_guest_path"]}"',
            f'"{record["manifest_relative_on_c"].replace(chr(92), chr(92)*2)}"',
            f'{record["manifest_bytes"]}u', _bytes(record["manifest_sha256"]),
            _literal(record["intent_action"]),
            _literal(record["intent_category"]),
        )) + " },")
    lines += ["};", "#endif"]
    temp = HEADER.with_suffix(".new")
    temp.write_text("\n".join(lines) + "\n")
    temp.replace(HEADER)


def build() -> dict:
    commits = validate()
    OUT.mkdir(parents=True, exist_ok=True)
    build_aosp_signapk()
    rs_res = render_carousel()
    static = build_static(rs_res)
    result = {}
    for app in UI_APPS:
        result[app] = make_apk(app, static, resources(app, rs_res=rs_res
                                                     if app == "SystemUI" else None))
    STAGE.mkdir(parents=True, exist_ok=True)
    INDEX_STAGE.mkdir(parents=True, exist_ok=True)
    manifests: dict[str, dict] = {}
    for name, record in result.items():
        filename = GUEST_APKS[name]
        dest = STAGE / filename
        shutil.copyfile(record["apk"], dest)
        if sha256(dest) != record["apk_sha256"]:
            raise ValueError(f"staging changed {name}")
        index = ui_class_index(name, record["dex"])
        cached_manifest = stage_compiled_manifest(name, dest)
        manifests[name] = {
            **{k: v for k, v in record.items() if k not in ("apk", "dex")},
            **index, **cached_manifest, "package_name": PACKAGES[name],
            "guest_path": "/system/app/" + filename,
            "relative_on_c": "system\\app\\" + filename,
            "index_guest_path": "/data/e63-uiindex/" + name + ".idx",
            "index_relative_on_c": "data\\e63-uiindex\\" + name + ".idx",
            "component_type": COMPONENT_TYPE[name],
        }
    # Remove obsolete earlier candidate names; only transient build/ files.
    for name in UI_APPS:
        obsolete = STAGE / (name + ".apk")
        if obsolete.name != GUEST_APKS[name]:
            obsolete.unlink(missing_ok=True)
    report = {"tag": TAG, "ui_repositories": commits,
              "framework_sha256": sha256(FMW / "framework.jar"),
              "framework_resources_sha256": sha256(FMW / "framework-res.apk"),
              "host_tools_sha256": {name: sha256(HOST / name)
                                    for name in TOOL_FILES},
              "systemui_carousel_rs_target_api": 16,
              "systemui_carousel_rs_downgrade_from_platform_api": 17,
              "guava_source_only_compatibility_edit":
                  "removed 22 source-only @Override annotations on abstract Object methods, checked allowlist; no bytecode implementation changed",
              "signed": True,
              "signature_scheme": "Android v1 SHA1withRSA, AOSP public development keys",
              "production_trust": False, "system_apks_installed": False,
              "activity_running_on_nokia": False, "android_runtime_ready": False,
              "out_of_tree_build": True, "ui_apks": manifests}
    write_stage_metadata(report)
    print("Four genuine-source APKs signed with PUBLIC AOSP development keys, "
          "on-disk indexes, compiled AXML caches and C pins staged "
          "(no Android Activity execution).", flush=True)
    return report


def write_stage_metadata(report: dict) -> None:
    pin_header(report["ui_apks"])
    fragment = STAGE / "ui-app.pkg-fragment"
    fragment.write_text("; UNRELEASED CANDIDATES: not a full Android system.\n" +
        "\n".join(
            f'"../../build/staged-android42-system/ui-app/{GUEST_APKS[name]}" - '
            f'"C:\\private\\E0B63E04\\system\\app\\{GUEST_APKS[name]}"\n'
            f'"../../build/staged-android42-system/ui-index/{name}.idx" - '
            f'"C:\\private\\E0B63E04\\data\\e63-uiindex\\{name}.idx"\n'
            f'"../../build/staged-android42-system/ui-manifest/{name}.axml" - '
            f'"C:\\private\\E0B63E04\\data\\e63-uimanifest\\{name}.axml"'
            for name in UI_APPS) + "\n")
    (OUT / "ui-build-provenance.json").write_text(
        json.dumps(report, indent=2) + "\n")
    (STAGE / "candidate-ui.json").write_text(
        json.dumps(report, indent=2) + "\n")


def restage_existing_manifests() -> dict:
    """Upgrade signed/staged APKS in place, WITHOUT rebuilding/re-signing them.

    This path adds only the small, byte-identical AXML caches to the separate
    experimental candidate. It refuses changed archives, indexes or certs.
    """
    provenance = STAGE / "candidate-ui.json"
    report = json.loads(provenance.read_text())
    if (report["tag"] != TAG or not report["signed"] or
            report["production_trust"] or report["android_runtime_ready"] or
            set(report["ui_apks"]) != set(UI_APPS)):
        raise ValueError("not existing authentic AOSP candidate")
    for name in UI_APPS:
        item = report["ui_apks"][name]
        apk = STAGE / GUEST_APKS[name]
        index = INDEX_STAGE / (name + ".idx")
        key = "shared" if name == "Launcher2" else "platform"
        if (item["package_name"] != PACKAGES[name] or
                item["required_executable"] != list(REQUIRED_CLASSES[name]) or
                item["component_type"] != COMPONENT_TYPE[name] or
                item["aosp_development_certificate"] != key or
                apk.stat().st_size != item["apk_bytes"] or
                sha256(apk) != item["apk_sha256"] or
                index.stat().st_size != item["index_bytes"] or
                sha256(index) != item["index_sha256"] or
                dev_certificate(key, apk) != item["certificate_sha256"]):
            raise ValueError(f"signed UI staging/provenance mismatch: {name}")
        item.update(stage_compiled_manifest(name, apk))
    write_stage_metadata(report)
    print("AXML cache added from existing unchanged, signed AOSP APKs; "
          "not an Android Activity or UI on Nokia.")
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--manifest-caches-only", action="store_true",
                     help="add caches to authenticated staged APKs; do not rebuild")
    args = cli.parse_args()
    restage_existing_manifests() if args.manifest_caches_only else build()
