#!/usr/bin/env python3
"""Add FOUR real AOSP 4.2 UI APKs + per-app class indexes to the old diagnostic.

Separate unreleased SIS, never overwrite 0.2 or the 32-payload boot diagnostic.
Both old six APKs (including simulated SystemUI.apk) and authentic AOSP UI
candidates have distinct names under /system/app on persistent C:. The native
key '4' authenticates/locates Launcher2 code but does NOT execute an Activity.
Requires on-device free space and an owner's backup/explicit install decision.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.make_aosp42_diagnostic_pkg import generate as base_diagnostic
from tools.build_aosp42_ui_apks import (
    COMPONENT_TYPE, GUEST_APKS, INDEX_STAGE, MANIFEST_STAGE, PACKAGES,
    REQUIRED_CLASSES, REQUIRED_INTENTS, STAGE, UI_APPS, HEADER,
)
from tools.stage_android42_runtime import BOOT_HEADER, BOOT_RECORD, dex_class_entries, executable_classes

PKG = ROOT / "symbian/android_java_app/e63android-aosp42-ui-diagnostic.pkg"
ROW = re.compile(
    r'^\s*\{\s*"([^"\n]+)",\s*"([^"\n]+)",\s*"([^"\n]+)",\s*'
    r'(\d+)u,\s*\{([^}]+)\},\s*"([^"\n]+)",\s*"([^"\n]+)",\s*'
    r'(\d+)u,\s*\{([^}]+)\},\s*"([^"\n]+)",\s*(\d+)u,\s*'
    r'(\d+)u,\s*\{([^}]+)\},\s*"([^"\n]+)",\s*"([^"\n]+)",\s*'
    r'(\d+)u,\s*\{([^}]+)\},\s*(0|"[^"\n]+"),\s*'
    r'(0|"[^"\n]+")\s*\},?$', re.M,
)


def parse_sha256(raw: str) -> str:
    octets = re.findall(r"0x([0-9a-f]{2})u", raw)
    if len(octets) != 32:
        raise ValueError("invalid AOSP UI native SHA-256 pin")
    return "".join(octets)


def parse_header() -> dict[str, tuple]:
    result: dict[str, tuple] = {}
    text = HEADER.read_text()
    if "#define E63_UI_APK_PIN_COUNT 4u" not in text:
        raise ValueError("UI APK pin count missing")
    for m in ROW.finditer(text):
        package, guest, relative, size, apk_sha, index, index_relative, \
            index_size, index_sha, component, service, dex_size, dex_sha, \
            manifest, manifest_relative, manifest_size, manifest_sha, \
            intent_action, intent_category = m.groups()
        if package in result:
            raise ValueError("duplicate AOSP UI package pin")
        result[package] = (guest, relative, int(size), parse_sha256(apk_sha),
                           index, index_relative, int(index_size),
                           parse_sha256(index_sha), component, int(service),
                           int(dex_size), parse_sha256(dex_sha), manifest,
                           manifest_relative, int(manifest_size),
                           parse_sha256(manifest_sha),
                           None if intent_action == "0" else intent_action[1:-1],
                           None if intent_category == "0" else intent_category[1:-1])
    if len(result) != 4:
        raise ValueError("expected four native UI APK pin rows")
    return result


def validate() -> dict:
    report = json.loads((STAGE / "candidate-ui.json").read_text())
    base = json.loads((ROOT / "build/staged-android42-system/candidate-runtime.json").read_text())
    if (report["android_runtime_ready"] or not report["signed"] or
            report["production_trust"] or report["activity_running_on_nokia"] or
            report["system_apks_installed"] or
            report["framework_sha256"] != base["files"]["framework.jar"]["sha256"] or
            report["framework_resources_sha256"] !=
                base["files"]["framework-res.apk"]["sha256"] or
            report["tag"] != "android-4.2.2_r1.2" or
            set(report["ui_apks"]) != set(UI_APPS)):
        raise ValueError("UI candidate provenance / bootclasspath mismatch")
    native = parse_header()
    for name in UI_APPS:
        item = report["ui_apks"][name]
        if item["package_name"] != PACKAGES[name] or \
                item["guest_path"] != "/system/app/" + GUEST_APKS[name] or \
                item["required_executable"] != list(REQUIRED_CLASSES[name]) or \
                item["component_type"] != COMPONENT_TYPE[name] or \
                native[item["package_name"]] != (
                    item["guest_path"],
                    item["relative_on_c"].replace("\\", "\\\\"),
                    item["apk_bytes"], item["apk_sha256"],
                    item["index_guest_path"],
                    item["index_relative_on_c"].replace("\\", "\\\\"),
                    item["index_bytes"], item["index_sha256"],
                    item["required_executable"][0],
                    int(item["component_type"] == "service"),
                    item["dex_bytes"], item["dex_sha256"],
                    item["manifest_guest_path"],
                    item["manifest_relative_on_c"].replace("\\", "\\\\"),
                    item["manifest_bytes"], item["manifest_sha256"],
                    item["intent_action"], item["intent_category"]):
            raise ValueError(f"native UI pins/provenance disagree: {name}")
        if (item["manifest_guest_path"] != "/data/e63-uimanifest/" + name + ".axml" or
                (item["intent_action"], item["intent_category"]) !=
                REQUIRED_INTENTS[name]):
            raise ValueError(f"unexpected compiled UI component intent: {name}")
        apk = STAGE / GUEST_APKS[name]
        index = INDEX_STAGE / (name + ".idx")
        manifest = MANIFEST_STAGE / (name + ".axml")
        if (not apk.is_file() or not index.is_file() or not manifest.is_file() or
                apk.stat().st_size != item["apk_bytes"] or
                index.stat().st_size != item["index_bytes"] or
                manifest.stat().st_size != item["manifest_bytes"] or
                hashlib.sha256(apk.read_bytes()).hexdigest() != item["apk_sha256"] or
                hashlib.sha256(index.read_bytes()).hexdigest() != item["index_sha256"] or
                hashlib.sha256(manifest.read_bytes()).hexdigest() !=
                    item["manifest_sha256"]):
            raise ValueError(f"missing or tampered staged UI payload: {name}")
        with zipfile.ZipFile(apk) as signed:
            entries = signed.namelist()
            if (len(entries) != len(set(entries)) or signed.testzip() or
                    not {"AndroidManifest.xml", "resources.arsc", "classes.dex",
                         "META-INF/MANIFEST.MF", "META-INF/CERT.SF",
                         "META-INF/CERT.RSA"}.issubset(entries)):
                raise ValueError(f"bad AOSP signed archive: {name}")
            if signed.read("AndroidManifest.xml") != manifest.read_bytes():
                raise ValueError(f"AXML cache does not derive from signed APK: {name}")
            dex = signed.read("classes.dex")
            classes = dex_class_entries(dex)
            if (signed.getinfo("classes.dex").compress_type != 0 or
                    len(dex) != item["dex_bytes"] or
                    hashlib.sha256(dex).hexdigest() != item["dex_sha256"] or
                    len(classes) != item["dex_classes"] or
                    not set(REQUIRED_CLASSES[name]).issubset(
                        executable_classes(dex,classes))):
                raise ValueError(f"AOSP UI DEX class/code mismatch: {name}")
        raw_index = index.read_bytes()
        if (raw_index[:8] != b"E63BOOT2" or
                len(raw_index) != BOOT_HEADER.size+len(classes)*BOOT_RECORD.size):
            raise ValueError(f"UI index format mismatch: {name}")
    return report


def generate() -> Path:
    base = base_diagnostic()  # re-verifies all 32 old diagnostic inputs/pins
    validate()
    old = base.read_text()
    old_version = '# {"AOSP 4.2 DEX Diagnostic (incomplete)"}, (0xE0B63E04), 0, 3, 0'
    if old.count(old_version) != 1 or old.count("C:\\private\\E0B63E04\\system") < 11:
        raise ValueError("existing AOSP boot diagnostic package changed")
    new_version = '# {"AOSP 4.2 UI DEX Diagnostic (no Activities)"}, (0xE0B63E04), 0, 4, 0'
    prefix = ("; UNRELEASED LOCAL UI DEX DIAGNOSTIC, NOT AN ANDROID PHONE.\n"
              "; Four real AOSP-sourced UI APKs signed by PUBLIC development keys.\n"
              "; Launcher2 classes may be verified; no Activity/JNI/Binder/UI execution.\n"
              "; Contains the old 6 APKs unchanged; simulated SystemUI stays old.\n"
              "; Same Nokia app UID as 0.2: BACK UP device before any opt-in install.\n"
              "; Requires ample free space on Nokia C:; NO hardware run inferred.\n")
    contents = prefix + old.replace(old_version, new_version)
    for name in UI_APPS:
        apk = GUEST_APKS[name]
        contents += (f'"../../build/staged-android42-system/ui-app/{apk}" - '
                     f'"C:\\private\\E0B63E04\\system\\app\\{apk}"\n')
        contents += (f'"../../build/staged-android42-system/ui-index/{name}.idx" - '
                     f'"C:\\private\\E0B63E04\\data\\e63-uiindex\\{name}.idx"\n')
    PKG.write_text(contents)
    print(f"UI diagnostic only: {PKG} (40 payloads, four AOSP testkey APKs)")
    return PKG


if __name__ == "__main__":
    generate()
