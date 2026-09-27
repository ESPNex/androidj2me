#ifndef E63_UI_STORE_H
#define E63_UI_STORE_H
/* Pinned genuine AOSP UI DEX on persistent C:; no whole /system in RAM.
 * Resolve* confirms authentic APK/index/manifest/class definitions only.
 * CallStaticInt runs bounded genuine static bytecode. ConstructObjectFields
 * additionally executes real app+core DEX constructors and can inspect a
 * limited heap of objects and empty arrays. Neither path starts an Activity,
 * renders a View, implements JNI/Binder or substitutes for Android services.
 * Keep StrictActivityEvent closed.
 */
#include <f32file.h>
#include "../runtime/boot_classpath.h"
#include "../runtime/aosp_object_vm.h"

typedef struct E63UiClassLocation {
    E63BootClass indexed_class;
    unsigned is_service;
    uint32_t dex_offset, dex_bytes;
    uint32_t manifest_line, matching_filters; /* ResolveComponent only */
} E63UiClassLocation;

typedef struct E63UiObjectField {
    const char *name, *type_descriptor;
    uint64_t value; /* genuine executed DEX field contents; 0 on failure */
} E63UiObjectField;

/* Read a field through a genuine DEX reference in a constructed object's
 * bounded temporary heap. If as_array is set, the field must reference a
 * real zero-length DEX-created array, not a native substitute. Optionally
 * interpret a zero-argument ()I/()Z DEX method on that same child. */
typedef struct E63UiObjectGraphField {
    const char *root_name, *root_type;
    const char *member_name, *member_type;
    unsigned as_array;
    uint64_t value;
    uint32_t array_length;
    const char *method_name, *method_return_type; /* NULL disables call */
    int32_t method_result;
} E63UiObjectGraphField;

class E63UiStore
    {
public:
    /* A package must match EXACTLY one generated authentic-source pin.
     * On any error out is zeroed. Neither a legacy shim APK nor an unsigned
     * arbitrary /data/app APK can be mistaken for the genuine candidate. */
    static TInt ResolveClass(RFs& aFs,const char* aPackage,
                             const char* aDescriptor,
                             E63UiClassLocation* aResult);
    /* After class_def verification, validate the matching Activity/Service
     * AND paired intent action/category from the genuine AAPT binary manifest.
     * This is metadata, NOT a lifecycle callback. */
    static TInt ResolveComponent(RFs& aFs,const char* aPackage,
                                 E63UiClassLocation* aResult);
    /* Run ONLY a primitive static (I...)I method from a signed, SHA-pinned
     * genuine UI DEX, never by replacing it with an OS-side implementation.
     * Verifies APK + class index + stored DEX before interpreting bytecode.
     * This is NOT class initialization, an Activity or a Java object VM. */
    static TInt CallStaticInt(RFs& aFs,const char* aPackage,
                              const char* aDescriptor,const char* aMethod,
                              const char* aPrototype,const int32_t* aArguments,
                              unsigned aCount,int32_t* aResult);
    /* Reauthenticates UI APK, index, DEX, core.jar and core DEX. Constructs
     * one temporary instance using REAL DEX bytecode, allocates only up to
     * 32 referenced objects/empty arrays, optionally calls a ()V method,
     * then reads up to eight fields while both pinned RFiles are open. This
     * is not a persistent GC heap or an Android lifecycle. */
    static TInt ConstructObjectFields(RFs& aFs,const char* aPackage,
             const char* aDescriptor,const char* aOptionalMethod,
             E63UiObjectField* aFields,unsigned aFieldCount);
    static TInt ConstructObjectFieldsWithArgs(RFs& aFs,const char* aPackage,
             const char* aDescriptor,const E63ObjectArg* aArguments,
             unsigned aArgumentCount,const char* aOptionalMethod,
             E63UiObjectField* aFields,unsigned aFieldCount);
    static TInt ConstructObjectGraphFields(RFs& aFs,const char* aPackage,
             const char* aDescriptor,const E63ObjectArg* aArguments,
             unsigned aArgumentCount,const char* aOptionalMethod,
             E63UiObjectField* aFields,unsigned aFieldCount,
             E63UiObjectGraphField* aGraph,unsigned aGraphCount);
    /* Explicitly pinned three-DEX subclass chain: signed APK, genuine
     * framework.jar immediate parent, core.jar Object. Reads real fields,
     * NEVER launches an Activity or supplies JNI/Binder/Android services. */
    static TInt ConstructLinkedObjectFields(RFs& aFs,const char* aPackage,
             const char* aDescriptor,const char* aFrameworkParent,
             const E63ObjectArg* aArguments,unsigned aArgumentCount,
             E63UiObjectField* aFields,unsigned aFieldCount);
    /* Optional inherited Java method: its DEX prototype must match the
     * typed arguments. Evaluated before reading the requested fields. */
    static TInt ConstructLinkedObjectFieldsWithMethod(RFs& aFs,
             const char* aPackage,const char* aDescriptor,
             const char* aFrameworkParent,
             const E63ObjectArg* aArguments,unsigned aArgumentCount,
             const char* aOptionalMethod,const E63ObjectArg* aMethodArguments,
             unsigned aMethodArgumentCount,
             E63UiObjectField* aFields,unsigned aFieldCount);
private:
    E63UiStore();
    };
#endif
