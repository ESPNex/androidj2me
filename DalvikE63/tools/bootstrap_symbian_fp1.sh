#!/usr/bin/env bash
# Rebuild locally obtained, nonredistributable S60 3rd FP1 toolchain on Debian 13.
# Read the SDK's Nokia_EULA.txt and only set NOKIA_SDK_LICENSE_ACCEPTED=1 if
# YOU independently agree to local installation/use and GnuPoc's SDK patches.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Keep the >1 GiB licensed SDK outside persistent workspace snapshots.
BASE="${SYMBIAN_TOOLCHAINS:-$ROOT/build/toolchains}"
if [[ "${NOKIA_SDK_LICENSE_ACCEPTED:-}" != "1" ]]; then
  echo 'Review Nokia_EULA.txt inside the Nokia SDK ZIP first.' >&2
  echo 'Then run with NOKIA_SDK_LICENSE_ACCEPTED=1 for your own local use.' >&2
  exit 2
fi
for tool in curl tar unzip python3 gcc g++ perl make patch sha256sum openssl; do
  command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 3; }
done
if ! ldconfig -p 2>/dev/null | grep -q 'libc.so.6.*lib32'; then
  echo 'On Debian 13, install: sudo apt-get install libc6-i386 lib32z1 lib32stdc++6 bison flex' >&2
fi
mkdir -p "$BASE/gnupoc-downloads" "$BASE/s60-fp1" "$BASE/gnupoc" "$BASE/csl-gcc"
archive="$BASE/s60-fp1/S60-SDK-200634-3.1-Cpp-f.1090b.zip"
gnu="$BASE/gnupoc-downloads/gnupoc-package-1.22.tar.gz"
csl="$BASE/gnupoc-downloads/gnu-csl-arm-2005Q1C-arm-none-symbianelf-i686-pc-linux-gnu.tar.bz2"
get_checked() {
  local url="$1" file="$2" hash="$3"
  if [[ ! -f "$file" ]]; then
    curl --fail --location --retry 4 --retry-delay 2 -o "$file.part" "$url"
    mv "$file.part" "$file"
  fi
  printf '%s  %s\n' "$hash" "$file" | sha256sum --check -
}
get_checked \
 'https://archive.org/download/nokia_sdks_n_dev_tools/S60-SDK-200634-3.1-Cpp-f.1090b.zip' \
 "$archive" 'f445cf1f7ddaa5ec5d5a8a806271db8880c9a430150b1cfcdc7de9d9bd758858'
get_checked \
 'https://www.martin.st/symbian/gnupoc-package-1.22.tar.gz' \
 "$gnu" '32c9e88eeeff53a5baf02f208e03ab9c42dc28e68991d761059807a28f8058ec'
get_checked \
 'https://www.martin.st/symbian/gnu-csl-arm-2005Q1C-arm-none-symbianelf-i686-pc-linux-gnu.tar.bz2' \
 "$csl" 'cd80c3068b69d2f7ebd9dc917cdd6353158d465623e8ec4ac244915143ce5ce0'
if [[ ! -d "$BASE/gnupoc/gnupoc-package-1.22" ]]; then
  tar -xzf "$gnu" -C "$BASE/gnupoc"
fi
if [[ ! -x "$BASE/csl-gcc/bin/arm-none-symbianelf-gcc" ]]; then
  tar -xjf "$csl" -C "$BASE/csl-gcc"
fi
"$BASE/csl-gcc/bin/arm-none-symbianelf-gcc" --version | head -1
src="$BASE/gnupoc/gnupoc-package-1.22"
python3 "$ROOT/tools/patch_gnupoc_122.py" "$src"
if [[ ! -x "$BASE/csl-gcc/bin/elf2e32" || ! -x "$BASE/csl-gcc/bin/signsis" ]]; then
  (cd "$src/tools" && ./install_eka2_tools "$BASE/csl-gcc")
fi
sdk="$BASE/s60-fp1/sdk"
if [[ ! -f "$sdk/epoc32/include/e32base.h" ]]; then
  (cd "$src/sdks" && ./install_gnupoc_s60_31 "$archive" "$sdk")
fi
python3 "$ROOT/tools/patch_sdk_perl.py" "$sdk"
if [[ ! -x "$BASE/gnupoc/bin/bldmake" ]]; then
  (cd "$src/sdks" && ./install_wrapper "$BASE/gnupoc/bin")
fi
python3 - "$BASE" <<'PY'
from pathlib import Path
import sys
base=Path(sys.argv[1]); p=base/'gnupoc/bin/gnupoc-common.sh'
s=p.read_text(); needle='EKA2TOOLS=~/csl-gcc/bin'; correct=f'EKA2TOOLS={base}/csl-gcc/bin'
if needle in s: p.write_text(s.replace(needle,correct))
elif correct not in s: raise SystemExit('Unexpected GnuPoc wrapper; set EKA2TOOLS by hand')
PY
printf '\nReady. In each shell, set:\n export EPOCROOT="%s/"\n export PATH="%s/gnupoc/bin:$PATH"\n' "$sdk" "$BASE"
printf 'Do not redistribute the SDK or a patched SDK. Toolchain >1 GiB may not survive workspace snapshots.\n'
