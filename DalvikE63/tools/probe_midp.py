#!/usr/bin/env python3
"""Bounded PC-only smoke: boot original MIDP 2.0 JAR in MicroEmulator.

EKA2L1 JAR support is S60v1/MIDP1 only, NOT our S60v3/MIDP2 JAR. This
alternative tests class loading/startup under a separate MIDP emulator; it
cannot prove Symbian socket permissions or rendering on a Nokia E63.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT.parent / "NokiaE63_MIDP/toolchain/microemulator.jar"
CLASSES = ("android.j2me.edition.E63Midlet", "android.j2me.edition.E63Canvas",
           "android.j2me.edition.StoreState", "android.j2me.edition.E63Midlet$1")


def probe(microemu: Path = DEFAULT, seconds: int = 4) -> dict:
    jar = Path(microemu)
    if not jar.is_file():
        raise FileNotFoundError(f"MicroEmulator JAR missing: {jar}; set --microemu")
    if not 2 <= seconds <= 12: raise ValueError("test timeout must be 2–12 seconds")
    with zipfile.ZipFile(jar) as bundle:
        manifest = bundle.read("META-INF/MANIFEST.MF").decode("latin-1")
    version = next((line.split(":", 1)[1].strip() for line in manifest.splitlines()
                    if line.startswith("Implementation-Version:")), "unknown")
    (ROOT / "build").mkdir(exist_ok=True)
    java = shutil.which("java")
    if not java: raise FileNotFoundError("JDK java not available")
    with tempfile.TemporaryDirectory(dir=ROOT / "build") as home:
        cmd = [java,"-verbose:class","-Djava.awt.headless=true",
               "-Duser.home=" + home,"-cp",str(jar),
               "org.microemu.app.Headless",
               str(ROOT / "j2me/Android_J2ME_E63_Bridge.jad")]
        try:
            run = subprocess.run(cmd,cwd=ROOT,capture_output=True,timeout=seconds)
            output = run.stdout + run.stderr
            timed_out = False
            code = run.returncode
        except subprocess.TimeoutExpired as ex:
            output = (ex.stdout or b"") + (ex.stderr or b"")
            timed_out = True
            code = None
    text = output.decode("utf-8","replace")
    (ROOT / "build/microemu-probe.log").write_text(text,encoding="utf-8")
    loaded = {name: (name + " source: __JVM_DefineClass__") in text
              for name in CLASSES}
    opened = "openJar url [" in text
    ok = all(loaded.values()) and opened and (timed_out or code == 0)
    report = {"result": "MIDP JAR startup observed, no display verification" if ok else "failed",
              "emulator": "MicroEmulator " + version + " headless (not S60/EKA2L1)",
              "jar": "j2me/Android_J2ME_E63_Bridge.jar",
              "classes_loaded": loaded, "jar_opened": opened,
              "terminated_by_test_timeout": timed_out, "exit_code": code,
              "log": "build/microemu-probe.log"}
    (ROOT / "build/microemu-probe.json").write_text(
        json.dumps(report,indent=2),encoding="utf-8")
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--microemu",type=Path,default=DEFAULT)
    parser.add_argument("--seconds",type=int,default=4)
    args=parser.parse_args()
    try:
        result=probe(args.microemu,args.seconds)
    except (OSError,ValueError,zipfile.BadZipFile,KeyError) as ex:
        parser.exit(2,str(ex)+"\n")
    print(json.dumps(result,indent=2))
    if result["result"] == "failed":parser.exit(1)
