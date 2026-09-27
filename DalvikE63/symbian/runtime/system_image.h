#ifndef E63_SYSTEM_IMAGE_H
#define E63_SYSTEM_IMAGE_H
/* Persistent guest /system, mounted read-only from the app's private Nokia C:.
 * This is a route/index and integrity gate, NOT an Android runtime VM.
 * A source checkout or SDK's android.jar is never accepted as a runtime JAR.
 * Only entries compiled into the candidate pins and verified against their
 * SHA-256 can be opened. Indexed JARs are NOT YET included in a releasable
 * SISX. The 0.2 SISX remains a separately preserved historical build.
 */
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef enum E63SystemStatus {
    E63_SYSTEM_OK=0,
    E63_SYSTEM_INVALID=-1,
    E63_SYSTEM_NOT_PRESENT=-2,
    E63_SYSTEM_UNTRUSTED=-3,
    E63_SYSTEM_READ_ONLY=-4
} E63SystemStatus;

typedef enum E63SystemFileKind {
    E63_SYSTEM_APP_APK=1,
    E63_SYSTEM_RUNTIME_JAR=2,
    E63_SYSTEM_RESOURCE_APK=3
} E63SystemFileKind;

typedef struct E63SystemFile {
    const char *guest_path; /* e.g. /system/app/Launcher.apk */
    const char *relative_on_c; /* fixed ASCII relative to C: private app root */
    const char *package_name; /* only set for pinned built-in APKs */
    size_t bytes;
    const uint8_t *sha256; /* generated pin, not a caller-supplied assertion */
    E63SystemFileKind kind;
} E63SystemFile;

/* Six preapproved LEGACY 0.2 APKs (including optional Files).
 * NULL if no old guest app exists for the exact package name. */
const char *e63_system_app_path(const char *package_name);
/* Separate, unsigned authentic-source AOSP UI CANDIDATE package identities;
 * not the legacy Activity dispatcher. Existence still needs a pinned C: file. */
const char *e63_system_ui_app_path(const char *package_name);
/* Look up an exact, canonical, read-only guest path; no arbitrary traversal.
 * Generated candidate framework pins permit metadata lookup, but the loader
 * still requires physical SHA-256-matching files on C:. No stub substitution. */
E63SystemStatus e63_system_find(const char *guest_path,
                                E63SystemFile *out);
/* Before loading or interpreting the file, check its WHOLE contents. */
E63SystemStatus e63_system_verify(const E63SystemFile *file,
                                  const uint8_t *bytes, size_t length);
const char *e63_system_status(E63SystemStatus status);
#ifdef __cplusplus
}
#endif
#endif
