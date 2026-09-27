"""Bounds-checked parser for D8's original multi-class Java ME DEX.

Unlike dalvik.dex.Dex (one-class service adapters), this parser indexes fields
and methods of the real MIDlet. dalvik.ui_vm executes the original UI on PC;
dalvik.store_j2me handles the legacy service CLI's StoreState subset.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass


class J2MEDexError(ValueError):
    pass


@dataclass(frozen=True)
class Method:
    owner: str
    name: str
    proto: str
    flags: int
    code_off: int

    @property
    def ref(self):
        return self.owner + "->" + self.name + self.proto


@dataclass(frozen=True)
class Code:
    registers: int
    ins: int
    outs: int
    tries: int
    words: tuple[int, ...]
    handlers: tuple[tuple[int, int, tuple[tuple[str, int], ...]], ...] = ()


class J2MEDex:
    """Bounds-checked index for the v035 DEX produced by pinned D8 8.0.40."""

    def __init__(self, blob: bytes):
        if not isinstance(blob, bytes) or len(blob) < 112 or len(blob) > 4 * 1024 * 1024:
            raise J2MEDexError("invalid converted DEX size")
        self.blob = blob
        if blob[:8] != b"dex\n035\x00":
            raise J2MEDexError("expected DEX-035")
        if struct.unpack_from("<I", blob, 8)[0] != zlib.adler32(blob[12:]) & 0xffffffff:
            raise J2MEDexError("invalid converted DEX checksum")
        if hashlib.sha1(blob[32:]).digest() != blob[12:32]:
            raise J2MEDexError("invalid converted DEX signature")
        (total, header, endian, link_size, link_off, map_off,
         ns, os_, nt, ot, np, op, nf, of, nm, om, nc, oc,
         dsize, doff) = struct.unpack_from("<20I", blob, 32)
        if (total != len(blob) or header != 112 or endian != 0x12345678
                or link_size or link_off or not 0 < nc <= 128
                or dsize != total - doff or not 112 <= doff < total):
            raise J2MEDexError("invalid converted DEX header")
        for label, count, offset, width in (("strings", ns, os_, 4),
                                            ("types", nt, ot, 4),
                                            ("protos", np, op, 12),
                                            ("fields", nf, of, 8),
                                            ("methods", nm, om, 8),
                                            ("classes", nc, oc, 32)):
            # D8 Java classes with no static or instance fields legitimately
            # have field_ids_size == field_ids_off == 0. The original MIDP
            # DEX had fields; do not require an invented field table in APKs.
            if count == 0:
                if label != "fields" or offset != 0:
                    raise J2MEDexError("missing required DEX table")
            elif count > 65536 or offset < 112 or offset + count * width > doff:
                raise J2MEDexError("invalid converted DEX table")
        self.strings = [self.string_at(self.u32(os_ + 4 * i)) for i in range(ns)]
        self.types = [self.strings[self.valid_index(self.u32(ot + 4 * i), ns)]
                      for i in range(nt)]
        self.protos = []
        for i in range(np):
            _, ret, params = struct.unpack_from("<III", blob, op + 12 * i)
            ps = []
            if params:
                count = self.u32(params)
                if count > 256: raise J2MEDexError("invalid parameter list")
                ps = [self.types[self.valid_index(self.u16(params + 4 + 2 * j), nt)]
                      for j in range(count)]
            self.protos.append("(" + "".join(ps) + ")" +
                               self.types[self.valid_index(ret, nt)])
        self.fields = []
        for i in range(nf):
            owner, kind, name = struct.unpack_from("<HHI", blob, of + 8 * i)
            self.fields.append(self.types[self.valid_index(owner, nt)] + "->" +
                               self.strings[self.valid_index(name, ns)] + ":" +
                               self.types[self.valid_index(kind, nt)])
        self.method_refs = []
        for i in range(nm):
            owner, proto, name = struct.unpack_from("<HHI", blob, om + 8 * i)
            self.method_refs.append(self.types[self.valid_index(owner, nt)] + "->" +
                                    self.strings[self.valid_index(name, ns)] +
                                    self.protos[self.valid_index(proto, np)])
        self.classes = {}
        self.methods = {}
        for i in range(nc):
            class_idx, _, super_idx, _, _, _, class_data, _ = \
                struct.unpack_from("<IIIIIIII", blob, oc + 32 * i)
            desc = self.types[self.valid_index(class_idx, nt)]
            if desc in self.classes or not class_data or super_idx >= nt:
                raise J2MEDexError("invalid/duplicate class definition")
            self.classes[desc] = self.types[super_idx]
            self._class_data(desc, class_data)

    def checked(self, offset: int, length: int):
        if offset < 0 or length < 0 or offset + length > len(self.blob):
            raise J2MEDexError("truncated converted DEX")

    @staticmethod
    def valid_index(i: int, limit: int):
        if i >= limit: raise J2MEDexError("invalid DEX index")
        return i

    def u16(self, offset):
        self.checked(offset, 2)
        return struct.unpack_from("<H", self.blob, offset)[0]

    def u32(self, offset):
        self.checked(offset, 4)
        return struct.unpack_from("<I", self.blob, offset)[0]

    def uleb(self, offset):
        value = 0
        for bit in (0, 7, 14, 21, 28):
            self.checked(offset, 1)
            b = self.blob[offset]
            offset += 1
            value |= (b & 127) << bit
            if b < 128:
                return value, offset
        raise J2MEDexError("invalid uleb128")

    def sleb(self, offset):
        value, shift = 0, 0
        for _ in range(5):
            self.checked(offset, 1)
            b=self.blob[offset];offset+=1
            value |= (b&127) << shift
            shift+=7
            if b < 128:
                if (b&64) and shift < 32:value -= 1<<shift
                return value,offset
        raise J2MEDexError("invalid sleb128")

    def string_at(self, offset):
        """Decode DEX Modified UTF-8 as UTF-16 code units, not UTF-8 bytes.

        The encoded NUL is C0 80; supplementary characters occupy TWO
        three-byte surrogate units. An isolated surrogate is legal Java
        String data and is preserved in Python (surrogatepass). Four-byte
        UTF-8, other overlong forms, wrong lengths and missing terminators
        are rejected before any bytecode is executed.
        """
        length, pos = self.uleb(offset)
        if length > 65535: raise J2MEDexError("oversized DEX string")
        units = bytearray()
        for _ in range(length):
            self.checked(pos, 1)
            first = self.blob[pos]
            if 1 <= first <= 0x7f:
                value, width = first, 1
            elif first == 0xc0:
                self.checked(pos, 2)
                if self.blob[pos + 1] != 0x80:
                    raise J2MEDexError("invalid encoded DEX NUL")
                value, width = 0, 2
            elif 0xc2 <= first <= 0xdf:
                self.checked(pos, 2)
                second = self.blob[pos + 1]
                if second & 0xc0 != 0x80:
                    raise J2MEDexError("bad modified UTF-8 continuation")
                value, width = ((first & 31) << 6) | (second & 63), 2
            elif 0xe0 <= first <= 0xef:
                self.checked(pos, 3)
                second, third = self.blob[pos + 1:pos + 3]
                if ((second & 0xc0) != 0x80 or (third & 0xc0) != 0x80 or
                        (first == 0xe0 and second < 0xa0)):
                    raise J2MEDexError("bad modified UTF-8 continuation/overlong")
                value = ((first & 15) << 12) | ((second & 63) << 6) | (third & 63)
                width = 3  # Surrogates are individual UTF-16 units in MUTF-8.
            else:
                raise J2MEDexError("invalid DEX MUTF-8 lead byte")
            units.extend((value & 255, value >> 8))
            pos += width
        self.checked(pos, 1)
        if self.blob[pos] != 0:
            raise J2MEDexError("DEX UTF-16 length/terminator mismatch")
        return units.decode("utf-16-le", "surrogatepass")

    def _class_data(self, desc, pos):
        counts = []
        for _ in range(4):
            count, pos = self.uleb(pos)
            if count > 4096: raise J2MEDexError("class data too large")
            counts.append(count)
        for count in counts[:2]:
            last = 0
            for _ in range(count):
                delta, pos = self.uleb(pos)
                last += delta
                self.valid_index(last, len(self.fields))
                _, pos = self.uleb(pos)
                if not self.fields[last].startswith(desc + "->"):
                    raise J2MEDexError("class field owner mismatch")
        for count in counts[2:]:
            last = 0
            for _ in range(count):
                delta, pos = self.uleb(pos)
                last += delta
                self.valid_index(last, len(self.method_refs))
                flags, pos = self.uleb(pos)
                at, pos = self.uleb(pos)
                ref = self.method_refs[last]
                if not ref.startswith(desc + "->") or ref in self.methods:
                    raise J2MEDexError("class method owner mismatch")
                if at: self.checked(at, 16)
                self.methods[ref] = Method(desc, ref.split("->", 1)[1].split("(", 1)[0],
                                           "(" + ref.split("(", 1)[1], flags, at)

    def code_for(self, ref: str) -> Code:
        method = self.methods.get(ref)
        if not method or not method.code_off:
            raise J2MEDexError("no executable code: " + ref)
        offset = method.code_off
        regs, ins, outs, tries, _, n = struct.unpack_from("<HHHHII", self.blob, offset)
        if not regs or regs > 256 or ins > regs or n > 65535:
            raise J2MEDexError("invalid converted code header")
        self.checked(offset + 16, 2 * n)
        words=struct.unpack_from("<%dH" % n, self.blob, offset + 16)
        handlers=[]
        if tries:
            if tries > 256: raise J2MEDexError("too many exception handlers")
            try_at=offset+16+2*n+(2 if n&1 else 0)
            self.checked(try_at,8*tries)
            encoded=try_at+8*tries
            count,pos=self.uleb(encoded)
            if count>512: raise J2MEDexError("too many encoded catches")
            lists={}
            for _ in range(count):
                at=pos-encoded
                how_many,pos=self.sleb(pos)
                if abs(how_many)>64:raise J2MEDexError("too many typed catches")
                entries=[]
                for _ in range(abs(how_many)):
                    type_idx,pos=self.uleb(pos)
                    addr,pos=self.uleb(pos)
                    if addr>=n:raise J2MEDexError("catch target out of code")
                    entries.append((self.types[self.valid_index(type_idx,len(self.types))],addr))
                if how_many<=0:
                    addr,pos=self.uleb(pos)
                    if addr>=n:raise J2MEDexError("catchall target out of code")
                    entries.append(("*",addr))
                lists[at]=tuple(entries)
            for i in range(tries):
                start,length,handler=struct.unpack_from("<IHH",self.blob,try_at+8*i)
                if not length or start+length>n or handler not in lists:
                    raise J2MEDexError("invalid try range/handler offset")
                handlers.append((start,start+length,lists[handler]))
        return Code(regs,ins,outs,tries,words,tuple(handlers))
