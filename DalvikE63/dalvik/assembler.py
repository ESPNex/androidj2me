"""Small DEX-035 assembler for the *declared* guest instruction subset.

This is not dx/d8 and never translates arbitrary Java bytecode. App sources in
apps/specs.py are assembled into actual Dalvik instructions in classes.dex.
The interpreter in vm.py reads those bytes, not the Python source files.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from typing import List, Tuple

HOST = "Lorg/e63/dalvik/runtime/Host;"


def uleb(value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError("uleb outside 32 bits")
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        result.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(result)


def align(data: bytearray, n: int = 4) -> None:
    data.extend(b"\x00" * (-len(data) % n))


def proto_types(proto: str) -> Tuple[Tuple[str, ...], str]:
    if not proto.startswith("(") or ")" not in proto:
        raise ValueError("invalid method prototype " + proto)
    end = proto.index(")")
    parts = []
    p = 1
    while p < end:
        begin = p
        while proto[p] == "[":
            p += 1
        if proto[p] == "L":
            p = proto.index(";", p, end) + 1
        else:
            if proto[p] not in "ZBSCIJFD":
                raise ValueError("invalid parameter descriptor")
            p += 1
        parts.append(proto[begin:p])
    ret = proto[end + 1:]
    if not ret or (ret != "V" and ret[0] not in "ZBSCIJFDL["):
        raise ValueError("invalid return descriptor")
    return tuple(parts), ret


def method_parts(ref: str) -> Tuple[str, str, str]:
    owner, rest = ref.split("->", 1)
    i = rest.index("(")
    proto = rest[i:]
    proto_types(proto)
    if not owner.startswith("L") or not owner.endswith(";") or not rest[:i]:
        raise ValueError("invalid method ref: " + ref)
    return owner, rest[:i], proto


def shorty(proto: str) -> str:
    args, ret = proto_types(proto)
    s = lambda t: "L" if t[0] in "L[" else t
    return s(ret) + "".join(s(t) for t in args)


class Asm:
    def __init__(self, registers: int, ins: int = 0):
        if not 0 <= ins <= registers <= 255:
            raise ValueError("bad register count")
        self.registers = registers
        self.ins = ins
        self.ops: list[tuple] = []

    def label(self, name: str): self.ops.append(("label", name)); return self
    def const(self, reg: int, value: int): self.ops.append(("const", reg, value)); return self
    def string(self, reg: int, text: str): self.ops.append(("string", reg, text)); return self
    def move(self, dst: int, src: int): self.ops.append(("move", dst, src)); return self
    def result(self, reg: int): self.ops.append(("result", reg)); return self
    def invoke(self, ref: str, *regs: int): self.ops.append(("invoke", ref, tuple(regs))); return self
    def if_eq(self, a: int, b: int, target: str): self.ops.append(("if_eq", a, b, target)); return self
    def if_ne(self, a: int, b: int, target: str): self.ops.append(("if_ne", a, b, target)); return self
    def if_eqz(self, reg: int, target: str): self.ops.append(("if_eqz", reg, target)); return self
    def if_nez(self, reg: int, target: str): self.ops.append(("if_nez", reg, target)); return self
    def goto(self, target: str): self.ops.append(("goto", target)); return self
    def ret(self): self.ops.append(("return_void",)); return self

    @staticmethod
    def _length(op: tuple) -> int:
        name = op[0]
        if name == "label": return 0
        if name in ("const", "string", "if_eq", "if_ne", "if_eqz", "if_nez", "goto"): return 2
        if name == "invoke": return 3
        if name in ("move", "result", "return_void"): return 1
        raise ValueError("unknown instruction " + name)

    def assemble(self, strings: dict[str, int], methods: dict[str, int]) -> tuple[list[int], int]:
        labels = {}
        pc = 0
        for op in self.ops:
            if op[0] == "label":
                if op[1] in labels: raise ValueError("duplicate label " + op[1])
                labels[op[1]] = pc
            else:
                pc += self._length(op)
        words = []
        outs = 0
        pc = 0
        for op in self.ops:
            name = op[0]
            if name == "label": continue
            if name == "const":
                _, dst, value = op
                if not (0 <= dst <= 255 and -32768 <= value <= 32767):
                    raise ValueError("const/16 operand outside range")
                part = [0x13 | dst << 8, value & 0xFFFF]
            elif name == "string":
                _, dst, text = op
                if dst > 255 or strings[text] > 65535:
                    raise ValueError("const-string operand outside range")
                part = [0x1A | dst << 8, strings[text]]
            elif name == "move":
                _, dst, src = op
                if dst >= 16 or src >= 16: raise ValueError("move register > 15")
                part = [0x01 | dst << 8 | src << 12]
            elif name == "result":
                _, dst = op
                if dst >= 256: raise ValueError("move-result register > 255")
                part = [0x0A | dst << 8]
            elif name in ("if_eq", "if_ne", "if_eqz", "if_nez", "goto"):
                target = labels[op[-1]]
                delta = target - pc
                if delta < -32768 or delta > 32767:
                    raise ValueError("branch too far")
                if name in ("if_eq", "if_ne"):
                    _, a, b, _ = op
                    if a >= 16 or b >= 16: raise ValueError("branch register > 15")
                    part = [(0x32 if name == "if_eq" else 0x33) | a << 8 | b << 12, delta & 0xFFFF]
                elif name in ("if_eqz", "if_nez"):
                    _, a, _ = op
                    if a >= 256: raise ValueError("branch register > 255")
                    part = [(0x38 if name == "if_eqz" else 0x39) | a << 8, delta & 0xFFFF]
                else:
                    part = [0x29, delta & 0xFFFF]  # goto/16
            elif name == "invoke":
                _, ref, regs = op
                if len(regs) > 5 or any(r < 0 or r >= 16 or r >= self.registers for r in regs):
                    raise ValueError("invoke-static accepts at most five nibble registers")
                if len(proto_types(method_parts(ref)[2])[0]) != len(regs):
                    raise ValueError("argument count differs from method prototype: " + ref)
                if methods[ref] > 65535: raise ValueError("method index > 65535")
                padded = list(regs) + [0] * (5 - len(regs))
                c, d, e, f, g = padded
                part = [0x71 | g << 8 | len(regs) << 12, methods[ref],
                        c | d << 4 | e << 8 | f << 12]
                outs = max(outs, len(regs))
            elif name == "return_void":
                part = [0x0E]
            else:
                raise ValueError("unhandled instruction " + name)
            for word in part:
                if not 0 <= word <= 0xFFFF: raise ValueError("invalid code unit")
            words += part
            pc += len(part)
        if not words or words[-1] != 0x0E:
            raise ValueError("method must end in return-void")
        if len(words) > 0xFFFF:
            raise ValueError("method too large")
        return words, outs


@dataclass
class GuestMethod:
    name: str
    proto: str
    asm: Asm


@dataclass
class GuestApp:
    apk_name: str
    package: str
    label: str
    methods: list[GuestMethod]
    system: bool = True
    assets: dict[str, str] | None = None  # ZIP name -> workspace source path

    @property
    def class_desc(self) -> str:
        return "L" + self.package.replace(".", "/") + "/Main;"

    @property
    def main_name(self) -> str:
        return self.package + ".Main"


class DexWriter:
    def __init__(self, app: GuestApp):
        self.app = app

    def build(self) -> bytes:
        cls = self.app.class_desc
        definitions = {cls + "->" + m.name + m.proto: m for m in self.app.methods}
        if len(definitions) != len(self.app.methods):
            raise ValueError("duplicate guest methods")
        refs = set(definitions)
        literal_strings = set()
        for m in self.app.methods:
            args, ret = proto_types(m.proto)
            if ret != "V" or len(args) != m.asm.ins:
                raise ValueError("unsupported guest prototype " + m.proto)
            for op in m.asm.ops:
                if op[0] == "invoke": refs.add(op[1])
                if op[0] == "string": literal_strings.add(op[2])
        types = {cls, "Ljava/lang/Object;"}
        names = {"Main.java"}
        protos = set()
        for ref in refs:
            owner, name, proto = method_parts(ref)
            types.add(owner)
            names.add(name)
            protos.add(proto)
            args, ret = proto_types(proto)
            types.add(ret)
            types.update(args)
            names.add(shorty(proto))
        # DEX requires string_ids ordered by decoded UTF-16 contents. App strings
        # in this milestone are BMP text without embedded NUL.
        string_values = sorted(types | names | literal_strings, key=lambda s: s.encode("utf-16-be"))
        str_idx = {s: i for i, s in enumerate(string_values)}
        type_values = sorted(types, key=lambda s: str_idx[s])
        type_idx = {s: i for i, s in enumerate(type_values)}
        proto_values = sorted(protos, key=lambda s: (type_idx[proto_types(s)[1]],
                                                        tuple(type_idx[t] for t in proto_types(s)[0])))
        proto_idx = {s: i for i, s in enumerate(proto_values)}
        ref_values = sorted(refs, key=lambda r: (type_idx[method_parts(r)[0]],
                                                  str_idx[method_parts(r)[1]],
                                                  proto_idx[method_parts(r)[2]]))
        ref_idx = {s: i for i, s in enumerate(ref_values)}
        if len(string_values) > 65535 or len(ref_values) > 65535:
            raise ValueError("too many strings or methods")
        header_size = 0x70
        string_off = header_size
        type_off = string_off + 4 * len(string_values)
        proto_off = type_off + 4 * len(type_values)
        method_off = proto_off + 12 * len(proto_values)
        class_off = method_off + 8 * len(ref_values)
        data_off = class_off + 32
        data = bytearray(b"\0" * data_off)
        string_offsets = []
        for text in string_values:
            string_offsets.append(len(data))
            if "\x00" in text or any(ord(c) > 0xFFFF for c in text):
                raise ValueError("MUTF-8 supplementary code point or NUL not yet supported")
            encoded = text.encode("utf-8")
            data += uleb(len(text)) + encoded + b"\0"
        align(data)
        type_lists = {}
        for proto in proto_values:
            args, _ = proto_types(proto)
            if args and args not in type_lists:
                type_lists[args] = len(data)
                data += struct.pack("<I", len(args))
                for desc in args:
                    data += struct.pack("<H", type_idx[desc])
                align(data)
        code_offsets = {}
        for ref, method in sorted(definitions.items(), key=lambda item: ref_idx[item[0]]):
            align(data)
            code_offsets[ref] = len(data)
            code, outs = method.asm.assemble(str_idx, ref_idx)
            data += struct.pack("<HHHHII", method.asm.registers, method.asm.ins,
                                outs, 0, 0, len(code))
            data += struct.pack("<%dH" % len(code), *code)
        class_data_off = len(data)
        direct = sorted(definitions, key=lambda r: ref_idx[r])
        data += uleb(0) + uleb(0) + uleb(len(direct)) + uleb(0)
        last = 0
        for ref in direct:
            idx = ref_idx[ref]
            data += uleb(idx - last) + uleb(0x9) + uleb(code_offsets[ref])
            last = idx
        align(data)
        map_off = len(data)
        entries = [
            (0x0000, 1, 0),
            (0x0001, len(string_values), string_off),
            (0x0002, len(type_values), type_off),
            (0x0003, len(proto_values), proto_off),
            (0x0005, len(ref_values), method_off),
            (0x0006, 1, class_off),
            (0x2002, len(string_values), string_offsets[0]),
        ]
        if type_lists:
            entries.append((0x1001, len(type_lists), min(type_lists.values())))
        if code_offsets:
            entries.append((0x2001, len(code_offsets), min(code_offsets.values())))
        entries += [(0x2000, 1, class_data_off), (0x1000, 1, map_off)]
        entries.sort(key=lambda row: row[2])
        data += struct.pack("<I", len(entries))
        for kind, size, offset in entries:
            data += struct.pack("<HHII", kind, 0, size, offset)
        file_size = len(data)
        for i, offset in enumerate(string_offsets):
            struct.pack_into("<I", data, string_off + 4 * i, offset)
        for i, desc in enumerate(type_values):
            struct.pack_into("<I", data, type_off + 4 * i, str_idx[desc])
        for i, proto in enumerate(proto_values):
            args, ret = proto_types(proto)
            struct.pack_into("<III", data, proto_off + 12 * i,
                             str_idx[shorty(proto)], type_idx[ret],
                             type_lists.get(args, 0))
        for i, ref in enumerate(ref_values):
            owner, name, proto = method_parts(ref)
            struct.pack_into("<HHI", data, method_off + 8 * i,
                             type_idx[owner], proto_idx[proto], str_idx[name])
        struct.pack_into("<IIIIIIII", data, class_off,
                         type_idx[cls], 0x11, type_idx["Ljava/lang/Object;"],
                         0, str_idx["Main.java"], 0, class_data_off, 0)
        data[:8] = b"dex\n035\x00"
        struct.pack_into("<20I", data, 32,
                         file_size, 0x70, 0x12345678, 0, 0, map_off,
                         len(string_values), string_off, len(type_values), type_off,
                         len(proto_values), proto_off, 0, 0,
                         len(ref_values), method_off, 1, class_off,
                         file_size - data_off, data_off)
        data[12:32] = hashlib.sha1(data[32:]).digest()
        struct.pack_into("<I", data, 8, zlib.adler32(data[12:]) & 0xFFFFFFFF)
        return bytes(data)
