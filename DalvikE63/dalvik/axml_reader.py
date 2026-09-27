"""Independent reader for the limited Android binary manifest written by axml.py.

This is a parser for validation, not an Android resource implementation. It
rejects unknown/malformed chunks rather than guessing what they contain.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


class AXMLError(ValueError): pass


def _u16(buf: bytes, off: int) -> int:
    if off < 0 or off + 2 > len(buf): raise AXMLError("truncated u16")
    return struct.unpack_from("<H", buf, off)[0]


def _u32(buf: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(buf): raise AXMLError("truncated u32")
    return struct.unpack_from("<I", buf, off)[0]


def _length8(buf: bytes, off: int, limit: int) -> tuple[int, int]:
    if off >= limit: raise AXMLError("truncated string length")
    b = buf[off]
    off += 1
    if b & 0x80:
        if off >= limit: raise AXMLError("truncated string length")
        b = ((b & 0x7F) << 8) | buf[off]
        off += 1
    return b, off


def _length16(buf: bytes, off: int, limit: int) -> tuple[int, int]:
    if off < 0 or off + 2 > limit: raise AXMLError("truncated UTF-16 length")
    first = _u16(buf, off)
    off += 2
    if first & 0x8000:
        if off + 2 > limit: raise AXMLError("truncated UTF-16 length")
        first = ((first & 0x7fff) << 16) | _u16(buf, off)
        off += 2
    return first, off


@dataclass(frozen=True)
class ManifestInfo:
    package: str
    main_class: str
    min_sdk: int
    target_sdk: int
    label: str | int  # an aapt resource ID needs resources.arsc for its text
    permissions: tuple[str, ...] = ()


def inspect(blob: bytes) -> ManifestInfo:
    if len(blob) < 8 or struct.unpack_from("<HHI", blob) != (0x0003, 8, len(blob)):
        raise AXMLError("not a binary Android XML tree")
    strings: list[str] = []
    resource_ids: list[int] = []
    stack: list[str] = []
    namespace_open = False
    seen = set()
    values = {}
    permissions: list[str] = []
    offset = 8
    while offset < len(blob):
        if offset + 8 > len(blob): raise AXMLError("truncated chunk")
        kind, header_size, size = struct.unpack_from("<HHI", blob, offset)
        if header_size < 8 or size < header_size or offset + size > len(blob):
            raise AXMLError("chunk beyond manifest")
        end = offset + size
        if kind == 0x0001:  # StringPool: UTF-8, no styles
            if strings or header_size != 28 or size < 28:
                raise AXMLError("bad/duplicate string pool")
            n, styles, flags, start, style_off = struct.unpack_from("<IIIII", blob, offset + 8)
            if n > 512 or styles or style_off or flags & ~0x100 or 28 + n * 4 > size:
                raise AXMLError("unsupported string pool")
            for i in range(n):
                at = offset + start + _u32(blob, offset + 28 + 4 * i)
                if at >= end: raise AXMLError("string offset outside pool")
                if flags & 0x100:  # our legacy binary XML: compact UTF-8
                    chars, at = _length8(blob, at, end)
                    bytecount, at = _length8(blob, at, end)
                    if at + bytecount + 1 > end or blob[at + bytecount] != 0:
                        raise AXMLError("truncated UTF-8 string")
                    try: s = blob[at:at + bytecount].decode("utf-8")
                    except UnicodeDecodeError as exc: raise AXMLError("bad UTF-8") from exc
                else:  # Android aapt's UTF-16 string pool
                    chars, at = _length16(blob, at, end)
                    if chars > 16000 or at + 2 * chars + 2 > end or _u16(blob, at + 2 * chars) != 0:
                        raise AXMLError("truncated UTF-16 string")
                    try: s = blob[at:at + 2 * chars].decode("utf-16-le")
                    except UnicodeDecodeError as exc: raise AXMLError("bad UTF-16") from exc
                if len(s.encode("utf-16-le")) // 2 != chars: raise AXMLError("bad string length")
                strings.append(s)
        elif kind == 0x0180:  # resource map
            if not strings or resource_ids or (size - header_size) % 4:
                raise AXMLError("bad resource map")
            resource_ids = [_u32(blob, offset + header_size + i * 4)
                            for i in range((size - header_size) // 4)]
        elif kind in (0x0100, 0x0101):  # namespace begin/end
            if header_size != 16 or size != 24 or not strings:
                raise AXMLError("invalid namespace chunk")
            prefix_idx, uri_idx = struct.unpack_from("<II", blob, offset + 16)
            if prefix_idx >= len(strings) or uri_idx >= len(strings) or \
               strings[prefix_idx] != "android" or \
               strings[uri_idx] != "http://schemas.android.com/apk/res/android":
                raise AXMLError("wrong Android namespace")
            if kind == 0x0100:
                if namespace_open or stack: raise AXMLError("duplicate Android namespace")
                namespace_open = True
            else:
                if stack or not namespace_open: raise AXMLError("premature namespace close")
                namespace_open = False
        elif kind in (0x0102, 0x0103):
            if header_size != 16 or not namespace_open or not resource_ids:
                raise AXMLError("XML element outside namespace/resource map")
            ns, name_idx = struct.unpack_from("<II", blob, offset + 16)
            if ns != 0xFFFFFFFF or name_idx >= len(strings):
                raise AXMLError("unknown element name or namespace")
            element = strings[name_idx]
            if kind == 0x0103:
                if size != 24 or not stack or stack.pop() != element:
                    raise AXMLError("bad closing XML element")
            else:
                if size < 36: raise AXMLError("short XML start element")
                attr_start, attr_size, count, id_idx, class_idx, style_idx = \
                    struct.unpack_from("<HHHHHH", blob, offset + 24)
                if attr_start != 20 or attr_size != 20 or count > 12 or \
                   id_idx or class_idx or style_idx or 16 + attr_start + count * 20 > size:
                    raise AXMLError("unsupported attributes layout")
                attrs = {}
                for i in range(count):
                    at = offset + 16 + attr_start + 20 * i
                    ans, a_name, raw, typed_size, res0, kind_value, data = \
                        struct.unpack_from("<IIIHBBI", blob, at)
                    if a_name >= len(strings) or typed_size != 8 or res0 or kind_value not in (1, 3, 0x10, 0x12):
                        raise AXMLError("invalid typed value")
                    namespace = ""
                    if ans != 0xFFFFFFFF:
                        if ans >= len(strings) or strings[ans] != \
                           "http://schemas.android.com/apk/res/android":
                            raise AXMLError("unknown attribute namespace")
                        namespace = "android:"
                    key = namespace + strings[a_name]
                    if key in attrs: raise AXMLError("duplicate attribute")
                    if kind_value == 3:
                        if data >= len(strings) or raw != data: raise AXMLError("bad string value")
                        attrs[key] = strings[data]
                    elif kind_value == 0x12:
                        if raw != 0xFFFFFFFF: raise AXMLError("bad boolean value")
                        attrs[key] = data != 0
                    elif kind_value == 1:  # bounded Android/app resource reference
                        if raw != 0xFFFFFFFF or data == 0:
                            raise AXMLError("bad resource reference")
                        attrs[key] = data
                    else:
                        if raw != 0xFFFFFFFF and not (raw < len(strings) and
                                                      strings[raw] == str(data)):
                            raise AXMLError("bad integer value")
                        attrs[key] = data
                if element in ("manifest", "uses-sdk", "application", "activity"):
                    if element in seen: raise AXMLError("duplicate required element")
                    seen.add(element)
                    values[element] = attrs
                elif element == "uses-permission":
                    name = attrs.get("android:name")
                    if (not isinstance(name, str) or
                            not name.startswith("android.permission.") or
                            len(permissions) >= 4 or name in permissions):
                        raise AXMLError("invalid or duplicate permission")
                    permissions.append(name)
                stack.append(element)
        else:
            raise AXMLError("unknown manifest chunk: 0x%04x" % kind)
        offset = end
    if offset != len(blob) or stack or namespace_open or \
       not {"manifest", "uses-sdk", "application", "activity"}.issubset(seen):
        raise AXMLError("incomplete Android manifest")
    main = values["activity"].get("android:name")
    pack = values["manifest"].get("package")
    if not isinstance(main, str) or not isinstance(pack, str) or \
       values["activity"].get("android:exported") is not True:
        raise AXMLError("invalid activity/package")
    if main.startswith("."): main = pack + main
    return ManifestInfo(pack, main, values["uses-sdk"].get("android:minSdkVersion"),
                        values["uses-sdk"].get("android:targetSdkVersion"),
                        values["application"].get("android:label"), tuple(permissions))
