"""Encode a minimal *binary* AndroidManifest.xml (Android ResXMLTree).

No resource references or resources.arsc are used by these private VM apps;
valid string attributes and API-level integer attributes are written directly.
"""
from __future__ import annotations

import struct
from collections import OrderedDict

ANDROID_URI = "http://schemas.android.com/apk/res/android"
ATTR_IDS = {
    "name": 0x01010003,
    "label": 0x01010001,
    "versionCode": 0x0101021B,
    "versionName": 0x0101021C,
    "minSdkVersion": 0x0101020C,
    "targetSdkVersion": 0x01010270,
    "exported": 0x01010010,
}
END = 0xFFFFFFFF


def _len8(n: int) -> bytes:
    if n < 0x80: return bytes((n,))
    if n > 0x7FFF: raise ValueError("string pool entry too long")
    return bytes(((n >> 8) | 0x80, n & 255))


def _chunk(kind: int, header_len: int, body: bytes = b"", header_extra: bytes = b"") -> bytes:
    assert header_len == 8 + len(header_extra)
    return struct.pack("<HHI", kind, header_len, header_len + len(body)) + header_extra + body


class StringPool:
    def __init__(self):
        self.entries: OrderedDict[str, int] = OrderedDict()

    def add(self, text: str) -> int:
        if text not in self.entries:
            self.entries[text] = len(self.entries)
        return self.entries[text]

    def index(self, text: str) -> int:
        return self.entries[text]

    def blob(self) -> bytes:
        data = bytearray()
        offsets = []
        for text in self.entries:
            raw = text.encode("utf-8")
            utf16_size = len(text.encode("utf-16-le")) // 2
            offsets.append(len(data))
            data.extend(_len8(utf16_size) + _len8(len(raw)) + raw + b"\x00")
        data.extend(b"\x00" * (-len(data) % 4))
        start = 28 + 4 * len(offsets)
        extra = struct.pack("<IIIII", len(offsets), 0, 0x100, start, 0)
        body = struct.pack("<%dI" % len(offsets), *offsets) + bytes(data)
        return _chunk(0x0001, 28, body, extra)


def manifest(package: str, label: str, main_class: str,
             permissions: tuple[str, ...] = ()) -> bytes:
    if len(permissions) > 4 or len(set(permissions)) != len(permissions) or any(
            not name.startswith("android.permission.") for name in permissions):
        raise ValueError("unsupported/duplicate manifest permission")
    pool = StringPool()
    for item in ("android", ANDROID_URI, "manifest", "package", "uses-sdk",
                 "uses-permission", "application", "activity", "intent-filter", "action", "category",
                 *ATTR_IDS.keys(), package, label, main_class, "1.0",
                 *permissions, "android.intent.action.MAIN", "android.intent.category.LAUNCHER"):
        pool.add(item)
    idx = pool.index
    uri = idx(ANDROID_URI)

    def node(kind: int, body: bytes) -> bytes:
        return _chunk(kind, 16, body, struct.pack("<II", 0, END))

    def begin(name: str, attrs: list[tuple[str | None, str, str | int]]) -> bytes:
        a = bytearray()
        for namespace, key, value in attrs:
            ns = uri if namespace == "android" else END
            if isinstance(value, bool):
                raw, typ, data = END, 0x12, 0xFFFFFFFF if value else 0  # TYPE_INT_BOOLEAN
            elif isinstance(value, int):
                raw, typ, data = END, 0x10, value  # TYPE_INT_DEC
            else:
                raw = idx(value)
                typ, data = 0x03, raw  # TYPE_STRING
            a.extend(struct.pack("<IIIHBBI", ns, idx(key), raw, 8, 0, typ, data))
        ext = struct.pack("<IIHHHHHH", END, idx(name), 20, 20, len(attrs), 0, 0, 0)
        return node(0x0102, ext + a)

    def end(name: str) -> bytes:
        return node(0x0103, struct.pack("<II", END, idx(name)))

    ns_begin = node(0x0100, struct.pack("<II", idx("android"), uri))
    ns_end = node(0x0101, struct.pack("<II", idx("android"), uri))
    ids = [0] * len(pool.entries)
    for key, res_id in ATTR_IDS.items():
        ids[idx(key)] = res_id
    resource_map = _chunk(0x0180, 8, struct.pack("<%dI" % len(ids), *ids))
    tree = b"".join([
        pool.blob(), resource_map, ns_begin,
        begin("manifest", [(None, "package", package),
                           ("android", "versionCode", 1),
                           ("android", "versionName", "1.0")]),
        begin("uses-sdk", [("android", "minSdkVersion", 17),
                           ("android", "targetSdkVersion", 17)]),
        end("uses-sdk"),
        *(begin("uses-permission", [("android", "name", permission)]) +
          end("uses-permission") for permission in permissions),
        begin("application", [("android", "label", label)]),
        begin("activity", [("android", "name", main_class),
                           ("android", "exported", True)]),
        begin("intent-filter", []),
        begin("action", [("android", "name", "android.intent.action.MAIN")]),
        end("action"),
        begin("category", [("android", "name", "android.intent.category.LAUNCHER")]),
        end("category"),
        end("intent-filter"), end("activity"), end("application"), end("manifest"), ns_end
    ])
    return _chunk(0x0003, 8, tree)
