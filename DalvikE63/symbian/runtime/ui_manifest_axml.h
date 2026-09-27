#ifndef E63_UI_MANIFEST_AXML_H
#define E63_UI_MANIFEST_AXML_H
/* Bounded, on-disk Android 4.2 compiled AndroidManifest.xml reader.
 * This recognizes a declared Activity/Service and its intent-filter; it is
 * NOT an ActivityManager, PackageManager, XML renderer or Dalvik runtime.
 *
 * read_at must address an already SHA-256-verified, byte-for-byte extracted
 * AXML cache from a whole-APK-pinned AOSP source. No XML/APK is loaded into
 * RAM. Unsupported string encodings/formats and damaged chunks fail closed.
 */
#include <stddef.h>
#include <stdint.h>
#include "boot_classpath.h"
#ifdef __cplusplus
extern "C" {
#endif

#define E63_UI_AXML_MAX_BYTES (128u*1024u)

typedef enum E63UiManifestStatus {
    E63_UI_MANIFEST_OK=0, E63_UI_MANIFEST_BAD_INPUT=-1,
    E63_UI_MANIFEST_INVALID=-2, E63_UI_MANIFEST_NOT_FOUND=-3,
    E63_UI_MANIFEST_IO=-4, E63_UI_MANIFEST_UNSUPPORTED=-5
} E63UiManifestStatus;

typedef struct E63UiManifestMatch {
    uint32_t line;               /* source line from genuine AAPT AXML */
    uint32_t matching_filters;   /* 0 for a Service without intent query */
    unsigned is_service;
} E63UiManifestMatch;

/* Verify unique package and unique declared class (not an activity-alias),
 * plus an action AND category in the SAME intent-filter if requested. Class
 * names are normalized using Android's relative-name convention against the
 * manifest package. Non-null intent strings MUST both be supplied together.
 * Clears *out on any error, including a missing/mismatched intent-filter.
 * Caller must verify extracted AXML bytes and original APK against their
 * independent compiled SHA-256 pins before invoking this reader. */
E63UiManifestStatus e63_ui_manifest_find(
    E63BootReadAt read_at, void *context, size_t bytes,
    const char *package_name, const char *class_descriptor, unsigned is_service,
    const char *intent_action, const char *intent_category,
    E63UiManifestMatch *out);
#ifdef __cplusplus
}
#endif
#endif
