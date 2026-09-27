#ifndef E63_BOOT_CLASSPATH_H
#define E63_BOOT_CLASSPATH_H
/* Small read-only index for real classes.dex files extracted, byte-for-byte,
 * from pinned Android 4.2 boot JARs. Stored on C: alongside those JARs.
 * Reads one 268-byte row at a time from an already SHA-256-VERIFIED RFile;
 * never copies the entire bootclasspath or /system into RAM.
 * This resolves CLASS DEFINITIONS ONLY: it is not Dalvik, class initialization,
 * JNI/Binder, exception processing, method execution or a runtime-ready flag.
 */
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define E63_BOOT_HEADER_BYTES 24u
#define E63_BOOT_RECORD_BYTES 268u
#define E63_BOOT_MAX_CLASSES 50000u
#define E63_BOOT_MAX_BYTES (16u*1024u*1024u)
#define E63_BOOT_DEX_SLOTS 10u
#define E63_BOOT_DESCRIPTOR_BYTES 256u

typedef int (*E63BootReadAt)(void *context, uint32_t offset,
                             uint8_t *destination, size_t length);

typedef enum E63BootStatus {
    E63_BOOT_OK=0, E63_BOOT_BAD_INPUT=-1, E63_BOOT_UNTRUSTED=-2,
    E63_BOOT_NOT_FOUND=-3, E63_BOOT_IO_ERROR=-4
} E63BootStatus;

typedef struct E63BootIndex {
    void *context;
    E63BootReadAt read_at;
    uint32_t class_count, total_bytes;
} E63BootIndex;

typedef struct E63BootClass {
    uint32_t dex_slot;        /* 0..9: AOSP dex_preopt.mk boot JAR order. */
    uint32_t class_def_index; /* index in THAT archive's extracted classes.dex */
} E63BootClass;

/* Caller must authenticate the whole on-disk index (and source JAR/DEX pins)
 * before calling open. On failure, *out is cleared. The format was generated
 * by tools/stage_android42_runtime.py from the ACTUAL local-built DEX files.
 */
E63BootStatus e63_boot_index_open(E63BootIndex *out,
                                  E63BootReadAt read_at, void *context,
                                  size_t file_bytes);
/* Exact descriptor lookup, binary-searching a canonical sorted on-disk table.
 * Does not load or execute the referenced class; later VM MUST revalidate the
 * referenced class_def against the pinned DEX when materializing it. */
E63BootStatus e63_boot_find_class(const E63BootIndex *index,
                                  const char *descriptor,
                                  E63BootClass *out);
/* Independently confirm that the pinned raw DEX in the returned slot REALLY
 * defines descriptor at class_def_index. Checks DEX-035 metadata on disk in
 * bounded reads, NOT bytecode validity or execution. The caller must first
 * SHA-256-verify and retain the exact pinned DEX file in read-only mode; this
 * function does not hash it. Class descriptor support is ASCII for now. */
E63BootStatus e63_boot_confirm_class(const E63BootClass *located,
                                     const char *descriptor,
                                     E63BootReadAt dex_read_at,
                                     void *dex_context, size_t dex_bytes);
const char *e63_boot_status(E63BootStatus status);

#ifdef __cplusplus
}
#endif
#endif
