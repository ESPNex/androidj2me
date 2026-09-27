"""Register interpreter for the original D8-translated E63Midlet/E63Canvas.

This is separate from classes2.dex's old screen adapters: here the screen
logic, strings, coordinates, asset selection and key handling are read from
classes.dex produced by D8 from the actual MIDP source. The MIDPHost provides
only device services. Unsupported opcodes/methods fail explicitly.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from .dex_j2me import J2MEDex
from .dex_ops import DecodeError, boundaries, joined, signed, width
from .midp_host import JObject, MIDPHost, NativeError, DeviceIOException, YieldFrame, truth
from .os_services import PackageService, PackageServiceError
from .ids import FILES

MIDLET = "Landroid/j2me/edition/E63Midlet;"
CANVAS = "Landroid/j2me/edition/E63Canvas;"
WIDE = object()


class UIVMError(RuntimeError):
    pass


class GuestThrow(Exception):
    def __init__(self, obj: JObject):
        self.obj = obj
        super().__init__(obj.desc + ": " + str(obj.fields.get("message", "")))


def parse_proto(proto: str) -> tuple[list[str], str]:
    if not proto.startswith("(") or ")" not in proto: raise UIVMError("bad prototype")
    text, ret = proto[1:].split(")", 1)
    params = []
    i = 0
    while i < len(text):
        first = i
        while i < len(text) and text[i] == "[": i += 1
        if i >= len(text): raise UIVMError("bad array descriptor")
        if text[i] == "L":
            i = text.find(";", i)
            if i < 0: raise UIVMError("bad class descriptor")
        i += 1
        params.append(text[first:i])
    return params, ret


def num32(x):
    x = int(x) & 0xffffffff
    return x - 0x100000000 if x >= 0x80000000 else x


def num64(x):
    x = int(x) & 0xffffffffffffffff
    return x - (1 << 64) if x >= (1 << 63) else x


def jdiv(a, b):
    if not b: raise UIVMError("divide by zero")
    return (abs(int(a)) // abs(int(b))) * (-1 if (a < 0) != (b < 0) else 1)


class JavaMEUI:
    def __init__(self, apk: Path, state: Path, width: int = 320, height: int = 240,
                 check_signature: bool = True, *, packages: PackageService | None = None):
        import subprocess
        import zipfile
        from .axml_reader import inspect
        from .tools import jdk_tool
        if check_signature:
            signer = jdk_tool("jarsigner")
            if signer is None: raise UIVMError("JDK jarsigner required for signed APK check")
            result = subprocess.run([signer,"-verify",str(apk)],capture_output=True,text=True)
            if result.returncode or "jar verified." not in result.stdout:
                raise UIVMError("APK signature invalid")
        with zipfile.ZipFile(apk) as archive:
            if archive.namelist().count("classes.dex")!=1 or \
               archive.namelist().count("AndroidManifest.xml")!=1:
                raise UIVMError("missing or duplicate APK DEX/manifest")
            info=inspect(archive.read("AndroidManifest.xml"))
            if info.package!="org.e63.dalvik.launcher" or info.min_sdk!=17 or \
               info.main_class!="android.j2me.edition.E63Midlet":
                raise UIVMError("OS manifest does not enter the J2ME MIDlet")
            original = archive.read("classes.dex")
        self.dex = J2MEDex(original)
        for desc in (MIDLET, CANVAS, "Landroid/j2me/edition/StoreState;"):
            if desc not in self.dex.classes: raise UIVMError("J2ME class absent from APK: " + desc)
        self.host = MIDPHost(apk, state, width, height)
        # OS/device service boundary: the interpreter never imports DesktopShell
        # and the backend cannot paint/choose a J2ME screen.
        if packages is None:
            from .pc_services import PCPackageService
            packages = PCPackageService(state)
        self.packages = packages
        self.host.sync_install_flag(packages.installed(FILES))
        self.static: dict[str, Any] = {}
        self.initialized: set[str] = set()
        self.initializing: set[str] = set()
        self.cache: dict[str, tuple] = {}
        self.depth = 0
        self.total_steps = 0
        self.executed_methods: set[str] = set()
        self.app = self.new_obj(MIDLET)
        self.run(MIDLET + "-><init>()V", [self.app])
        self.run(MIDLET + "->startApp()V", [self.app])

    def new_obj(self, desc: str) -> JObject:
        self.initialize(desc)
        return JObject(desc)

    def initialize(self, desc):
        if desc not in self.dex.classes or desc in self.initialized or desc in self.initializing:
            return
        self.initializing.add(desc)
        try:
            name = desc + "-><clinit>()V"
            if name in self.dex.methods: self.run(name, [])
            self.initialized.add(desc)
        finally:
            self.initializing.remove(desc)

    def _resolve(self, ref: str, receiver, opcode: int):
        if opcode not in (0x6e, 0x72, 0x74, 0x78) or not isinstance(receiver, JObject):
            return ref
        # Virtual/interface dispatch: only guest override methods can replace
        # a referenced parent's method. Native MIDP operations stay host calls.
        suffix = ref.split("->", 1)[1]
        cls = receiver.desc
        while cls in self.dex.classes:
            candidate = cls + "->" + suffix
            if candidate in self.dex.methods: return candidate
            cls = self.dex.classes[cls]
        return ref

    @staticmethod
    def _find_handler(code, pc: int, exception: JObject, starts, payloads):
        for begin,end,targets in code.handlers:
            if begin <= pc < end:
                for typ,addr in targets:
                    match=(typ=="*" or typ==exception.desc or
                           typ=="Ljava/lang/Throwable;" or
                           typ=="Ljava/lang/Exception;" and
                           exception.desc.endswith("Exception;"))
                    if match:
                        if addr not in starts or addr in payloads:
                            raise UIVMError("invalid exception target")
                        return addr
        return None

    def run(self, ref: str, args: list[Any]):
        owner = ref.split("->", 1)[0]
        if owner not in self.dex.classes or ref not in self.dex.methods:
            try: return self.host.call(ref, args)
            except DeviceIOException as ex:
                raise GuestThrow(JObject("Ljava/io/IOException;",{"message":str(ex)})) from ex
        if self.depth >= 56: raise UIVMError("J2ME guest recursion limit")
        method = self.dex.methods[ref]
        if not method.code_off: raise UIVMError("abstract/native J2ME method " + ref)
        self.executed_methods.add(ref)
        self.initialize(owner)
        code = self.dex.code_for(ref)
        if ref not in self.cache:
            self.cache[ref] = boundaries(code.words)
        starts, payloads = self.cache[ref]
        words = code.words
        formal, ret = parse_proto(method.proto)
        if not method.flags & 0x8: formal = [owner] + formal
        if len(args) != len(formal): raise UIVMError("J2ME argument count mismatch: " + ref)
        registers = [None] * code.registers
        dest = code.registers - code.ins
        for typ, value in zip(formal, args):
            if dest >= len(registers): raise UIVMError("argument exceeds register frame")
            registers[dest] = value
            dest += 2 if typ in ("J", "D") else 1
            if typ in ("J", "D"):
                if dest - 1 >= len(registers): raise UIVMError("bad wide argument")
                registers[dest - 1] = WIDE
        if dest != code.registers: raise UIVMError("bad J2ME ins_size: " + ref)
        self.depth += 1
        pc, steps, pending, caught = 0, 0, WIDE, None
        try:
            while pc < len(words):
                if pc not in starts or pc in payloads:
                    raise UIVMError("executed instruction data in " + ref)
                self.total_steps += 1
                steps += 1
                if steps > 100000 or self.total_steps > 1500000:
                    raise UIVMError("J2ME instruction budget exhausted: " + ref)
                word, op = words[pc], words[pc] & 255
                a = word >> 8
                nextpc = pc + width(words, pc)

                def reg(i):
                    if i < 0 or i >= len(registers): raise UIVMError("register out of bounds")
                    return registers[i]

                def put(i, value):
                    if i < 0 or i >= len(registers): raise UIVMError("register out of bounds")
                    registers[i] = value

                if op == 0x00: pass  # alignment NOP; payloads are never reached
                elif op in (0x01, 0x04, 0x07):
                    put(a & 15, reg((a >> 4) & 15))
                elif op in (0x02, 0x05, 0x08):
                    put(a, reg(words[pc + 1]))
                elif op in (0x03, 0x06, 0x09):
                    put(words[pc + 1], reg(words[pc + 2]))
                elif op in (0x0a, 0x0b, 0x0c):
                    if pending is WIDE: raise UIVMError("orphaned move-result")
                    put(a, pending)
                    if op == 0x0b: put(a + 1, WIDE)
                    pending = WIDE
                elif op == 0x0d:
                    if caught is None:raise UIVMError("orphaned move-exception")
                    put(a,caught);caught=None
                elif op in (0x0e, 0x0f, 0x10, 0x11):
                    return None if op == 0x0e else reg(a)
                elif op == 0x12:
                    put(a & 15, signed((a >> 4) & 15, 4))
                elif op in (0x13, 0x16):
                    put(a, signed(words[pc+1], 16))
                    if op == 0x16: put(a+1, WIDE)
                elif op in (0x14, 0x17):
                    put(a, signed(joined(words, pc + 1), 32))
                    if op == 0x17: put(a+1, WIDE)
                elif op == 0x15:
                    put(a, num32(words[pc+1] << 16))
                elif op == 0x18:
                    val = joined(words, pc + 1) | joined(words, pc+3) << 32
                    put(a, num64(val)); put(a+1, WIDE)
                elif op == 0x19:
                    put(a, num64(words[pc+1] << 48)); put(a+1, WIDE)
                elif op == 0x1a:
                    put(a, self.dex.strings[words[pc+1]])
                elif op == 0x1b:
                    put(a, self.dex.strings[joined(words, pc+1)])
                elif op == 0x1f:  # check-cast vAA, type@BBBB
                    typ = self.dex.types[words[pc+1]]
                    value = reg(a)
                    if truth(value) and isinstance(value, JObject) and \
                       value.desc != typ and typ != "Ljava/lang/Object;" and \
                       typ not in self._parents(value.desc):
                        raise UIVMError("invalid J2ME check-cast")
                elif op == 0x21:  # array-length
                    arr = reg((a >> 4) & 15)
                    if not isinstance(arr, list): raise UIVMError("array-length on non-array")
                    put(a & 15, len(arr))
                elif op == 0x22:  # new-instance
                    put(a, self.new_obj(self.dex.types[words[pc+1]]))
                elif op == 0x23:  # new-array vA, vB, type@CCCC
                    typ = self.dex.types[words[pc+1]]
                    length = reg((a >> 4) & 15)
                    if not isinstance(length, int) or length < 0 or length > 100000:
                        raise UIVMError("array allocation too large")
                    put(a & 15, [None if typ.startswith("[L") or typ.startswith("[[") else 0
                                 for _ in range(length)])
                elif op == 0x26:  # fill-array-data, 31t
                    arr = reg(a)
                    target = pc + signed(joined(words, pc+1), 32)
                    if target not in payloads or words[target] != 0x0300 or not isinstance(arr, list):
                        raise UIVMError("invalid fill-array-data payload")
                    size = words[target+1]
                    count = joined(words, target+2)
                    if count != len(arr) or size not in (1,2,4,8):
                        raise UIVMError("invalid fill-array-data dimensions")
                    data = struct.pack("<%dH" % (width(words, target)-4),
                                       *words[target+4:target+width(words,target)])
                    for i in range(count):
                        v = int.from_bytes(data[i*size:(i+1)*size], "little")
                        arr[i] = signed(v,size*8)
                elif op == 0x27:
                    value=reg(a)
                    if not isinstance(value,JObject):raise UIVMError("throw on non-Throwable")
                    handler=self._find_handler(code,pc,value,starts,payloads)
                    if handler is None:raise GuestThrow(value)
                    caught=value;nextpc=handler;pending=WIDE
                elif op == 0x28:
                    nextpc = pc + signed(a, 8)
                elif op == 0x29:
                    nextpc = pc + signed(words[pc+1], 16)
                elif op == 0x2a:
                    nextpc = pc + signed(joined(words, pc+1), 32)
                elif op in (0x2b, 0x2c):
                    target = pc + signed(joined(words, pc+1), 32)
                    if target not in payloads: raise UIVMError("switch payload missing")
                    n = words[target+1]
                    if op == 0x2b and words[target] == 0x0100:
                        first = signed(joined(words,target+2),32)
                        idx = int(reg(a)) - first
                        if 0 <= idx < n:
                            nextpc = pc + signed(joined(words, target+4+2*idx),32)
                    elif op == 0x2c and words[target] == 0x0200:
                        keys = [signed(joined(words,target+2+2*i),32) for i in range(n)]
                        if reg(a) in keys:
                            i = keys.index(reg(a))
                            nextpc = pc + signed(joined(words,target+2+2*n+2*i),32)
                    else: raise UIVMError("incorrect switch payload")
                elif op == 0x31:  # cmp-long vAA, vBB, vCC
                    x,y = reg(words[pc+1] & 255),reg(words[pc+1] >> 8)
                    put(a, -1 if x<y else 1 if x>y else 0)
                elif 0x32 <= op <= 0x37:
                    x,y = reg(a&15),reg(a>>4)
                    if op==0x32: match=x==y
                    elif op==0x33: match=x!=y
                    elif op==0x34: match=x<y
                    elif op==0x35: match=x>=y
                    elif op==0x36: match=x>y
                    else: match=x<=y
                    if match: nextpc = pc+signed(words[pc+1],16)
                elif 0x38 <= op <= 0x3d:
                    x=reg(a)
                    # Null and numeric zero are both false per Dalvik register model.
                    if x is None: x=0
                    elif not isinstance(x,(int,float)): x=1
                    match=(x==0,x!=0,x<0,x>=0,x>0,x<=0)[op-0x38]
                    if match:nextpc=pc+signed(words[pc+1],16)
                elif 0x44 <= op <= 0x51:  # aget*/aput* vAA, vBB, vCC
                    bc=words[pc+1]; b,c=bc&255,bc>>8
                    arr=reg(b); idx=reg(c)
                    if not isinstance(arr,list) or not isinstance(idx,int) or not 0<=idx<len(arr):
                        raise UIVMError("array index/reference invalid")
                    if op<=0x4a: put(a,arr[idx])
                    else: arr[idx]=reg(a)
                elif 0x52 <= op <= 0x5f:  # iget*/iput* vA, vB, field@CCCC
                    b=a>>4;a=a&15
                    fieldref=self.dex.fields[words[pc+1]]
                    obj=reg(b)
                    if not isinstance(obj,JObject): raise UIVMError("null/nonobject field receiver " + fieldref)
                    if op<=0x58:
                        value=obj.fields.get(fieldref)
                        if value is None and fieldref.endswith((":I",":Z",":B",":S",":J",":C")):
                            value=0
                        put(a,value)
                        if op==0x53:put(a+1,WIDE)
                    else: obj.fields[fieldref]=reg(a)
                elif 0x60 <= op <= 0x6d:  # sget*/sput*
                    fieldref=self.dex.fields[words[pc+1]]
                    self.initialize(fieldref.split("->",1)[0])
                    if op<=0x66:
                        put(a,self.static.get(fieldref,0))
                        if op==0x61:put(a+1,WIDE)
                    else:self.static[fieldref]=reg(a)
                elif 0x6e <= op <= 0x78:  # invoke-kind 35c or range 3rc
                    index=words[pc+1]
                    if index>=len(self.dex.method_refs):raise UIVMError("method index out of bounds")
                    target=self.dex.method_refs[index]
                    if op<=0x72:
                        count=(word>>12)&15
                        raw=words[pc+2]
                        slots=[raw&15,(raw>>4)&15,(raw>>8)&15,(raw>>12)&15,(word>>8)&15][:count]
                    else:
                        count=a
                        slots=list(range(words[pc+2], words[pc+2]+count))
                    values=[reg(slot) for slot in slots]
                    proto=target[target.index("("):]
                    types,_=parse_proto(proto)
                    if op not in (0x71,0x77): types=[target.split("->",1)[0]]+types
                    args2=[];at=0
                    for typ in types:
                        if at>=len(values):raise UIVMError("invoke missing argument: " + target)
                        args2.append(values[at]);at+=2 if typ in ("J","D") else 1
                    if at!=count:raise UIVMError("invoke register count mismatch: " + target)
                    target=self._resolve(target,args2[0] if args2 else None,op)
                    try:
                        pending=self.run(target,args2)
                    except GuestThrow as thrown:
                        handler=self._find_handler(code,pc,thrown.obj,starts,payloads)
                        if handler is None:raise
                        caught=thrown.obj;nextpc=handler;pending=WIDE
                elif op in (0x1d,0x1e):  # monitor enter/exit: single-threaded host UI
                    if reg(a) is None: raise UIVMError("monitor on null")
                elif op in (0x84,0x8d,0x8e):
                    x=reg((a>>4)&15)
                    if op==0x84: put(a&15,int(x));put((a&15)+1,WIDE)  # int-to-long
                    elif op==0x8d:put(a&15,signed(int(x)&255,8))
                    else:put(a&15,int(x)&65535)  # int-to-char
                elif 0x90 <= op <= 0xaf:  # arithmetic 23x: dest AA, src BB, src CC
                    bc=words[pc+1];x,y=reg(bc&255),reg(bc>>8)
                    put(a,self._arith(op,x,y))
                elif 0xb0 <= op <= 0xcf:  # arithmetic/2addr 12x
                    dest,source=a&15,(a>>4)&15
                    put(dest,self._arith(op-0x20,reg(dest),reg(source)))
                elif 0xd0 <= op <= 0xd7:  # int/lit16 22s
                    dest,source=a&15,a>>4
                    put(dest,self._litop(op,reg(source),signed(words[pc+1],16)))
                elif 0xd8 <= op <= 0xe2:  # int/lit8 22b
                    bc=words[pc+1];x=reg(bc&255);lit=signed(bc>>8,8)
                    put(a,self._litop(op,x,lit))
                else: raise UIVMError(f"unsupported UI DEX opcode {op:02x} in {ref} pc={pc}")
                if nextpc not in starts and nextpc != len(words):
                    raise UIVMError("jump into instruction data")
                pc=nextpc
            raise UIVMError("method fell off DEX code: "+ref)
        except (UIVMError,NativeError,DecodeError) as ex:
            raise UIVMError(f"{ex} [at {ref} pc={pc} op={words[pc]&255:02x}]") from ex
        finally:
            self.depth -= 1

    def _parents(self, desc):
        while desc in self.dex.classes:
            desc=self.dex.classes[desc]
            yield desc

    def _arith(self,op,x,y):
        if op in (0x90,0x9b):v=x+y
        elif op in (0x91,0x9c):v=x-y
        elif op in (0x92,0x9d):v=x*y
        elif op in (0x93,0x9e):v=jdiv(x,y)
        elif op in (0x94,0x9f):v=x-jdiv(x,y)*y
        elif op in (0x95,0xa0):v=int(x)&int(y)
        elif op in (0x96,0xa1):v=int(x)|int(y)
        elif op in (0x97,0xa2):v=int(x)^int(y)
        elif op in (0x98,0xa3):v=int(x)<<(int(y)&31)
        elif op in (0x99,0xa4):v=int(x)>>(int(y)&31)
        elif op in (0x9a,0xa5):v=(int(x)&0xffffffff)>>(int(y)&31)
        else:raise UIVMError("unsupported arithmetic opcode %02x"%op)
        return num64(v) if 0x9b<=op<=0xa5 else num32(v)

    def _litop(self,op,x,lit):
        if op==0xd0:v=x+lit
        elif op==0xd1:v=lit-x
        elif op==0xd2:v=x*lit
        elif op==0xd3:v=jdiv(x,lit)
        elif op==0xd4:v=x-jdiv(x,lit)*lit
        elif op==0xd5:v=x&lit
        elif op==0xd6:v=x|lit
        elif op==0xd7:v=x^lit
        elif op==0xd8:v=x+lit
        elif op==0xd9:v=lit-x
        elif op==0xda:v=x*lit
        elif op==0xdb:v=jdiv(x,lit)
        elif op==0xdc:v=x-jdiv(x,lit)*lit
        elif op==0xdd:v=x&lit
        elif op==0xde:v=x|lit
        elif op==0xdf:v=x^lit
        elif op==0xe0:v=x<<(lit&31)
        elif op==0xe1:v=x>>(lit&31)
        elif op==0xe2:v=(x&0xffffffff)>>(lit&31)
        else:raise UIVMError("unsupported int/lit opcode %02x"%op)
        return num32(v)

    def key(self, code: int):
        self.total_steps=0
        import time
        # The original MIDlet debounces Back at 220 ms. PC UI requests may
        # arrive in a burst; advance the guest clock rather than bypassing it.
        self.host.now_ms=max(int(time.time()*1000),self.host.now_ms+260)
        canvas=self.app.fields.get(MIDLET+"->canvas:"+CANVAS)
        if not isinstance(canvas,JObject):raise UIVMError("original J2ME Canvas missing")
        self.run(CANVAS+"->keyPressed(I)V",[canvas,code])

    def pointer(self,x:int,y:int):
        self.total_steps=0
        import time
        self.host.now_ms=max(int(time.time()*1000),self.host.now_ms+260)
        canvas=self.app.fields.get(MIDLET+"->canvas:"+CANVAS)
        self.run(CANVAS+"->pointerPressed(II)V",[canvas,x,y])

    def tick(self, milliseconds: int = 700):
        """Run ONE iteration of the original guest ticker, not a Python clone.

        Host Thread.sleep yields at the end; the next tick enters the Java
        method again, carrying the same generation/guest fields forward.
        """
        if not 0 < milliseconds <= 10000: raise UIVMError("invalid tick interval")
        self.total_steps=0
        self.host.now_ms += milliseconds
        store = self.app.fields.get(MIDLET+"->store:Landroid/j2me/edition/StoreState;")
        installed_key = "Landroid/j2me/edition/StoreState;->installed:Z"
        before = bool(store.fields.get(installed_key)) if isinstance(store,JObject) else False
        generation = self.app.fields.get(MIDLET+"->tickerGeneration:I", 0)
        self.host.yield_on_sleep = True
        try:
            self.run(MIDLET+"->tickLoop(I)V",[self.app,generation])
        except YieldFrame:
            pass
        finally:
            self.host.yield_on_sleep = False
        if not before and isinstance(store,JObject) and store.fields.get(installed_key):
            # The guest DEX has finished its install timer. Only the package
            # service can confirm that an APK was installed on the OS backend.
            try:
                if not self.packages.installed(FILES): self.packages.install(FILES)
                if not self.packages.installed(FILES):
                    raise PackageServiceError("installer did not commit FileManager")
            except PackageServiceError as exc:
                # Guest saveSettings() ran before the OS installer. A failed
                # commit must never persist OPEN or leave a misleading button.
                self.host.sync_install_flag(False)
                fresh = self.new_obj("Landroid/j2me/edition/StoreState;")
                self.run("Landroid/j2me/edition/StoreState;-><init>(Z)V", [fresh, 0])
                self.app.fields[MIDLET+"->store:Landroid/j2me/edition/StoreState;"] = fresh
                self.app.fields[MIDLET+"->installPercent:I"] = 0
                raise UIVMError("OS package installation failed: " + str(exc)) from exc

    def skip_boot(self):
        self.total_steps=0
        self.run(MIDLET+"->navigate(I)V",[self.app,1])

    def form_action(self, text: str = "", accept: bool = True):
        """Feed native MIDP TextField, then call ORIGINAL guest commandAction."""
        self.total_steps=0
        if not isinstance(text,str) or len(text)>64:raise UIVMError("invalid form input")
        form=self.host.current
        if form is not None and form is self.app.fields.get(MIDLET+"->editorForm:Ljavax/microedition/lcdui/Form;"):
            field=self.app.fields.get(MIDLET+"->editorField:Ljavax/microedition/lcdui/TextField;")
            which="editDoneCommand" if accept else "editBackCommand"
        elif form is not None and form is self.app.fields.get(MIDLET+"->bridgeForm:Ljavax/microedition/lcdui/Form;"):
            field=self.app.fields.get(MIDLET+"->bridgeCodeField:Ljavax/microedition/lcdui/TextField;")
            which="bridgeConnectCommand" if accept else "bridgeBackCommand"
        else:
            raise UIVMError("no editable MIDP Form is current")
        if accept and isinstance(field,JObject):
            self.host.call("Ljavax/microedition/lcdui/TextField;->setString(Ljava/lang/String;)V",
                           [field,text])
        command=self.app.fields.get(MIDLET+"->"+which+":Ljavax/microedition/lcdui/Command;")
        self.run(MIDLET+"->commandAction(Ljavax/microedition/lcdui/Command;Ljavax/microedition/lcdui/Displayable;)V",
                 [self.app,command,form])
        # MIDP Thread.start / Display.callSerially schedule actual guest
        # Runnable.run bytecode. Never run the ticker here: tick() owns it.
        for _ in range(8):
            if not self.host.pending_threads:break
            runnable=self.host.pending_threads.pop(0)
            self.run(runnable.desc+"->run()V",[runnable])
        if self.host.pending_threads:raise UIVMError("guest UI worker budget exceeded")

    def png(self):
        self.total_steps=0
        canvas=self.app.fields.get(MIDLET+"->canvas:"+CANVAS)
        if self.host.current and self.host.current.desc == "Ljavax/microedition/lcdui/Form;":
            return self.form_png(self.host.current)
        return self.host.png(self,canvas)

    def form_png(self,form):
        # LCDUI Form is a native control: the text/fields come from the MIDlet.
        from PIL import Image,ImageDraw
        import io
        image=Image.new('RGB',(self.host.width,self.host.height),(51,51,51))
        d=ImageDraw.Draw(image)
        f=self.host.font(0)
        d.rectangle((0,0,self.host.width,30),fill=(45,51,60))
        d.text((8,5),form.fields.get('title',''),font=f,fill='white')
        y=42
        for item in form.fields.get('items',[]):
            if isinstance(item,str):
                for line in [item[i:i+41] for i in range(0,len(item),41)]:
                    d.text((9,y),line,font=self.host.font(8),fill=(220,220,220));y+=16
            elif isinstance(item,JObject):
                d.text((9,y),str(item.fields.get('label','')),font=f,fill='white');y+=17
                text=str(item.fields.get('text',''))
                if item.fields.get('constraints',0)&65536:text='•'*len(text)
                d.rectangle((9,y,310,y+25),outline=(51,153,255))
                d.text((14,y+4),text,font=f,fill='white');y+=35
        buf=io.BytesIO();image.save(buf,'PNG');return buf.getvalue()
