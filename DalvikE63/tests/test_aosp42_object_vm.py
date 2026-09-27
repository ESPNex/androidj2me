"""Authentic AOSP 4.2.2 Launcher2 object-constructor bytecode, PC gate only.

Fixtures are zlib-compressed, SHA-pinned ORIGINAL classes.dex from local AOSP
builds, not synthetic DEX or a PC replacement for Nokia/Android UI. Target
must additionally verify the whole original APK/JAR and the class indexes.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from tests.test_aosp42_native_boot import BootClass, CALLBACK
from tools.stage_android42_runtime import dex_class_entries, uleb128

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/aosp42_dex"
ITEM = b"Lcom/android/launcher2/ItemInfo;"
DRAG = b"Lcom/android/launcher2/DropTarget$DragObject;"
OBJECT = b"Ljava/lang/Object;"
RECT = b"Landroid/graphics/Rect;"


class Source(ctypes.Structure):
    _fields_ = [("read_at", CALLBACK), ("context", ctypes.c_void_p),
                ("dex_bytes", ctypes.c_size_t)]


class ConstructorArgument(ctypes.Structure):
    _fields_ = [("type_descriptor", ctypes.c_char_p),
                ("bits", ctypes.c_uint64)]


class MemoryReader:
    def __init__(self, data: bytes, fail_at: int | None = None):
        self.data = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        self.size = len(data)
        self.fail_at = fail_at
        self.max_request = self.total_read = 0
        self.cb = CALLBACK(self.read)
        self.source = Source(self.cb, None, self.size)

    def read(self, context, offset, destination, length):
        self.max_request = max(self.max_request, length)
        self.total_read += length
        if (offset + length > self.size or
                self.fail_at is not None and
                offset <= self.fail_at < offset + length):
            return 0
        ctypes.memmove(destination, ctypes.addressof(self.data) + offset, length)
        return 1


def dex_string(data: bytes, index: int) -> str:
    string_table = struct.unpack_from("<I", data, 60)[0]
    at = struct.unpack_from("<I", data, string_table + 4 * index)[0]
    _, at = uleb128(data, at)
    return data[at:data.index(0, at)].decode("utf8")


def code_offset(data: bytes, descriptor: str, method: str) -> int:
    index = dex_class_entries(data).index(descriptor)
    class_table = struct.unpack_from("<I", data, 100)[0]
    at = struct.unpack_from("<I", data, class_table + index * 32 + 24)[0]
    counts = []
    for _ in range(4):
        count, at = uleb128(data, at)
        counts.append(count)
    for count in counts[:2]:
        for _ in range(count):
            _, at = uleb128(data, at)
            _, at = uleb128(data, at)
    method_table = struct.unpack_from("<I", data, 92)[0]
    for count in counts[2:]:
        method_index = 0
        for _ in range(count):
            delta, at = uleb128(data, at)
            _, at = uleb128(data, at)
            code, at = uleb128(data, at)
            method_index += delta
            name_index = struct.unpack_from("<I", data,
                                method_table + method_index * 8 + 4)[0]
            if dex_string(data, name_index) == method:
                return code + 16
    raise AssertionError(f"{descriptor} -> {method} not found")


class AospObjectVmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("gcc"):
            raise unittest.SkipTest("host gcc missing")
        provenance = json.loads((FIXTURE / "provenance.json").read_text())
        if provenance["tag"] != "android-4.2.2_r1.2":
            raise AssertionError("AOSP fixture tag mismatch")
        cls.dex = {}
        for name, record in provenance["files"].items():
            data = zlib.decompress((FIXTURE / record["fixture"]).read_bytes())
            if (len(data), hashlib.sha256(data).hexdigest()) != (
                    record["bytes"], record["sha256"]):
                raise AssertionError("AOSP DEX fixture pin mismatch: " + name)
            cls.dex[name] = data
        cls.temp = tempfile.TemporaryDirectory()
        so = Path(cls.temp.name) / "aosp_object_vm.so"
        subprocess.run(["gcc", "-std=c99", "-pedantic", "-Wall", "-Wextra",
                        "-Werror", "-fPIC", "-shared",
                        str(ROOT / "symbian/runtime/aosp_object_vm.c"),
                        str(ROOT / "symbian/runtime/boot_classpath.c"),
                        "-o", str(so)], check=True)
        cls.lib = ctypes.CDLL(str(so))
        cls.new = cls.lib.e63_object_vm_new
        cls.new.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                           ctypes.POINTER(Source), ctypes.POINTER(BootClass),
                           ctypes.c_char_p,
                           ctypes.POINTER(Source), ctypes.POINTER(BootClass)]
        cls.new.restype = ctypes.c_int
        cls.new_args = cls.lib.e63_object_vm_new_args
        cls.new_args.argtypes = [*cls.new.argtypes,
                                 ctypes.POINTER(ConstructorArgument), ctypes.c_uint]
        cls.new_args.restype = ctypes.c_int
        cls.new_linked = cls.lib.e63_object_vm_new_linked_args
        cls.new_linked.argtypes = [*cls.new.argtypes[:4],
                                   ctypes.POINTER(Source),
                                   ctypes.POINTER(BootClass),
                                   *cls.new.argtypes[4:],
                                   ctypes.POINTER(ConstructorArgument),
                                   ctypes.c_uint]
        cls.new_linked.restype = ctypes.c_int
        cls.field = cls.lib.e63_object_vm_field
        cls.field.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                              ctypes.POINTER(ctypes.c_uint64)]
        cls.field.restype = ctypes.c_int
        cls.heap_field = cls.lib.e63_object_vm_heap_field
        cls.heap_field.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                   ctypes.c_char_p, ctypes.c_char_p,
                                   ctypes.POINTER(ctypes.c_uint64)]
        cls.heap_field.restype = ctypes.c_int
        cls.array_length = cls.lib.e63_object_vm_array_length
        cls.array_length.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                     ctypes.POINTER(ctypes.c_uint32)]
        cls.array_length.restype = ctypes.c_int
        cls.static_ref = cls.lib.e63_object_vm_static_ref
        cls.static_ref.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                   ctypes.c_char_p, ctypes.c_char_p,
                                   ctypes.POINTER(ctypes.c_uint32)]
        cls.static_ref.restype = ctypes.c_int
        cls.ref_type = cls.lib.e63_object_vm_ref_type
        cls.ref_type.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.c_char_p, ctypes.c_size_t]
        cls.ref_type.restype = ctypes.c_int
        cls.call = cls.lib.e63_object_vm_call_void
        cls.call.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        cls.call.restype = ctypes.c_int
        cls.call_args = cls.lib.e63_object_vm_call_void_args
        cls.call_args.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                  ctypes.c_char_p,
                                  ctypes.POINTER(ConstructorArgument),
                                  ctypes.c_uint]
        cls.call_args.restype = ctypes.c_int
        cls.call_int = cls.lib.e63_object_vm_call_int
        cls.call_int.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.c_char_p, ctypes.c_char_p,
                                 ctypes.POINTER(ctypes.c_int32)]
        cls.call_int.restype = ctypes.c_int
        cls.free = cls.lib.e63_object_vm_free
        cls.free.argtypes = [ctypes.c_void_p]
        cls.item = BootClass(0, dex_class_entries(cls.dex["Launcher2"]).index(
            ITEM.decode()))
        cls.drag = BootClass(0, dex_class_entries(cls.dex["Launcher2"]).index(
            DRAG.decode()))
        cls.obj = BootClass(0, dex_class_entries(cls.dex["core"]).index(
            OBJECT.decode()))
        cls.application = BootClass(0, dex_class_entries(cls.dex["Launcher2"]).index(
            "Lcom/android/launcher2/ApplicationInfo;"))
        cls.shortcut = BootClass(0, dex_class_entries(cls.dex["Launcher2"]).index(
            "Lcom/android/launcher2/ShortcutInfo;"))
        cls.folder = BootClass(0, dex_class_entries(cls.dex["Launcher2"]).index(
            "Lcom/android/launcher2/FolderInfo;"))
        cls.widget = BootClass(0, dex_class_entries(cls.dex["Launcher2"]).index(
            "Lcom/android/launcher2/LauncherAppWidgetInfo;"))
        cls.rect = BootClass(4, dex_class_entries(cls.dex["framework"]).index(
            RECT.decode()))
        cls.pair = BootClass(4, dex_class_entries(cls.dex["framework"]).index(
            "Landroid/util/Pair;"))
        cls.point = BootClass(4, dex_class_entries(cls.dex["framework"]).index(
            "Landroid/graphics/Point;"))
        cls.measure_spec = BootClass(4, dex_class_entries(
            cls.dex["framework"]).index("Landroid/view/View$MeasureSpec;"))
        cls.layout_params = BootClass(4, dex_class_entries(
            cls.dex["framework"]).index("Landroid/view/ViewGroup$LayoutParams;"))
        cls.margin_params = BootClass(4, dex_class_entries(
            cls.dex["framework"]).index("Landroid/view/ViewGroup$MarginLayoutParams;"))
        cls.frame_params = BootClass(4, dex_class_entries(
            cls.dex["framework"]).index("Landroid/widget/FrameLayout$LayoutParams;"))
        cls.cell_params = BootClass(0, dex_class_entries(
            cls.dex["Launcher2"]).index("Lcom/android/launcher2/CellLayout$LayoutParams;"))
        cls.binder_class = BootClass(4, dex_class_entries(
            cls.dex["framework"]).index("Landroid/os/Binder;"))
        cls.process_class = BootClass(4, dex_class_entries(
            cls.dex["framework"]).index("Landroid/os/Process;"))
        cls.service_manager = BootClass(4, dex_class_entries(
            cls.dex["framework"]).index("Landroid/os/ServiceManager;"))
        static_so = Path(cls.temp.name) / "boot_method.so"
        subprocess.run(["gcc", "-std=c99", "-pedantic", "-Wall", "-Wextra",
                        "-Werror", "-fPIC", "-shared",
                        str(ROOT / "symbian/runtime/boot_classpath.c"),
                        str(ROOT / "symbian/runtime/boot_method.c"),
                        "-o", str(static_so)], check=True)
        cls.static_lib = ctypes.CDLL(str(static_so))
        cls.static = cls.static_lib.e63_boot_call_static_int
        cls.static.argtypes = [ctypes.POINTER(BootClass), ctypes.c_char_p,
                               ctypes.c_char_p, ctypes.c_char_p,
                               ctypes.POINTER(ctypes.c_int32), ctypes.c_uint,
                               CALLBACK, ctypes.c_void_p, ctypes.c_size_t,
                               ctypes.POINTER(ctypes.c_int32)]
        cls.static.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def construct(self, descriptor=ITEM, located=None, app=None, core=None):
        app = app or MemoryReader(self.dex["Launcher2"])
        core = core or MemoryReader(self.dex["core"])
        value = ctypes.c_void_p()
        rc = self.new(ctypes.byref(value), ctypes.byref(app.source),
                      ctypes.byref(located or self.item), descriptor,
                      ctypes.byref(core.source), ctypes.byref(self.obj))
        return rc, value, app, core

    def construct_with_args(self, descriptor, located, values, app=None,
                            core=None):
        app = app or MemoryReader(self.dex["Launcher2"])
        core = core or MemoryReader(self.dex["core"])
        args = (ConstructorArgument * len(values))(
            *(ConstructorArgument(typ, bits) for typ, bits in values))
        vm = ctypes.c_void_p()
        rc = self.new_args(ctypes.byref(vm), ctypes.byref(app.source),
                           ctypes.byref(located), descriptor,
                           ctypes.byref(core.source), ctypes.byref(self.obj),
                           args, len(values))
        return rc, vm, app, core

    def construct_linked(self, values, app=None, framework=None, core=None,
                         parent=None):
        app = app or MemoryReader(self.dex["Launcher2"])
        framework = framework or MemoryReader(self.dex["framework"])
        core = core or MemoryReader(self.dex["core"])
        args = (ConstructorArgument * len(values))(
            *(ConstructorArgument(typ, bits) for typ, bits in values))
        vm = ctypes.c_void_p()
        rc = self.new_linked(ctypes.byref(vm), ctypes.byref(app.source),
            ctypes.byref(self.cell_params),
            b"Lcom/android/launcher2/CellLayout$LayoutParams;",
            ctypes.byref(framework.source),
            ctypes.byref(parent or self.margin_params),
            ctypes.byref(core.source), ctypes.byref(self.obj),
            args, len(values))
        return rc, vm, app, framework, core

    def get(self, vm, name: bytes, typ: bytes):
        value = ctypes.c_uint64(0xffff)
        rc = self.field(vm, name, typ, ctypes.byref(value))
        return rc, value.value

    def view_measure_spec(self, method: bytes, values: list[int],
                          reader=None):
        reader = reader or MemoryReader(self.dex["framework"])
        args = (ctypes.c_int32 * len(values))(*values)
        result = ctypes.c_int32(99)
        prototype = b"(II)I" if len(values) == 2 else b"(I)I"
        rc = self.static(ctypes.byref(self.measure_spec),
                         b"Landroid/view/View$MeasureSpec;", method,
                         prototype, args, len(values), reader.cb, None,
                         reader.size, ctypes.byref(result))
        return rc, result.value, reader

    def test_view_measure_spec_real_framework_dex_math_not_a_view(self):
        # These are genuine View.MeasureSpec static methods in framework.jar,
        # not a rendered android.view.View or a shim for onMeasure().
        for size, mode, expected in ((240, 0x40000000, 0x400000f0),
                                     (320, -0x80000000, 0x80000140),
                                     (0, 0, 0)):
            with self.subTest(size=size, mode=mode):
                rc, spec, source = self.view_measure_spec(
                    b"makeMeasureSpec", [size, mode])
                self.assertEqual(rc, 0)
                self.assertEqual(spec & 0xffffffff, expected)
                self.assertLessEqual(source.max_request, 268)
                for name, value in ((b"getSize", size),
                                    (b"getMode", mode & 0xffffffff)):
                    rc, result, _ = self.view_measure_spec(name, [spec],
                                                            reader=source)
                    self.assertEqual(rc, 0)
                    self.assertEqual(result & 0xffffffff, value)
        tampered = bytearray(self.dex["framework"])
        at = code_offset(tampered, "Landroid/view/View$MeasureSpec;",
                         "makeMeasureSpec")
        self.assertEqual(tampered[at], 0x90)  # real add-int, not a host mask
        tampered[at] = 0xff
        rc, result, _ = self.view_measure_spec(
            b"makeMeasureSpec", [240, 0x40000000],
            reader=MemoryReader(bytes(tampered)))
        self.assertEqual((rc, result), (-4, 0))

    def test_iteminfo_constructor_and_super_from_two_real_dex_files(self):
        rc, vm, app, core = self.construct()
        self.assertEqual(rc, 0)
        try:
            for name, typ, bits in [
                (b"id", b"J", 0xffffffffffffffff),
                (b"container", b"J", 0xffffffffffffffff),
                (b"screen", b"I", 0xffffffff),
                (b"cellX", b"I", 0xffffffff),
                (b"cellY", b"I", 0xffffffff),
                (b"spanX", b"I", 1), (b"spanY", b"I", 1),
                (b"minSpanX", b"I", 1), (b"minSpanY", b"I", 1),
                (b"itemType", b"I", 0),
                (b"requiresDbUpdate", b"Z", 0),
                (b"title", b"Ljava/lang/CharSequence;", 0),
                (b"dropPos", b"[I", 0),
            ]:
                with self.subTest(name=name):
                    self.assertEqual(self.get(vm, name, typ), (0, bits))
            self.assertEqual(self.call(vm, b"unbind"), 0)
            self.assertEqual(self.get(vm, b"id", b"J"),
                             (0, 0xffffffffffffffff))
            self.assertEqual(self.get(vm, b"id", b"I"), (-3, 0))
            self.assertEqual(self.get(vm, b"unbound", b"I"), (-3, 0))
            self.assertEqual(self.call(vm, b"missing"), -3)
            self.assertEqual(self.call(vm, b"<init>"), -1)
            self.assertEqual(self.call(vm, b"onAddToDatabase"), -3)
        finally:
            self.free(vm)
        for reader in (app, core):
            self.assertLessEqual(reader.max_request, 268)
            self.assertLess(reader.total_read, 80_000)
        self.assertLessEqual(app.size, 32 * 1024 * 1024)

    def test_drag_object_real_ui_gesture_state_not_fake_fields(self):
        rc, vm, _, _ = self.construct(DRAG, self.drag)
        self.assertEqual(rc, 0)
        try:
            for name, typ, bits in (
                (b"x", b"I", 0xffffffff),
                (b"y", b"I", 0xffffffff),
                (b"xOffset", b"I", 0xffffffff),
                (b"yOffset", b"I", 0xffffffff),
                (b"dragComplete", b"Z", 0),
                (b"cancelled", b"Z", 0),
                (b"deferDragViewCleanupPostAnimation", b"Z", 1),
                (b"dragView", b"Lcom/android/launcher2/DragView;", 0),
                (b"postAnimationRunnable", b"Ljava/lang/Runnable;", 0),
            ):
                with self.subTest(name=name):
                    self.assertEqual(self.get(vm, name, typ), (0, bits))
            self.assertEqual(self.call(vm, b"unbind"), -3)
        finally:
            self.free(vm)

    def test_real_launcher_model_subclass_and_inherited_field_resolution(self):
        # These objects form UI-model input, not Views; both constructors
        # invoke the genuine ItemInfo.<init> in Launcher2 and Object.<init>
        # in core.jar. dx field_ids for itemType name the CHILD, while the
        # actual field storage is declared in ItemInfo. No host field alias.
        for descriptor, located in (
                (b"Lcom/android/launcher2/ApplicationInfo;", self.application),
                (b"Lcom/android/launcher2/ShortcutInfo;", self.shortcut)):
            with self.subTest(descriptor=descriptor):
                rc, vm, app, core = self.construct(descriptor, located)
                self.assertEqual(rc, 0)
                try:
                    self.assertEqual(self.get(vm, b"id", b"J"),
                                     (0, 0xffffffffffffffff))
                    self.assertEqual(self.get(vm, b"container", b"J"),
                                     (0, 0xffffffffffffffff))
                    self.assertEqual(self.get(vm, b"spanX", b"I"), (0, 1))
                    self.assertEqual(self.get(vm, b"itemType", b"I"), (0, 1))
                    self.assertEqual(self.call(vm, b"unbind"), 0)  # inherited
                    if located.class_def_index == self.application.class_def_index:
                        self.assertEqual(self.get(vm, b"flags", b"I"), (0, 0))
                finally:
                    self.free(vm)
                self.assertLessEqual(app.max_request, 268)
                self.assertLessEqual(core.max_request, 268)
                self.assertLess(app.total_read, 100_000)

    def test_parameterized_real_widget_model_constructor_and_prototype(self):
        # Real UI data object, NOT a running AppWidgetHostView. The second
        # Java argument is an honest typed null reference, never a fake
        # ComponentName object on the Nokia host.
        descriptor = b"Lcom/android/launcher2/LauncherAppWidgetInfo;"
        args = [(b"I", 37), (b"Landroid/content/ComponentName;", 0)]
        rc, vm, app, core = self.construct_with_args(descriptor,
                                                      self.widget, args)
        self.assertEqual(rc, 0)
        try:
            for name, typ, bits in (
                (b"id", b"J", 0xffffffffffffffff),
                (b"appWidgetId", b"I", 37),
                (b"itemType", b"I", 4),
                (b"providerName", b"Landroid/content/ComponentName;", 0),
                (b"hostView", b"Landroid/appwidget/AppWidgetHostView;", 0),
                (b"spanX", b"I", 0xffffffff),
                (b"spanY", b"I", 0xffffffff),
                (b"minWidth", b"I", 0xffffffff),
                (b"minHeight", b"I", 0xffffffff),
            ):
                with self.subTest(name=name):
                    self.assertEqual(self.get(vm, name, typ), (0, bits))
            # Genuine overridden unbind executes invoke-super to the real
            # ItemInfo.unbind DEX method, then clears hostView in widget DEX.
            self.assertEqual(self.call(vm, b"unbind"), 0)
            self.assertEqual(self.get(vm, b"hostView",
                       b"Landroid/appwidget/AppWidgetHostView;"), (0, 0))
            self.assertEqual(self.get(vm, b"appWidgetId", b"I"), (0, 37))
        finally:
            self.free(vm)
        self.assertLessEqual(app.max_request, 268)
        self.assertLessEqual(core.max_request, 268)
        for bad_args in (
                [(b"Z", 37), args[1]],
                [(b"I", 37), (b"Ljava/lang/String;", 0)],
                [(b"I", 37), (b"Landroid/content/ComponentName;", 1)],
                [(b"I", 37)],
                [(b"I", 37), args[1], (b"I", 5)]):
            with self.subTest(bad_args=bad_args):
                rc, absent, _, _ = self.construct_with_args(
                    descriptor, self.widget, bad_args)
                self.assertNotEqual(rc, 0)
                self.assertFalse(absent.value)

    def test_real_folder_constructs_two_core_arraylists_and_emptyarray_clinit(self):
        rc, vm, app, core = self.construct(
            b"Lcom/android/launcher2/FolderInfo;", self.folder)
        self.assertEqual(rc, 0)
        try:
            self.assertEqual(self.get(vm, b"itemType", b"I"), (0, 2))
            self.assertEqual(self.get(vm, b"id", b"J"),
                             (0, 0xffffffffffffffff))
            first = self.get(vm, b"contents", b"Ljava/util/ArrayList;")
            second = self.get(vm, b"listeners", b"Ljava/util/ArrayList;")
            self.assertEqual(first[0], second[0], 0)
            self.assertTrue(first[1] > 1 and second[1] > 1)
            self.assertNotEqual(first[1], second[1])
            arrays = []
            for ref in (first[1], second[1]):
                size = ctypes.c_uint64(999)
                self.assertEqual(self.heap_field(vm, ref, b"size", b"I",
                                                 ctypes.byref(size)), 0)
                self.assertEqual(size.value, 0)
                mod_count = ctypes.c_uint64(999)
                self.assertEqual(self.heap_field(vm, ref, b"modCount", b"I",
                                                 ctypes.byref(mod_count)), 0)
                self.assertEqual(mod_count.value, 0)
                array = ctypes.c_uint64(0)
                self.assertEqual(self.heap_field(vm, ref, b"array",
                                      b"[Ljava/lang/Object;",
                                      ctypes.byref(array)), 0)
                self.assertGreater(array.value, 0)
                arrays.append(array.value)
                length = ctypes.c_uint32(123)
                self.assertEqual(self.array_length(vm, array.value,
                                                    ctypes.byref(length)), 0)
                self.assertEqual(length.value, 0)
            # Both instances read the ONE static EmptyArray.OBJECT that was
            # initialized by actual core.jar <clinit> bytecode, not malloc(0).
            self.assertEqual(arrays[0], arrays[1])
            singleton = ctypes.c_uint32(0)
            self.assertEqual(self.static_ref(vm,
                b"Llibcore/util/EmptyArray;", b"OBJECT",
                b"[Ljava/lang/Object;", ctypes.byref(singleton)), 0)
            self.assertEqual(singleton.value, arrays[0])
            array_type = ctypes.create_string_buffer(256)
            self.assertEqual(self.ref_type(vm, singleton.value,array_type,
                                            len(array_type)), 0)
            self.assertEqual(array_type.value, b"[Ljava/lang/Object;")
            invalid = ctypes.c_uint32(99)
            self.assertEqual(self.array_length(vm, first[1],
                                                ctypes.byref(invalid)), -1)
            self.assertEqual(invalid.value, 0)
            self.assertEqual(self.array_length(vm, 0,
                                                ctypes.byref(invalid)), -1)
            for invalid_ref in (0, 999, arrays[0]):
                reject = ctypes.c_uint64(99)
                self.assertEqual(self.heap_field(vm, invalid_ref, b"size",
                                  b"I", ctypes.byref(reject)), -1)
                self.assertEqual(reject.value, 0)
            # Real FolderInfo.unbind invokes ItemInfo.unbind and then
            # virtual ArrayList.clear on listeners. The authentic empty-list
            # branch skips Arrays.fill; no native List.clear substitution.
            self.assertEqual(self.call(vm, b"unbind"), 0)
            self.assertEqual(self.call(vm, b"unbind"), 0)
            for ref in (first[1], second[1]):
                for name in (b"size", b"modCount"):
                    value = ctypes.c_uint64(99)
                    self.assertEqual(self.heap_field(vm, ref, name, b"I",
                                                   ctypes.byref(value)), 0)
                    self.assertEqual(value.value, 0)
                # Execute real core.jar virtual methods, not native field
                # getters: size returns I; isEmpty branches and returns Z.
                for name, typ, expected in ((b"size", b"I", 0),
                                             (b"isEmpty", b"Z", 1)):
                    value = ctypes.c_int32(99)
                    self.assertEqual(self.call_int(vm, ref, name, typ,
                                                    ctypes.byref(value)), 0)
                    self.assertEqual(value.value, expected)
            invalid_return = ctypes.c_int32(99)
            self.assertEqual(self.call_int(vm, first[1], b"size", b"Z",
                                            ctypes.byref(invalid_return)), -3)
            self.assertEqual(invalid_return.value, 0)
            self.assertEqual(self.call_int(vm, arrays[0], b"size", b"I",
                                            ctypes.byref(invalid_return)), -1)
            self.assertEqual(self.get(vm, b"itemType", b"I"), (0, 2))
        finally:
            self.free(vm)
        self.assertLessEqual(app.max_request, 268)
        self.assertLessEqual(core.max_request, 268)
        self.assertLess(app.total_read, 100_000)
        self.assertLess(core.total_read, 300_000)

    def test_real_core_boolean_return_is_interpreted_and_branch_checked(self):
        original = self.dex["core"]
        at = code_offset(original, "Ljava/util/ArrayList;", "isEmpty")
        self.assertEqual(original[at + 4 * 2], 0x12)
        for offset, expected in ((4, (0, 0)), (3, (-2, 0)),
                                 (-1, (-7, 0))):
            # No true target would ever accept this altered core DEX. The
            # test bypasses SHA so the VM's bytecode semantics are observable.
            with self.subTest(offset=offset):
                altered = bytearray(original)
                if offset == 4:
                    struct.pack_into("<H", altered, at + 4 * 2, 0x0012)
                    # const/4 v0, 0 instead of 1 in the real isEmpty branch
                elif offset == 3:
                    struct.pack_into("<H", altered, at + 3 * 2, 1)
                    # if-nez jumps into its own middle operand -> reject
                else:
                    struct.pack_into("<H", altered, at + 2 * 2, 0x0038)
                    struct.pack_into("<H", altered, at + 7 * 2, 0xff28)
                    # empty-list if-eqz jumps to goto -1: bounded loop
                rc, vm, app, core = self.construct(
                    b"Lcom/android/launcher2/FolderInfo;", self.folder,
                    core=MemoryReader(bytes(altered)))
                self.assertEqual(rc, 0)
                try:
                    listeners = self.get(vm, b"listeners",
                                         b"Ljava/util/ArrayList;")[1]
                    value = ctypes.c_int32(99)
                    self.assertEqual(self.call_int(vm, listeners, b"isEmpty",
                                       b"Z", ctypes.byref(value)), expected[0])
                    self.assertEqual(value.value, expected[1])
                    self.assertEqual(self.get(vm, b"itemType", b"I"), (0, 2))
                finally:
                    self.free(vm)

    def test_real_virtual_clear_branch_and_rollback_of_unsupported_static(self):
        # This core DEX is deliberately tampered AFTER its pin would reject
        # it on the target. It demonstrates we interpret the actual changed
        # ArrayList.clear bytecode rather than substituting a native clear.
        descriptor = b"Lcom/android/launcher2/FolderInfo;"
        original = self.dex["core"]
        at = code_offset(original, "Ljava/util/ArrayList;", "clear")
        self.assertEqual(original[at + 3 * 2], 0x38)  # if-eqz v0, +18
        self.assertEqual(original[at + 4 * 2], 18)
        altered = bytearray(original)
        struct.pack_into("<H", altered, at + 4 * 2, 10)
        rc, vm, app, core = self.construct(descriptor, self.folder,
                                            core=MemoryReader(bytes(altered)))
        self.assertEqual(rc, 0)
        try:
            listeners = self.get(vm, b"listeners", b"Ljava/util/ArrayList;")[1]
            contents = self.get(vm, b"contents", b"Ljava/util/ArrayList;")[1]
            self.assertEqual(self.call(vm, b"unbind"), 0)
            changed = ctypes.c_uint64(99)
            self.assertEqual(self.heap_field(vm, listeners, b"modCount", b"I",
                                             ctypes.byref(changed)), 0)
            self.assertEqual(changed.value, 1)  # genuine modified DEX iput
            intact = ctypes.c_uint64(99)
            self.assertEqual(self.heap_field(vm, contents, b"modCount", b"I",
                                             ctypes.byref(intact)), 0)
            self.assertEqual(intact.value, 0)
        finally:
            self.free(vm)

        for offset, expected in ((2, -4), (3, -2)):
            with self.subTest(offset=offset):
                altered = bytearray(original)
                struct.pack_into("<H", altered, at + 4 * 2, offset)
                rc, vm, app, core = self.construct(
                    descriptor, self.folder, core=MemoryReader(bytes(altered)))
                self.assertEqual(rc, 0)
                try:
                    listeners = self.get(vm, b"listeners",
                                         b"Ljava/util/ArrayList;")[1]
                    self.assertEqual(self.call(vm, b"unbind"), expected)
                    self.assertEqual(self.call(vm, b"unbind"), expected)
                    intact = ctypes.c_uint64(99)
                    self.assertEqual(self.heap_field(vm, listeners,
                                  b"modCount", b"I", ctypes.byref(intact)), 0)
                    self.assertEqual(intact.value, 0)
                finally:
                    self.free(vm)

    def test_reject_modified_real_emptyarray_class_initializer(self):
        # SHA would reject this changed DEX BEFORE the VM. Bypassing the
        # caller trust gate here separately checks that <clinit> is *read*
        # from core.jar and never treated as an empty native helper.
        bad = bytearray(self.dex["core"])
        at = code_offset(bad, "Llibcore/util/EmptyArray;", "<clinit>")
        self.assertEqual(bad[at], 0x12)
        bad[at] = 0xff
        rc, vm, _, _ = self.construct(
            b"Lcom/android/launcher2/FolderInfo;", self.folder,
            core=MemoryReader(bytes(bad)))
        self.assertEqual(rc, -4)
        self.assertFalse(vm.value)

    def test_framework_point_executes_creator_class_initializer_and_ctor(self):
        # Point.<clinit> in authentic framework.jar constructs Point$1, whose
        # real DEX implements Parcelable.Creator and invokes core Object.
        # No C++ Parcelable or UI shim supplies this field/instance.
        descriptor = b"Landroid/graphics/Point;"
        rc, vm, app, core = self.construct_with_args(
            descriptor, self.point, [(b"I", 240), (b"I", 320)],
            app=MemoryReader(self.dex["framework"]))
        self.assertEqual(rc, 0)
        try:
            self.assertEqual(self.get(vm, b"x", b"I"), (0, 240))
            self.assertEqual(self.get(vm, b"y", b"I"), (0, 320))
            creator = ctypes.c_uint32(0)
            self.assertEqual(self.static_ref(vm, descriptor, b"CREATOR",
                             b"Landroid/os/Parcelable$Creator;",
                             ctypes.byref(creator)), 0)
            self.assertGreater(creator.value, 1)
            typ = ctypes.create_string_buffer(256)
            self.assertEqual(self.ref_type(vm, creator.value,
                                            typ, len(typ)), 0)
            self.assertEqual(typ.value, b"Landroid/graphics/Point$1;")
            self.assertEqual(self.array_length(vm, creator.value,
                                    ctypes.byref(ctypes.c_uint32(99))), -1)
            absent = ctypes.c_uint32(99)
            self.assertEqual(self.static_ref(vm, descriptor, b"CREATOR",
                             b"Ljava/lang/Object;",
                             ctypes.byref(absent)), -3)
            self.assertEqual(absent.value, 0)
        finally:
            self.free(vm)
        self.assertLess(app.total_read, 150_000)
        self.assertLess(core.total_read, 90_000)
        original = self.dex["framework"]
        for modified, label, expected in (
                (code_offset(original, descriptor.decode(), "<clinit>"),
                 "clinit", -4),
                (code_offset(original, "Landroid/graphics/Point$1;",
                             "<init>"), "creator_ctor", -4)):
            with self.subTest(label=label):
                tampered = bytearray(original)
                tampered[modified] = 0xff
                rc, missing, app, core = self.construct(
                    descriptor, self.point,
                    app=MemoryReader(bytes(tampered)))
                self.assertEqual(rc, expected)
                self.assertFalse(missing.value)
        # If the genuine Point$1 implements no Parcelable.Creator, storing
        # it into the interface-typed field must fail, not be silently cast.
        tampered = bytearray(original)
        row = struct.unpack_from("<I", tampered, 100)[0] + 32 * \
            dex_class_entries(tampered).index("Landroid/graphics/Point$1;")
        self.assertNotEqual(struct.unpack_from("<I", tampered, row + 12)[0], 0)
        struct.pack_into("<I", tampered, row + 12, 0)
        rc, missing, app, core = self.construct(
            descriptor, self.point, app=MemoryReader(bytes(tampered)))
        self.assertEqual(rc, -2)
        self.assertFalse(missing.value)
        # A forged Point$1 -> Point superclass would recurse back into the
        # already INITIALIZING Point, so detect it instead of overflowing the
        # host/Nokia stack. Original signed DEX would reject this alteration.
        tampered = bytearray(original)
        point_type = struct.unpack_from("<I", tampered,
            struct.unpack_from("<I", tampered, 100)[0] +
            32 * self.point.class_def_index)[0]
        struct.pack_into("<I", tampered, row + 8, point_type)
        rc, missing, app, core = self.construct(
            descriptor, self.point, app=MemoryReader(bytes(tampered)))
        self.assertEqual(rc, -4)
        self.assertFalse(missing.value)

    def test_framework_point_set_offset_hashcode_execute_real_methods(self):
        # Stateful Java methods and integer math from the signed framework
        # DEX, without a host implementation of Point or rendering a View.
        point = b"Landroid/graphics/Point;"
        rc, vm, app, core = self.construct_with_args(point, self.point,
            [(b"I", 240), (b"I", 320)],
            app=MemoryReader(self.dex["framework"]))
        self.assertEqual(rc, 0)
        try:
            args = (ConstructorArgument * 2)(
                ConstructorArgument(b"I", 100), ConstructorArgument(b"I", 200))
            self.assertEqual(self.call_args(vm, 0, b"set", args, 2), 0)
            self.assertEqual(self.get(vm, b"x", b"I"), (0, 100))
            self.assertEqual(self.get(vm, b"y", b"I"), (0, 200))
            args = (ConstructorArgument * 2)(
                ConstructorArgument(b"I", 10),
                ConstructorArgument(b"I", (-20) & 0xffffffff))
            self.assertEqual(self.call_args(vm, 0, b"offset", args, 2), 0)
            self.assertEqual(self.get(vm, b"x", b"I"), (0, 110))
            self.assertEqual(self.get(vm, b"y", b"I"), (0, 180))
            result = ctypes.c_int32(-1)
            self.assertEqual(self.call_int(vm, 0, b"hashCode", b"I",
                                            ctypes.byref(result)), 0)
            self.assertEqual(result.value, 110 * 31 + 180)
            # The DEX prototype rejects a long masquerading as an int and
            # leaves all genuine object fields unchanged.
            args[1].type_descriptor = b"J"
            self.assertNotEqual(self.call_args(vm, 0, b"offset", args, 2), 0)
            self.assertEqual(self.get(vm, b"y", b"I"), (0, 180))
        finally:
            self.free(vm)
        self.assertLess(app.max_request, 268)
        bad = bytearray(self.dex["framework"])
        offset = code_offset(bad, point.decode(), "offset")
        self.assertEqual(bad[offset + 4], 0xb0)
        bad[offset + 4] = 0xff  # only in a host test; target SHA rejects it
        rc, vm, _, _ = self.construct_with_args(point, self.point,
            [(b"I", 240), (b"I", 320)], app=MemoryReader(bytes(bad)))
        self.assertEqual(rc, 0)
        try:
            args = (ConstructorArgument * 2)(
                ConstructorArgument(b"I", 10), ConstructorArgument(b"I", 20))
            self.assertEqual(self.call_args(vm, 0, b"offset", args, 2), -4)
            self.assertEqual(self.get(vm, b"x", b"I"), (0, 240))
            self.assertEqual(self.get(vm, b"y", b"I"), (0, 320))
        finally:
            self.free(vm)

    def test_real_viewgroup_layoutparams_parameterized_constructor(self):
        # Real Android ViewGroup.LayoutParams(II) calls its actual core
        # Object.<init> and writes width/height in framework.jar bytecode.
        # This is a Java layout DATA object, not a View or Android renderer.
        desc = b"Landroid/view/ViewGroup$LayoutParams;"
        params = [(b"I", 240), (b"I", 320)]
        rc, vm, app, core = self.construct_with_args(
            desc, self.layout_params, params,
            app=MemoryReader(self.dex["framework"]))
        self.assertEqual(rc, 0)
        try:
            self.assertEqual(self.get(vm, b"width", b"I"), (0, 240))
            self.assertEqual(self.get(vm, b"height", b"I"), (0, 320))
        finally:
            self.free(vm)
        self.assertLessEqual(app.max_request, 268)
        self.assertLessEqual(core.max_request, 268)
        # Its actual core Object constructor is required, never replaced by
        # a host stub. Altered DEX would fail the signed target's SHA gate.
        broken_core = bytearray(self.dex["core"])
        object_ctor = code_offset(broken_core, OBJECT.decode(), "<init>")
        self.assertEqual(broken_core[object_ctor], 0x0e)
        broken_core[object_ctor] = 0xff
        rc, missing, _, _ = self.construct_with_args(
            desc, self.layout_params, params,
            app=MemoryReader(self.dex["framework"]),
            core=MemoryReader(bytes(broken_core)))
        self.assertEqual(rc, -4)
        self.assertFalse(missing.value)

    def test_real_frame_layout_params_ancestors_and_static_int_dex(self):
        # Actual AOSP UI *layout data*: FrameLayout.LayoutParams(II) invokes
        # MarginLayoutParams(II), which invokes LayoutParams(II), then core
        # Object.<init>. MarginLayoutParams.<clinit> must assign the static
        # int DEFAULT_RELATIVE read by the constructor; not host defaults.
        framework = self.dex["framework"]
        args = [(b"I", 240), (b"I", 320)]
        for desc, cls in ((b"Landroid/view/ViewGroup$MarginLayoutParams;",
                           self.margin_params),
                          (b"Landroid/widget/FrameLayout$LayoutParams;",
                           self.frame_params)):
            with self.subTest(desc=desc):
                rc, vm, app, core = self.construct_with_args(
                    desc, cls, args, app=MemoryReader(framework))
                self.assertEqual(rc, 0)
                try:
                    self.assertEqual(self.get(vm, b"width", b"I"), (0, 240))
                    self.assertEqual(self.get(vm, b"height", b"I"), (0, 320))
                    self.assertEqual(self.get(vm, b"startMargin", b"I"),
                                     (0, 0x80000000))
                    self.assertEqual(self.get(vm, b"endMargin", b"I"),
                                     (0, 0x80000000))
                    self.assertEqual(self.get(vm, b"layoutDirection", b"I"),
                                     (0, 0xffffffff))
                    if cls is self.frame_params:
                        self.assertEqual(self.get(vm, b"gravity", b"I"),
                                         (0, 0xffffffff))
                finally:
                    self.free(vm)
                self.assertLessEqual(app.max_request, 268)
                self.assertLessEqual(core.max_request, 268)
        # A changed <clinit> must be executed/validated, not replaced by -1.
        bad = bytearray(framework)
        at = code_offset(bad,
            "Landroid/view/ViewGroup$MarginLayoutParams;", "<clinit>")
        self.assertEqual(bad[at:at + 2], b"\x12\xf0")
        bad[at + 1] = 0x00  # host mutation: const/4 -1 becomes 0
        rc, altered, _, _ = self.construct_with_args(
            b"Landroid/widget/FrameLayout$LayoutParams;",
            self.frame_params, args, app=MemoryReader(bytes(bad)))
        self.assertEqual(rc, 0)
        try:
            self.assertEqual(self.get(altered, b"layoutDirection", b"I"),
                             (0, 0))
        finally:
            self.free(altered)
        bad[at] = 0xff  # signed target SHA pin rejects even before the VM
        rc, missing, _, _ = self.construct_with_args(
            b"Landroid/widget/FrameLayout$LayoutParams;",
            self.frame_params, args, app=MemoryReader(bytes(bad)))
        self.assertEqual(rc, -4)
        self.assertFalse(missing.value)
        # A forged invoke-direct register count must not turn the real
        # MarginLayoutParams(II) call into a fake no-op parent invocation.
        bad = bytearray(framework)
        ctor = code_offset(bad, "Landroid/widget/FrameLayout$LayoutParams;",
                           "<init>")
        self.assertEqual(bad[ctor:ctor+2], b"\x70\x30")
        bad[ctor+1] = 0x20
        rc, missing, _, _ = self.construct_with_args(
            b"Landroid/widget/FrameLayout$LayoutParams;",
            self.frame_params, args, app=MemoryReader(bytes(bad)))
        self.assertEqual(rc, -2)
        self.assertFalse(missing.value)

    def test_real_launcher_cell_layout_params_links_app_framework_core(self):
        # Launcher2.CellLayout$LayoutParams(IIII) is genuine UI layout DATA,
        # defined in a signed app APK. It extends a separately built
        # framework.jar MarginLayoutParams -> LayoutParams -> core Object.
        # Numeric type_id/field_id ranges overlap across all three DEXes:
        # resolving those as one global ID would be a false Java object.
        args = [(b"I", 1), (b"I", 2), (b"I", 3), (b"I", 4)]
        rc, vm, app, framework, core = self.construct_linked(args)
        self.assertEqual(rc, 0)
        try:
            for field, expected in ((b"cellX", 1), (b"cellY", 2),
                                    (b"cellHSpan", 3), (b"cellVSpan", 4),
                                    (b"width", 0xffffffff),
                                    (b"height", 0xffffffff),
                                    (b"layoutDirection", 0xffffffff),
                                    (b"startMargin", 0x80000000),
                                    (b"endMargin", 0x80000000)):
                self.assertEqual(self.get(vm, field, b"I"), (0, expected),
                                 field)
            self.assertEqual(self.get(vm, b"canReorder", b"Z"), (0, 1))
            # Invoke genuine inherited framework.jar Java bytecode on an APK
            # instance, rather than replacing layout fields in native code.
            margins = (ConstructorArgument * 4)(
                *(ConstructorArgument(b"I", n) for n in (11, 12, 13, 14)))
            self.assertEqual(self.call_args(vm, 0, b"setMargins", margins, 4), 0)
            for field, expected in ((b"leftMargin", 11),
                                    (b"topMargin", 12),
                                    (b"rightMargin", 13),
                                    (b"bottomMargin", 14),
                                    (b"initialLeftMargin", 11),
                                    (b"initialRightMargin", 13),
                                    (b"startMargin", 0x80000000),
                                    (b"endMargin", 0x80000000)):
                self.assertEqual(self.get(vm, field, b"I"), (0, expected),
                                 field)
        finally:
            self.free(vm)
        for image in (app, framework, core):
            self.assertLessEqual(image.max_request, 268)
        # Pinned class row MUST be the actual immediate superclass. The
        # source images are themselves SHA-authenticated by the target caller.
        rc, missing, _, _, _ = self.construct_linked(
            args, parent=self.layout_params)
        self.assertEqual(rc, -2)
        self.assertFalse(missing.value)
        bad = bytearray(self.dex["framework"])
        code = code_offset(bad,
            "Landroid/view/ViewGroup$MarginLayoutParams;", "<clinit>")
        bad[code] = 0xff
        rc, missing, _, _, _ = self.construct_linked(
            args, framework=MemoryReader(bytes(bad)))
        self.assertEqual(rc, -4)
        self.assertFalse(missing.value)
        rc, missing, _, _, _ = self.construct_linked(
            args, framework=MemoryReader(self.dex["Launcher2"]))
        self.assertNotEqual(rc, 0)
        self.assertFalse(missing.value)

    def test_real_process_mypid_is_native_not_fabricated(self):
        # Android 4.2 declares myPid()I ACC_NATIVE with NO code_item in
        # framework.jar. A host PID is NOT a substitute for target JNI.
        reader = MemoryReader(self.dex["framework"])
        result = ctypes.c_int32(99)
        status = self.static(ctypes.byref(self.process_class),
            b"Landroid/os/Process;", b"myPid", b"()I",
            None, 0, reader.cb, None, reader.size, ctypes.byref(result))
        self.assertEqual((status, result.value), (-4, 0))
        self.assertLessEqual(reader.max_request, 268)

    def test_binder_and_service_manager_native_barriers_fail_closed(self):
        # These are *real* AOSP DEX, not fake Binder/ServiceManager instances.
        # Binder.<init> reaches native Binder.init(): without a real JNI
        # runtime, native binder transport/Parcel and service process, even
        # an empty Binder Java object is not constructible. ServiceManager's
        # actual <clinit> similarly needs unsupported HashMap/IPC semantics.
        for descriptor, klass in ((b"Landroid/os/Binder;", self.binder_class),
                                  (b"Landroid/os/ServiceManager;",
                                   self.service_manager)):
            with self.subTest(descriptor=descriptor):
                rc, vm, app, core = self.construct(
                    descriptor, klass,
                    app=MemoryReader(self.dex["framework"]))
                self.assertEqual(rc, -4)
                self.assertFalse(vm.value)
                self.assertLessEqual(app.max_request, 268)
                self.assertLessEqual(core.max_request, 268)

    def test_real_android_framework_pair_constructor_not_an_app_shim(self):
        # framework.jar is an ACTUAL Android boot DEX, not Launcher2 or a
        # fabricated Activity. Pair's two Object references are typed Java
        # nulls; its constructor writes the genuine first/second fields.
        descriptor = b"Landroid/util/Pair;"
        args = [(b"Ljava/lang/Object;", 0), (b"Ljava/lang/Object;", 0)]
        framework = MemoryReader(self.dex["framework"])
        rc, vm, app, core = self.construct_with_args(
            descriptor, self.pair, args, app=framework)
        self.assertEqual(rc, 0)
        try:
            self.assertEqual(self.get(vm, b"first", b"Ljava/lang/Object;"),
                             (0, 0))
            self.assertEqual(self.get(vm, b"second", b"Ljava/lang/Object;"),
                             (0, 0))
            self.assertEqual(self.get(vm, b"first", b"I"), (-3, 0))
        finally:
            self.free(vm)
        self.assertLessEqual(app.max_request, 268)
        self.assertLessEqual(core.max_request, 268)
        # No target would execute altered bytes: caller SHA rejects first.
        bad = bytearray(self.dex["framework"])
        at = code_offset(bad, "Landroid/util/Pair;", "<init>")
        self.assertEqual(bad[at], 0x70)
        bad[at] = 0xff
        rc, absent, app, core = self.construct_with_args(
            descriptor, self.pair, args, app=MemoryReader(bytes(bad)))
        self.assertEqual(rc, -4)
        self.assertFalse(absent.value)

    def test_reject_real_rect_class_initializer_instead_of_faking_it(self):
        rc, vm, _, _ = self.construct(RECT, self.rect,
                                      app=MemoryReader(self.dex["framework"]))
        self.assertEqual(rc, -4)
        self.assertFalse(vm.value)

    def test_reject_wrong_classes_corrupt_code_or_short_read(self):
        wrong = BootClass(0, self.drag.class_def_index)
        rc, vm, _, _ = self.construct(located=wrong)
        self.assertNotEqual(rc, 0)
        self.assertFalse(vm.value)
        rc, vm, _, _ = self.construct(core=MemoryReader(self.dex["Launcher2"]))
        self.assertNotEqual(rc, 0)
        self.assertFalse(vm.value)
        bad = bytearray(self.dex["Launcher2"])
        at = code_offset(bad, ITEM.decode(), "<init>")
        self.assertEqual(bad[at] & 255, 0x16)  # real const-wide/16 instruction
        bad[at] = 0xff  # hypothetical altered code; SHA pin would FIRST reject!
        rc, vm, _, _ = self.construct(app=MemoryReader(bytes(bad)))
        self.assertEqual(rc, -4)
        self.assertFalse(vm.value)
        rc, vm, _, _ = self.construct(app=MemoryReader(self.dex["Launcher2"],
                                                       fail_at=at))
        self.assertEqual(rc, -5)
        self.assertFalse(vm.value)
        # Wrong immediate superclass must fail: don't silently replace the
        # missing ItemInfo constructor with Object's real, shorter code.
        bad = bytearray(self.dex["Launcher2"])
        child = code_offset(bad,
            "Lcom/android/launcher2/ApplicationInfo;", "<init>")
        parent = code_offset(bad, ITEM.decode(), "<init>")
        self.assertEqual(bad[child], 0x70)  # child invoke-direct
        self.assertEqual(bad[parent + 8], 0x70)  # ItemInfo -> core Object
        object_method_ref = struct.unpack_from("<H", bad, parent + 10)[0]
        struct.pack_into("<H", bad, child + 2, object_method_ref)
        rc, vm, _, _ = self.construct(
            b"Lcom/android/launcher2/ApplicationInfo;", self.application,
            app=MemoryReader(bytes(bad)))
        self.assertEqual(rc, -4)
        self.assertFalse(vm.value)
        # The invoked core Object.<init> is also interpreted, never stubbed.
        damaged_core = bytearray(self.dex["core"])
        core_code = code_offset(damaged_core, OBJECT.decode(), "<init>")
        self.assertEqual(damaged_core[core_code], 0x0e)
        damaged_core[core_code] = 0xff
        rc, vm, _, _ = self.construct(core=MemoryReader(bytes(damaged_core)))
        self.assertEqual(rc, -4)
        self.assertFalse(vm.value)


if __name__ == "__main__":
    unittest.main()
