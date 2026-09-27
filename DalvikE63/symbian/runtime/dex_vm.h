#ifndef E63_DEX_VM_H
#define E63_DEX_VM_H

/* First portable C99 DEX interpreter milestone. It executes the original
 * StoreState DEX's primitive-register, boolean-field and branch instructions.
 * It does not yet implement heap, MIDP Graphics, guest exceptions, or UI.
 * Unsupported interpreter faults discard staged field writes; this is NOT
 * general Java/Dalvik exception behavior. A DEX checksum does NOT prove
 * that its containing APK is trusted/signed.
 */
#include "dex_preflight.h"

#ifdef __cplusplus
extern "C" {
#endif

#define E63_VM_MAX_FIELDS 256u
#define E63_VM_MAX_REGISTERS 256u
#define E63_VM_MAX_WORDS 8192u
#define E63_VM_STEP_BUDGET 2048u

typedef enum E63VmStatus {
    E63_VM_OK = 0,
    E63_VM_INVALID = -1,
    E63_VM_NO_METHOD = -2,
    E63_VM_UNSUPPORTED = -3,
    E63_VM_BUDGET = -4
} E63VmStatus;

typedef struct E63VmObject {
    const E63DexView *dex;   /* Borrowed. Keep view AND its DEX buffer alive. */
    uint32_t class_index;
    char class_descriptor[128];
    int32_t fields[E63_VM_MAX_FIELDS]; /* Indexed by field_id, NOT field name. */
} E63VmObject;

E63VmStatus e63_vm_new(const E63DexView *view, const char *class_descriptor,
                       E63VmObject *out);
/* No implicit constructor: call the guest <init> method explicitly.
 * result must be non-NULL for I/Z returns; params are primitive I/Z only. */
E63VmStatus e63_vm_call(E63VmObject *instance, const char *name,
                        const char *prototype, const int32_t *params,
                        uint32_t param_count, int32_t *result);
const char *e63_vm_status(E63VmStatus status);

#ifdef __cplusplus
}
#endif
#endif
