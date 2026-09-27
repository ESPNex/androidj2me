#ifndef E63_UI_APK_ARCHIVE_H
#define E63_UI_APK_ARCHIVE_H
/* On-disk, bounded reader for genuine AOSP system APK ZIPs. The caller MUST
 * first verify the WHOLE APK's compiled SHA-256 pin and retain its read-only
 * RFile. This function alone authenticates nothing and runs no Activity.
 *
 * Reads at most 256 bytes at a time (except class verification in the existing
 * boot index reader may request 268); no 16-MB Launcher or 12-MB Settings is
 * copied to RAM. AOSP SignApk writes data descriptors for compressed
 * non-DEX entries; bounds are checked. Stored DEX must have a fixed local
 * header. Global ZIP comments and multi-disk/ZIP64 are rejected fail-closed.
 */
#include <stddef.h>
#include <stdint.h>
#include "boot_classpath.h"
#ifdef __cplusplus
extern "C" {
#endif

#define E63_UI_APK_MAX_BYTES (32u*1024u*1024u)
#define E63_UI_APK_MAX_ENTRIES 2048u

typedef enum E63UiArchiveStatus {
    E63_UI_ARCHIVE_OK=0, E63_UI_ARCHIVE_BAD_INPUT=-1,
    E63_UI_ARCHIVE_INVALID=-2, E63_UI_ARCHIVE_UNSUPPORTED=-3,
    E63_UI_ARCHIVE_IO=-4, E63_UI_ARCHIVE_BAD_CRC=-5
} E63UiArchiveStatus;

typedef struct E63UiDexSlice {
    E63BootReadAt archive_read_at;
    void *archive_context;
    uint32_t archive_bytes;
    uint32_t dex_offset, dex_bytes;
    uint32_t manifest_offset, manifest_compressed_bytes;
    uint32_t resources_offset, resources_compressed_bytes;
    uint16_t manifest_compression, resources_compression;
} E63UiDexSlice;

/* Locate one STORED primary DEX and validate its local/central ZIP headers
 * and full CRC. Confirm compiled manifest/resource entries also exist; they
 * are NOT interpreted/rendered by this function. Never open app classes from
 * this result before checking the external SHA-256 pin of the entire APK.
 * Clears *out on failure. */
E63UiArchiveStatus e63_ui_apk_open(E63UiDexSlice *out,
                                   E63BootReadAt read_at, void *context,
                                   size_t bytes);
/* Bounded callback into stored DEX bytes for e63_boot_confirm_class.
 * context = E63UiDexSlice*. Must remain valid with the APK RFile open. */
int e63_ui_dex_read_at(void *context, uint32_t offset,
                       uint8_t *dst, size_t length);
const char *e63_ui_archive_status(E63UiArchiveStatus status);
#ifdef __cplusplus
}
#endif
#endif
