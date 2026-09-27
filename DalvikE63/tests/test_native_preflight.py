"""Compile and exercise the portable DEX intake intended for a future E63 port.

No Symbian SDK is present: this proves C99 compatibility on the PC only.
"""
import ctypes
import hashlib
import random
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
DEX=ROOT / "j2me/classes.dex"
SRC=ROOT / "symbian/runtime"


class DexView(ctypes.Structure):
    _fields_=[("data",ctypes.c_void_p),("size",ctypes.c_size_t)] + [
        (x,ctypes.c_uint32) for x in (
            "strings_count","strings_off","types_count","types_off",
            "protos_count","protos_off","fields_count","fields_off",
            "methods_count","methods_off","classes_count","classes_off",
            "data_off","data_count")]


class NativePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gcc=shutil.which("gcc")
        if not gcc:raise unittest.SkipTest("native C99 preflight needs gcc")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.base=Path(cls.tmp.name)
        common=[gcc,"-std=c99","-O2","-Wall","-Wextra","-Werror","-pedantic"]
        cls.cli=cls.base / "e63_dex_check"
        cls.so=cls.base / "dex_preflight.so"
        subprocess.run(common+[str(SRC / "dex_preflight.c"),
                     str(SRC / "preflight_cli.c"),"-o",str(cls.cli)],check=True)
        subprocess.run(common+["-fPIC","-shared",str(SRC / "dex_preflight.c"),
                             "-o",str(cls.so)],check=True)
        core=ctypes.CDLL(str(cls.so))
        cls.open=core.e63_dex_open
        cls.open.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(DexView)]
        cls.open.restype=ctypes.c_int
        cls.has_code=core.e63_dex_has_code
        cls.has_code.argtypes=[ctypes.POINTER(DexView),ctypes.c_char_p,ctypes.c_char_p]
        cls.has_code.restype=ctypes.c_int
        cls.count=core.e63_dex_count_code
        cls.count.argtypes=[ctypes.POINTER(DexView)]
        cls.count.restype=ctypes.c_int

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    @classmethod
    def parsed(cls, raw: bytes):
        backing=ctypes.create_string_buffer(raw)
        view=DexView()
        code=cls.open(backing,len(raw),ctypes.byref(view))
        return code,view,backing  # backing must outlive the borrowed C view

    @staticmethod
    def checksummed(raw):
        raw=bytearray(raw)
        raw[12:32]=hashlib.sha1(raw[32:]).digest()
        struct.pack_into("<I",raw,8,zlib.adler32(raw[12:]) & 0xffffffff)
        return bytes(raw)

    def test_real_converted_j2me_methods_have_executable_dex_code(self):
        raw=DEX.read_bytes()
        code,view,buffer=self.parsed(raw)
        self.assertEqual(code,0)
        self.assertEqual((view.classes_count,view.methods_count,self.count(view)),(9,215,118))
        for owner,name in ((b"Landroid/j2me/edition/E63Midlet;",b"startApp"),
                           (b"Landroid/j2me/edition/E63Midlet;",b"tickLoop"),
                           (b"Landroid/j2me/edition/E63Canvas;",b"paint"),
                           (b"Landroid/j2me/edition/E63Canvas;",b"keyPressed"),
                           (b"Landroid/j2me/edition/BridgeClient;",b"ping")):
            self.assertEqual(self.has_code(view,owner,name),1)
        self.assertEqual(self.has_code(view,b"Landroid/j2me/edition/E63Canvas;",b"imaginary"),0)
        self.assertIsNotNone(buffer)
        run=subprocess.run([str(self.cli),str(DEX)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn("with_code=118 guest_ui=1",run.stdout)
        with ZipFile(ROOT / "apks/Launcher.apk") as z:
            self.assertEqual(raw,z.read("classes.dex"))

    def test_corrupt_checksum_table_offset_code_and_truncation_fail_closed(self):
        original=DEX.read_bytes()
        broken=bytearray(original);broken[-8]^=1
        self.assertEqual(self.parsed(bytes(broken))[0],3) # checksum
        bad_magic=bytearray(original);bad_magic[5]=ord('9')
        self.assertEqual(self.parsed(self.checksummed(bad_magic))[0],2)
        bad_offset=bytearray(original);struct.pack_into("<I",bad_offset,0x3c,len(original)-2)
        self.assertEqual(self.parsed(self.checksummed(bad_offset))[0],4)
        bad_string=bytearray(original)
        strings_off=struct.unpack_from("<I",original,0x3c)[0]
        struct.pack_into("<I",bad_string,strings_off,len(original)+4)
        self.assertEqual(self.parsed(self.checksummed(bad_string))[0],5)
        bad_method=bytearray(original)
        methods_off=struct.unpack_from("<I",original,0x5c)[0]
        struct.pack_into("<I",bad_method,methods_off+4,999999)
        self.assertEqual(self.parsed(self.checksummed(bad_method))[0],4)
        self.assertNotEqual(self.parsed(original[:56])[0],0)
        self.assertNotEqual(self.parsed(b"")[0],0)

    def test_checksum_is_not_a_signature_and_fuzz_does_not_escape_bounds(self):
        original=DEX.read_bytes()
        changed=bytearray(original)
        pos=changed.index(b"Play Store\0")
        changed[pos:pos+10]=b"Play Space"
        self.assertEqual(self.parsed(self.checksummed(changed))[0],0)
        # A valid Adler32 does not make this altered DEX a signed/trusted APK.
        rng=random.Random(20260926)
        for _ in range(160):
            modified=bytearray(original)
            index=rng.randrange(len(modified))
            modified[index]^=rng.randint(1,255)
            code,view,backing=self.parsed(self.checksummed(modified))
            self.assertIn(code,range(6))
            if code==0:self.assertGreaterEqual(self.count(view),0)
            self.assertIsNotNone(backing)


if __name__=="__main__":unittest.main()
