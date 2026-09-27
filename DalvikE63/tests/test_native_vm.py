"""PC GCC tests for the portable C99 VM running actual J2ME-converted DEX.

It currently runs StoreState's primitive subset, NOT E63Canvas on the phone.
"""
from __future__ import annotations

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

from dalvik.dex_j2me import J2MEDex
from dalvik.store_j2me import J2MEStoreState

ROOT=Path(__file__).resolve().parents[1]
DEX=ROOT / "j2me/classes.dex"
SRC=ROOT / "symbian/runtime"
OWNER=b"Landroid/j2me/edition/StoreState;"


class View(ctypes.Structure):
    _fields_=[("data",ctypes.c_void_p),("size",ctypes.c_size_t)] + [
        (n,ctypes.c_uint32) for n in (
            "strings_count strings_off types_count types_off protos_count protos_off "
            "fields_count fields_off methods_count methods_off classes_count "
            "classes_off data_off data_count").split()]


class Method(ctypes.Structure):
    _fields_=[("method_index",ctypes.c_uint32),("class_index",ctypes.c_uint32),
              ("code_off",ctypes.c_uint32),("registers",ctypes.c_uint16),
              ("ins",ctypes.c_uint16),("outs",ctypes.c_uint16),
              ("tries",ctypes.c_uint16),("words_count",ctypes.c_uint32),
              ("words_le",ctypes.c_void_p)]


class Object(ctypes.Structure):
    _fields_=[("dex",ctypes.POINTER(View)),("class_index",ctypes.c_uint32),
              ("class_descriptor",ctypes.c_char*128),("fields",ctypes.c_int32*256)]


class NativeDexVMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gcc=shutil.which("gcc")
        if not gcc:raise unittest.SkipTest("gcc required for portable C99 DEX VM")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.base=Path(cls.tmp.name)
        common=[gcc,"-std=c99","-O2","-Wall","-Wextra","-Werror","-pedantic",
                str(SRC / "dex_preflight.c"),str(SRC / "dex_vm.c")]
        lib=cls.base / "libe63dexvm.so"
        cls.cli=cls.base / "e63_vm_check"
        subprocess.run(common+["-fPIC","-shared","-o",str(lib)],check=True)
        subprocess.run(common+[str(SRC / "vm_cli.c"),"-o",str(cls.cli)],check=True)
        cls.core=ctypes.CDLL(str(lib))
        cls.core.e63_dex_open.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(View)]
        cls.core.e63_dex_open.restype=ctypes.c_int
        cls.core.e63_dex_find_code.argtypes=[ctypes.POINTER(View),ctypes.c_char_p,
             ctypes.c_char_p,ctypes.c_char_p,ctypes.POINTER(Method)]
        cls.core.e63_dex_find_code.restype=ctypes.c_int
        cls.core.e63_vm_new.argtypes=[ctypes.POINTER(View),ctypes.c_char_p,ctypes.POINTER(Object)]
        cls.core.e63_vm_new.restype=ctypes.c_int
        cls.core.e63_vm_call.argtypes=[ctypes.POINTER(Object),ctypes.c_char_p,
             ctypes.c_char_p,ctypes.POINTER(ctypes.c_int32),ctypes.c_uint32,
             ctypes.POINTER(ctypes.c_int32)]
        cls.core.e63_vm_call.restype=ctypes.c_int

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    @classmethod
    def guest(cls, code: bytes, saved: int):
        backing=ctypes.create_string_buffer(code)
        view=View()
        cls_status=cls.core.e63_dex_open(backing,len(code),ctypes.byref(view))
        if cls_status:raise AssertionError(f"DEX preflight failed: {cls_status}")
        obj=Object()
        if cls.core.e63_vm_new(ctypes.byref(view),OWNER,ctypes.byref(obj)):
            raise AssertionError("native VM could not allocate guest StoreState")
        return backing,view,obj  # both buffers MUST outlive the borrowed pointers

    @classmethod
    def invoke(cls, guest, name: str, proto: str, *args):
        obj=guest[2]
        values=(ctypes.c_int32*len(args))(*args) if args else None
        result=ctypes.c_int32(-99)
        status=cls.core.e63_vm_call(ctypes.byref(obj),name.encode(),proto.encode(),
                values,len(args),ctypes.byref(result))
        return status,(None if proto.endswith("V") else result.value)

    @staticmethod
    def rehash(data: bytearray) -> bytes:
        data[12:32]=hashlib.sha1(data[32:]).digest()
        struct.pack_into("<I",data,8,zlib.adler32(data[12:]) & 0xffffffff)
        return bytes(data)

    def test_real_native_store_methods_match_python_dex_interpreter(self):
        raw=DEX.read_bytes()
        run=subprocess.run([str(self.cli),str(DEX)],text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn("first=1 waiting=3 after=2 installed=1",run.stdout)
        for saved in (0,1):
            with self.subTest(saved=saved):
                guest=self.guest(raw,saved)
                method=Method()
                self.assertEqual(self.core.e63_dex_find_code(ctypes.byref(guest[1]),
                    OWNER,b"activate",b"()I",ctypes.byref(method)),1)
                self.assertGreater(method.words_count,0)
                self.assertEqual(self.core.e63_dex_find_code(ctypes.byref(guest[1]),
                    OWNER,b"activate",b"()Z",ctypes.byref(method)),0)
                python=J2MEStoreState(J2MEDex(raw),bool(saved))
                self.assertEqual(self.invoke(guest,"<init>","(Z)V",saved),(0,None))
                actions=[("isInstalled","()Z",python.is_installed),
                         ("activate","()I",python.activate),
                         ("isInstalling","()Z",python.is_installing),
                         ("activate","()I",python.activate),
                         ("finishInstall","()V",python.finish_install),
                         ("isInstalled","()Z",python.is_installed),
                         ("isInstalling","()Z",python.is_installing),
                         ("activate","()I",python.activate)]
                for name,proto,fn in actions:
                    with self.subTest(method=name):
                        status,result=self.invoke(guest,name,proto)
                        self.assertEqual(status,0)
                        expected=fn()
                        self.assertEqual(result,expected)

    def test_mutated_original_dex_changes_native_control_flow(self):
        original=DEX.read_bytes()
        method=J2MEDex(original).methods[
            "Landroid/j2me/edition/StoreState;->activate()I"]
        code=bytearray(original)
        at=method.code_off+16+3*2  # actual first if-eqz at pc=3
        self.assertEqual(code[at],0x38)
        code[at]=0x39               # if-nez: reverse guest branch
        changed=self.rehash(code)
        self.assertNotEqual(changed,original)
        for saved in (0,1):
            guest=self.guest(changed,saved)
            self.assertEqual(self.invoke(guest,"<init>","(Z)V",saved),(0,None))
            native=self.invoke(guest,"activate","()I")
            python=J2MEStoreState(J2MEDex(changed),bool(saved)).activate()
            self.assertEqual(native,(0,python))
            self.assertNotEqual(native[1],J2MEStoreState(J2MEDex(original),bool(saved)).activate())
        # This temporary DEX is not a signed APK; the test bypasses APK checks.

    def test_unknown_opcode_invalid_branch_and_loop_budget_fail_closed(self):
        original=DEX.read_bytes()
        method=J2MEDex(original).methods[
            "Landroid/j2me/edition/StoreState;->activate()I"]
        base=method.code_off+16
        cases=(((0,0xff),-3),       # reachable unknown opcode
               ((20*2,0xff),-3),   # unreachable exception handler: still rejected
               ((3*2+2,1),-1),     # branch into middle of instruction
               (((0,0x28),(1,0x00)),-4)) # goto/8 +0 loops; finite budget
        for edits,expected in cases:
            with self.subTest(edits=edits):
                mutated=bytearray(original)
                for offset,byte in (edits if isinstance(edits[0],tuple) else (edits,)):
                    mutated[base+offset]=byte
                guest=self.guest(self.rehash(mutated),0)
                self.assertEqual(self.invoke(guest,"<init>","(Z)V",0),(0,None))
                status,_=self.invoke(guest,"activate","()I")
                self.assertEqual(status,expected)
        guest=self.guest(original,0)
        self.assertEqual(self.invoke(guest,"missing","()I")[0],-2)
        self.assertEqual(self.invoke(guest,"activate","(Z)I",0)[0],-2)
        self.assertEqual(self.invoke(guest,"activate","()I",1)[0],-1)

    def test_bounded_random_instruction_mutations_fail_or_terminate(self):
        original=DEX.read_bytes()
        j2me=J2MEDex(original)
        method=j2me.methods["Landroid/j2me/edition/StoreState;->activate()I"]
        code=j2me.code_for("Landroid/j2me/edition/StoreState;->activate()I")
        start=method.code_off+16
        rng=random.Random(20260926)
        for trial in range(160):
            with self.subTest(trial=trial):
                mutated=bytearray(original)
                pos=start+rng.randrange(len(code.words)*2)
                mutated[pos]^=rng.randint(1,255)
                fresh=self.rehash(mutated)
                raw=ctypes.create_string_buffer(fresh)
                view=View()
                if self.core.e63_dex_open(raw,len(fresh),ctypes.byref(view))!=0:
                    continue # rejected at structural gate
                obj=Object()
                self.assertEqual(self.core.e63_vm_new(ctypes.byref(view),OWNER,
                                                       ctypes.byref(obj)),0)
                guest=(raw,view,obj)
                self.assertEqual(self.invoke(guest,"<init>","(Z)V",0)[0],0)
                status,_=self.invoke(guest,"activate","()I")
                self.assertIn(status,(0,-1,-2,-3,-4))

    def test_interpreter_fault_does_not_commit_partial_guest_fields(self):
        original=DEX.read_bytes()
        method=J2MEDex(original).methods[
            "Landroid/j2me/edition/StoreState;->activate()I"]
        broken=bytearray(original)
        at=method.code_off+16+18*2 # after iput-boolean installing=1
        self.assertEqual(broken[at],0x1e) # monitor-exit -> throw
        broken[at]=0x27
        guest=self.guest(self.rehash(broken),0)
        self.assertEqual(self.invoke(guest,"<init>","(Z)V",0),(0,None))
        self.assertEqual(self.invoke(guest,"activate","()I")[0],-3)
        self.assertEqual(self.invoke(guest,"isInstalling","()Z"),(0,0))
        # Rollback is for unsupported interpreter faults, not a claim of
        # general Dalvik exception semantics.

    def test_external_invoke_is_exactly_whitelisted_object_constructor(self):
        raw=DEX.read_bytes()
        constructor=J2MEDex(raw).methods[
            "Landroid/j2me/edition/StoreState;-><init>(Z)V"]
        altered=bytearray(raw)
        ref_at=constructor.code_off+16+2 # second word is method_id for invoke-direct
        self.assertNotEqual(struct.unpack_from("<H",altered,ref_at)[0],0)
        struct.pack_into("<H",altered,ref_at,0)
        guest=self.guest(self.rehash(altered),0)
        self.assertEqual(self.invoke(guest,"<init>","(Z)V",0)[0],-3)


if __name__=="__main__":unittest.main()
