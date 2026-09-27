"""Interpret the original StoreState DEX in the legacy CLI/service host.

This intentionally small interpreter is distinct from dalvik.ui_vm, which
executes E63Midlet/E63Canvas with PC MIDP graphics and input. Neither Python
implementation is compiled for Symbian; symbian/runtime/dex_vm.c currently
interprets only the StoreState primitive subset in portable C99.
"""
from __future__ import annotations

import threading

from .dex_j2me import J2MEDex, J2MEDexError


CLASS = "Landroid/j2me/edition/StoreState;"


class StoreVMError(J2MEDexError):
    pass


class J2MEStoreState:
    def __init__(self, dex: J2MEDex, initially_installed: bool):
        self.dex = dex
        if CLASS not in dex.classes:
            raise StoreVMError("original StoreState is absent from converted DEX")
        self.instance: dict[str, int] = {}
        self.lock = threading.RLock()
        self._call("<init>(Z)V", int(initially_installed))

    def activate(self) -> int:
        return self._call("activate()I")

    def finish_install(self) -> None:
        self._call("finishInstall()V")

    def is_installed(self) -> bool:
        return bool(self._call("isInstalled()Z"))

    def is_installing(self) -> bool:
        return bool(self._call("isInstalling()Z"))

    @staticmethod
    def _s16(value):
        return value - 65536 if value >= 32768 else value

    def _call(self, method: str, *params):
        ref = CLASS + "->" + method
        code = self.dex.code_for(ref)
        args = (self.instance,) + params
        if code.ins != len(args):
            raise StoreVMError("J2ME method argument count mismatch")
        regs = [None] * code.registers
        regs[-code.ins:] = args
        words = code.words
        starts = set()
        pc = 0
        # Reject corrupted layouts, even in unreachable catch-handler code.
        sizes = {0x70: 3, 0x5c: 2, 0x55: 2, 0x38: 2, 0x39: 2,
                 0x12: 1, 0x1d: 1, 0x1e: 1, 0x0f: 1, 0x0e: 1,
                 0x0d: 1, 0x27: 1}
        branches = []
        while pc < len(words):
            starts.add(pc)
            w = words[pc]
            op = w & 255
            n = sizes.get(op)
            if not n or pc + n > len(words):
                raise StoreVMError("unsupported/truncated J2ME opcode %02x" % op)
            if op in (0x38, 0x39):
                branches.append(pc + self._s16(words[pc + 1]))
            if op in (0x55, 0x5c):
                field = self.dex.fields[words[pc + 1]] if words[pc + 1] < len(self.dex.fields) else ""
                if field not in (CLASS + "->installed:Z", CLASS + "->installing:Z"):
                    raise StoreVMError("field outside original StoreState")
            if op == 0x70:
                index = words[pc + 1]
                if index >= len(self.dex.method_refs) or \
                   self.dex.method_refs[index] != "Ljava/lang/Object;-><init>()V":
                    raise StoreVMError("unexpected J2ME direct invoke")
            pc += n
        if any(target not in starts for target in branches):
            raise StoreVMError("branch into instruction data")
        with self.lock:
            pc, steps, monitor = 0, 0, 0
            while pc < len(words):
                steps += 1
                if steps > 1000:
                    raise StoreVMError("J2ME instruction budget exhausted")
                op = words[pc] & 255
                w = words[pc]
                if op == 0x70:  # invoke-direct {this}, Object.<init>()V
                    count = w >> 12 & 15
                    obj = words[pc + 2] & 15
                    if count != 1 or obj >= len(regs) or regs[obj] is not self.instance:
                        raise StoreVMError("invalid Java Object constructor")
                    pc += 3
                elif op in (0x55, 0x5c):  # iget-boolean / iput-boolean vA, vB, field@CCCC
                    a, b = w >> 8 & 15, w >> 12 & 15
                    if a >= len(regs) or b >= len(regs) or regs[b] is not self.instance:
                        raise StoreVMError("invalid J2ME field register")
                    field = self.dex.fields[words[pc + 1]].split("->", 1)[1].split(":", 1)[0]
                    if op == 0x55:
                        regs[a] = self.instance.get(field, 0)
                    else:
                        if type(regs[a]) is not int or regs[a] not in (0, 1):
                            raise StoreVMError("boolean field write is not boolean")
                        self.instance[field] = regs[a]
                    pc += 2
                elif op in (0x38, 0x39):  # if-eqz / if-nez
                    a = w >> 8
                    if a >= len(regs): raise StoreVMError("invalid branch register")
                    zero = not regs[a]
                    pc += self._s16(words[pc + 1]) if (zero == (op == 0x38)) else 2
                elif op == 0x12:  # const/4
                    a, val = w >> 8 & 15, w >> 12 & 15
                    if a >= len(regs): raise StoreVMError("invalid const register")
                    regs[a] = val - 16 if val >= 8 else val
                    pc += 1
                elif op in (0x1d, 0x1e):  # monitor-enter / exit
                    a = w >> 8
                    if a >= len(regs) or regs[a] is not self.instance:
                        raise StoreVMError("invalid synchronized monitor")
                    monitor += 1 if op == 0x1d else -1
                    if monitor < 0 or monitor > 1:
                        raise StoreVMError("unbalanced monitor")
                    pc += 1
                elif op == 0x0f:  # return vAA
                    a = w >> 8
                    if a >= len(regs) or monitor: raise StoreVMError("invalid synchronized return")
                    return regs[a]
                elif op == 0x0e:  # return-void
                    if monitor: raise StoreVMError("unbalanced synchronized return")
                    return None
                else:
                    # move-exception and throw: only appear in compiler-generated
                    # handlers, not on successful paths; no swallowed exceptions.
                    raise StoreVMError("unexpected exception handler execution")
            raise StoreVMError("J2ME method fell off code")
