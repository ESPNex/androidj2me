"""DEX MUTF-8 conformance across Python and the portable C99 Nokia intake.

Mutate an UNUSED string_id in a real D8 DEX and refresh DEX size, signature
and checksum. These are format tests; the changed data is NOT a signed APK.
"""
from __future__ import annotations

import ctypes
import hashlib
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from dalvik.dex_j2me import J2MEDex, J2MEDexError
from tests.test_native_preflight import DexView

ROOT = Path(__file__).resolve().parents[1]
RAW = (ROOT / "j2me/classes.dex").read_bytes()
IDX = J2MEDex(RAW).strings.index("Play Store")


def uleb(num: int) -> bytes:
    out = bytearray()
    while True:
        b = num & 127
        num >>= 7
        out.append(b | (128 if num else 0))
        if not num:
            return bytes(out)


def mutf(text: str) -> tuple[int, bytes]:
    units = struct.unpack("<%dH" % (len(text.encode("utf-16-le", "surrogatepass")) // 2),
                          text.encode("utf-16-le", "surrogatepass"))
    body = bytearray()
    for u in units:
        if u == 0:
            body.extend(b"\xc0\x80")
        elif u <= 127:
            body.append(u)
        elif u <= 0x7ff:
            body.extend((0xc0 | (u >> 6), 0x80 | (u & 63)))
        else:
            body.extend((0xe0 | (u >> 12), 0x80 | ((u >> 6) & 63), 0x80 | (u & 63)))
    return len(units), bytes(body)


def dex_with_string(declared: int, body: bytes, *, terminator: bool = True) -> bytes:
    image = bytearray(RAW)
    at = len(image)
    image.extend(uleb(declared))
    image.extend(body)
    if terminator:
        image.append(0)
    table = struct.unpack_from("<I", image, 0x3c)[0]
    struct.pack_into("<I", image, table + 4 * IDX, at)
    struct.pack_into("<I", image, 0x20, len(image))
    data_off = struct.unpack_from("<I", image, 0x6c)[0]
    struct.pack_into("<I", image, 0x68, len(image) - data_off)
    image[12:32] = hashlib.sha1(image[32:]).digest()
    struct.pack_into("<I", image, 8, zlib.adler32(image[12:]) & 0xffffffff)
    return bytes(image)


class DexUnicodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("gcc")
        if not cc: raise unittest.SkipTest("C99 compiler required")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        so = Path(cls.tmp.name) / "preflight.so"
        subprocess.run([cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-pedantic", "-fPIC", "-shared",
                        str(ROOT / "symbian/runtime/dex_preflight.c"),
                        "-o", str(so)], check=True)
        c = ctypes.CDLL(str(so))
        cls.open = c.e63_dex_open
        cls.open.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(DexView))
        cls.open.restype = ctypes.c_int
        cls.utf8 = c.e63_dex_string_utf8
        cls.utf8.argtypes = (ctypes.POINTER(DexView), ctypes.c_uint32,
                             ctypes.c_void_p, ctypes.c_size_t,
                             ctypes.POINTER(ctypes.c_size_t))
        cls.utf8.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def c_open(self, data):
        raw = ctypes.create_string_buffer(data)
        view = DexView()
        return self.open(raw, len(data), ctypes.byref(view)), view, raw

    def test_unicode_bmp_supplementary_nul_and_lone_utf16_surrogate(self):
        for value in ("città · café ☕ 😀", "A\0B", "😀😀", "\ud83d"):
            with self.subTest(value=repr(value)):
                units, encoded = mutf(value)
                data = dex_with_string(units, encoded)
                self.assertEqual(J2MEDex(data).strings[IDX], value)
                status, view, raw = self.c_open(data)
                self.assertEqual(status, 0)
                output = ctypes.create_string_buffer(512)
                used = ctypes.c_size_t()
                result = self.utf8(ctypes.byref(view), IDX, output, 512,
                                   ctypes.byref(used))
                if value == "\ud83d":
                    self.assertEqual(result, 0)  # valid UTF-16, not scalar UTF-8
                else:
                    self.assertEqual(result, 1)
                    self.assertEqual(output.raw[:used.value], value.encode("utf-8"))
                    self.assertEqual(output.raw[used.value], 0)
                self.assertIsNotNone(raw)

    def test_malformed_sequences_are_rejected_by_both_parsers(self):
        invalid = (
            (1, b"\xf0\x9f\x98\x80", True),  # normal UTF-8 forbidden in DEX
            (1, b"\xc0\x81", True),          # only C0 80 encodes NUL
            (1, b"\xc1\x81", True),
            (1, b"\xe0\x80\x80", True),     # overlong 3-byte form
            (1, b"\xe2\x28\xa1", True),
            (1, b"\x80", True),
            (2, b"A", True),                 # early raw 00 / wrong UTF-16 length
            (1, b"AB", True),                # excess payload before terminator
            (1, b"A", False),               # missing terminator
        )
        for units, body, terminator in invalid:
            with self.subTest(data=body, units=units, terminator=terminator):
                data = dex_with_string(units, body, terminator=terminator)
                with self.assertRaises(J2MEDexError): J2MEDex(data)
                self.assertEqual(self.c_open(data)[0], 5)

    def test_scalar_conversion_cannot_overflow_or_truncate_multibyte(self):
        units, body = mutf("😀")
        status, view, raw = self.c_open(dex_with_string(units, body))
        self.assertEqual(status, 0)
        for cap in range(1, 5):
            output = ctypes.create_string_buffer(cap)
            used = ctypes.c_size_t()
            self.assertEqual(self.utf8(ctypes.byref(view), IDX, output, cap,
                                       ctypes.byref(used)), 0)
        output = ctypes.create_string_buffer(5)
        used = ctypes.c_size_t()
        self.assertEqual(self.utf8(ctypes.byref(view), IDX, output, 5,
                                   ctypes.byref(used)), 1)
        self.assertEqual(output.raw, b"\xf0\x9f\x98\x80\x00")
        self.assertIsNotNone(raw)


if __name__ == "__main__": unittest.main()
