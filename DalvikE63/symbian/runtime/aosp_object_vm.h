#ifndef E63_AOSP_OBJECT_VM_H
#define E63_AOSP_OBJECT_VM_H
/* Bounded OBJECT/constructor step for authentic AOSP DEX, not a UI adapter.
 * Reads a pinned application DEX and pinned core.jar DEX by offset. Executes
 * real constructors (including multi-level core ancestors) and a tiny subset
 * of instance methods. The temporary heap supports at most 32 references to
 * constructed objects/zero-length arrays and a few actual DEX <clinit> paths.
 * Declared fields come from class_data/field_ids, never a host schema.
 *
 * Caller MUST SHA-256 verify the original APK/all original JARs, each DEX
 * source and their independent class indexes before calling this module.
 * The borrowed
 * read_at contexts must remain live/read-only for the lifetime of the VM.
 * No APK signature verifier, general class initialization, GC, nonempty
 * arrays, exceptions, general dispatch, JNI, Binder, Android services or
 * Android Activity/Views. Unknown opcodes fail preflight even in dead code;
 * parsed but unimplemented calls fail closed if actually reached.
 */
#include <stdint.h>
#include <stddef.h>
#include "boot_classpath.h"
#ifdef __cplusplus
extern "C" {
#endif

#define E63_OBJECT_MAX_FIELDS 64u
#define E63_OBJECT_MAX_CODE_WORDS 4096u
#define E63_OBJECT_MAX_REGISTERS 64u
#define E63_OBJECT_STEP_BUDGET 4096u
#define E63_OBJECT_MAX_HEAP_HANDLES 32u
#define E63_OBJECT_MAX_STATIC_FIELDS 32u

typedef enum E63ObjectStatus {
    E63_OBJECT_OK=0, E63_OBJECT_BAD_INPUT=-1, E63_OBJECT_UNTRUSTED=-2,
    E63_OBJECT_NOT_FOUND=-3, E63_OBJECT_UNSUPPORTED=-4,
    E63_OBJECT_IO=-5, E63_OBJECT_NO_MEMORY=-6, E63_OBJECT_BUDGET=-7
} E63ObjectStatus;

typedef struct E63ObjectSource {
    E63BootReadAt read_at;
    void *context;
    size_t dex_bytes;
} E63ObjectSource;

typedef struct E63ObjectVm E63ObjectVm;

/* Arguments to the ONE selected app constructor. Descriptors are checked
 * against the ACTUAL DEX proto_id/type_list, never trusted as a schema.
 * Supported: I/Z (32-bit low bits), J (64-bit bits), and a typed L...;/[...
 * NULL reference (bits==0); non-null object parameters require a real heap.
 * Maximum four argument values / five Dalvik input register words. */
typedef struct E63ObjectArg {
    const char *type_descriptor;
    uint64_t bits;
} E63ObjectArg;

/* Construct one selected app instance from genuine bytecode; allocation
 * by its constructor may create further objects in app/core. Its superclass
 * chain (up to four levels) resolves across the two verified DEX images and
 * terminates in core java.lang.Object. The real ()V constructor runs at
 * every invoked level. Unsupported <clinit>/bytecode or missing superclass
 * fails closed. On failure *out is NULL; no partial heap escapes. */
E63ObjectStatus e63_object_vm_new(
    E63ObjectVm **out,
    const E63ObjectSource *app_dex, const E63BootClass *app_class,
    const char *class_descriptor,
    const E63ObjectSource *core_dex, const E63BootClass *core_object_class);

/* Same verified class chain with an app ()V, (I...)V or typed-null-reference
 * constructor. Every argument is checked against the true DEX prototype.
 * This does NOT provide Android app widget services, a View, or a GC heap. */
E63ObjectStatus e63_object_vm_new_args(
    E63ObjectVm **out,
    const E63ObjectSource *app_dex, const E63BootClass *app_class,
    const char *class_descriptor,
    const E63ObjectSource *core_dex, const E63BootClass *core_object_class,
    const E63ObjectArg *args, unsigned argument_count);

/* Three independently SHA-verified DEX images: APK child, a pinned actual
 * framework.jar immediate superclass (class_def MUST match the child's
 * super descriptor), and core.jar Object. Method/field/type references are
 * resolved in their DECLARING DEX. Not a general class loader: native
 * methods, JNI, Binder and other boot-JAR dependencies fail closed. */
E63ObjectStatus e63_object_vm_new_linked_args(
    E63ObjectVm **out,
    const E63ObjectSource *app_dex, const E63BootClass *app_class,
    const char *class_descriptor,
    const E63ObjectSource *framework_dex,
    const E63BootClass *framework_parent_class,
    const E63ObjectSource *core_dex,
    const E63BootClass *core_object_class,
    const E63ObjectArg *args, unsigned argument_count);

/* Read the most-derived declared field matching EXACT DEX name and type
 * in the verified app ancestor chain. I, Z and J are supported (J returned
 * as signed 64-bit raw bits). No hardcoded Java field values exist in the
 * native implementation. *out is zeroed on failure. */
E63ObjectStatus e63_object_vm_field(const E63ObjectVm *vm,
                                     const char *field_name,
                                     const char *type_descriptor,
                                     uint64_t *out);

/* Read a FIELD of a referenced, constructed object in the same temporary
 * bounded heap (handles are only meaningful inside this VM). This can read
 * actual java.util.ArrayList fields after the real FolderInfo constructor.
 * The reference must be a live object, not an array or forged host pointer. */
E63ObjectStatus e63_object_vm_heap_field(const E63ObjectVm *vm,
                                         uint32_t reference,
                                         const char *field_name,
                                         const char *type_descriptor,
                                         uint64_t *out);
/* Only zero-length arrays may be allocated by the current DEX subset.
 * Return their genuine length, rejecting non-arrays and stale handles. */
E63ObjectStatus e63_object_vm_array_length(const E63ObjectVm *vm,
                                            uint32_t reference,
                                            uint32_t *out);
/* Inspect a static reference actually assigned by DEX <clinit> and the
 * runtime descriptor of a live object/array handle. Neither API creates
 * objects or fabricates a missing initializer's values. */
E63ObjectStatus e63_object_vm_static_ref(const E63ObjectVm *vm,
                                         const char *owner_descriptor,
                                         const char *field_name,
                                         const char *type_descriptor,
                                         uint32_t *out_reference);
E63ObjectStatus e63_object_vm_ref_type(const E63ObjectVm *vm,
                                       uint32_t reference,
                                       char *out,size_t out_bytes);

/* Invoke an instance ()V or typed-argument (...)V method from actual DEX
 * on root (reference==0) or a child. The DEX prototype is checked against
 * args; 0-bit references are NULL, not fabricated Android objects. The
 * changed heap and class statics roll back atomically on interpreter error.
 * Limited immediate-super / zero-arg virtual dispatch; NO Android lifecycle. */
E63ObjectStatus e63_object_vm_call_void_args(E63ObjectVm *vm,
                              uint32_t reference, const char *method_name,
                              const E63ObjectArg *arguments,
                              unsigned argument_count);
E63ObjectStatus e63_object_vm_call_void(E63ObjectVm *vm,
                                        const char *method_name);

/* Execute actual zero-argument ()I or ()Z virtual bytecode on the root
 * (reference==0) or a constructed child handle, with transactional rollback
 * on failure. For example core ArrayList.size()/isEmpty() on FolderInfo's
 * actual references. This is not a fabricated native getter. */
E63ObjectStatus e63_object_vm_call_int(E63ObjectVm *vm,
                                        uint32_t reference,
                                        const char *method_name,
                                        const char *return_type,
                                        int32_t *out);

void e63_object_vm_free(E63ObjectVm *vm);
const char *e63_object_vm_status(E63ObjectStatus status);
#ifdef __cplusplus
}
#endif
#endif
