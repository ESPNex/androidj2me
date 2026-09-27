#ifndef E63_APK_JAVA_VM_H
#define E63_APK_JAVA_VM_H

/* Fail-closed, bounded C99 Dalvik subset for D8 Java Program methods
 * packaged in each independent Android Activity APK. The companion
 * apk_activity_vm executes the actual Main/GuestActivity lifecycle DEX.
 * Neither implements android.jar/framework, JIT, GC, general Java objects
 * or APK signature verification. Screens are decided by app-specific DEX;
 * device services are explicit allowlisted Host callbacks below.
 */
#include "dex_preflight.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum E63JavaType { E63_JAVA_EMPTY=0, E63_JAVA_INT=1,
                            E63_JAVA_STRING=2, E63_JAVA_OBJECT=3 } E63JavaType;
typedef struct E63JavaValue {
    E63JavaType type;
    int32_t number;
    const char *string; /* Borrowed scalar UTF-8 <=512 bytes; never retain after invoke(). */
} E63JavaValue;

typedef enum E63JavaService {
    E63_SERVICE_TITLE=1, E63_SERVICE_TEXT, E63_SERVICE_OPTION,
    E63_SERVICE_IMAGE, E63_SERVICE_INPUT, E63_SERVICE_DIALOG,
    E63_SERVICE_OPEN, E63_SERVICE_GET_FLAG, E63_SERVICE_SET_FLAG,
    E63_SERVICE_IS_INSTALLED, E63_SERVICE_SEARCH_FILE,
    E63_SERVICE_INSTALL, E63_SERVICE_LIST, E63_SERVICE_MKDIR,
    E63_SERVICE_TOUCH, E63_SERVICE_RENAME, E63_SERVICE_DELETE,
    E63_SERVICE_IMPORT_FILE, E63_SERVICE_WAV
} E63JavaService;

typedef struct E63JavaHost {
    void *context;
    /* Return zero for success; write an INT result for I-returning calls.
     * No generic reflection or arbitrary Android API invocation is possible. */
    int (*invoke)(void *context, E63JavaService service,
                  const E63JavaValue *args, unsigned count,
                  E63JavaValue *result);
} E63JavaHost;

typedef enum E63JavaStatus { E63_JAVA_OK=0, E63_JAVA_BAD_INPUT=-1,
                             E63_JAVA_NO_CODE=-2, E63_JAVA_UNSUPPORTED=-3,
                             E63_JAVA_HOST_FAILURE=-4, E63_JAVA_BUDGET=-5
} E63JavaStatus;

/* Program's exact static method/prototype: onStart/onSelect/onCommand.
 * This helper remains isolated for tests and called by apk_activity_vm for
 * Main's real DEX hook; it never runs Host.java's Android implementation.
 * DEX memory remains borrowed. */
E63JavaStatus e63_java_run(const E63DexView *dex, const char *program,
                           const char *method_name, const char *prototype,
                           const E63JavaValue *arguments, unsigned arg_count,
                           const E63JavaHost *host);
const char *e63_java_status(E63JavaStatus status);

#ifdef __cplusplus
}
#endif
#endif
