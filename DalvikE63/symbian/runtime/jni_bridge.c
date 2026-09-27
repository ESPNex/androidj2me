#include "jni_bridge.h"
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define JNI_BRIDGE_MAGIC 0x4536334au
#define JNI_NAME_BYTES 128u

typedef jint (JNICALL *E63NativeInt)(JNIEnv*,jclass);
typedef struct JniClass {
    E63BootClass where;
    E63BootReadAt read_at;
    void *context;
    size_t bytes;
    char descriptor[256];
    uint8_t occupied;
} JniClass;
typedef struct JniMethod {
    E63NativeInt call;
    jclass owner;
    char name[JNI_NAME_BYTES];
} JniMethod;
struct E63JniBridge {
    uint32_t magic;
    JNIEnv env; /* C JNI: address of this field IS JNIEnv* */
    struct JNINativeInterface functions;
    JniClass classes[E63_JNI_MAX_CLASSES];
    JniMethod methods[E63_JNI_MAX_METHODS];
    unsigned class_count,method_count,depth;
};
static E63JniBridge *from_env(JNIEnv *env)
    {
    E63JniBridge *b;
    if (!env) return 0;
    b=(E63JniBridge*)((char*)env - offsetof(E63JniBridge,env));
    return b->magic==JNI_BRIDGE_MAGIC && env==&b->env &&
           b->env==&b->functions ? b : 0;
    }
static JniClass *get_class(E63JniBridge *b,jclass clazz)
    {
    unsigned i;
    if (!b || !clazz) return 0;
    for (i=0u;i<b->class_count;++i)
        if (b->classes[i].occupied && (jclass)&b->classes[i]==clazz)
            return &b->classes[i];
    return 0;
    }
static jint JNICALL jni_version(JNIEnv *env)
    {return from_env(env) ? JNI_VERSION_1_6 : JNI_ERR;}
static jclass JNICALL jni_find_class(JNIEnv *env,const char *name)
    {
    E63JniBridge *b=from_env(env);
    size_t n;
    unsigned i;
    if (!b || !name) return 0;
    /* Only EXACT classes explicitly opened by a verified boot loader can
     * be found. No dynamic class loading, name alias or host stub. */
    for (n=0u;n<253u && name[n];++n)
        if ((unsigned char)name[n]<33u ||
            (unsigned char)name[n]>126u || name[n]==';') return 0;
    if (!n || n>=253u || name[n]) return 0;
    for (i=0u;i<b->class_count;++i)
        if (b->classes[i].occupied &&
            b->classes[i].descriptor[0]=='L' &&
            strncmp(b->classes[i].descriptor+1,name,n)==0 &&
            b->classes[i].descriptor[n+1u]==';' &&
            b->classes[i].descriptor[n+2u]==0)
            return (jclass)&b->classes[i];
    return 0;
    }
static jint JNICALL jni_register(JNIEnv *env,jclass clazz,
                                  const JNINativeMethod *methods,jint count)
    {
    E63JniBridge *b=from_env(env);
    JniClass *owner=get_class(b,clazz);
    unsigned i,j;
    if (!owner || !methods || count<=0 ||
        count>(jint)E63_JNI_MAX_METHODS ||
        b->method_count>E63_JNI_MAX_METHODS-(unsigned)count ||
        sizeof(void*)!=sizeof(E63NativeInt)) return JNI_ERR;
    /* Atomic preflight. Both method_id *and* class_def come from the
     * authentic DEX; a non-native or code-bearing lookalike is rejected. */
    for (i=0u;i<(unsigned)count;++i)
        {
        size_t n;
        /* The other JNI vtable entries require managed Java references,
         * exceptions and GC. Do not accept *any* other AOSP native method:
         * a trusted pointer alone cannot make Binder/Parcel safe to call. */
        if (!methods[i].name || !methods[i].signature ||
            !methods[i].fnPtr || strcmp(methods[i].signature,"()I")!=0 ||
            strcmp(owner->descriptor,"Landroid/os/Process;")!=0 ||
            strcmp(methods[i].name,"myPid")!=0)
            return JNI_ERR;
        for (n=0u;n<JNI_NAME_BYTES && methods[i].name[n];++n) {}
        if (!n || n>=JNI_NAME_BYTES) return JNI_ERR;
        for (j=0u;j<b->method_count;++j)
            if (b->methods[j].owner==clazz &&
                strcmp(methods[i].name,b->methods[j].name)==0)
                return JNI_ERR;
        for (j=0u;j<i;++j)
            if (strcmp(methods[i].name,methods[j].name)==0)
                return JNI_ERR;
        if (e63_boot_inspect_native_static_int(&owner->where,
            owner->descriptor,methods[i].name,methods[i].signature,
            owner->read_at,owner->context,owner->bytes)!=E63_BOOT_METHOD_OK)
            return JNI_ERR;
        }
    for (i=0u;i<(unsigned)count;++i)
        {
        JniMethod *item=&b->methods[b->method_count++];
        /* jni.h specifies a void* fnPtr even though it contains a native
         * function address. Copy the representation (32-bit ARM, or tested
         * same-width host); do not call through a forged DEX pointer. */
        memcpy(&item->call,&methods[i].fnPtr,sizeof(item->call));
        item->owner=clazz;
        strcpy(item->name,methods[i].name);
        }
    return JNI_OK;
    }
static jint JNICALL jni_unregister(JNIEnv *env,jclass clazz)
    {
    E63JniBridge *b=from_env(env);
    unsigned i=0u;
    if (!get_class(b,clazz)) return JNI_ERR;
    while (i<b->method_count)
        {
        if (b->methods[i].owner==clazz)
            {
            --b->method_count;
            if (i<b->method_count)
                memmove(&b->methods[i],&b->methods[i+1],
                        (b->method_count-i)*sizeof(b->methods[0]));
            memset(&b->methods[b->method_count],0,sizeof(b->methods[0]));
            }
        else ++i;
        }
    return JNI_OK;
    }
E63JniBridge *e63_jni_bridge_new(void)
    {
    E63JniBridge *b=(E63JniBridge*)calloc(1u,sizeof(*b));
    if (!b) return 0;
    b->magic=JNI_BRIDGE_MAGIC;
    b->functions.GetVersion=jni_version;
    b->functions.FindClass=jni_find_class;
    b->functions.RegisterNatives=jni_register;
    b->functions.UnregisterNatives=jni_unregister;
    b->env=&b->functions;
    return b;
    }
void e63_jni_bridge_free(E63JniBridge *b)
    {if (b) {memset(b,0,sizeof(*b));free(b);}}
E63JniStatus e63_jni_bridge_class(E63JniBridge *b,
            const E63BootClass *where,const char *descriptor,
            E63BootReadAt dex_read_at,void *dex_context,size_t dex_bytes,
            jclass *out_class)
    {
    size_t n;
    unsigned i;
    E63BootStatus rc;
    if (out_class) *out_class=0;
    if (!b || b->magic!=JNI_BRIDGE_MAGIC || !where || !descriptor ||
        !dex_read_at || !out_class ||
        dex_bytes<112u || dex_bytes>32u*1024u*1024u ||
        where->dex_slot>=E63_BOOT_DEX_SLOTS) return E63_JNI_BAD_INPUT;
    for (n=0u;n<255u && descriptor[n];++n) {}
    if (n<3u || n>=255u || descriptor[n] ||
        descriptor[0]!='L' || descriptor[n-1u]!=';')
        return E63_JNI_BAD_INPUT;
    rc=e63_boot_confirm_class(where,descriptor,dex_read_at,
                              dex_context,dex_bytes);
    if (rc!=E63_BOOT_OK) return rc==E63_BOOT_IO_ERROR ?
                                 E63_JNI_IO : E63_JNI_UNTRUSTED;
    for (i=0u;i<b->class_count;++i)
        if (strcmp(b->classes[i].descriptor,descriptor)==0)
            {
            if (b->classes[i].where.dex_slot!=where->dex_slot ||
                b->classes[i].where.class_def_index!=where->class_def_index ||
                b->classes[i].read_at!=dex_read_at ||
                b->classes[i].context!=dex_context ||
                b->classes[i].bytes!=dex_bytes)
                return E63_JNI_UNTRUSTED;
            *out_class=(jclass)&b->classes[i];return E63_JNI_OK;
            }
    if (b->class_count>=E63_JNI_MAX_CLASSES) return E63_JNI_NO_MEMORY;
    {
    JniClass *clazz=&b->classes[b->class_count++];
    clazz->where=*where;clazz->read_at=dex_read_at;
    clazz->context=dex_context;clazz->bytes=dex_bytes;
    memcpy(clazz->descriptor,descriptor,n+1u);
    clazz->occupied=1u;
    *out_class=(jclass)clazz;
    }
    return E63_JNI_OK;
    }
JNIEnv *e63_jni_bridge_env(E63JniBridge *b)
    {return b && b->magic==JNI_BRIDGE_MAGIC ? &b->env : 0;}
E63JniStatus e63_jni_bridge_call_int(E63JniBridge *b,
              jclass clazz,const char *name,int32_t *out)
    {
    unsigned i;
    size_t n;
    if (out) *out=0;
    if (!b || b->magic!=JNI_BRIDGE_MAGIC || !get_class(b,clazz) ||
        !name || !out) return E63_JNI_BAD_INPUT;
    for (n=0u;n<JNI_NAME_BYTES && name[n];++n) {}
    if (!n || n>=JNI_NAME_BYTES) return E63_JNI_BAD_INPUT;
    if (b->depth>=4u) return E63_JNI_UNSUPPORTED;
    for (i=0u;i<b->method_count;++i)
        if (b->methods[i].owner==clazz &&
            strcmp(b->methods[i].name,name)==0)
            {
            jint result;
            ++b->depth;
            result=b->methods[i].call(&b->env,clazz);
            --b->depth;
            *out=(int32_t)result;
            return E63_JNI_OK;
            }
    return E63_JNI_NOT_FOUND;
    }
