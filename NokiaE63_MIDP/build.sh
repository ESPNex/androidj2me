#!/usr/bin/env bash
# Builds a real preverified MIDP 2.0 / CLDC 1.1 MIDlet, not a desktop JAR.
set -euo pipefail
cd "$(dirname "$0")"
JAR="${JAVA_HOME:-$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")}/bin/jar"
[ -x "$JAR" ] || { echo "JDK jar tool not found" >&2; exit 1; }
for lib in toolchain/cldc.jar toolchain/midp.jar toolchain/ecj.jar toolchain/proguard.jar; do
  [ -s "$lib" ] || { echo "Missing build dependency: $lib" >&2; exit 1; }
done
rm -rf build/classes
mkdir -p build/classes
java -cp toolchain/ecj.jar org.eclipse.jdt.internal.compiler.batch.Main \
  -source 1.3 -target cldc1.1 -encoding UTF-8 -g:none \
  -bootclasspath toolchain/cldc.jar:toolchain/midp.jar \
  -d build/classes src/android/j2me/edition/*.java
"$JAR" cfm build/raw.jar MANIFEST.MF -C build/classes . -C res .
java -jar toolchain/proguard.jar @proguard.pro
cp build/preverified.jar ../Android_J2ME_E63.jar
size=$(wc -c < ../Android_J2ME_E63.jar | tr -d '[:space:]')
{
  printf 'MIDlet-Name: Android J2ME Edition\r\n'
  printf 'MIDlet-Version: 1.0.3\r\n'
  printf 'MIDlet-Vendor: Utente\r\n'
  printf 'MIDlet-1: Android J2ME Edition, /icon.png, android.j2me.edition.E63Midlet\r\n'
  printf 'MicroEdition-Configuration: CLDC-1.1\r\n'
  printf 'MicroEdition-Profile: MIDP-2.0\r\n'
  printf 'MIDlet-Jar-URL: Android_J2ME_E63.jar\r\n'
  printf 'MIDlet-Jar-Size: %s\r\n' "$size"
} > ../Android_J2ME_E63.jad
printf 'Built %s bytes: %s\n' "$size" "$(realpath ../Android_J2ME_E63.jar)"
printf 'JAD: %s\n' "$(realpath ../Android_J2ME_E63.jad)"
