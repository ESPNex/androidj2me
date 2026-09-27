#ifndef E63_JNI_BRIDGE_H
#define E63_JNI_BRIDGE_H
/* REAL JNI 1.6 C calling convention, extremely restricted boot-Dex gate.
 * Only FindClass (classes opened from an authenticated DEX), GetVersion,
 * RegisterNatives, UnregisterNatives and invocation of the verified
 * android.os.Process.myPid()I ONLY are provided. Other native registrations
 * are rejected because they may require unsupported Java object functions.
 * Everything else in the 4.2 JNINativeInterface is
 * unavailable, NOT a silent stub. It is NOT a working Dalvik JNI runtime:
 * no managed object handles, pending exceptions, GC, JavaVM, threads or
 * Binder/Parcel JNI. Do not register a native which uses those entries.
 */
#include "boot_method.h"
#include "third_party/aosp42_jni.h" /* official AOSP android-4.2.2_r1.2 */
#ifdef __cplusplus
extern "C" {
#endif
#define E63_JNI_MAX_CLASSES 4u
#define E63_JNI_MAX_METHODS 8u

typedef struct E63JniBridge E63JniBridge;
typedef enum E63JniStatus {
    E63_JNI_OK=0,E63_JNI_BAD_INPUT=-1,E63_JNI_UNTRUSTED=-2,
    E63_JNI_NOT_FOUND=-3,E63_JNI_UNSUPPORTED=-4,
    E63_JNI_NO_MEMORY=-5,E63_JNI_IO=-6
} E63JniStatus;

E63JniBridge *e63_jni_bridge_new(void);
void e63_jni_bridge_free(E63JniBridge *bridge);
/* Caller verifies the original /system JAR, extracted DEX SHA and class
 * index FIRST. Keeps the read_at context immutable while bridge is alive.
 * This function rechecks class_def and checks the JNI lookup descriptor. */
E63JniStatus e63_jni_bridge_class(E63JniBridge *bridge,
            const E63BootClass *where,const char *descriptor,
            E63BootReadAt dex_read_at,void *dex_context,size_t dex_bytes,
            jclass *out_class);
/* AOSP JNI C API: (*env)->RegisterNatives(env,clazz,methods,count) must
 * verify each ACC_STATIC|ACC_NATIVE no-code declaration in the real DEX. */
JNIEnv *e63_jni_bridge_env(E63JniBridge *bridge);
E63JniStatus e63_jni_bridge_call_int(E63JniBridge *bridge,
              jclass clazz,const char *name,int32_t *out);
#ifdef __cplusplus
}
#endif
#endif
