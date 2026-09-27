"""GCC-only proof: ORIGINAL converted Canvas key events drive Midlet DEX.

The C host supplies only MIDP game-action mapping and a repaint dirty bit.
No C Graphics.paint, native SIS, RFs or device compatibility is claimed.
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

from dalvik.dex_j2me import J2MEDex
from dalvik.ui_vm import CANVAS, MIDLET, JavaMEUI

ROOT=Path(__file__).resolve().parents[1]
DEX=ROOT / "j2me/classes.dex"
SRC=ROOT / "symbian/runtime"
APK=ROOT / "apks/Launcher.apk"
STORE="Landroid/j2me/edition/StoreState;"
GAME=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_int32,
                      ctypes.POINTER(ctypes.c_int32))
TIME=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_int64))


class View(ctypes.Structure):
    _fields_=[("data",ctypes.c_void_p),("size",ctypes.c_size_t)] + [
        (name,ctypes.c_uint32) for name in (
            "strings_count strings_off types_count types_off protos_count protos_off "
            "fields_count fields_off methods_count methods_off classes_count "
            "classes_off data_off data_count").split()]


class NativeUiVm:
    def __init__(self,lib,blob: bytes):
        self.core=lib
        self.backing=ctypes.create_string_buffer(blob)
        self.view=View()
        if lib.e63_dex_open(self.backing,len(blob),ctypes.byref(self.view)):
            raise AssertionError("DEX preflight failed")
        def action(_,code,out):
            out[0]={-1:1,-2:6,-3:2,-4:5,-5:8,
                    -1001:1,-1002:6,-1003:2,-1004:5,-1005:8}.get(code,0)
            return 0
        self.game=GAME(action)  # callback MUST remain alive while VM exists
        self.vm=lib.e63_ui_new(ctypes.byref(self.view),self.game,None)
        if not self.vm:raise AssertionError("native UI VM memory exhausted")
        self.time_ms=1000
        def clock(_,out):
            out[0]=self.time_ms
            return 0
        self.time_callback=TIME(clock)  # Keep alive while native VM calls it.
        if lib.e63_ui_set_time_host(self.vm,self.time_callback,None):
            raise AssertionError("invalid native time host")
        if lib.e63_ui_set_viewport(self.vm,320,240):
            raise AssertionError("invalid E63 display viewport")
        self.midlet=self.object(MIDLET)
        self.canvas=self.object(CANVAS)
        self.store=self.object(STORE)
        self.selected=self.array(18)
        self.ids={}
        for owner,fields in ((MIDLET,(("screen","I"),("editMode","I"),
                                     ("selected","[I"),("store",STORE),
                                     ("canvas",CANVAS),("resumeAtHome","Z"),
                                     ("editorForm","Ljavax/microedition/lcdui/Form;"))),
                             (CANVAS,(("app",MIDLET),)),
                             (STORE,(("installed","Z"),))):
            for name,desc in fields:
                field=lib.e63_dex_field_id(ctypes.byref(self.view),owner.encode(),
                                           name.encode(),desc.encode())
                if field<0:raise AssertionError(f"DEX field missing: {owner}->{name}:{desc}")
                self.ids[owner,name]=field
        assert lib.e63_ui_set_ref(self.vm,self.canvas,self.ids[CANVAS,"app"],self.midlet)==0
        assert lib.e63_ui_set_ref(self.vm,self.midlet,self.ids[MIDLET,"canvas"],self.canvas)==0
        assert lib.e63_ui_set_ref(self.vm,self.midlet,self.ids[MIDLET,"store"],self.store)==0
        assert lib.e63_ui_set_array(self.vm,self.midlet,self.ids[MIDLET,"selected"],self.selected)==0

    def close(self):
        if self.vm:self.core.e63_ui_free(self.vm);self.vm=None

    def object(self,owner: str):
        h=ctypes.c_uint32()
        status=self.core.e63_ui_object(self.vm,owner.encode(),ctypes.byref(h))
        if status:raise AssertionError(f"guest object allocation: {status}")
        return h.value

    def array(self,n):
        h=ctypes.c_uint32()
        status=self.core.e63_ui_int_array(self.vm,n,ctypes.byref(h))
        if status:raise AssertionError(f"array allocation: {status}")
        return h.value

    def set(self,owner,name,value):
        handle={MIDLET:self.midlet,CANVAS:self.canvas,STORE:self.store}[owner]
        status=self.core.e63_ui_set_int(self.vm,handle,self.ids[owner,name],value)
        if status:raise AssertionError(f"field {name}: {status}")

    def get(self,owner,name):
        handle={MIDLET:self.midlet,CANVAS:self.canvas,STORE:self.store}[owner]
        value=ctypes.c_int32()
        status=self.core.e63_ui_get_int(self.vm,handle,self.ids[owner,name],ctypes.byref(value))
        if status:raise AssertionError(f"field {name}: {status}")
        return value.value

    def selected_at(self,screen):
        value=ctypes.c_int32()
        status=self.core.e63_ui_array_get(self.vm,self.selected,screen,ctypes.byref(value))
        if status:raise AssertionError(f"array get: {status}")
        return value.value

    def call(self,owner,name,proto,*params):
        ref={MIDLET:self.midlet,CANVAS:self.canvas,STORE:self.store}[owner]
        values=(ctypes.c_int32*len(params))(*params) if params else None
        result=ctypes.c_int32(-999)
        status=self.core.e63_ui_call(self.vm,ref,name.encode(),proto.encode(),
                       values,len(params),ctypes.byref(result))
        return status,(result.value if proto.endswith(("I","Z")) else None)


class NativeOriginalUiEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=shutil.which("gcc")
        if not cc:raise unittest.SkipTest("gcc needed for C99 UI event VM")
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.base=Path(cls.tmp.name)
        shared=cls.base / "libui_events.so"
        sources=[str(SRC / "dex_preflight.c"),str(SRC / "ui_event_vm.c")]
        flags=[cc,"-std=c99","-O2","-Wall","-Wextra","-Werror","-pedantic"]
        subprocess.run(flags+["-fPIC","-shared"]+sources+["-o",str(shared)],check=True)
        cls.cli=cls.base / "e63_ui_event_check"
        subprocess.run(flags+sources+[str(SRC / "ui_event_cli.c"),"-o",str(cls.cli)],check=True)
        cls.lib=ctypes.CDLL(str(shared))
        for function,inputs,output in (
           ("e63_dex_open",[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(View)],ctypes.c_int),
           ("e63_dex_field_id",[ctypes.POINTER(View),ctypes.c_char_p,ctypes.c_char_p,ctypes.c_char_p],ctypes.c_int),
           ("e63_ui_new",[ctypes.POINTER(View),GAME,ctypes.c_void_p],ctypes.c_void_p),
           ("e63_ui_free",[ctypes.c_void_p],None),
           ("e63_ui_set_time_host",[ctypes.c_void_p,TIME,ctypes.c_void_p],ctypes.c_int),
           ("e63_ui_set_viewport",[ctypes.c_void_p,ctypes.c_uint16,ctypes.c_uint16],ctypes.c_int),
           ("e63_ui_object",[ctypes.c_void_p,ctypes.c_char_p,ctypes.POINTER(ctypes.c_uint32)],ctypes.c_int),
           ("e63_ui_int_array",[ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)],ctypes.c_int),
           ("e63_ui_set_int",[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_int32],ctypes.c_int),
           ("e63_ui_get_int",[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.POINTER(ctypes.c_int32)],ctypes.c_int),
           ("e63_ui_set_ref",[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32],ctypes.c_int),
           ("e63_ui_set_array",[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32],ctypes.c_int),
           ("e63_ui_array_set",[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_int32],ctypes.c_int),
           ("e63_ui_array_get",[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.POINTER(ctypes.c_int32)],ctypes.c_int),
           ("e63_ui_call",[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.c_char_p,
                           ctypes.POINTER(ctypes.c_int32),ctypes.c_uint32,ctypes.POINTER(ctypes.c_int32)],ctypes.c_int),
           ("e63_ui_repaint_pending",[ctypes.c_void_p],ctypes.c_int),
           ("e63_ui_clear_repaint",[ctypes.c_void_p],None)):
            method=getattr(cls.lib,function);method.argtypes=inputs;method.restype=output
        cls.original=DEX.read_bytes()

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def native(self,blob=None):
        return NativeUiVm(self.lib,blob if blob is not None else self.original)

    def python_ui(self,slug):
        return JavaMEUI(APK,self.base / slug)

    @staticmethod
    def rehash(data):
        data[12:32]=hashlib.sha1(data[32:]).digest()
        struct.pack_into("<I",data,8,zlib.adler32(data[12:]) & 0xffffffff)
        return bytes(data)

    def test_standalone_c_cli_executes_original_canvas_and_midlet_bytecode(self):
        checked=subprocess.run([str(self.cli),str(DEX)],capture_output=True,text=True)
        self.assertEqual(checked.returncode,0,checked.stderr)
        self.assertIn("screen=2 focus_home=1 redraw=1",checked.stdout)
        self.assertIn("Canvas pointer DEX: home_screen=1",checked.stdout)

    def test_real_midlet_list_count_follows_dex_with_python_parity(self):
        vm=self.native()
        ui=self.python_ui("list_count")
        try:
            app=ui.app
            store=app.fields[MIDLET+"->store:"+STORE]
            for installed in (0,1):
                vm.set(STORE,"installed",installed)
                store.fields[STORE+"->installed:Z"]=installed
                for screen in range(14):
                    vm.set(MIDLET,"screen",screen)
                    app.fields[MIDLET+"->screen:I"]=screen
                    expected=ui.run(MIDLET+"->listCount()I",[app])
                    self.assertEqual(vm.call(MIDLET,"listCount","()I"),(0,expected),
                                     (screen,installed))
        finally:vm.close()

    def test_original_canvas_keypad_navigation_runs_midlet_and_redraw_request(self):
        vm=self.native()
        ui=self.python_ui("numeric_keys")
        try:
            for key,expected in ((53,1),(56,1),(53,2)):
                # KEY_NUM5 boots to HOME; KEY_NUM8 moves focus to Settings;
                # KEY_NUM5 chooses it via Midlet.activate DEX.
                self.assertEqual(vm.call(CANVAS,"keyPressed","(I)V",key),(0,None))
                ui.key(key)
                self.assertEqual(vm.get(MIDLET,"screen"),ui.app.fields[MIDLET+"->screen:I"])
                sel=ui.app.fields[MIDLET+"->selected:[I"]
                self.assertEqual([vm.selected_at(i) for i in range(18)],sel)
                self.assertEqual(vm.get(MIDLET,"screen"),expected)
                self.assertEqual(self.lib.e63_ui_repaint_pending(vm.vm),1)
                self.lib.e63_ui_clear_repaint(vm.vm)
            self.assertEqual(vm.call(CANVAS,"keyPressed","(I)V",57),(0,None))
            ui.key(57)
            self.assertEqual(vm.get(MIDLET,"screen"),ui.app.fields[MIDLET+"->screen:I"])
            self.assertEqual(self.lib.e63_ui_repaint_pending(vm.vm),0)
        finally:vm.close()

    def test_jelly_bean_panel_keys_are_guest_dex_in_native_and_python(self):
        for key,expected in ((49,14),(51,15),(55,16)):
            with self.subTest(key=key):
                vm=self.native()
                ui=self.python_ui("holo_panel_"+str(key))
                try:
                    vm.set(MIDLET,"screen",1)
                    ui.tick(2100)
                    self.assertEqual(vm.call(CANVAS,"keyPressed","(I)V",key),(0,None))
                    ui.key(key)
                    self.assertEqual(vm.get(MIDLET,"screen"),expected)
                    self.assertEqual(ui.app.fields[MIDLET+"->screen:I"],expected)
                    self.assertEqual(self.lib.e63_ui_repaint_pending(vm.vm),1)
                    self.assertEqual(vm.call(CANVAS,"pointerPressed","(II)V",160,220),(0,None))
                    ui.pointer(160,220)
                    self.assertEqual(vm.get(MIDLET,"screen"),1)
                    self.assertEqual(ui.app.fields[MIDLET+"->screen:I"],1)
                finally:vm.close()

    def test_negative_s60_keys_execute_guest_back_and_navigation(self):
        vm=self.native()
        try:
            vm.set(MIDLET,"screen",1)  # Home from native boot seed.
            self.assertEqual(vm.call(CANVAS,"keyPressed","(I)V",55)[0],0)
            self.assertEqual(vm.get(MIDLET,"screen"),16)  # Quick Settings.
            self.assertEqual(vm.call(CANVAS,"keyPressed","(I)V",-6)[0],0)
            self.assertEqual(vm.get(MIDLET,"screen"),1)  # Guest back(), not host UI.
            self.assertEqual(vm.call(CANVAS,"keyPressed","(I)V",-1004)[0],0)
            self.assertEqual(vm.selected_at(1),1)  # D-pad RIGHT maps to guest move.
            self.assertEqual(vm.call(CANVAS,"keyPressed","(I)V",-1003)[0],0)
            self.assertEqual(vm.selected_at(1),0)  # D-pad LEFT remains navigation.
            vm.time_ms=1100
            self.assertEqual(vm.call(CANVAS,"keyPressed","(I)V",-6)[0],0)
            self.assertEqual(vm.get(MIDLET,"screen"),1)  # Debounced repeat.
            vm.time_ms=1300
            self.assertNotEqual(vm.call(CANVAS,"keyPressed","(I)V",-6)[0],0)
            self.assertEqual(vm.get(MIDLET,"screen"),1)  # Exit lifecycle unported;
            # native AppUi uses its own Exit() only on Home after this failure.
        finally:vm.close()

    def test_original_canvas_key_repeat_uses_device_game_action_and_guest_move(self):
        vm=self.native()
        ui=self.python_ui("repeat_key")
        try:
            vm.set(MIDLET,"screen",1)
            ui.app.fields[MIDLET+"->screen:I"]=1
            canvas=ui.app.fields[MIDLET+"->canvas:"+CANVAS]
            for key in (-1,-2,-3,-4):
                self.assertEqual(vm.call(CANVAS,"keyRepeated","(I)V",key),(0,None))
                ui.run(CANVAS+"->keyRepeated(I)V",[canvas,key])
                self.assertEqual(vm.selected_at(1),ui.app.fields[MIDLET+"->selected:[I"][1])
                self.assertEqual(self.lib.e63_ui_repaint_pending(vm.vm),1)
                self.lib.e63_ui_clear_repaint(vm.vm)
        finally:vm.close()

    def test_original_canvas_pointer_home_uses_host_viewport_and_guest_geometry(self):
        vm=self.native()
        ui=self.python_ui("pointer_home")
        try:
            vm.set(MIDLET,"screen",2)
            ui.app.fields[MIDLET+"->screen:I"]=2
            for x,y in ((160,220),(160,210)):
                # Middle bottom nav button: E63Canvas.pointerPressed calls
                # host getWidth/getHeight then ORIGINAL Midlet.home/navigate.
                vm.set(MIDLET,"screen",2)
                ui.app.fields[MIDLET+"->screen:I"]=2
                self.assertEqual(vm.call(CANVAS,"pointerPressed","(II)V",x,y),(0,None))
                ui.pointer(x,y)
                self.assertEqual(vm.get(MIDLET,"screen"),ui.app.fields[MIDLET+"->screen:I"])
                self.assertEqual(vm.get(MIDLET,"screen"),1)
                self.assertEqual(self.lib.e63_ui_repaint_pending(vm.vm),1)
                self.lib.e63_ui_clear_repaint(vm.vm)
            self.assertEqual(self.lib.e63_ui_set_viewport(vm.vm,0,240),-1)
        finally:vm.close()

    def test_canvas_lifecycle_notification_executes_guest_midlet_methods(self):
        vm=self.native()
        ui=self.python_ui("lifecycle")
        try:
            # Seed Settings state without running guest navigation in the host.
            vm.set(MIDLET,"screen",2)
            ui.app.fields[MIDLET+"->screen:I"]=2
            canvas=ui.app.fields[MIDLET+"->canvas:"+CANVAS]
            self.assertEqual(vm.call(CANVAS,"hideNotify","()V"),(0,None))
            ui.run(CANVAS+"->hideNotify()V",[canvas])
            self.assertEqual(vm.get(MIDLET,"resumeAtHome"),
                             ui.app.fields[MIDLET+"->resumeAtHome:Z"])
            self.assertEqual(vm.call(CANVAS,"showNotify","()V"),(0,None))
            ui.run(CANVAS+"->showNotify()V",[canvas])
            self.assertEqual(vm.get(MIDLET,"screen"),ui.app.fields[MIDLET+"->screen:I"])
            self.assertEqual(vm.get(MIDLET,"resumeAtHome"),0)
            self.assertEqual(self.lib.e63_ui_repaint_pending(vm.vm),1)
        finally:vm.close()

    def test_mutating_original_method_changes_native_ui_choice(self):
        original=self.native()
        change=bytearray(self.original)
        original_dex=J2MEDex(self.original)
        method=original_dex.methods[MIDLET+"->listCount()I"]
        words=original_dex.code_for(MIDLET+"->listCount()I").words
        self.assertEqual(words.count(0x2212),1)
        offset=method.code_off+16+2*words.index(0x2212)  # HOME's default 2
        self.assertEqual(change[offset:offset+2],b"\x12\x22")
        change[offset+1]=0x42         # const/4 v2,#4; actual guest DEX changes
        modified=self.native(self.rehash(change))
        try:
            for guest in (original,modified):
                guest.set(MIDLET,"screen",1)
                guest.set(STORE,"installed",0)
            self.assertEqual(original.call(MIDLET,"listCount","()I"),(0,2))
            self.assertEqual(modified.call(MIDLET,"listCount","()I"),(0,4))
        finally:original.close();modified.close()

    def test_limits_missing_methods_and_unsupported_io_fail_closed(self):
        vm=self.native()
        try:
            self.assertEqual(vm.call(MIDLET,"notAMethod","()I")[0],-2)
            self.assertEqual(vm.call(MIDLET,"move","(I)V",1,2)[0],-1)
            vm.set(MIDLET,"screen",1)  # Guest Home back reaches unported lifecycle.
            self.assertNotEqual(vm.call(MIDLET,"back","()V")[0],0)
            self.assertEqual(vm.get(MIDLET,"screen"),1)  # Atomic rollback.
            out=ctypes.c_uint32()
            self.assertEqual(self.lib.e63_ui_int_array(vm.vm,33,ctypes.byref(out)),-5)
            self.assertEqual(self.lib.e63_ui_array_get(vm.vm,vm.selected,18,
                              ctypes.byref(ctypes.c_int32())),-1)
            self.assertEqual(self.lib.e63_ui_set_ref(vm.vm,vm.canvas,
                             vm.ids[CANVAS,"app"],vm.store),-1)
        finally:vm.close()

    def test_bad_bytecode_and_malformed_catch_fail_without_executing(self):
        original=J2MEDex(self.original)
        for name,pc,byte,code,screen in (
                ("listCount",2,0xff,-3,1),  # unknown opcode even before branch
                ("move",14*2+1,0,-4,13),  # goto/8 +0 on POWER_OFF: budget
                ("move",2*2+2,1,-1,13)): # if branch into instruction data
            with self.subTest(name=name,pc=pc):
                method=original.methods[MIDLET+"->"+name+("()I" if name=="listCount" else "(I)V")]
                broken=bytearray(self.original)
                broken[method.code_off+16+pc]=byte
                vm=self.native(self.rehash(broken))
                try:
                    vm.set(MIDLET,"screen",screen)
                    self.assertEqual(vm.call(MIDLET,name,"()I" if name=="listCount" else "(I)V",
                                             *(() if name=="listCount" else (1,)))[0],code)
                    self.assertEqual(vm.get(MIDLET,"screen"),screen)
                    self.assertEqual(self.lib.e63_ui_repaint_pending(vm.vm),0)
                finally:vm.close()
        method=original.methods[CANVAS+"->keyPressed(I)V"]
        words=original.code_for(method.ref).words
        try_at=method.code_off+16+len(words)*2+(2 if len(words)&1 else 0)
        damaged=bytearray(self.original)
        struct.pack_into("<H",damaged,try_at+6,0xffff) # invalid handler_off
        vm=self.native(self.rehash(damaged))
        try:self.assertEqual(vm.call(CANVAS,"keyPressed","(I)V",53)[0],-1)
        finally:vm.close()

    def test_interpreter_fault_after_array_write_rolls_back_guest_and_repaint(self):
        source=J2MEDex(self.original)
        method=source.methods[MIDLET+"->move(I)V"]
        broken=bytearray(self.original)
        at=method.code_off+16+37*2
        self.assertEqual(broken[at],0x54)  # iget-object canvas, AFTER aput
        broken[at]=0x1f                 # check-cast is known, unsupported if reached
        vm=self.native(self.rehash(broken))
        try:
            vm.set(MIDLET,"screen",1)
            self.assertEqual(vm.call(MIDLET,"move","(I)V",1)[0],-3)
            self.assertEqual(vm.selected_at(1),0)
            self.assertEqual(self.lib.e63_ui_repaint_pending(vm.vm),0)
        finally:vm.close()


if __name__=="__main__":unittest.main()
