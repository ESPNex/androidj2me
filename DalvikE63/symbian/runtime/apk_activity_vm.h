#ifndef E63_APK_ACTIVITY_VM_H
#define E63_APK_ACTIVITY_VM_H
/* Bounded execution of the ACTUAL Main/GuestActivity DEX method bodies in
 * one of the six pinned APKs. These are NOT android.jar/framework bytecode:
 * Activity's superclass and two Host UI primitives are explicitly brokered.
 * One Activity object, no heap/GC/classloader, no arbitrary framework APIs.
 */
#include "apk_java_runtime.h"
#ifdef __cplusplus
extern "C" {
#endif

typedef struct E63ActivityState {
    unsigned char constructed, created, started, resumed, resumed_once;
} E63ActivityState;

typedef struct E63ActivityHost {
    void *context;
    /* Host.begin(this) and Host.navigated() from verified DEX calls only. */
    int (*begin)(void *context);
    int (*navigated)(void *context);
    /* Same strict Host service dispatcher used by Program bytecode. */
    const E63JavaHost *program_host;
} E63ActivityHost;

/* Future execution boundary for a REAL loaded framework.jar DEX VM. The
 * strict entry never falls back to the 0.2 Activity no-ops or Host UI shim.
 * A callback must execute the real framework method (with object identity,
 * heap, classloader and exception semantics); reporting success as a no-op
 * would violate this contract. No implementation is installed yet.
 */
typedef struct E63FrameworkDispatch {
    void *context;
    E63JavaStatus (*invoke)(void *context, const char *class_descriptor,
                            const char *method_name, const char *prototype,
                            const E63JavaValue *args, unsigned count,
                            E63JavaValue *result);
} E63FrameworkDispatch;

/* Events: onCreate (construct + GuestActivity.onCreate with null Bundle),
 * onResume, onPause, onDestroy, choose(I), command(I,String,String).
 * The latter two invoke real GuestActivity -> Main -> Program code.
 * No VM event succeeds if its DEX definition or a required hook is missing.
 */
E63JavaStatus e63_activity_event(const E63JavaSession *session,
                                  E63ActivityState *state,
                                  const E63ActivityHost *host,
                                  const char *event,
                                  const E63JavaValue *args, unsigned count);
/* For NEW Android-4.2 integration work. No executable framework exists yet:
 * NULL dispatcher and incomplete dispatch both return UNSUPPORTED, never a
 * fabricated successful Activity lifecycle. Does not mutate state on error.
 */
E63JavaStatus e63_activity_event_framework(const E63JavaSession *session,
                                  E63ActivityState *state,
                                  const E63ActivityHost *host,
                                  const E63FrameworkDispatch *framework,
                                  const char *event,
                                  const E63JavaValue *args, unsigned count);
#ifdef __cplusplus
}
#endif
#endif
