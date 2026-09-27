"""DEX-035 instruction widths and bounded code/payload decoding for Java ME UI.

The opcode layouts are from the Android Dalvik bytecode specification. Unknown
and optimized/odex opcodes are rejected; data payloads are never executed.
"""
from __future__ import annotations


class DecodeError(ValueError):
    pass


ONE = {0x00, 0x01, 0x04, 0x07, *range(0x0a, 0x13), 0x1d, 0x1e,
       0x21, 0x27, 0x28, *range(0x7b, 0x90), *range(0xb0, 0xd0)}
TWO = {0x02, 0x05, 0x08, 0x13, 0x15, 0x16, 0x19, 0x1a, 0x1c,
       0x1f, 0x20, 0x22, 0x23, 0x29, *range(0x2d, 0x3e),
       *range(0x44, 0x6e), *range(0x90, 0xb0), *range(0xd0, 0xe3)}
THREE = {0x03, 0x06, 0x09, 0x14, 0x17, 0x1b, 0x24, 0x25,
         0x26, 0x2a, 0x2b, 0x2c, *range(0x6e, 0x73), *range(0x74, 0x79)}


def signed(n: int, bits: int) -> int:
    return n - (1 << bits) if n >= 1 << (bits - 1) else n


def joined(words, at):
    return words[at] | words[at + 1] << 16


def width(words: tuple[int, ...], pc: int) -> int:
    w = words[pc]
    op = w & 255
    if w == 0x0100:  # packed-switch payload: ident,size,first-key,targets
        if pc + 4 > len(words): raise DecodeError("truncated packed-switch payload")
        n = 4 + 2 * words[pc + 1]
    elif w == 0x0200:  # sparse-switch payload: ident,size,keys,targets
        if pc + 2 > len(words): raise DecodeError("truncated sparse-switch payload")
        n = 2 + 4 * words[pc + 1]
    elif w == 0x0300:  # array payload: ident,element-width,size,values
        if pc + 4 > len(words): raise DecodeError("truncated array-data payload")
        n = 4 + (words[pc + 1] * joined(words, pc + 2) + 1) // 2
    elif op in ONE: n = 1
    elif op in TWO: n = 2
    elif op in THREE: n = 3
    elif op == 0x18: n = 5
    else: raise DecodeError(f"unsupported DEX opcode 0x{op:02x} at pc {pc}")
    if not 0 < n <= 65535 or pc + n > len(words):
        raise DecodeError("truncated or oversized instruction/payload")
    return n


def boundaries(words: tuple[int, ...]) -> tuple[set[int], set[int]]:
    if not words or len(words) > 65535: raise DecodeError("invalid code size")
    starts, payloads, branches = set(), set(), []
    pc = 0
    while pc < len(words):
        w, op = words[pc], words[pc] & 255
        n = width(words, pc)
        starts.add(pc)
        if w in (0x0100, 0x0200, 0x0300):
            payloads.add(pc)
        elif op == 0x28:
            branches.append(pc + signed(w >> 8, 8))
        elif op == 0x29:
            branches.append(pc + signed(words[pc + 1], 16))
        elif op == 0x2a:
            branches.append(pc + signed(joined(words, pc + 1), 32))
        elif 0x32 <= op <= 0x3d:
            branches.append(pc + signed(words[pc + 1], 16))
        elif op in (0x26, 0x2b, 0x2c):
            branches.append(pc + signed(joined(words, pc + 1), 32))
        pc += n
    if any(t not in starts for t in branches):
        raise DecodeError("branch into instruction data or outside method")
    return starts, payloads
