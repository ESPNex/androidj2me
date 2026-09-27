"""Host gate for virtual /dev/binder's *bounded transport*, NOT Android services.

These wire formats follow the pinned AOSP 4.2.2 framework/native Parcel.cpp and
IServiceManager.cpp. No service named 'activity', 'package', etc. is invented.
"""
from __future__ import annotations
import ctypes as C
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class Parcel(C.Structure):
    _fields_=[('bytes',C.c_uint8*2048),('object_offsets',C.c_uint16*8),
              ('length',C.c_uint16),('cursor',C.c_uint16),('objects',C.c_uint8)]

HANDLER=C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_uint32,C.c_uint32,C.c_uint32,
                    C.POINTER(Parcel),C.POINTER(Parcel))

class BinderWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('gcc'):
            raise unittest.SkipTest('gcc required')
        (ROOT/'build').mkdir(exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(dir=ROOT/'build')
        so=Path(cls.tmp.name)/'binder.so'
        subprocess.run(['gcc','-std=c99','-O2','-Wall','-Wextra','-Werror',
                        '-pedantic','-fPIC','-shared',
                        str(ROOT/'symbian/runtime/binder_ipc.c'),'-o',str(so)],check=True)
        lib=C.CDLL(str(so));cls.lib=lib
        def bind(name,args,rest=C.c_int):
            fn=getattr(lib,'e63_binder_'+name);fn.argtypes=args;fn.restype=rest
            return fn
        cls.new=bind('new',[],C.c_void_p)
        cls.free=bind('free',[C.c_void_p],None)
        cls.connect=bind('connect',[C.c_void_p,C.c_uint32,C.c_uint32],C.c_void_p)
        cls.disconnect=bind('disconnect',[C.c_void_p],None)
        cls.export=bind('export',[C.c_void_p,HANDLER,C.c_void_p,
                                  C.POINTER(C.c_uint32)])
        cls.release=bind('release',[C.c_void_p,C.c_uint32])
        cls.reset=bind('parcel_reset',[C.POINTER(Parcel)],None)
        cls.write_int=bind('write_int',[C.POINTER(Parcel),C.c_int32])
        cls.read_int=bind('read_int',[C.POINTER(Parcel),C.POINTER(C.c_int32)])
        cls.write_string=bind('write_string',[C.POINTER(Parcel),C.c_char_p])
        cls.read_string=bind('read_string',[C.POINTER(Parcel),C.c_void_p,C.c_size_t])
        cls.write_token=bind('write_token',[C.POINTER(Parcel),C.c_char_p])
        cls.read_token=bind('read_token',[C.POINTER(Parcel),C.c_char_p])
        cls.write_handle=bind('write_handle',[C.POINTER(Parcel),C.c_uint32])
        cls.read_handle=bind('read_handle',[C.POINTER(Parcel),C.POINTER(C.c_uint32)])
        cls.validate=bind('parcel_validate',[C.POINTER(Parcel)])
        cls.transact=bind('transact',[C.c_void_p,C.c_uint32,C.c_uint32,
                                      C.POINTER(Parcel),C.POINTER(Parcel)])

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def setUp(self):
        self.domain=self.new();self.assertTrue(self.domain)
        self.sys=self.connect(self.domain,11,1000)
        self.app=self.connect(self.domain,21,10042)
        self.isolated=self.connect(self.domain,22,99001)
        self.assertTrue(self.sys and self.app and self.isolated)
        self.callbacks=[]

    def tearDown(self):
        for name in ('sys','app','isolated'):
            client=getattr(self,name)
            if client:self.disconnect(client)
        self.free(self.domain)

    def request(self,code,name=b'unit.test',handle=0,allow=0,
                interface=b'android.os.IServiceManager'):
        p=Parcel(); self.assertEqual(self.write_token(C.byref(p),interface),0)
        if code==4:self.assertEqual(self.write_int(C.byref(p),int(name)),0)
        else:self.assertEqual(self.write_string(C.byref(p),name),0)
        if code==3:
            self.assertEqual(self.write_handle(C.byref(p),handle),0)
            self.assertEqual(self.write_int(C.byref(p),allow),0)
        return p

    def wire(self,client,code,name=b'unit.test',handle=0,allow=0):
        request=self.request(code,name,handle,allow)
        reply=Parcel();rc=self.transact(client,0,code,C.byref(request),C.byref(reply))
        return rc,reply

    def export_service(self,owner=None):
        owner=owner or self.sys
        @HANDLER
        def service(ctx,code,pid,uid,request,reply):
            if code!=17:return -4
            if request.contents.cursor!=0 or request.contents.length!=0:return -6
            # Genuine caller identity comes from the broker session, not Parcel.
            return self.write_int(reply,pid*100000+uid)
        self.callbacks.append(service)
        handle=C.c_uint32()
        self.assertEqual(self.export(owner,service,None,C.byref(handle)),0)
        self.assertGreater(handle.value,0)
        return handle.value

    def read_handle_value(self,reply):
        v=C.c_uint32(0xffffffff)
        self.assertEqual(self.read_handle(C.byref(reply),C.byref(v)),0)
        return v.value

    def test_aosp_42_parcel_layout_and_null_binder(self):
        empty=Parcel()
        self.assertEqual(self.write_string(C.byref(empty),b''),0)
        self.assertEqual(bytes(empty.bytes[:8]),bytes(8))
        buffer=C.create_string_buffer(4)
        self.assertEqual(self.read_string(C.byref(empty),buffer,4),0)
        self.assertEqual(buffer.value,b'')
        p=self.request(2)
        token='android.os.IServiceManager'.encode('utf-16le')
        prefix=(0x100).to_bytes(4,'little')+ (len(token)//2).to_bytes(4,'little')
        self.assertEqual(bytes(p.bytes[:len(prefix)+len(token)]),prefix+token)
        self.assertEqual(p.length%4,0)
        self.assertEqual(self.validate(C.byref(p)),0)
        self.assertEqual(self.read_token(C.byref(p),b'android.os.IServiceManager'),0)
        name=C.create_string_buffer(64)
        self.assertEqual(self.read_string(C.byref(p),name,len(name)),0)
        self.assertEqual(name.value,b'unit.test')
        self.assertEqual(p.cursor,p.length)
        rc,empty=self.wire(self.app,2)
        self.assertEqual(rc,0)
        self.assertEqual(empty.objects,0)
        self.assertEqual(self.read_handle_value(empty),0)
        self.assertEqual(bytes(empty.bytes[:4]),bytes.fromhex('852a6273'))

    def test_register_lookup_transact_identity_and_service_lifetime(self):
        handle=self.export_service()
        rc,reply=self.wire(self.sys,3,handle=handle)
        self.assertEqual(rc,0)
        result=C.c_int32(99)
        self.assertEqual(self.read_int(C.byref(reply),C.byref(result)),0)
        self.assertEqual(result.value,0)
        # CHECK and GET use AOSP IServiceManager transaction codes 2 and 1.
        for code in (2,1):
            rc,reply=self.wire(self.app,code)
            self.assertEqual(rc,0)
            self.assertEqual(self.read_handle_value(reply),handle)
        self.assertEqual(reply.objects,1)
        self.assertEqual(reply.object_offsets[0],0)
        self.assertEqual(bytes(reply.bytes[:4]),bytes.fromhex('852a6873'))
        request=Parcel();out=Parcel()
        self.assertEqual(self.transact(self.app,handle,17,
                                       C.byref(request),C.byref(out)),0)
        self.assertEqual(self.read_int(C.byref(out),C.byref(result)),0)
        self.assertEqual(result.value,21*100000+10042)
        self.assertEqual(self.release(self.app,handle),0)
        self.assertEqual(self.release(self.app,handle),0)
        self.assertEqual(self.transact(self.app,handle,17,
                                       C.byref(request),C.byref(out)),-2)
        # Real release/death: owner disconnect makes service disappear, and
        # stale guest handles must not authorize the next exported endpoint.
        self.disconnect(self.sys);self.sys=0
        rc,reply=self.wire(self.app,2)
        self.assertEqual((rc,self.read_handle_value(reply)),(0,0))
        self.sys=self.connect(self.domain,31,1000)
        new=self.export_service()
        self.assertNotEqual(new,handle)
        self.assertEqual(self.transact(self.app,new,17,
                                       C.byref(request),C.byref(out)),-2)

    def test_list_protocol_duplicates_and_permissions(self):
        handle=self.export_service()
        rc,_=self.wire(self.app,3,handle=handle)
        self.assertEqual(rc,-2)  # only system may add services
        self.assertEqual(self.wire(self.sys,3,handle=handle)[0],0)
        rc,reply=self.wire(self.sys,3,handle=handle)
        self.assertEqual(rc,0)
        value=C.c_int32()
        self.assertEqual(self.read_int(C.byref(reply),C.byref(value)),0)
        self.assertEqual(value.value,-17) # EEXIST without replacing owner
        rc,reply=self.wire(self.app,4,name=0)
        self.assertEqual(rc,0)
        buf=C.create_string_buffer(64)
        self.assertEqual(self.read_string(C.byref(reply),buf,len(buf)),0)
        self.assertEqual(buf.value,b'unit.test')
        self.assertEqual(self.wire(self.app,4,name=1)[0],-3)
        rc,reply=self.wire(self.isolated,2)
        self.assertEqual((rc,self.read_handle_value(reply)),(0,0))
        handle2=self.export_service()
        self.assertEqual(self.wire(self.sys,3,name=b'public',handle=handle2,
                                   allow=1)[0],0)
        rc,reply=self.wire(self.isolated,2,name=b'public')
        self.assertEqual((rc,self.read_handle_value(reply)),(0,handle2))

    def test_fail_closed_on_fake_tokens_bad_utf16_and_untracked_objects(self):
        p=self.request(2,interface=b'not.android.os.IServiceManager')
        reply=Parcel()
        before=bytes(p.bytes[:p.length])
        self.assertEqual(self.transact(self.app,0,2,C.byref(p),C.byref(p)),-1)
        self.assertEqual(bytes(p.bytes[:p.length]),before)
        self.assertEqual(self.transact(self.app,0,2,C.byref(p),C.byref(reply)),-2)
        self.assertEqual(reply.length,0)
        p=self.request(2)
        # malformed UTF-16LE terminator; no Latin-1 or silent truncation
        at=4+4+((len('android.os.IServiceManager')+1)*2+3 & ~3)+4
        p.bytes[at+len('unit.test')*2]=1
        self.assertEqual(self.transact(self.app,0,2,C.byref(p),C.byref(reply)),-6)
        handle=self.export_service()
        p=self.request(3,handle=handle)
        p.object_offsets[0]=2 # forged metadata; object data is NOT authority
        self.assertEqual(self.validate(C.byref(p)),-6)
        self.assertNotEqual(self.transact(self.sys,0,3,C.byref(p),C.byref(reply)),0)
        p=self.request(3,handle=handle)
        p.objects=0
        self.assertEqual(self.transact(self.sys,0,3,C.byref(p),C.byref(reply)),-6)
        self.assertEqual(reply.length,0)
        self.assertEqual(self.wire(self.app,2,name=b'unit.test')[0],0)

    def test_missing_android_services_are_not_fabricated(self):
        for name in (b'activity',b'package',b'window',b'power',b'input'):
            rc,p=self.wire(self.app,2,name)
            self.assertEqual((rc,self.read_handle_value(p)),(0,0))

if __name__=='__main__':unittest.main()
