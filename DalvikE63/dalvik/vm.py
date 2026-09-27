"""Bounded register VM for DEX-035, including actual javac/D8 APK programs.

The Java Activity's Android UI backend runs on Android; here only its static
Program methods are interpreted and an allowlisted Host ABI supplies device
primitives. No ART, JIT, general Java heap, Android framework or APK execution
on a physical E63 is claimed. Unsupported D8 opcodes fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .dex import Dex, DexError
from .assembler import HOST, method_parts, proto_types


class VMError(RuntimeError):
    pass


def signed16(v: int) -> int:
    return v - 65536 if v & 0x8000 else v


@dataclass
class VM:
    dex: Dex
    host: object
    max_steps: int = 10000
    max_depth: int = 12

    def call(self, name: str, proto: str, *args):
        ref = self.dex.class_desc + "->" + name + proto
        return self._execute(ref, tuple(args), 0)

    def _verify_instructions(self, code):
        """Preflight instruction widths, indices, registers and branch targets.

        A jump must land at a decoded instruction boundary, never in its data.
        This does not claim to be Android's complete DEX verifier.
        """
        words = code.words
        starts = set()
        branches = []
        pc = 0
        last = -1
        lengths = {0x12: 1, 0x13: 2, 0x1A: 2, 0x01: 1, 0x0A: 1,
                   0x28: 1, 0x29: 2, 0x32: 2, 0x33: 2, 0x38: 2, 0x39: 2,
                   0x71: 3, 0x0E: 1}
        while pc < len(words):
            starts.add(pc)
            word = words[pc]
            op = word & 255
            width = lengths.get(op)
            if width is None or pc + width > len(words):
                raise VMError("unsupported/truncated Dalvik instruction at PC %d" % pc)
            aa = word >> 8
            if op in (0x13, 0x1A, 0x0A, 0x38, 0x39) and aa >= code.registers:
                raise VMError("instruction register out of range")
            if op == 0x12 and (aa & 15) >= code.registers:
                raise VMError("const/4 register out of range")
            if op == 0x1A and words[pc + 1] >= len(self.dex.strings):
                raise VMError("string reference out of range")
            if op == 0x01 or op in (0x32, 0x33):
                if (word >> 8 & 15) >= code.registers or (word >> 12 & 15) >= code.registers:
                    raise VMError("two-register instruction out of range")
            if op == 0x0A and last != 0x71:
                raise VMError("orphaned move-result")
            if op == 0x28:  # D8 uses the compact 8-bit goto, unlike DexWriter.
                delta = aa - 256 if aa & 128 else aa
                branches.append(pc + delta)
            if op in (0x29, 0x32, 0x33, 0x38, 0x39):
                branches.append(pc + signed16(words[pc + 1]))
            if op == 0x71:
                count, index = word >> 12 & 15, words[pc + 1]
                if index >= len(self.dex.method_refs) or count > 5 or count > code.outs:
                    raise VMError("invalid invoke-static")
                ref = self.dex.method_refs[index]
                if not (ref.startswith(HOST + "->") or ref.startswith(self.dex.class_desc + "->")):
                    raise VMError("unsupported external method")
                if count != len(proto_types(method_parts(ref)[2])[0]):
                    raise VMError("invoke-static argument count mismatch")
                cdefg = words[pc + 2]
                regs = [cdefg & 15, cdefg >> 4 & 15,
                        cdefg >> 8 & 15, cdefg >> 12 & 15, word >> 8 & 15][:count]
                if any(r >= code.registers for r in regs):
                    raise VMError("invoke-static register out of range")
            last = op
            pc += width
        if not words or last != 0x0E or any(t not in starts for t in branches):
            raise VMError("method lacks final return or branch targets instruction data")

    def _execute(self, ref: str, args: tuple, depth: int):
        if depth >= self.max_depth:
            raise VMError("maximum guest call depth reached")
        code = self.dex.codes.get(ref)
        if code is None:
            raise VMError("unsupported guest method " + ref)
        self._verify_instructions(code)
        expected, ret = proto_types(method_parts(ref)[2])
        if len(args) != len(expected) or code.ins != len(args) or ret != "V":
            raise VMError("bad method prototype/argument count")
        regs = [None] * code.registers
        if code.ins:
            regs[-code.ins:] = list(args)
        words = code.words
        pc = 0
        steps = 0
        pending = None
        last_invoke = False

        def reg(i: int):
            if i >= len(regs): raise VMError("register out of range")
            return regs[i]

        def word(i: int) -> int:
            if i < 0 or i >= len(words): raise VMError("instruction truncated")
            return words[i]

        def jump(origin: int, delta: int) -> int:
            target = origin + delta
            if target < 0 or target >= len(words):
                raise VMError("branch outside method")
            return target

        while pc < len(words):
            steps += 1
            if steps > self.max_steps: raise VMError("instruction budget exceeded")
            at = pc
            w = word(pc)
            opcode = w & 255
            aa = w >> 8
            if opcode == 0x12:  # const/4 vA, #+B
                a, value = aa & 15, aa >> 4
                if a >= len(regs): raise VMError("const/4 register out of range")
                regs[a] = value - 16 if value & 8 else value
                pc += 1
            elif opcode == 0x13:  # const/16 vAA, #+BBBB
                if aa >= len(regs): raise VMError("const register out of range")
                regs[aa] = signed16(word(pc + 1))
                pc += 2
            elif opcode == 0x1A:  # const-string vAA, string@BBBB
                if aa >= len(regs): raise VMError("string register out of range")
                idx = word(pc + 1)
                if idx >= len(self.dex.strings): raise VMError("string index out of range")
                regs[aa] = self.dex.strings[idx]
                pc += 2
            elif opcode == 0x01:  # move vA, vB
                a, b = (w >> 8) & 15, (w >> 12) & 15
                regs[a] = reg(b)
                pc += 1
            elif opcode == 0x0A:  # move-result vAA
                if not last_invoke or aa >= len(regs):
                    raise VMError("move-result not immediately after invoke")
                regs[aa] = pending
                pc += 1
            elif opcode == 0x28:  # goto +AA, signed eight-bit
                pc = jump(at, aa - 256 if aa & 128 else aa)
            elif opcode == 0x29:  # goto/16
                pc = jump(at, signed16(word(pc + 1)))
            elif opcode in (0x32, 0x33):  # if-eq, if-ne vA,vB,+CCCC
                a, b = (w >> 8) & 15, (w >> 12) & 15
                equal = reg(a) == reg(b)
                take = equal if opcode == 0x32 else not equal
                pc = jump(at, signed16(word(pc + 1))) if take else pc + 2
            elif opcode in (0x38, 0x39):  # if-eqz, if-nez
                value = reg(aa)
                zero = value is None or value == 0
                take = zero if opcode == 0x38 else not zero
                pc = jump(at, signed16(word(pc + 1))) if take else pc + 2
            elif opcode == 0x71:  # invoke-static {vC..vG}, method@BBBB
                count, g = (w >> 12) & 15, (w >> 8) & 15
                if count > 5 or count > code.outs:
                    raise VMError("invalid invoke argument count")
                idx = word(pc + 1)
                if idx >= len(self.dex.method_refs): raise VMError("bad method index")
                rword = word(pc + 2)
                r = [rword & 15, (rword >> 4) & 15, (rword >> 8) & 15,
                     (rword >> 12) & 15, g][:count]
                ref2 = self.dex.method_refs[idx]
                ps, _ = proto_types(method_parts(ref2)[2])
                if count != len(ps): raise VMError("invalid invoke method prototype")
                params = tuple(reg(n) for n in r)
                if ref2.startswith(HOST + "->"):
                    pending = self.host.call(ref2, params)
                else:
                    pending = self._execute(ref2, params, depth + 1)
                pc += 3
            elif opcode == 0x0E:  # return-void
                return None
            else:
                raise VMError("unsupported Dalvik opcode 0x%02x at PC %d" % (opcode, pc))
            last_invoke = opcode == 0x71
        raise VMError("method ended without return")
