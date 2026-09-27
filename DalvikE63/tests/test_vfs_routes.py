"""Native C99 route checks before the Symbian private-C: RFs adapter."""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class NativeMountRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=shutil.which("gcc")
        if not cc:raise unittest.SkipTest("gcc required for C99 mount router")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(dir=ROOT / "build")
        binary=Path(cls.tmp.name) / "vfs_mount.so"
        subprocess.run([cc,"-std=c99","-Wall","-Wextra","-Werror", "-fPIC", "-shared",
                        str(ROOT / "symbian/runtime/vfs_mount.c"),
                        str(ROOT / "symbian/runtime/vfs_ram.c"),"-o",str(binary)],check=True)
        lib=ctypes.CDLL(str(binary))
        cls.lib=lib
        class Route(ctypes.Structure):
            _fields_=[("kind",ctypes.c_int),("read_only",ctypes.c_uint8),
                      ("relative",ctypes.c_char*513)]
        cls.Route=Route
        cls.route=lib.e63_route_guest_path
        cls.route.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.c_int,ctypes.POINTER(Route)]
        cls.route.restype=ctypes.c_int
        cls.alloc=lib.e63_ram_new
        cls.alloc.argtypes=[]
        cls.alloc.restype=ctypes.c_void_p
        cls.release=lib.e63_ram_free
        cls.release.argtypes=[ctypes.c_void_p]
        cls.put=lib.e63_ram_write
        cls.put.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int,
                          ctypes.c_char_p,ctypes.c_size_t]
        cls.put.restype=ctypes.c_int
        cls.get=lib.e63_ram_read
        cls.get.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int,
                          ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t)]
        cls.get.restype=ctypes.c_int
        cls.erase=lib.e63_ram_delete
        cls.erase.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int]
        cls.erase.restype=ctypes.c_int
        cls.bytes_used=lib.e63_ram_bytes_used
        cls.bytes_used.argtypes=[ctypes.c_void_p]
        cls.bytes_used.restype=ctypes.c_size_t

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def check(self,path,write,caller,expected,kind=None,relative=None):
        out=self.Route()
        code=self.route(path.encode(),write,caller,ctypes.byref(out))
        self.assertEqual(code,expected,(path,write,caller))
        if code==0:
            if kind is not None:self.assertEqual(out.kind,kind)
            if relative is not None:self.assertEqual(out.relative.decode(),relative)

    def test_mounts_and_aliases(self):
        self.check("/",0,1,0,1,"")
        self.check("/system/app/Launcher.apk",0,1,0,2,"app/Launcher.apk")
        # /dev/binder is a virtual IPC endpoint, not a C: partition or file.
        self.check("/dev/binder",0,1,0,5,"")
        self.check("/dev/binder",1,1,0,5,"")
        for caller in (2,3):
            self.check("/dev/binder",0,caller,-2)
            self.check("/dev/binder",1,caller,-2)
        self.check("/dev/binder/partition",0,1,-3)
        self.check("/dev/block/sda",0,1,-3)
        self.check("/tmp/session",1,1,0,1,"tmp/session")
        self.check("/cache/image",1,2,0,1,"cache/image")
        self.check("/data/app/FileManager.apk",1,3,0,3,"app/FileManager.apk")
        for path in ("/sdcard/DCIM/picture.jpg","/storage/emulated/0/DCIM/picture.jpg",
                     "/storage/emulated/legacy/DCIM/picture.jpg",
                     "/data/media/0/DCIM/picture.jpg"):
            self.check(path,0,2,0,4,"DCIM/picture.jpg")
        self.check("/data/data/org.e63.dalvik.files/settings.xml",1,2,0,3,
                   "data/org.e63.dalvik.files/settings.xml")

    def test_pinned_bootdex_cache_cannot_be_written_by_guest(self):
        index = "/data/e63-bootdex/boot-classes.idx"
        jar_dex = "/data/e63-bootdex/core.jar.classes.dex"
        for path in ("/data/e63-bootdex", index, jar_dex):
            self.check(path, 0, 1, 0, 3)
            for caller in (1, 2, 3):
                self.check(path, 1, caller, -2)
        self.check(index, 0, 2, -2)  # FileManager can't browse OS cache
        self.check("/data/e63-bootdex-other/user.txt", 1, 1, 0, 3)

    def test_native_volatile_ram_storage_is_bounded_and_erased_on_restart(self):
        fs=self.alloc()
        self.assertTrue(fs)
        try:
            self.assertEqual(self.put(fs,b"/tmp/session",1,b"ab\x00cd",5),0)
            self.assertEqual(self.put(fs,b"/cache/index",2,b"cache",5),0)
            self.assertEqual(self.bytes_used(fs),10)
            tiny=ctypes.create_string_buffer(2)
            size=ctypes.c_size_t(2)
            self.assertEqual(self.get(fs,b"/tmp/session",1,tiny,ctypes.byref(size)),-6)
            self.assertEqual(size.value,5)
            actual=ctypes.create_string_buffer(size.value)
            self.assertEqual(self.get(fs,b"/tmp/session",1,actual,ctypes.byref(size)),0)
            self.assertEqual(actual.raw,b"ab\x00cd")
            self.assertEqual(self.put(fs,b"/tmp/session",1,b"new",3),0)
            self.assertEqual(self.bytes_used(fs),8)
            self.assertEqual(self.put(fs,b"/tmp/session",1,b"x"*(64*1024+1),64*1024+1),-4)
            self.assertEqual(self.bytes_used(fs),8)  # failed overwrite atomic
            self.assertEqual(self.put(fs,b"/data/file",1,b"no",2),-2)
            self.assertEqual(self.put(fs,b"/system/app/Launcher.apk",1,b"no",2),-2)
            self.assertEqual(self.put(fs,b"/tmp/../invalid",1,b"no",2),-1)
            self.assertEqual(self.erase(fs,b"/cache/index",2),0)
            self.assertEqual(self.bytes_used(fs),3)
            self.assertEqual(self.erase(fs,b"/cache/index",2),-3)
            large=b"0"*(64*1024)
            for i in range(3):
                self.assertEqual(self.put(fs,f"/cache/bulk{i}".encode(),1,large,len(large)),0)
            self.assertEqual(self.put(fs,b"/cache/full",1,large,len(large)),-4)
            self.assertEqual(self.erase(fs,b"/tmp/session",1),0)
            self.assertEqual(self.put(fs,b"/cache/full",1,large,len(large)),0)
            self.assertEqual(self.bytes_used(fs),256*1024)
        finally:self.release(fs)
        restarted=self.alloc()
        try:
            size=ctypes.c_size_t(0)
            self.assertEqual(self.get(restarted,b"/tmp/session",1,None,ctypes.byref(size)),-3)
            self.assertEqual(self.bytes_used(restarted),0)
        finally:self.release(restarted)

    def test_denials_and_path_canonicalization(self):
        for path in ("/", "/system/app/Launcher.apk"):
            self.check(path,1,1,-2)
        for path in ("/data/app/FileManager.apk", "/sdcard/DCIM/picture.jpg"):
            self.check(path,1,1,-2)
        self.check("/data/app/FileManager.apk",1,2,-2)
        self.check("/data/data/org.e63.other/secret",0,2,-2)
        self.check("/data/data/org.e63.dalvik.files",1,2,-2)
        self.check("/data/data/org.e63.other/secret",1,3,-2)
        self.check("/data/media/0/file",1,2,-2)
        self.check("/storage/emulated/legacy/file",1,2,-2)
        self.check("/system/app/Unknown.apk",0,1,-3)
        self.check("/unknown/data",0,1,-3)
        for path in ("/../etc/passwd","/tmp/../no","/tmp/./no","/sdcard//x",
                     "/data/", "/tmp\\file", "C:/data/file", "/tmp/\x01bad",
                     "/"+"z"*513, "/sdcard/Download/.. ",
                     "/sdcard/Download/file.", "/sdcard/Download/file "):
            self.check(path,0,1,-1)
        self.check("/sdcard/Download/città.txt",1,2,0,4,"Download/città.txt")
        self.check("/tmp/a/b",1,1,-2)
        self.check("/tmp/session",0,99,-2)


if __name__=="__main__":unittest.main()
