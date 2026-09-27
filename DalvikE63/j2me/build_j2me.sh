#!/usr/bin/env bash
# Independent MIDP 2.0 / CLDC 1.1 build of the *actual* J2ME sources.
# Requires an existing Java ME toolchain; does not download sources or SDKs.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
ROOT="$(cd .. && pwd)"
TOOLCHAIN="${MIDP_TOOLCHAIN:-$ROOT/../NokiaE63_MIDP/toolchain}"
JDK="${JAVA_HOME:-/usr/lib/jvm/jdk-11}"
JAVA="$JDK/bin/java"
JAR="$JDK/bin/jar"
[ -x "$JAVA" ] && [ -x "$JAR" ] || { echo 'JDK with java/jar required' >&2; exit 1; }
for lib in cldc.jar midp.jar ecj.jar proguard.jar; do
  [ -s "$TOOLCHAIN/$lib" ] || { echo "Missing Java ME SDK library: $TOOLCHAIN/$lib" >&2; exit 1; }
done
OUT="$ROOT/build/j2me"
rm -rf "$OUT/classes"
mkdir -p "$OUT/classes"
"$JAVA" -cp "$TOOLCHAIN/ecj.jar" org.eclipse.jdt.internal.compiler.batch.Main \
  -source 1.3 -target cldc1.1 -encoding UTF-8 -g:none \
  -bootclasspath "$TOOLCHAIN/cldc.jar:$TOOLCHAIN/midp.jar" \
  -d "$OUT/classes" src/android/j2me/edition/*.java
"$JAR" cfm "$OUT/raw.jar" MANIFEST.MF -C "$OUT/classes" . -C res .
"$JAVA" -jar "$TOOLCHAIN/proguard.jar" \
  -injars "$OUT/raw.jar" -outjars "$OUT/preverified.jar" \
  -libraryjars "$TOOLCHAIN/cldc.jar" -libraryjars "$TOOLCHAIN/midp.jar" \
  -microedition -dontshrink -dontoptimize -dontobfuscate \
  -keepattributes Exceptions,SourceFile,LineNumberTable \
  -keep 'class * { *; }'
cp "$OUT/preverified.jar" "$HERE/Android_J2ME_E63_Bridge.jar"
size=$(wc -c < "$HERE/Android_J2ME_E63_Bridge.jar" | tr -d '[:space:]')
{
  printf 'MIDlet-Name: Android J2ME Edition\r\n'
  printf 'MIDlet-Version: 1.2.1\r\n'
  printf 'MIDlet-Vendor: Utente\r\n'
  printf 'MIDlet-1: Android J2ME Edition, /icon.png, android.j2me.edition.E63Midlet\r\n'
  printf 'MIDlet-Permissions-Opt: javax.microedition.io.Connector.socket\r\n'
  printf 'MicroEdition-Configuration: CLDC-1.1\r\n'
  printf 'MicroEdition-Profile: MIDP-2.0\r\n'
  printf 'MIDlet-Jar-URL: Android_J2ME_E63_Bridge.jar\r\n'
  printf 'MIDlet-Jar-Size: %s\r\n' "$size"
} > "$HERE/Android_J2ME_E63_Bridge.jad"
python3 - "$HERE" <<'PY'
import hashlib, json, pathlib, sys
base = pathlib.Path(sys.argv[1])
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
files = sorted([*base.glob('src/**/*.java'), *base.glob('res/*'), base / 'MANIFEST.MF'])
record = {'schema': 1, 'midp': '2.0', 'cldc': '1.1',
          'jar_sha256': sha(base / 'Android_J2ME_E63_Bridge.jar'),
          'files': {str(p.relative_to(base)): sha(p) for p in files}}
(base / 'source_provenance.json').write_text(json.dumps(record, indent=2) + '\n')
PY
printf 'MIDP 2.0/CLDC 1.1 bridge JAR: %s bytes\n' "$size"
