#!/usr/bin/env python3
"""Cross-compile/sign a launchable *partial* Symbian preview, NOT Android.

Native Nokia UI, authentic AOSP boot JAR and APK payloads, a single ABI-correct
JNI 1.6 static-native invocation, virtual /dev/binder-backed Symbian IPC and
an EMPTY service manager transport. Missing Android Activity/ServiceManager
Java execution, Binder FD/death/async and Android services remain missing.
Never interpret a generated SISX as evidence of a Nokia hardware run.
"""
from __future__ import annotations
import hashlib
import shutil
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.build_aosp42_diagnostic_sis import BASE,SDK,run
from tools.make_aosp42_jni_binder_preview_pkg import generate
from tools.verify_symbian_sis import verify
OUT=ROOT/'build/aosp42-jni-binder-preview'


def build() -> Path:
    pkg=generate()
    for path in (SDK/'epoc32/include/e32base.h',
                 BASE/'csl-gcc/bin/arm-none-symbianelf-gcc',
                 BASE/'csl-gcc/bin/signsis'):
        if not path.is_file():raise FileNotFoundError(path)
    OUT.mkdir(parents=True,exist_ok=True)
    run([str(BASE/'gnupoc/bin/bldmake'),'bldfiles'],OUT/'bldmake.log')
    exe=SDK/'epoc32/release/gcce/urel/e63android.exe'
    exe.unlink(missing_ok=True)
    run([str(BASE/'gnupoc/bin/abld'),'build','gcce','urel'],OUT/'abld.log')
    if not exe.is_file() or exe.stat().st_size<1000:
        raise ValueError('GCCE did not create a new e63android.exe')
    shutil.copyfile(exe,OUT/'e63android.exe')
    private=OUT/'private';private.mkdir(mode=0o700,exist_ok=True)
    key=private/'preview.key.pem';cert=private/'preview.cert.pem'
    if not key.is_file() or not cert.is_file():
        run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
             '-sha1','-days','730','-subj',
             '/CN=E63 JNI Binder IPC Preview/O=Not Android',
             '-keyout',str(key),'-out',str(cert)],
            OUT/'local-signing.log',cwd=ROOT)
        key.chmod(0o600)
    unsigned=OUT/'e63android-aosp42-jni-binder-preview-unsigned.sis'
    signed=OUT/'e63android-aosp42-jni-binder-preview.sisx'
    run([str(BASE/'gnupoc/bin/makesis'),pkg.name,str(unsigned)],OUT/'makesis.log')
    run([str(BASE/'gnupoc/bin/signsis'),str(unsigned),str(signed),
         str(cert),str(key)],OUT/'signsis.log')
    run([str(BASE/'gnupoc/bin/signsis'),'-o',str(signed)],OUT/'signsis-info.log')
    verify('e63android-jni-binder-preview',signed,SDK)
    print('LAUNCHABLE SYMBIAN PREVIEW (not complete Android):',signed)
    print(signed.stat().st_size,'bytes; SHA-256',
          hashlib.sha256(signed.read_bytes()).hexdigest())
    print('Same SID as historical 0.2: back up phone before ANY installation.')
    return signed

if __name__=='__main__':build()
