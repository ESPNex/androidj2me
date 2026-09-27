"""Actual JNI 1.6 C vtable registration gated by pinned Android 4.2 DEX.

This proves only a native ()I method. It is not a general JVM/Android JNI.
"""
from __future__ import annotations
import ctypes as C
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from tests.test_aosp42_native_boot import BootClass,CALLBACK
from tests.test_aosp42_object_vm import MemoryReader,dex_string
from tools.stage_android42_runtime import dex_class_entries,uleb128

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/aosp42_dex'
PROCESS='Landroid/os/Process;'


def method_access_flags(data: bytes, descriptor: str, name: str):
    index=dex_class_entries(data).index(descriptor)
    row=struct.unpack_from('<8I',data,struct.unpack_from('<I',data,100)[0]+32*index)
    at=row[6]
    counts=[]
    for _ in range(4):
        count,at=uleb128(data,at);counts.append(count)
    for count in counts[:2]:
        for _ in range(count):
            _,at=uleb128(data,at)
            _,at=uleb128(data,at)
    method_index=0
    for _ in range(counts[2]):
        delta,at=uleb128(data,at)
        flags_at=at
        flags,at=uleb128(data,at)
        code_at=at
        code,at=uleb128(data,at)
        method_index+=delta
        name_id=struct.unpack_from('<I',data,
                        struct.unpack_from('<I',data,92)[0]+8*method_index+4)[0]
        if dex_string(data,name_id)==name:return flags_at,flags,code_at,code
    raise AssertionError(f'{name} not declared in {descriptor}')


class JniNativeMethodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('gcc'):raise unittest.SkipTest('gcc required')
        cls.dex=zlib.decompress((FIXTURE/'framework.classes.dex.zlib').read_bytes())
        cls.cls=BootClass(4,dex_class_entries(cls.dex).index(PROCESS))
        cls.binder_cls=BootClass(4,dex_class_entries(cls.dex).index(
                                'Landroid/os/Binder;'))
        cls.tmp=tempfile.TemporaryDirectory(dir=ROOT/'build')
        so=Path(cls.tmp.name)/'jni.so'
        subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror',
                        '-pedantic','-fPIC','-shared',
                        str(ROOT/'symbian/runtime/boot_classpath.c'),
                        str(ROOT/'symbian/runtime/boot_method.c'),
                        str(ROOT/'symbian/runtime/jni_bridge.c'),
                        str(ROOT/'tests/native_jni_probe.c'),'-o',str(so)],check=True)
        cls.lib=C.CDLL(str(so))
        cls.new=cls.lib.e63_jni_bridge_new;cls.new.restype=C.c_void_p
        cls.free=cls.lib.e63_jni_bridge_free;cls.free.argtypes=[C.c_void_p]
        cls.bind=cls.lib.e63_jni_bridge_class
        cls.bind.argtypes=[C.c_void_p,C.POINTER(BootClass),C.c_char_p,
                           CALLBACK,C.c_void_p,C.c_size_t,C.POINTER(C.c_void_p)]
        cls.bind.restype=C.c_int
        cls.call=cls.lib.e63_jni_bridge_call_int
        cls.call.argtypes=[C.c_void_p,C.c_void_p,C.c_char_p,
                           C.POINTER(C.c_int32)]
        cls.call.restype=C.c_int
        cls.inspect=cls.lib.e63_boot_inspect_native_static_int
        cls.inspect.argtypes=[C.POINTER(BootClass),C.c_char_p,C.c_char_p,
                              C.c_char_p,CALLBACK,C.c_void_p,C.c_size_t]
        cls.inspect.restype=C.c_int
        for name in ('e63_test_jni_register_pid','e63_test_jni_register_bad_atomic',
                     'e63_test_jni_register_binder','e63_test_jni_unregister'):
            f=getattr(cls.lib,name);f.argtypes=[C.c_void_p,C.c_void_p];f.restype=C.c_int

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_native_method_declaration_requires_real_framework_dex(self):
        reader=MemoryReader(self.dex)
        self.assertEqual(self.inspect(C.byref(self.cls),PROCESS.encode(),
            b'myPid',b'()I',reader.cb,None,reader.size),0)
        self.assertLessEqual(reader.max_request,268)
        self.assertEqual(self.inspect(C.byref(self.cls),PROCESS.encode(),
            b'unknown',b'()I',reader.cb,None,reader.size),-3)
        self.assertEqual(self.inspect(C.byref(self.cls),PROCESS.encode(),
            b'myPid',b'(I)I',reader.cb,None,reader.size),-1)
        wrong=MemoryReader(zlib.decompress(
                        (FIXTURE/'Launcher2.classes.dex.zlib').read_bytes()))
        self.assertNotEqual(self.inspect(C.byref(self.cls),PROCESS.encode(),
            b'myPid',b'()I',wrong.cb,None,wrong.size),0)

    def test_real_jni_vtable_and_verified_registration(self):
        reader=MemoryReader(self.dex)
        bridge=self.new();self.assertTrue(bridge)
        try:
            clazz=C.c_void_p()
            self.assertEqual(self.bind(bridge,C.byref(self.cls),
                PROCESS.encode(),reader.cb,None,reader.size,C.byref(clazz)),0)
            self.assertTrue(clazz.value)
            value=C.c_int32(99)
            self.assertEqual(self.call(bridge,clazz,b'myPid',C.byref(value)),-3)
            self.assertEqual(value.value,0) # no native code is fabricated
            self.assertNotEqual(self.lib.e63_test_jni_register_bad_atomic(
                bridge,clazz),0)
            self.assertEqual(self.call(bridge,clazz,b'myPid',C.byref(value)),-3)
            self.assertEqual(self.lib.e63_test_jni_register_pid(bridge,clazz),0)
            self.assertEqual(self.call(bridge,clazz,b'myPid',C.byref(value)),0)
            self.assertEqual(value.value,4317) # host test callback, NOT Nokia PID
            self.assertNotEqual(self.lib.e63_test_jni_register_pid(bridge,clazz),0)
            self.assertEqual(self.lib.e63_test_jni_unregister(bridge,clazz),0)
            self.assertEqual(self.call(bridge,clazz,b'myPid',C.byref(value)),-3)
            self.assertEqual(value.value,0)
        finally:self.free(bridge)
        self.assertLessEqual(reader.max_request,268)

    def test_real_binder_native_declared_but_must_not_use_incomplete_jni(self):
        # android.os.Binder.getCallingPid() also has an authentic native
        # declaration; registering it would be unsafe until Binder identity,
        # Parcel and managed references are available. Fail, do not fake.
        reader=MemoryReader(self.dex)
        bridge=self.new()
        try:
            clazz=C.c_void_p()
            self.assertEqual(self.bind(bridge,C.byref(self.binder_cls),
                b'Landroid/os/Binder;',reader.cb,None,reader.size,
                C.byref(clazz)),0)
            self.assertNotEqual(self.lib.e63_test_jni_register_binder(
                bridge,clazz),0)
            value=C.c_int32(99)
            self.assertEqual(self.call(bridge,clazz,b'getCallingPid',
                                       C.byref(value)),-3)
            self.assertEqual(value.value,0)
        finally:self.free(bridge)

    def test_no_registration_if_native_flag_or_code_item_is_forged(self):
        flags_at,flags,code_at,code=method_access_flags(self.dex,PROCESS,'myPid')
        self.assertEqual(code,0)
        self.assertEqual(flags & 0x108,0x108)
        self.assertEqual(self.dex[flags_at+1] & 2,2) # ULEB flags > 127
        for variant in ('non_native','code_item'):
            with self.subTest(variant=variant):
                bad=bytearray(self.dex)
                if variant=='non_native':bad[flags_at+1] &= ~2
                else:bad[code_at]=1
                reader=MemoryReader(bytes(bad)) # bypass SHA ONLY for test
                self.assertEqual(self.inspect(C.byref(self.cls),PROCESS.encode(),
                    b'myPid',b'()I',reader.cb,None,reader.size),-4)
                bridge=self.new()
                try:
                    clazz=C.c_void_p()
                    self.assertEqual(self.bind(bridge,C.byref(self.cls),
                        PROCESS.encode(),reader.cb,None,reader.size,
                        C.byref(clazz)),0)
                    self.assertNotEqual(self.lib.e63_test_jni_register_pid(
                        bridge,clazz),0)
                    value=C.c_int32(99)
                    self.assertEqual(self.call(bridge,clazz,b'myPid',
                                               C.byref(value)),-3)
                    self.assertEqual(value.value,0)
                finally:self.free(bridge)

if __name__=='__main__':unittest.main()
