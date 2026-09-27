#!/usr/bin/env bash
# HISTORICAL 0.2 build path. Current source is an unfinished 4.2 strict mode:
# refuse to build/sign a misleading SISX until real framework VM integration.
# Does not modify/replace the preserved 0.1/0.2 or J2ME release SISX files.
# The final suite belongs at the END of the new work, not now.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if grep -q '^#define E63_FRAMEWORK_PIN_COUNT 0u$' \
    "$ROOT/symbian/android_java_app/framework_pins.h" || \
   grep -q 'aBackend,0,aEvent,aArgs,aCount' \
    "$ROOT/symbian/android_java_app/e63android_app.cpp"; then
  echo 'Framework 4.2 incomplete: refusing to build/sign a misleading SISX.' >&2
  echo 'Keep using the preserved release/e63android-0.2-activity-unicode-services-test.sisx.' >&2
  exit 2
fi
BASE="${SYMBIAN_TOOLCHAINS:-$ROOT/build/toolchains}"
export EPOCROOT="$BASE/s60-fp1/sdk/"
export PATH="$BASE/gnupoc/bin:$PATH"
for item in "$EPOCROOT/epoc32/include/e32base.h" \
            "$BASE/csl-gcc/bin/arm-none-symbianelf-gcc" \
            "$BASE/csl-gcc/bin/signsis"; do
  [[ -e "$item" ]] || { echo "Local S60 FP1 toolchain absent: $item" >&2; exit 2; }
done
command -v bldmake >/dev/null && command -v abld >/dev/null
# Confirm all six staged signed APKs correspond to the GENERATED pins and
# execute their actual Program DEX on the C99 PC bridge before packaging.
# Exclude SignedSymbianJavaReleaseTests here: an existing release SISX can
# legitimately contain the PREVIOUS signed APK bytes during a rebuild.
# Once the new SISX passes payload verification and is copied to release/,
# run the FULL suite to confirm release <-> staged APKs match again.
(cd "$ROOT" && python3 -m unittest \
  tests.test_android_java_apks.AndroidJavaAPKTests \
  tests.test_android_java_apks.NativeAndroidJavaTests -q)
mkdir -p "$ROOT/build/symbian_java/private"
chmod 700 "$ROOT/build/symbian_java/private"
cd "$ROOT/symbian/android_java_app"
bldmake bldfiles > "$ROOT/build/symbian_java/bldmake.log" 2>&1
rm -f "$EPOCROOT/epoc32/release/gcce/urel/e63android.exe"
abld build gcce urel > "$ROOT/build/symbian_java/abld.log" 2>&1 || {
  tail -100 "$ROOT/build/symbian_java/abld.log" >&2; exit 3;
}
if grep -qE 'error:|Error [0-9]|No rule to make target|undefined reference' \
    "$ROOT/build/symbian_java/abld.log"; then
  grep -nE 'error:|Error [0-9]|No rule to make target|undefined reference' \
    "$ROOT/build/symbian_java/abld.log" >&2
  exit 4
fi
[[ -s "$EPOCROOT/epoc32/release/gcce/urel/e63android.exe" ]] || {
    echo 'GCCE did not produce a Symbian E32 EXE' >&2; exit 5;
}
key="$ROOT/build/symbian_java/private/local.key.pem"
cert="$ROOT/build/symbian_java/private/local.cert.pem"
if [[ ! -s "$key" || ! -s "$cert" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -sha1 -days 730 \
    -subj '/CN=E63 Java APK Local Test/O=Individual Test' \
    -keyout "$key" -out "$cert" > "$ROOT/build/symbian_java/keygen.log" 2>&1
  chmod 600 "$key"
fi
makesis e63android.pkg "$ROOT/build/symbian_java/e63android-unsigned.sis" \
  > "$ROOT/build/symbian_java/makesis.log" 2>&1
signsis "$ROOT/build/symbian_java/e63android-unsigned.sis" \
  "$ROOT/build/symbian_java/e63android.sisx" "$cert" "$key" \
  > "$ROOT/build/symbian_java/signsis.log" 2>&1
signsis -o "$ROOT/build/symbian_java/e63android.sisx" \
  > "$ROOT/build/symbian_java/signsis-info.log" 2>&1
python3 "$ROOT/tools/verify_symbian_sis.py" e63android \
  "$ROOT/build/symbian_java/e63android.sisx" --sdk "$EPOCROOT"
echo 'Cross-build only: NO device verification and NO complete Android runtime.'
echo "SISX test output: $ROOT/build/symbian_java/e63android.sisx"
