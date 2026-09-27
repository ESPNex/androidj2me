#include "e63_boot_store.h"
#include "e63_system_store.h"
#include "boot_dex_pins.h"
#include "../runtime/apk_sha256.h"
#include "../runtime/jni_bridge.h"
#include "../runtime/vfs_mount.h"
#include <e32base.h>
#include <string.h>

_LIT(KBootPrivateRoot,"C:\\private\\E0B63E04\\");
static const char* const kBootJars[E63_BOOT_DEX_SLOTS]={
    "/system/framework/core.jar",
    "/system/framework/core-junit.jar",
    "/system/framework/bouncycastle.jar",
    "/system/framework/ext.jar",
    "/system/framework/framework.jar",
    "/system/framework/telephony-common.jar",
    "/system/framework/mms-common.jar",
    "/system/framework/android.policy.jar",
    "/system/framework/services.jar",
    "/system/framework/apache-xml.jar"
};

#if E63_BOOT_DEX_PIN_COUNT == E63_BOOT_DEX_SLOTS
static TInt OpenCheckedBootFile(RFs& aFs,const E63BootFilePin& aPin,
                                size_t aMaximum,RFile& aFile)
    {
    E63MountRoute route;
    if (!aPin.guest_path || !aPin.relative_on_c || !aPin.length ||
        aPin.length>aMaximum ||
        e63_route_guest_path(aPin.guest_path,0,E63_CALLER_OS,&route)!=
            E63_ROUTE_OK || route.kind!=E63_MOUNT_C_PRIVATE ||
        !route.relative[0]) return KErrArgument;
    /* Generated pin must match the canonical /data route, not an arbitrary
     * host pathname. The only source of a physical path is the compiled pin. */
    const char *physical=aPin.relative_on_c;
    if (strncmp(physical,"data\\",5u)!=0) return KErrArgument;
    physical+=5;
    size_t i=0;
    while (route.relative[i])
        {
        const char character=route.relative[i]=='/' ? '\\' : route.relative[i];
        if (physical[i]!=character) return KErrArgument;
        ++i;
        }
    if (physical[i]) return KErrArgument;
    TBuf<192> path(KBootPrivateRoot);
    const size_t length=strlen(aPin.relative_on_c);
    if (length>static_cast<size_t>(path.MaxLength()-path.Length()))
        return KErrOverflow;
    for (i=0;i<length;++i)
        path.Append(static_cast<TUint16>(aPin.relative_on_c[i]));
    TInt error=aFile.Open(aFs,path,EFileRead|EFileShareReadersOnly);
    if (error!=KErrNone) return error;
    TInt actual=0;
    error=aFile.Size(actual);
    if (error!=KErrNone || actual<0 ||
        static_cast<size_t>(actual)!=aPin.length)
        {aFile.Close();return error==KErrNone ? KErrCorrupt : error;}
    E63Sha256Context hash;
    e63_sha256_init(&hash);
    TBuf8<4096> piece;
    size_t remaining=aPin.length;
    while (remaining)
        {
        const TInt wanted=remaining>static_cast<size_t>(piece.MaxLength()) ?
                          piece.MaxLength() : static_cast<TInt>(remaining);
        piece.Zero();
        error=aFile.Read(piece,wanted);
        if (error!=KErrNone || piece.Length()!=wanted)
            {aFile.Close();return error==KErrNone ? KErrCorrupt : error;}
        e63_sha256_update(&hash,piece.Ptr(),static_cast<size_t>(wanted));
        remaining-=static_cast<size_t>(wanted);
        }
    TUint8 digest[32];
    e63_sha256_final(&hash,digest);
    if (memcmp(digest,aPin.sha256,sizeof(digest))!=0)
        {aFile.Close();return KErrCorrupt;}
    TInt start=0;
    error=aFile.Seek(ESeekStart,start);
    if (error!=KErrNone) aFile.Close();
    return error;
    }
#endif

TInt E63BootStore::ResolveClass(RFs& aFs,const char* aDescriptor,
                                E63BootClass* aResult)
    {
    if (!aResult || !aDescriptor) return KErrArgument;
    memset(aResult,0,sizeof(*aResult));
    RFile indexFile;
    E63BootIndex index;
    TInt error=OpenIndex(aFs,indexFile,&index);
    if (error!=KErrNone) return error;
    E63BootClass found;
    const E63BootStatus status=e63_boot_find_class(&index,aDescriptor,&found);
    indexFile.Close();
    if (status==E63_BOOT_NOT_FOUND) return KErrNotFound;
    if (status!=E63_BOOT_OK) return status==E63_BOOT_BAD_INPUT ?
                                  KErrArgument : KErrCorrupt;
    /* A cache entry by itself is never a bootclasspath JAR. Require the
     * original /system JAR to exist and match its separately compiled pin. */
    RFile jarFile;
    error=E63SystemStore::OpenPinned(aFs,kBootJars[found.dex_slot],jarFile,0);
    if (error!=KErrNone) return error;
    RFile dexFile;
    error=OpenDex(aFs,found.dex_slot,dexFile);
    if (error!=KErrNone) {jarFile.Close();return error;}
    TInt size=0;
    error=dexFile.Size(size);
    if (error==KErrNone && size>0 &&
        e63_boot_confirm_class(&found,aDescriptor,ReadAt,&dexFile,
                               static_cast<size_t>(size))!=E63_BOOT_OK)
        error=KErrCorrupt;
    dexFile.Close();
    jarFile.Close();
    if (error==KErrNone) *aResult=found;
    return error;
    }

TInt E63BootStore::CallStaticInt(RFs& aFs,const char* aDescriptor,
                                 const char* aMethod,const char* aPrototype,
                                 const int32_t* aArguments,unsigned aCount,
                                 int32_t* aResult)
    {
    if (!aResult) return KErrArgument;
    *aResult=0;
    if (!aDescriptor || !aMethod || !aPrototype) return KErrArgument;
    /* ResolveClass checks the SHA-256 index AND original /system JAR and
     * confirms the raw DEX class_def. The second OpenDex binds a new verified
     * read-only RFile to the method interpreter for this one synchronous call. */
    E63BootClass where;
    TInt error=ResolveClass(aFs,aDescriptor,&where);
    if (error!=KErrNone) return error;
    RFile dex;
    error=OpenDex(aFs,where.dex_slot,dex);
    if (error!=KErrNone) return error;
    TInt bytes=0;
    error=dex.Size(bytes);
    if (error==KErrNone && bytes>0)
        {
        const E63BootMethodStatus status=e63_boot_call_static_int(
            &where,aDescriptor,aMethod,aPrototype,aArguments,aCount,
            ReadAt,&dex,static_cast<size_t>(bytes),aResult);
        if (status!=E63_BOOT_METHOD_OK)
            error=status==E63_BOOT_METHOD_NOT_FOUND ? KErrNotFound :
                  status==E63_BOOT_METHOD_BAD_INPUT ? KErrArgument :
                  status==E63_BOOT_METHOD_UNSUPPORTED ? KErrNotSupported :
                  status==E63_BOOT_METHOD_BUDGET ? KErrTimedOut : KErrCorrupt;
        }
    else if (error==KErrNone) error=KErrCorrupt;
    dex.Close();
    if (error!=KErrNone) *aResult=0;
    return error;
    }

static jint JNICALL E63AndroidProcessMyPid(JNIEnv* aEnv,jclass aClass)
    {
    /* A platform port of AOSP's native Process.myPid(), not a fabricated
     * Java value. The current Symbian process is the only process available
     * to this restricted JNI boundary; no guest PID namespace exists yet. */
    if (!aEnv || !aClass || aEnv->GetVersion()!=JNI_VERSION_1_6)
        return 0;
    RProcess process;
    return static_cast<jint>(process.Id().Id());
    }

TInt E63BootStore::CallNativeProcessPid(RFs& aFs,int32_t* aResult)
    {
    if (!aResult) return KErrArgument;
    *aResult=0;
    E63BootClass where;
    TInt error=ResolveClass(aFs,"Landroid/os/Process;",&where);
    if (error!=KErrNone) return error;
    if (where.dex_slot!=4u) return KErrCorrupt;
    /* ResolveClass checks the original JAR + boot index. OpenDex verifies
     * the extracted source again, keeping the RFile alive through JNI. */
    RFile dex;
    error=OpenDex(aFs,where.dex_slot,dex);
    if (error!=KErrNone) return error;
    TInt bytes=0;
    error=dex.Size(bytes);
    if (error==KErrNone && bytes>0)
        {
        E63JniBridge* bridge=e63_jni_bridge_new();
        if (!bridge) error=KErrNoMemory;
        else
            {
            jclass clazz=0;
            const E63JniStatus status=e63_jni_bridge_class(bridge,&where,
                "Landroid/os/Process;",ReadAt,&dex,
                static_cast<size_t>(bytes),&clazz);
            if (status==E63_JNI_OK)
                {
                JNIEnv* env=e63_jni_bridge_env(bridge);
                JNINativeMethod native={"myPid","()I",0};
                jint (JNICALL *entry)(JNIEnv*,jclass)=E63AndroidProcessMyPid;
                /* JNI 1.6 specifies a void* fnPtr for a function pointer.
                 * Copy the 32-bit representation rather than coercing it. */
                if (!env || sizeof(entry)!=sizeof(native.fnPtr))
                    error=KErrNotSupported;
                else
                    {
                    memcpy(&native.fnPtr,&entry,sizeof(entry));
                    if (env->RegisterNatives(clazz,&native,1)!=JNI_OK)
                        error=KErrNotSupported;
                    else
                        {
                        int32_t value=0;
                        if (e63_jni_bridge_call_int(bridge,clazz,"myPid",
                                                    &value)!=E63_JNI_OK ||
                            value<=0)
                            error=KErrCorrupt;
                        else *aResult=value;
                        }
                    }
                }
            else error=status==E63_JNI_IO ? KErrGeneral : KErrCorrupt;
            e63_jni_bridge_free(bridge);
            }
        }
    else if (error==KErrNone) error=KErrCorrupt;
    dex.Close();
    if (error!=KErrNone) *aResult=0;
    return error;
    }

static TInt ObjectStatusToSymbian(E63ObjectStatus aStatus)
    {
    switch (aStatus)
        {
        case E63_OBJECT_OK: return KErrNone;
        case E63_OBJECT_BAD_INPUT: return KErrArgument;
        case E63_OBJECT_NOT_FOUND: return KErrNotFound;
        case E63_OBJECT_UNSUPPORTED: return KErrNotSupported;
        case E63_OBJECT_NO_MEMORY: return KErrNoMemory;
        case E63_OBJECT_BUDGET: return KErrTimedOut;
        default: return KErrCorrupt;
        }
    }

TInt E63BootStore::ConstructObjectFields(RFs& aFs,const char* aDescriptor,
                 const E63ObjectArg* aArguments,unsigned aArgumentCount,
                 E63BootObjectField* aFields,unsigned aFieldCount)
    {
    return ConstructObjectWithStatic(aFs,aDescriptor,aArguments,
             aArgumentCount,aFields,aFieldCount,0);
    }
TInt E63BootStore::ConstructObjectWithStatic(RFs& aFs,
                 const char* aDescriptor,
                 const E63ObjectArg* aArguments,unsigned aArgumentCount,
                 E63BootObjectField* aFields,unsigned aFieldCount,
                 E63BootStaticProbe* aStatic)
    {
    return ProbeObject(aFs,aDescriptor,aArguments,aArgumentCount,
                       aFields,aFieldCount,aStatic,0);
    }
TInt E63BootStore::ProbeObject(RFs& aFs,const char* aDescriptor,
                 const E63ObjectArg* aArguments,unsigned aArgumentCount,
                 E63BootObjectField* aFields,unsigned aFieldCount,
                 E63BootStaticProbe* aStatic,E63BootMethodProbe* aMethod)
    {
    unsigned i;
    if (aStatic) aStatic->reference=0u;
    if (aMethod) aMethod->result=0;
    if (!aFields || !aFieldCount || aFieldCount>8u)
        return KErrArgument;
    for (i=0u;i<aFieldCount;++i) aFields[i].value=0u;
    if (!aDescriptor || aArgumentCount>4u ||
        (aArgumentCount && !aArguments) ||
        (aStatic && (!aStatic->owner_descriptor || !aStatic->field_name ||
                     !aStatic->field_type ||
                     !aStatic->expected_instance_type)) ||
        (aMethod && (!aMethod->void_method || !aMethod->int_method ||
                     !aMethod->return_type || aMethod->argument_count>4u ||
                     (aMethod->argument_count && !aMethod->arguments))))
        return KErrArgument;
    for (i=0u;i<aFieldCount;++i)
        if (!aFields[i].name || !aFields[i].type_descriptor)
            return KErrArgument;
    E63BootClass klass,object;
    TInt error=ResolveClass(aFs,aDescriptor,&klass);
    if (error!=KErrNone) return error;
    if (klass.dex_slot>=E63_BOOT_DEX_SLOTS) return KErrCorrupt;
    error=ResolveClass(aFs,"Ljava/lang/Object;",&object);
    if (error!=KErrNone) return error;
    if (object.dex_slot!=0u) return KErrCorrupt;
    /* ResolveClass has SHA-checked each original JAR, index and DEX; reopen
     * and verify the exact same pinned sources, retaining both immutable
     * RFiles while the VM executes. Never trust a class index in isolation. */
    RFile appJar;
    error=E63SystemStore::OpenPinned(aFs,kBootJars[klass.dex_slot],appJar,0);
    if (error!=KErrNone) return error;
    RFile coreJar;
    error=E63SystemStore::OpenPinned(aFs,kBootJars[object.dex_slot],coreJar,0);
    if (error!=KErrNone) {appJar.Close();return error;}
    RFile appDex;
    error=OpenDex(aFs,klass.dex_slot,appDex);
    if (error!=KErrNone) {coreJar.Close();appJar.Close();return error;}
    RFile coreDex;
    error=OpenDex(aFs,object.dex_slot,coreDex);
    if (error!=KErrNone)
        {appDex.Close();coreJar.Close();appJar.Close();return error;}
    TInt appBytes=0,coreBytes=0;
    error=appDex.Size(appBytes);
    if (error==KErrNone) error=coreDex.Size(coreBytes);
    if (error==KErrNone && appBytes>0 && coreBytes>0)
        {
        E63ObjectSource appSource;
        appSource.read_at=ReadAt;
        appSource.context=&appDex;
        appSource.dex_bytes=static_cast<size_t>(appBytes);
        E63ObjectSource coreSource;
        coreSource.read_at=ReadAt;
        coreSource.context=&coreDex;
        coreSource.dex_bytes=static_cast<size_t>(coreBytes);
        E63ObjectVm* vm=0;
        E63ObjectStatus result=e63_object_vm_new_args(&vm,&appSource,&klass,
                 aDescriptor,&coreSource,&object,aArguments,aArgumentCount);
        if (result==E63_OBJECT_OK && aMethod)
            result=e63_object_vm_call_void_args(vm,0u,
                aMethod->void_method,aMethod->arguments,
                aMethod->argument_count);
        if (result==E63_OBJECT_OK && aMethod)
            result=e63_object_vm_call_int(vm,0u,aMethod->int_method,
                                          aMethod->return_type,
                                          &aMethod->result);
        if (result==E63_OBJECT_OK)
            for (i=0u;i<aFieldCount;++i)
                {
                result=e63_object_vm_field(vm,aFields[i].name,
                               aFields[i].type_descriptor,&aFields[i].value);
                if (result!=E63_OBJECT_OK) break;
                }
        if (result==E63_OBJECT_OK && aStatic)
            {
            char actual[E63_BOOT_DESCRIPTOR_BYTES];
            result=e63_object_vm_static_ref(vm,
                aStatic->owner_descriptor,aStatic->field_name,
                aStatic->field_type,&aStatic->reference);
            if (result==E63_OBJECT_OK)
                result=e63_object_vm_ref_type(vm,aStatic->reference,actual,
                                               sizeof(actual));
            if (result==E63_OBJECT_OK &&
                strcmp(actual,aStatic->expected_instance_type)!=0)
                result=E63_OBJECT_UNTRUSTED;
            }
        e63_object_vm_free(vm);
        error=ObjectStatusToSymbian(result);
        }
    else if (error==KErrNone) error=KErrCorrupt;
    coreDex.Close();appDex.Close();coreJar.Close();appJar.Close();
    if (error!=KErrNone)
        {
        for (i=0u;i<aFieldCount;++i) aFields[i].value=0u;
        if (aStatic) aStatic->reference=0u;
        if (aMethod) aMethod->result=0;
        }
    return error;
    }

int E63BootStore::ReadAt(void* aContext,uint32_t aOffset,
                         uint8_t* aBuffer,size_t aLength)
    {
    if (!aContext || !aBuffer || !aLength ||
        aLength>E63_BOOT_RECORD_BYTES ||
        aOffset>0x7fffffffu-aLength) return 0;
    RFile* file=static_cast<RFile*>(aContext);
    TPtr8 piece(aBuffer,0,static_cast<TInt>(aLength));
    const TInt error=file->Read(static_cast<TInt>(aOffset),piece,
                                static_cast<TInt>(aLength));
    return error==KErrNone && piece.Length()==static_cast<TInt>(aLength);
    }

TInt E63BootStore::OpenIndex(RFs& aFs,RFile& aFile,E63BootIndex* aIndex)
    {
    if (!aIndex) return KErrArgument;
    memset(aIndex,0,sizeof(*aIndex));
#if E63_BOOT_DEX_PIN_COUNT == E63_BOOT_DEX_SLOTS
    TInt error=OpenCheckedBootFile(aFs,e63_boot_index_pin,E63_BOOT_MAX_BYTES,
                                    aFile);
    if (error!=KErrNone) return error;
    if (e63_boot_index_open(aIndex,ReadAt,&aFile,
                            e63_boot_index_pin.length)!=E63_BOOT_OK)
        {aFile.Close();memset(aIndex,0,sizeof(*aIndex));return KErrCorrupt;}
    return KErrNone;
#else
    (void)aFs;(void)aFile;
    return KErrNotSupported; /* zero pins: never resolve against a stub */
#endif
    }

TInt E63BootStore::OpenDex(RFs& aFs,unsigned aSlot,RFile& aFile)
    {
#if E63_BOOT_DEX_PIN_COUNT == E63_BOOT_DEX_SLOTS
    if (aSlot>=E63_BOOT_DEX_SLOTS) return KErrArgument;
    return OpenCheckedBootFile(aFs,e63_boot_dex_pins[aSlot],
                               32u*1024u*1024u,aFile);
#else
    (void)aFs;(void)aSlot;(void)aFile;
    return KErrNotSupported;
#endif
    }
