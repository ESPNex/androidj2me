#ifndef E63_BOOT_METHOD_H
#define E63_BOOT_METHOD_H
/* First NATIVE execution path for actual Android 4.2 bootclasspath DEX.
 * Given a class_def from the pinned, on-disk boot index, locate an EXACT
 * static (I...)I method in the independently pinned raw DEX and execute its
 * primitive-register bytecode. Never buffer /system or a whole DEX in RAM:
 * only the selected code_item (<=4096 16-bit words) is copied. No JNI,
 * objects, GC, exceptions, class initialization, Activity or Android service
 * semantics are implemented. Unsupported instructions fail CLOSED.
 *
 * SECURITY: The callback MUST read an already SHA-256-verified, read-only,
 * immutable-for-duration RFile. e63_boot_confirm_class rechecks the
 * descriptor/class_def, but neither function authenticates the original JAR.
 */
#include "boot_classpath.h"
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define E63_BOOT_METHOD_MAX_CODE_WORDS 4096u
#define E63_BOOT_METHOD_MAX_REGISTERS 64u
#define E63_BOOT_METHOD_MAX_ARGUMENTS 4u
#define E63_BOOT_METHOD_STEP_LIMIT 4096u

typedef enum E63BootMethodStatus {
    E63_BOOT_METHOD_OK=0,
    E63_BOOT_METHOD_BAD_INPUT=-1,
    E63_BOOT_METHOD_UNTRUSTED=-2,
    E63_BOOT_METHOD_NOT_FOUND=-3,
    E63_BOOT_METHOD_UNSUPPORTED=-4,
    E63_BOOT_METHOD_IO_ERROR=-5,
    E63_BOOT_METHOD_BUDGET=-6
} E63BootMethodStatus;

/* Call only after resolving class with e63_boot_find_class and verifying
 * source /system JAR and raw /data DEX pins. No host implementation of the
 * named Java method is supplied; the result comes exclusively from DEX code.
 * The output is zeroed on every failure. */
E63BootMethodStatus e63_boot_call_static_int(
    const E63BootClass *where, const char *descriptor,
    const char *name, const char *prototype, const int32_t *arguments,
    unsigned argument_count, E63BootReadAt dex_read_at, void *dex_context,
    size_t dex_bytes, int32_t *output);
/* Authorize an exact, genuinely ACC_NATIVE|ACC_STATIC, code_item-less ()I
 * declaration from the authenticated boot DEX before JNI registration. Does
 * not call the native method or authenticate the enclosing original JAR. */
E63BootMethodStatus e63_boot_inspect_native_static_int(
    const E63BootClass *where,const char *descriptor,const char *name,
    const char *prototype,E63BootReadAt dex_read_at,void *dex_context,
    size_t dex_bytes);
const char *e63_boot_method_status(E63BootMethodStatus status);

#ifdef __cplusplus
}
#endif
#endif
