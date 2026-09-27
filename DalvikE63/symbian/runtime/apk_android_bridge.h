#ifndef E63_APK_ANDROID_BRIDGE_H
#define E63_APK_ANDROID_BRIDGE_H
/* Bounded Host service bridge for signed-build-pinned Activity/Main/Program
 * bytecode. The GuestActivity lifecycle and Main hooks execute as DEX; only
 * explicit Activity superclass/Host calls are shimmed. This is NOT the Android
 * framework. UI row strings are scalar UTF-8 decoded from DEX MUTF-8; the
 * Symbian display converts them to UTF-16. Paths/assets remain allowlisted.
 */
#include "apk_activity_vm.h"
#ifdef __cplusplus
extern "C" {
#endif

#define E63_ANDROID_ROWS 24u
#define E63_ANDROID_TEXT 160u
#define E63_ANDROID_PACKAGE 72u

typedef enum E63AndroidKind {
    E63_ANDROID_TEXT_ROW=1, E63_ANDROID_IMAGE_ROW=2,
    E63_ANDROID_OPTION_ROW=3, E63_ANDROID_INPUT_ROW=4,
    E63_ANDROID_DIALOG_ROW=5
} E63AndroidKind;
typedef struct E63AndroidRow {
    E63AndroidKind kind;
    int32_t id, arity;
    char text[E63_ANDROID_TEXT];
} E63AndroidRow;
typedef struct E63AndroidScreen {
    char title[E63_ANDROID_TEXT];
    E63AndroidRow rows[E63_ANDROID_ROWS];
    unsigned row_count;
    char open_package[E63_ANDROID_PACKAGE]; /* nonempty = request to navigate */
} E63AndroidScreen;
typedef struct E63AndroidBackend {
    void *context;
    /* Device primitives only. 0=available, otherwise unsupported/error.
     * The C bridge validates all paths, package names and asset ownership
     * before forwarding. Result always an INT for INT-returning calls; LIST
     * may write a bounded scalar UTF-8 listing into text. Never report
     * installed/guest-enabled until explicit user consent AND verification of
     * the shipped APK; this is not Android's PackageManager on Symbian.
     */
    int (*device)(void *context, E63JavaService service,
                  const E63JavaValue *args, unsigned count,
                  int32_t *result, char *text, unsigned text_capacity);
} E63AndroidBackend;

/* screen is committed ONLY after a successful VM run. Device I/O may have
 * already happened if the guest faults later: not a transactional filesystem.
 * Missing device callbacks fail safely: no fabricated installed state/files,
 * with an honest visible error row for storage/install/audio operations. */
/* Compatibility harness for Program-only tests; the E63 target calls the
 * ACTUAL Activity-Dex entry below, not this older static entry. */
E63JavaStatus e63_android_event(const E63JavaSession *session,
                                 E63AndroidScreen *screen,
                                 const E63AndroidBackend *backend,
                                 const char *method_name,
                                 const E63JavaValue *args, unsigned count);
/* Execute onCreate/onStart/onResume/onPause/onStop/onDestroy, choose, command
 * through the verified Activity DEX. Caller owns the single Activity state. */
E63JavaStatus e63_android_activity_event(const E63JavaSession *session,
                                          E63ActivityState *state,
                                          E63AndroidScreen *screen,
                                          const E63AndroidBackend *backend,
                                          const char *event,
                                          const E63JavaValue *args,
                                          unsigned count);
/* Opt-in strict 4.2 integration boundary. Does NOT revert to 0.2 shims.
 * Currently returns UNSUPPORTED: no executable framework VM/JAR yet, and
 * Host.java Android UI bytecode is not interpreted. Not a release feature. */
E63JavaStatus e63_android_activity_event_framework(
                                          const E63JavaSession *session,
                                          E63ActivityState *state,
                                          E63AndroidScreen *screen,
                                          const E63AndroidBackend *backend,
                                          const E63FrameworkDispatch *framework,
                                          const char *event,
                                          const E63JavaValue *args,
                                          unsigned count);
#ifdef __cplusplus
}
#endif
#endif
