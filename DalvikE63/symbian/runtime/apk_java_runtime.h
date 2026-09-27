#ifndef E63_APK_JAVA_RUNTIME_H
#define E63_APK_JAVA_RUNTIME_H
/* Native entry to ONE of the six exact built-in APKs.
 * SHA-256 pin over *all* APK bytes is required before ZIP/DEX processing;
 * caller owns and must keep the APK buffer live for the entire session.
 * Arbitrary externally installed APKs are NEVER trusted by this interface.
 * Android OS services are delegated explicitly through E63JavaHost; this is
 * not a complete Android runtime or an Android APK signature verifier.
 */
#include "apk_java_vm.h"
#include "apk_dex_loader.h"
#ifdef __cplusplus
extern "C" {
#endif

typedef struct E63JavaSession {
    E63DexView dex;
    const uint8_t *apk;
    size_t apk_bytes;
    unsigned pin_index;
    const char *package_name, *program;
    char activity[96]; /* Main descriptor derived from pinned Program owner. */
} E63JavaSession;

typedef enum E63SessionStatus {
    E63_SESSION_OK=0, E63_SESSION_INVALID=1,
    E63_SESSION_NOT_TRUSTED=2, E63_SESSION_BAD_APK=3,
    E63_SESSION_NO_PROGRAM=4
} E63SessionStatus;

/* Only the fixed package names below can be opened by the Symbian host.
 * Filename is the pinned APK basename. The in-progress C: /system/app mapping
 * is resolved separately by system_image.c: never use a DEX-supplied pathname
 * as a Symbian RFs filename. Historical 0.1/0.2 binaries are unaffected. */
const char *e63_session_apk_name(const char *package_name);
E63SessionStatus e63_session_open(E63JavaSession *session,
                                   const char *package_name,
                                   const uint8_t *apk, size_t size);
E63JavaStatus e63_session_run(const E63JavaSession *session,
                               const char *name, const char *prototype,
                               const E63JavaValue *arguments, unsigned count,
                               const E63JavaHost *host);
/* Does the *verified* APK own this exact asset path (without assets/)? */
int e63_session_owns_asset(const E63JavaSession *session,
                            const char *asset_name);
const char *e63_session_status(E63SessionStatus status);
#ifdef __cplusplus
}
#endif
#endif
