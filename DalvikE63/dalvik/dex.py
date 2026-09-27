"""Read and validate the DEX-035 parts needed by the first DalvikE63 VM.

No execution of Python source from APKs. Every instruction below is read from
classes.dex and dispatched by vm.py. Unsupported opcodes fail closed.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass


class DexError(ValueError):
    pass


@dataclass
class Code:
    registers: int
    ins: int
    outs: int
    words: tuple[int, ...]


class Dex:
    MAX_FILE = 4 * 1024 * 1024
    MAX_TABLE = 65536

    def __init__(self, blob: bytes):
        if not isinstance(blob, bytes) or len(blob) < 0x70 or len(blob) > self.MAX_FILE:
            raise DexError("invalid DEX size")
        self.blob = blob
        if blob[:8] != b"dex\n035\x00":
            raise DexError("only DEX version 035 is supported")
        if zlib.adler32(blob[12:]) & 0xFFFFFFFF != self.u32(8):
            raise DexError("invalid DEX Adler-32 checksum")
        if hashlib.sha1(blob[32:]).digest() != blob[12:32]:
            raise DexError("invalid DEX SHA-1 signature")
        (total, header, endian, link_size, link_off, map_off,
         nstring, ostr, ntype, otype, nproto, oproto,
         nfield, ofield, nmethod, omethod, nclass, oclass,
         dsize, doff) = struct.unpack_from("<20I", blob, 32)
        if total != len(blob) or header != 0x70 or endian != 0x12345678:
            raise DexError("invalid DEX header")
        if link_size or link_off or nfield or ofield or nclass != 1:
            raise DexError("unsupported DEX linking/fields/classes")
        if dsize != len(blob) - doff or not 0x70 <= doff < len(blob):
            raise DexError("invalid DEX data region")
        for n, off, width in ((nstring, ostr, 4), (ntype, otype, 4),
                              (nproto, oproto, 12), (nmethod, omethod, 8),
                              (nclass, oclass, 32)):
            if n > self.MAX_TABLE or (n and (off < 0x70 or off + n * width > doff)):
                raise DexError("DEX table exceeds header region")
        if map_off < doff or map_off + 4 > len(blob):
            raise DexError("bad DEX map")
        nmap = self.u32(map_off)
        if nmap > 40 or map_off + 4 + 12 * nmap > len(blob):
            raise DexError("bad DEX map count")
        self.map_entries = [struct.unpack_from("<HHII", blob, map_off + 4 + i * 12)
                            for i in range(nmap)]
        if any(unused or count == 0 or offset >= len(blob)
               for _, unused, count, offset in self.map_entries):
            raise DexError("invalid DEX map entry")
        if [x[3] for x in self.map_entries] != sorted(x[3] for x in self.map_entries):
            raise DexError("unordered DEX map")
        self.strings = [self._string(self.u32(ostr + i * 4)) for i in range(nstring)]
        if self.strings != sorted(self.strings, key=lambda s: s.encode("utf-16-be")):
            raise DexError("unordered string_ids")
        self.types = [self._str(self.u32(otype + i * 4)) for i in range(ntype)]
        self.protos = []
        for i in range(nproto):
            short_idx, ret_idx, params_off = struct.unpack_from("<III", blob, oproto + i * 12)
            ret = self._type(ret_idx)
            params = self._type_list(params_off)
            if not self._str(short_idx): raise DexError("empty shorty")
            self.protos.append("(" + "".join(params) + ")" + ret)
        self.method_refs = []
        for i in range(nmethod):
            owner, proto_idx, name_idx = struct.unpack_from("<HHI", blob, omethod + i * 8)
            if proto_idx >= len(self.protos): raise DexError("bad proto index")
            self.method_refs.append(self._type(owner) + "->" + self._str(name_idx)
                                    + self.protos[proto_idx])
        (class_idx, flags, super_idx, ifaces, source, annos, class_data, values) = \
            struct.unpack_from("<IIIIIIII", blob, oclass)
        if flags & 1 != 1 or ifaces or annos or values or super_idx >= ntype:
            raise DexError("invalid or unsupported class definition")
        self.class_desc = self._type(class_idx)
        if source != 0xFFFFFFFF: self._str(source)
        if not doff <= class_data < len(blob): raise DexError("bad class_data offset")
        self.codes = self._read_class_data(class_data)
        if not self.codes: raise DexError("empty class")

    def checked(self, offset: int, length: int) -> None:
        if offset < 0 or length < 0 or offset + length > len(self.blob):
            raise DexError("truncated DEX data")

    def u16(self, offset: int) -> int:
        self.checked(offset, 2)
        return struct.unpack_from("<H", self.blob, offset)[0]

    def u32(self, offset: int) -> int:
        self.checked(offset, 4)
        return struct.unpack_from("<I", self.blob, offset)[0]

    def uleb(self, offset: int) -> tuple[int, int]:
        v = 0
        for shift in (0, 7, 14, 21, 28):
            self.checked(offset, 1)
            b = self.blob[offset]
            offset += 1
            v |= (b & 127) << shift
            if not b & 128:
                if v > 0xFFFFFFFF: raise DexError("oversized uleb128")
                return v, offset
        raise DexError("unterminated uleb128")

    def _string(self, offset: int) -> str:
        length, offset = self.uleb(offset)
        if length > 16000: raise DexError("oversized DEX string")
        self.checked(offset, 1)
        end = self.blob.find(b"\x00", offset, min(len(self.blob), offset + 4 * length + 2))
        if end < 0: raise DexError("unterminated string")
        try:
            s = self.blob[offset:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DexError("unsupported MUTF-8") from exc
        if len(s.encode("utf-16-le")) // 2 != length:
            raise DexError("bad DEX string length")
        return s

    def _str(self, index: int) -> str:
        if index >= len(self.strings): raise DexError("string index out of bounds")
        return self.strings[index]

    def _type(self, index: int) -> str:
        if index >= len(self.types): raise DexError("type index out of bounds")
        return self.types[index]

    def _type_list(self, offset: int) -> list[str]:
        if offset == 0: return []
        if offset % 4: raise DexError("unaligned type_list")
        n = self.u32(offset)
        if n > 255: raise DexError("too many method parameters")
        return [self._type(self.u16(offset + 4 + 2 * i)) for i in range(n)]

    def _read_class_data(self, offset: int) -> dict[str, Code]:
        fields, offset = self.uleb(offset)
        instance, offset = self.uleb(offset)
        direct, offset = self.uleb(offset)
        virtual, offset = self.uleb(offset)
        if fields or instance or virtual or direct > 256:
            raise DexError("unsupported class fields/virtual methods")
        codes = {}
        last_idx = 0
        for _ in range(direct):
            delta, offset = self.uleb(offset)
            flags, offset = self.uleb(offset)
            at, offset = self.uleb(offset)
            last_idx += delta
            if last_idx >= len(self.method_refs) or flags & 0x9 != 0x9 or not at:
                raise DexError("bad method definition")
            ref = self.method_refs[last_idx]
            if not ref.startswith(self.class_desc + "->") or ref in codes:
                raise DexError("class contains an invalid or duplicate method")
            codes[ref] = self._code(at)
        return codes

    def _code(self, offset: int) -> Code:
        if offset % 4: raise DexError("unaligned code_item")
        self.checked(offset, 16)
        registers, ins, outs, tries, debug_off, n = struct.unpack_from("<HHHHII", self.blob, offset)
        if not 0 < registers <= 256 or ins > registers or outs > registers or tries or debug_off or n > 65535:
            raise DexError("unsupported code_item")
        self.checked(offset + 16, n * 2)
        return Code(registers, ins, outs, struct.unpack_from("<%dH" % n, self.blob, offset + 16))
