#include "e63_ui_store.h"
#include "e63_system_store.h"
#include "e63_boot_store.h"
#include "ui_apk_pins.h"
#include "../runtime/ui_apk_archive.h"
#include "../runtime/ui_manifest_axml.h"
#include "../runtime/boot_method.h"
#include "../runtime/aosp_object_vm.h"
#include "../runtime/apk_sha256.h"
#include "../runtime/system_image.h"
#include "../runtime/vfs_mount.h"
#include <e32base.h>
#include <string.h>

_LIT(KUiPrivateRoot,"C:\\private\\E0B63E04\\");

static const E63UiApkPin* FindPin(const char* aPackage)
    {
    unsigned i;
    if (!aPackage) return 0;
#if E63_UI_APK_PIN_COUNT > 0
    for (i=0u;i<E63_UI_APK_PIN_COUNT;++i)
        if (strcmp(e63_ui_apk_pins[i].package_name,aPackage)==0)
            return &e63_ui_apk_pins[i];
#else
    (void)i;
#endif
    return 0;
    }

static TInt OpenPinnedData(RFs& aFs,const char* aGuest,
                           const char* aPhysical,size_t aBytes,
                           size_t aMinBytes,size_t aMaxBytes,
                           const uint8_t aSha256[32],RFile& aFile)
    {
    E63MountRoute route;
    if (!aGuest || !aPhysical || !aSha256 ||
        aBytes<aMinBytes || aBytes>aMaxBytes ||
        e63_route_guest_path(aGuest,0,E63_CALLER_OS,&route)!=
            E63_ROUTE_OK || route.kind!=E63_MOUNT_C_PRIVATE ||
        !route.relative[0]) return KErrArgument;
    const char* physical=aPhysical;
    if (strncmp(physical,"data\\",5u)!=0) return KErrArgument;
    physical+=5;
    size_t j=0u;
    while (route.relative[j])
        {
        const char ch=route.relative[j]=='/' ? '\\' : route.relative[j];
        if (physical[j]!=ch) return KErrArgument;
        ++j;
        }
    if (physical[j]!=0) return KErrArgument;
    TBuf<192> path(KUiPrivateRoot);
    const size_t length=strlen(aPhysical);
    if (length>static_cast<size_t>(path.MaxLength()-path.Length()))
        return KErrOverflow;
    for (j=0u;j<length;++j)
        path.Append(static_cast<TUint16>(aPhysical[j]));
    TInt error=aFile.Open(aFs,path,EFileRead|EFileShareReadersOnly);
    if (error!=KErrNone) return error;
    TInt actual=0;
    error=aFile.Size(actual);
    if (error!=KErrNone || actual<0 ||
        static_cast<size_t>(actual)!=aBytes)
        {aFile.Close();return error==KErrNone ? KErrCorrupt : error;}
    E63Sha256Context hash;
    e63_sha256_init(&hash);
    TBuf8<4096> chunk;
    size_t remaining=aBytes;
    while (remaining)
        {
        const TInt take=remaining>static_cast<size_t>(chunk.MaxLength()) ?
                        chunk.MaxLength() : static_cast<TInt>(remaining);
        chunk.Zero();
        error=aFile.Read(chunk,take);
        if (error!=KErrNone || chunk.Length()!=take)
            {aFile.Close();return error==KErrNone ? KErrCorrupt : error;}
        e63_sha256_update(&hash,chunk.Ptr(),static_cast<size_t>(take));
        remaining-=static_cast<size_t>(take);
        }
    TUint8 digest[32];
    e63_sha256_final(&hash,digest);
    if (memcmp(digest,aSha256,sizeof(digest))!=0)
        {aFile.Close();return KErrCorrupt;}
    return KErrNone;
    }

static TInt OpenIndex(RFs& aFs,const E63UiApkPin& aPin,RFile& aIndex)
    {
    return OpenPinnedData(aFs,aPin.index_guest_path,aPin.index_relative_on_c,
                          aPin.index_bytes,E63_BOOT_HEADER_BYTES,
                          E63_BOOT_MAX_BYTES,aPin.index_sha256,aIndex);
    }
static TInt OpenManifest(RFs& aFs,const E63UiApkPin& aPin,RFile& aManifest)
    {
    return OpenPinnedData(aFs,aPin.manifest_guest_path,
                          aPin.manifest_relative_on_c,aPin.manifest_bytes,
                          40u,E63_UI_AXML_MAX_BYTES,aPin.manifest_sha256,
                          aManifest);
    }

static TInt VerifyDex(RFile& aApk,const E63UiApkPin& aPin,
                      const E63UiDexSlice& aDex)
    {
    if (aDex.dex_bytes!=aPin.dex_bytes ||
        aDex.dex_offset>aDex.archive_bytes ||
        aDex.dex_bytes>aDex.archive_bytes-aDex.dex_offset)
        return KErrCorrupt;
    E63Sha256Context hash;
    e63_sha256_init(&hash);
    TBuf8<4096> chunk;
    uint32_t at=0u;
    while (at<aDex.dex_bytes)
        {
        const TInt wanted=aDex.dex_bytes-at>static_cast<uint32_t>(
                            chunk.MaxLength()) ? chunk.MaxLength() :
                           static_cast<TInt>(aDex.dex_bytes-at);
        chunk.Zero();
        const TInt error=aApk.Read(static_cast<TInt>(aDex.dex_offset+at),
                                   chunk,wanted);
        if (error!=KErrNone || chunk.Length()!=wanted)
            return error==KErrNone ? KErrCorrupt : error;
        e63_sha256_update(&hash,chunk.Ptr(),static_cast<size_t>(wanted));
        at+=static_cast<uint32_t>(wanted);
        }
    TUint8 digest[32];
    e63_sha256_final(&hash,digest);
    return memcmp(digest,aPin.dex_sha256,sizeof(digest))==0 ?
           KErrNone : KErrCorrupt;
    }

TInt E63UiStore::ResolveClass(RFs& aFs,const char* aPackage,
                              const char* aDescriptor,
                              E63UiClassLocation* aResult)
    {
    if (!aResult) return KErrArgument;
    memset(aResult,0,sizeof(*aResult));
    const E63UiApkPin* pin=FindPin(aPackage);
    const char* systemPath=e63_system_ui_app_path(aPackage);
    if (!pin || !aDescriptor || !systemPath ||
        strcmp(systemPath,pin->guest_path)!=0)
        return KErrArgument;
    RFile apk;
    TInt error=E63SystemStore::OpenPinned(aFs,pin->guest_path,apk,0);
    if (error!=KErrNone) return error;
    RFile indexFile;
    error=OpenIndex(aFs,*pin,indexFile);
    if (error!=KErrNone) {apk.Close();return error;}
    E63BootIndex index;
    E63BootClass where;
    E63UiDexSlice dex;
    E63BootStatus lookup=e63_boot_index_open(&index,E63BootStore::ReadAt,
                                             &indexFile,pin->index_bytes);
    if (lookup==E63_BOOT_OK)
        lookup=e63_boot_find_class(&index,aDescriptor,&where);
    if (lookup!=E63_BOOT_OK)
        {
        indexFile.Close();apk.Close();
        return lookup==E63_BOOT_NOT_FOUND ? KErrNotFound : KErrCorrupt;
        }
    if (where.dex_slot!=0u)
        {indexFile.Close();apk.Close();return KErrCorrupt;}
    const E63UiArchiveStatus archive=e63_ui_apk_open(
        &dex,E63BootStore::ReadAt,&apk,pin->apk_bytes);
    if (archive!=E63_UI_ARCHIVE_OK)
        {indexFile.Close();apk.Close();return archive==E63_UI_ARCHIVE_UNSUPPORTED ?
                                          KErrNotSupported : KErrCorrupt;}
    error=VerifyDex(apk,*pin,dex);
    if (error==KErrNone &&
        e63_boot_confirm_class(&where,aDescriptor,e63_ui_dex_read_at,
                               &dex,dex.dex_bytes)!=E63_BOOT_OK)
        error=KErrCorrupt;
    if (error==KErrNone)
        {
        aResult->indexed_class=where;
        aResult->is_service=pin->is_service;
        aResult->dex_offset=dex.dex_offset;
        aResult->dex_bytes=dex.dex_bytes;
        }
    indexFile.Close();apk.Close();
    return error;
    }

TInt E63UiStore::ResolveComponent(RFs& aFs,const char* aPackage,
                                  E63UiClassLocation* aResult)
    {
    if (!aResult) return KErrArgument;
    memset(aResult,0,sizeof(*aResult));
    const E63UiApkPin* pin=FindPin(aPackage);
    if (!pin) return KErrArgument;
    E63UiClassLocation located;
    TInt error=ResolveClass(aFs,aPackage,pin->component,&located);
    if (error!=KErrNone) return error;
    RFile axml;
    error=OpenManifest(aFs,*pin,axml);
    if (error!=KErrNone) return error;
    E63UiManifestMatch found;
    const E63UiManifestStatus xml=e63_ui_manifest_find(
        E63BootStore::ReadAt,&axml,pin->manifest_bytes,
        pin->package_name,pin->component,pin->is_service,
        pin->intent_action,pin->intent_category,&found);
    axml.Close();
    if (xml!=E63_UI_MANIFEST_OK)
        return xml==E63_UI_MANIFEST_NOT_FOUND ? KErrNotFound :
               xml==E63_UI_MANIFEST_UNSUPPORTED ? KErrNotSupported : KErrCorrupt;
    located.manifest_line=found.line;
    located.matching_filters=found.matching_filters;
    *aResult=located;
    return KErrNone;
    }

TInt E63UiStore::CallStaticInt(RFs& aFs,const char* aPackage,
                                const char* aDescriptor,const char* aMethod,
                                const char* aPrototype,
                                const int32_t* aArguments,unsigned aCount,
                                int32_t* aResult)
    {
    if (!aResult) return KErrArgument;
    *aResult=0;
    if (!aDescriptor || !aMethod || !aPrototype) return KErrArgument;
    E63UiClassLocation location;
    /* Authenticates the APK, sorted /data index, stored DEX and class_def.
     * A fresh read-only APK handle below is independently reauthenticated
     * before the interpreter reads its selected code_item at an offset. */
    TInt error=ResolveClass(aFs,aPackage,aDescriptor,&location);
    if (error!=KErrNone) return error;
    const E63UiApkPin* pin=FindPin(aPackage);
    const char* systemPath=e63_system_ui_app_path(aPackage);
    if (!pin || !systemPath || strcmp(systemPath,pin->guest_path)!=0)
        return KErrCorrupt;
    RFile apk;
    error=E63SystemStore::OpenPinned(aFs,pin->guest_path,apk,0);
    if (error!=KErrNone) return error;
    E63UiDexSlice dex;
    const E63UiArchiveStatus archive=e63_ui_apk_open(
        &dex,E63BootStore::ReadAt,&apk,pin->apk_bytes);
    if (archive!=E63_UI_ARCHIVE_OK ||
        dex.dex_offset!=location.dex_offset ||
        dex.dex_bytes!=location.dex_bytes)
        {
        apk.Close();
        return archive==E63_UI_ARCHIVE_UNSUPPORTED ? KErrNotSupported :
                                                     KErrCorrupt;
        }
    error=VerifyDex(apk,*pin,dex);
    if (error==KErrNone)
        {
        const E63BootMethodStatus method=e63_boot_call_static_int(
            &location.indexed_class,aDescriptor,aMethod,aPrototype,
            aArguments,aCount,e63_ui_dex_read_at,&dex,dex.dex_bytes,aResult);
        if (method!=E63_BOOT_METHOD_OK)
            error=method==E63_BOOT_METHOD_NOT_FOUND ? KErrNotFound :
                  method==E63_BOOT_METHOD_BAD_INPUT ? KErrArgument :
                  method==E63_BOOT_METHOD_UNSUPPORTED ? KErrNotSupported :
                  method==E63_BOOT_METHOD_BUDGET ? KErrTimedOut : KErrCorrupt;
        }
    apk.Close();
    if (error!=KErrNone) *aResult=0;
    return error;
    }

static TInt ObjectStatusToSymbian(E63ObjectStatus aStatus)
    {
    switch (aStatus)
        {
        case E63_OBJECT_OK:return KErrNone;
        case E63_OBJECT_BAD_INPUT:return KErrArgument;
        case E63_OBJECT_NOT_FOUND:return KErrNotFound;
        case E63_OBJECT_UNSUPPORTED:return KErrNotSupported;
        case E63_OBJECT_NO_MEMORY:return KErrNoMemory;
        case E63_OBJECT_BUDGET:return KErrTimedOut;
        default:return KErrCorrupt;
        }
    }

TInt E63UiStore::ConstructObjectFieldsWithArgs(RFs& aFs,const char* aPackage,
                  const char* aDescriptor,const E63ObjectArg* aArguments,
                  unsigned aArgumentCount,const char* aOptionalMethod,
                  E63UiObjectField* aFields,unsigned aFieldCount)
    {
    return ConstructObjectGraphFields(aFs,aPackage,aDescriptor,aArguments,
                                      aArgumentCount,aOptionalMethod,aFields,
                                      aFieldCount,0,0u);
    }
TInt E63UiStore::ConstructObjectGraphFields(RFs& aFs,const char* aPackage,
                  const char* aDescriptor,const E63ObjectArg* aArguments,
                  unsigned aArgumentCount,const char* aOptionalMethod,
                  E63UiObjectField* aFields,unsigned aFieldCount,
                  E63UiObjectGraphField* aGraph,unsigned aGraphCount)
    {
    unsigned i;
    if (!aFields || !aFieldCount || aFieldCount>8u || aGraphCount>8u ||
        (aGraphCount && !aGraph)) return KErrArgument;
    for (i=0u;i<aFieldCount;++i) aFields[i].value=0u;
    for (i=0u;i<aGraphCount;++i)
        {aGraph[i].value=0u;aGraph[i].array_length=0u;
         aGraph[i].method_result=0;}
    if (!aDescriptor || !aPackage) return KErrArgument;
    for (i=0u;i<aFieldCount;++i)
        if (!aFields[i].name || !aFields[i].type_descriptor)
            return KErrArgument;
    for (i=0u;i<aGraphCount;++i)
        if (!aGraph[i].root_name || !aGraph[i].root_type ||
            !aGraph[i].member_name || !aGraph[i].member_type ||
            (!!aGraph[i].method_name != !!aGraph[i].method_return_type))
            return KErrArgument;
    /* Both class indexes and ORIGINAL signed APK/core.jar are verified,
     * plus the two byte-identical independently pinned raw DEX sources.
     * A class index or one extracted classes.dex alone isn't sufficient. */
    E63UiClassLocation location;
    TInt error=ResolveClass(aFs,aPackage,aDescriptor,&location);
    if (error!=KErrNone) return error;
    E63BootClass object;
    error=E63BootStore::ResolveClass(aFs,"Ljava/lang/Object;",&object);
    if (error!=KErrNone) return error;
    if (object.dex_slot!=0u) return KErrCorrupt;
    const E63UiApkPin* pin=FindPin(aPackage);
    const char* guest=e63_system_ui_app_path(aPackage);
    if (!pin || !guest || strcmp(guest,pin->guest_path)!=0)
        return KErrCorrupt;
    RFile apk;
    error=E63SystemStore::OpenPinned(aFs,pin->guest_path,apk,0);
    if (error!=KErrNone) return error;
    E63UiDexSlice dex;
    const E63UiArchiveStatus archive=e63_ui_apk_open(
        &dex,E63BootStore::ReadAt,&apk,pin->apk_bytes);
    if (archive!=E63_UI_ARCHIVE_OK ||
        dex.dex_offset!=location.dex_offset ||
        dex.dex_bytes!=location.dex_bytes)
        {
        apk.Close();
        return archive==E63_UI_ARCHIVE_UNSUPPORTED ? KErrNotSupported :
                                                     KErrCorrupt;
        }
    error=VerifyDex(apk,*pin,dex);
    if (error!=KErrNone) {apk.Close();return error;}
    RFile core;
    error=E63BootStore::OpenDex(aFs,object.dex_slot,core);
    if (error!=KErrNone) {apk.Close();return error;}
    TInt coreBytes=0;
    error=core.Size(coreBytes);
    if (error==KErrNone && coreBytes>0)
        {
        E63ObjectSource appSource;
        appSource.read_at=e63_ui_dex_read_at;
        appSource.context=&dex;
        appSource.dex_bytes=dex.dex_bytes;
        E63ObjectSource coreSource;
        coreSource.read_at=E63BootStore::ReadAt;
        coreSource.context=&core;
        coreSource.dex_bytes=static_cast<size_t>(coreBytes);
        E63ObjectVm* vm=0;
        E63ObjectStatus result=e63_object_vm_new_args(
            &vm,&appSource,&location.indexed_class,aDescriptor,
            &coreSource,&object,aArguments,aArgumentCount);
        if (result==E63_OBJECT_OK && aOptionalMethod)
            result=e63_object_vm_call_void(vm,aOptionalMethod);
        if (result==E63_OBJECT_OK)
            {
            for (i=0u;i<aFieldCount;++i)
                {
                result=e63_object_vm_field(vm,aFields[i].name,
                                aFields[i].type_descriptor,&aFields[i].value);
                if (result!=E63_OBJECT_OK) break;
                }
            }
        if (result==E63_OBJECT_OK)
            for (i=0u;i<aGraphCount;++i)
                {
                uint64_t ref=0u;
                result=e63_object_vm_field(vm,aGraph[i].root_name,
                                            aGraph[i].root_type,&ref);
                if (result!=E63_OBJECT_OK) break;
                if (!ref || ref>0xffffffffu)
                    {result=E63_OBJECT_UNTRUSTED;break;}
                if (aGraph[i].method_name)
                    {
                    result=e63_object_vm_call_int(vm,
                        static_cast<uint32_t>(ref),aGraph[i].method_name,
                        aGraph[i].method_return_type,
                        &aGraph[i].method_result);
                    if (result!=E63_OBJECT_OK) break;
                    }
                result=e63_object_vm_heap_field(vm,static_cast<uint32_t>(ref),
                          aGraph[i].member_name,aGraph[i].member_type,
                          &aGraph[i].value);
                if (result!=E63_OBJECT_OK) break;
                if (aGraph[i].as_array)
                    {
                    if (!aGraph[i].value || aGraph[i].value>0xffffffffu)
                        {result=E63_OBJECT_UNTRUSTED;break;}
                    result=e63_object_vm_array_length(vm,
                          static_cast<uint32_t>(aGraph[i].value),
                          &aGraph[i].array_length);
                    if (result!=E63_OBJECT_OK) break;
                    }
                }
        e63_object_vm_free(vm);
        error=ObjectStatusToSymbian(result);
        }
    else if (error==KErrNone) error=KErrCorrupt;
    core.Close();apk.Close();
    if (error!=KErrNone)
        {
        for (i=0u;i<aFieldCount;++i) aFields[i].value=0u;
        for (i=0u;i<aGraphCount;++i)
            {aGraph[i].value=0u;aGraph[i].array_length=0u;
             aGraph[i].method_result=0;}
        }
    return error;
    }

TInt E63UiStore::ConstructObjectFields(RFs& aFs,const char* aPackage,
                  const char* aDescriptor,const char* aOptionalMethod,
                  E63UiObjectField* aFields,unsigned aFieldCount)
    {
    return ConstructObjectFieldsWithArgs(aFs,aPackage,aDescriptor,0,0u,
                                         aOptionalMethod,aFields,aFieldCount);
    }

TInt E63UiStore::ConstructLinkedObjectFields(RFs& aFs,
                    const char* aPackage,const char* aDescriptor,
                    const char* aFrameworkParent,
                    const E63ObjectArg* aArguments,unsigned aArgumentCount,
                    E63UiObjectField* aFields,unsigned aFieldCount)
    {
    return ConstructLinkedObjectFieldsWithMethod(aFs,aPackage,aDescriptor,
              aFrameworkParent,aArguments,aArgumentCount,0,0,0u,
              aFields,aFieldCount);
    }

TInt E63UiStore::ConstructLinkedObjectFieldsWithMethod(RFs& aFs,
                    const char* aPackage,const char* aDescriptor,
                    const char* aFrameworkParent,
                    const E63ObjectArg* aArguments,unsigned aArgumentCount,
                    const char* aOptionalMethod,
                    const E63ObjectArg* aMethodArguments,
                    unsigned aMethodArgumentCount,
                    E63UiObjectField* aFields,unsigned aFieldCount)
    {
    unsigned i;
    if (!aFields || !aFieldCount || aFieldCount>8u)
        return KErrArgument;
    for (i=0u;i<aFieldCount;++i) aFields[i].value=0u;
    if (!aPackage || !aDescriptor || !aFrameworkParent ||
        aArgumentCount>4u || (aArgumentCount && !aArguments) ||
        aMethodArgumentCount>4u ||
        (aMethodArgumentCount && (!aOptionalMethod || !aMethodArguments)))
        return KErrArgument;
    for (i=0u;i<aFieldCount;++i)
        if (!aFields[i].name || !aFields[i].type_descriptor)
            return KErrArgument;
    /* The caller pin for the actual APK, both original system JARs and
     * their independently extracted DEX files must all be authenticated.
     * FrameworkParent is checked AGAIN against the app's own super_type by
     * e63_object_vm_new_linked_args; it cannot be a substitute class. */
    E63UiClassLocation location;
    TInt error=ResolveClass(aFs,aPackage,aDescriptor,&location);
    if (error!=KErrNone) return error;
    E63BootClass parent,object;
    error=E63BootStore::ResolveClass(aFs,aFrameworkParent,&parent);
    if (error!=KErrNone) return error;
    if (parent.dex_slot!=4u) return KErrCorrupt;
    error=E63BootStore::ResolveClass(aFs,"Ljava/lang/Object;",&object);
    if (error!=KErrNone) return error;
    if (object.dex_slot!=0u) return KErrCorrupt;
    const E63UiApkPin* pin=FindPin(aPackage);
    const char* guest=e63_system_ui_app_path(aPackage);
    if (!pin || !guest || strcmp(guest,pin->guest_path)!=0)
        return KErrCorrupt;
    RFile apk;
    error=E63SystemStore::OpenPinned(aFs,pin->guest_path,apk,0);
    if (error!=KErrNone) return error;
    E63UiDexSlice dex;
    const E63UiArchiveStatus archive=e63_ui_apk_open(
        &dex,E63BootStore::ReadAt,&apk,pin->apk_bytes);
    if (archive!=E63_UI_ARCHIVE_OK ||
        dex.dex_offset!=location.dex_offset ||
        dex.dex_bytes!=location.dex_bytes)
        {
        apk.Close();
        return archive==E63_UI_ARCHIVE_UNSUPPORTED ? KErrNotSupported :
                                                     KErrCorrupt;
        }
    error=VerifyDex(apk,*pin,dex);
    if (error!=KErrNone) {apk.Close();return error;}
    RFile framework;
    error=E63BootStore::OpenDex(aFs,parent.dex_slot,framework);
    if (error!=KErrNone) {apk.Close();return error;}
    RFile core;
    error=E63BootStore::OpenDex(aFs,object.dex_slot,core);
    if (error!=KErrNone)
        {framework.Close();apk.Close();return error;}
    TInt frameworkBytes=0,coreBytes=0;
    error=framework.Size(frameworkBytes);
    if (error==KErrNone) error=core.Size(coreBytes);
    if (error==KErrNone && frameworkBytes>0 && coreBytes>0)
        {
        E63ObjectSource appSource,frameworkSource,coreSource;
        appSource.read_at=e63_ui_dex_read_at;
        appSource.context=&dex;
        appSource.dex_bytes=dex.dex_bytes;
        frameworkSource.read_at=E63BootStore::ReadAt;
        frameworkSource.context=&framework;
        frameworkSource.dex_bytes=static_cast<size_t>(frameworkBytes);
        coreSource.read_at=E63BootStore::ReadAt;
        coreSource.context=&core;
        coreSource.dex_bytes=static_cast<size_t>(coreBytes);
        E63ObjectVm* vm=0;
        E63ObjectStatus result=e63_object_vm_new_linked_args(
            &vm,&appSource,&location.indexed_class,aDescriptor,
            &frameworkSource,&parent,&coreSource,&object,
            aArguments,aArgumentCount);
        if (result==E63_OBJECT_OK && aOptionalMethod)
            result=e63_object_vm_call_void_args(vm,0u,aOptionalMethod,
                                    aMethodArguments,aMethodArgumentCount);
        if (result==E63_OBJECT_OK)
            for (i=0u;i<aFieldCount;++i)
                {
                result=e63_object_vm_field(vm,aFields[i].name,
                              aFields[i].type_descriptor,&aFields[i].value);
                if (result!=E63_OBJECT_OK) break;
                }
        e63_object_vm_free(vm);
        error=ObjectStatusToSymbian(result);
        }
    else if (error==KErrNone) error=KErrCorrupt;
    core.Close();framework.Close();apk.Close();
    if (error!=KErrNone)
        for (i=0u;i<aFieldCount;++i) aFields[i].value=0u;
    return error;
    }
