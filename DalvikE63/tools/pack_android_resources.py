"""Build a real API-17 Android resource table and binary manifest with aapt.

Only assets explicitly named by the Java Program are copied into each APK;
no copies of the entire old MIDlet resource directory. Tested via an
independent `aapt dump badging` after signing, not just our XML reader.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_STORED, ZipFile


def package_android(app, dex: bytes, sources: dict[str, Path], index: dict,
                    root: Path, build: Path, android_jar: Path) -> Path:
    folder = build / app.slug / "package"
    shutil.rmtree(folder, ignore_errors=True)
    resources = folder / "res"
    (resources / "values").mkdir(parents=True)
    (resources / "drawable").mkdir(parents=True)
    own_assets = folder / "assets"
    own_assets.mkdir()
    icon_name = {
        "files": "files.png", "settings": "settings.png", "store": "store.png",
        "systemui": "warning.png", "packageinstaller": "files.png"}
    icon = (root / "j2me/res/icon.png" if app.slug == "launcher" else
            root / "assets" / icon_name[app.slug])
    shutil.copyfile(icon, resources / "drawable/icon.png")
    (resources / "values/strings.xml").write_text(
        '<resources><string name="app_name">' + escape(app.label) +
        '</string></resources>\n', encoding="utf-8")
    permissions = "\n".join('  <uses-permission android:name="' + name + '"/>'
                            for name in app.permissions)
    (folder / "AndroidManifest.xml").write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
  package="''' + app.package + '''" android:versionCode="1" android:versionName="1.0">
  <uses-sdk android:minSdkVersion="17" android:targetSdkVersion="17"/>
''' + permissions + '''
  <application android:label="@string/app_name" android:icon="@drawable/icon"
    android:theme="@android:style/Theme.Holo.NoActionBar" android:allowBackup="false">
    <activity android:name=".Main" android:exported="true">
      <intent-filter>
        <action android:name="android.intent.action.MAIN"/>
        <category android:name="android.intent.category.LAUNCHER"/>
      </intent-filter>
    </activity>
  </application>
</manifest>
''', encoding="utf-8")
    (own_assets / "e63-assets.json").write_text(
        json.dumps(index, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8")
    for name, source in sources.items():
        dst = own_assets / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dst)
    unsigned = build / app.slug / "unsigned.apk"
    command = ["aapt", "package", "-f", "-M", str(folder / "AndroidManifest.xml"),
               "-S", str(resources), "-A", str(own_assets),
               "-I", str(android_jar), "-0", "wav", "-0", "apk",
               "-F", str(unsigned)]
    result = subprocess.run(command, capture_output=True, text=True, cwd=root)
    if result.returncode:
        raise RuntimeError("aapt packaging failed: " + result.stdout + result.stderr)
    with ZipFile(unsigned, "a", allowZip64=False) as zipf:
        zipf.writestr("classes.dex", dex, compress_type=ZIP_STORED)
    return unsigned
