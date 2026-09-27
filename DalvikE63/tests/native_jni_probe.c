/* Host-only verifier for the official Android 4.2 JNI C calling convention.
 * This is not compiled into the E63 app and does not fake its process IDs.
 */
#include "../symbian/runtime/jni_bridge.h"
#include <string.h>

static jint JNICALL host_native(JNIEnv *env,jclass clazz)
    {
    return clazz && env && (*env)->GetVersion(env)==JNI_VERSION_1_6 ?
           (jint)4317 : (jint)-1;
    }
static void *method_pointer(void)
    {
    void *bits=0;
    jint (JNICALL *fn)(JNIEnv*,jclass)=host_native;
    if (sizeof(bits)==sizeof(fn)) memcpy(&bits,&fn,sizeof(bits));
    return bits;
    }
int e63_test_jni_register_pid(E63JniBridge *bridge,jclass clazz)
    {
    JNIEnv *env=e63_jni_bridge_env(bridge);
    JNINativeMethod method={"myPid","()I",0};
    if (!env || (*env)->FindClass(env,"android/os/Process")!=clazz)
        return JNI_ERR;
    method.fnPtr=method_pointer();
    return (*env)->RegisterNatives(env,clazz,&method,1);
    }
int e63_test_jni_register_bad_atomic(E63JniBridge *bridge,jclass clazz)
    {
    JNIEnv *env=e63_jni_bridge_env(bridge);
    JNINativeMethod methods[2]={{"myPid","()I",0},
                                {"myPid","(I)I",0}};
    if (!env) return JNI_ERR;
    methods[0].fnPtr=methods[1].fnPtr=method_pointer();
    return (*env)->RegisterNatives(env,clazz,methods,2);
    }
int e63_test_jni_register_binder(E63JniBridge *bridge,jclass clazz)
    {
    JNIEnv *env=e63_jni_bridge_env(bridge);
    JNINativeMethod method={"getCallingPid","()I",0};
    if (!env || (*env)->FindClass(env,"android/os/Binder")!=clazz)
        return JNI_ERR;
    method.fnPtr=method_pointer();
    return (*env)->RegisterNatives(env,clazz,&method,1);
    }
int e63_test_jni_unregister(E63JniBridge *bridge,jclass clazz)
    {
    JNIEnv *env=e63_jni_bridge_env(bridge);
    return env ? (*env)->UnregisterNatives(env,clazz) : JNI_ERR;
    }
