#!/usr/bin/env python3
"""Unreleased JNI 1.6 ()I + virtual Binder broker *preview* (no Android boot).

Derived from the independently SHA-verified 44-payload AOSP 4.2 diagnostic;
never overwrite the historical 0.2 or 0.5 SISX/PKG. This Symbian app starts
and reports genuine JNI/process and service absence, NOT an Android Activity.
"""
from __future__ import annotations
from pathlib import Path
from tools.make_aosp42_ui_axml_diagnostic_pkg import generate as base_generate
ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/'symbian/android_java_app/e63android-aosp42-jni-binder-preview.pkg'


def generate() -> Path:
    original=base_generate()
    text=original.read_text()
    before='# {"AOSP 4.2 UI AXML Diagnostic (no Activities)"}, (0xE0B63E04), 0, 5, 0'
    after='# {"AOSP 4.2 JNI Binder IPC Preview (no Activities)"}, (0xE0B63E04), 0, 6, 0'
    if text.count(before)!=1 or text.count('e63-uimanifest')!=4:
        raise ValueError('44-payload base package was modified')
    head=('; EXPERIMENTAL / NOT Android: real partial JNI static-native gate\n'
          '; and a bounded in-process broker reached via Symbian RSessionBase.\n'
          '; No Activity, system_server, ActivityManager or Android rendering.\n'
          '; Signed with a LOCAL test certificate: do not replace historical\n'
          '; 0.2 without a BACKUP; C: installation is large.\n')
    PKG.write_text(head+text.replace(before,after))
    return PKG

if __name__=='__main__':print(generate())
