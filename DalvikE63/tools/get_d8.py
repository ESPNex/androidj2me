#!/usr/bin/env python3
"""Optional download of a pinned *binary build tool*, never AOSP sources.

Run only with explicit user consent. The binary is stored under excluded
build/tools/, not redistributed inside the project archive.
"""
import hashlib
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / 'build/tools/r8-8.0.40.jar'
SHA256 = 'ab1379835c7d3e5f21f80347c3c81e2f762e0b9b02748ae5232c3afa14adf702'
URL = 'https://dl.google.com/dl/android/maven2/com/android/tools/r8/8.0.40/r8-8.0.40.jar'


def check(path: pathlib.Path):
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == SHA256


if __name__ == '__main__':
    if check(DEST):
        print('Already verified:', DEST)
    else:
        DEST.parent.mkdir(parents=True, exist_ok=True)
        temp = DEST.with_suffix('.download')
        try:
            with urllib.request.urlopen(URL, timeout=60) as response, temp.open('wb') as file:
                total = 0
                while True:
                    chunk = response.read(65536)
                    if not chunk: break
                    total += len(chunk)
                    if total > 25 * 1024 * 1024: raise ValueError('tool larger than expected')
                    file.write(chunk)
            if not check(temp): raise ValueError('downloaded binary hash mismatch')
            temp.replace(DEST)
            print('Downloaded verified D8 tool (R8 8.0.40):', DEST)
        finally:
            temp.unlink(missing_ok=True)
