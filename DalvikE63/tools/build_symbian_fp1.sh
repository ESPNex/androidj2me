#!/usr/bin/env bash
# Real GCCE ARM/Symbian build (NOT an E63 installation or phone runtime test).
# Assumes tools/bootstrap_symbian_fp1.sh was run after local Nokia EULA review.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${SYMBIAN_TOOLCHAINS:-$ROOT/build/toolchains}"
export EPOCROOT="$BASE/s60-fp1/sdk/"
export PATH="$BASE/gnupoc/bin:$PATH"
for item in "$EPOCROOT/epoc32/include/e32base.h" \
            "$BASE/csl-gcc/bin/arm-none-symbianelf-gcc" \
            "$BASE/csl-gcc/bin/signsis"; do
  [[ -e "$item" ]] || { echo "Missing toolchain: $item" >&2; exit 2; }
done
command -v bldmake >/dev/null && command -v abld >/dev/null
python3 "$ROOT/tools/make_symbian_assets.py"
# The bytecode packaged in the native UI must BE the signed APK's DEX.
unzip -p "$ROOT/apks/Launcher.apk" classes.dex | cmp - "$ROOT/j2me/classes.dex"
mkdir -p "$ROOT/build/symbian/private"
chmod 700 "$ROOT/build/symbian/private"
cd "$ROOT/symbian"
bldmake bldfiles > "$ROOT/build/symbian/bldmake.log" 2>&1
# GnuPoc abld sometimes RETURNS ZERO when make/compiler emitted errors.
for app in e63os e63bridge e63bridge_launch; do
  rm -f "$EPOCROOT/epoc32/release/gcce/urel/$app.exe"
done
abld build gcce urel > "$ROOT/build/symbian/abld.log" 2>&1 || {
  tail -100 "$ROOT/build/symbian/abld.log" >&2; exit 3;
}
if grep -qE 'error:|Error [0-9]|No rule to make target|undefined reference' \
    "$ROOT/build/symbian/abld.log"; then
  grep -nE 'error:|Error [0-9]|No rule to make target|undefined reference' \
    "$ROOT/build/symbian/abld.log" >&2
  exit 4
fi
for app in e63os e63bridge e63bridge_launch; do
  [[ -s "$EPOCROOT/epoc32/release/gcce/urel/$app.exe" ]] || {
    echo "No ARM E32 output: $app" >&2; exit 5;
  }
done
key="$ROOT/build/symbian/private/e63-local.key.pem"
cert="$ROOT/build/symbian/private/e63-local.cert.pem"
if [[ ! -s "$key" || ! -s "$cert" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -sha1 -days 730 \
    -subj '/CN=E63 Local Prototype/O=Individual Test' \
    -keyout "$key" -out "$cert" > "$ROOT/build/symbian/keygen.log" 2>&1
  chmod 600 "$key"
fi
for app in e63os e63bridge; do
  makesis "$app.pkg" "$ROOT/build/symbian/$app-unsigned.sis" \
    > "$ROOT/build/symbian/makesis-$app.log" 2>&1
  signsis "$ROOT/build/symbian/$app-unsigned.sis" \
    "$ROOT/build/symbian/$app.sisx" "$cert" "$key" \
    > "$ROOT/build/symbian/signsis-$app.log" 2>&1
  signsis -o "$ROOT/build/symbian/$app.sisx" \
    > "$ROOT/build/symbian/signsis-$app-info.log" 2>&1
  [[ -s "$ROOT/build/symbian/$app.sisx" ]] || exit 6
  python3 "$ROOT/tools/verify_symbian_sis.py" "$app" \
    "$ROOT/build/symbian/$app.sisx" --sdk "$EPOCROOT"
  file "$ROOT/build/symbian/$app.sisx"
  sha256sum "$ROOT/build/symbian/$app.sisx"
done
openssl x509 -in "$cert" -noout -fingerprint -sha256 -dates
printf '\nSISX outputs: %s/build/symbian/{e63os,e63bridge}.sisx\n' "$ROOT"
printf 'SELF-SIGNED TEST PACKAGES ONLY. Do not mistake GCCE build for verified execution on E63.\n'
