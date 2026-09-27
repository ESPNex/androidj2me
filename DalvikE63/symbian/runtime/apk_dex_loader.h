#ifndef E63_APK_DEX_LOADER_H
#define E63_APK_DEX_LOADER_H

/* Standalone, bounded C99 APK ZIP -> DEX-035 extractor for the native VM.
 * No zlib needed: build_android_java_apks.py deliberately STORES classes.dex.
 * Own/keep the entire APK byte buffer until finished with E63DexView.
 * Validates central/local headers, uniqueness, CRC-32 and DEX preflight,
 * NOT Android's APK v1 cryptographic signature or Android framework APIs.
 * Future E63 package manager MUST authenticate APKs before using this loader.
 */
#include "dex_preflight.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum E63ApkStatus {
    E63_APK_OK=0,
    E63_APK_INVALID=1,
    E63_APK_UNSUPPORTED=2,
    E63_APK_MISSING_DEX=3,
    E63_APK_BAD_DEX=4
} E63ApkStatus;

#define E63_APK_MAX_BYTES (16u * 1024u * 1024u)
E63ApkStatus e63_apk_dex_open(const uint8_t *apk, size_t bytes, E63DexView *out);
const char *e63_apk_status(E63ApkStatus status);

#ifdef __cplusplus
}
#endif
#endif
