#ifndef E63_BOOT_STORE_H
#define E63_BOOT_STORE_H
/* Nokia S60 RFile adapter for the pinned, on-disk Android bootclasspath.
 * Both raw DEX caches and the sorted index live on persistent C: /data;
 * neither the whole guest /system nor a whole DEX is copied into RAM.
 * A pinned class definition is NOT an executable Dalvik/Android runtime.
 */
#include <f32file.h>
#include "../runtime/boot_classpath.h"
#include "../runtime/boot_method.h"
#include "../runtime/aosp_object_vm.h"

/* Field value read from a genuine bootclasspath object, not a native schema.
 * Null references are the only external object parameters in this subset. */
typedef struct E63BootObjectField {
    const char *name, *type_descriptor;
    uint64_t value;
} E63BootObjectField;
/* An optional independently typed DEX-initialized static reference, e.g.
 * android.graphics.Point.CREATOR -> actual Point$1 instance. */
typedef struct E63BootStaticProbe {
    const char *owner_descriptor,*field_name,*field_type;
    const char *expected_instance_type;
    uint32_t reference; /* zero on failure; nonzero only after DEX <clinit> */
} E63BootStaticProbe;
/* Both probes execute verified methods, never C++ implementations of them. */
typedef struct E63BootMethodProbe {
    const char *void_method;
    const E63ObjectArg *arguments;
    unsigned argument_count;
    const char *int_method,*return_type; /* I or Z */
    int32_t result;
} E63BootMethodProbe;

class E63BootStore
    {
public:
    /* On success the caller owns aFile. Keep the RFile object (same address)
     * open until done with aIndex; its read_at callback borrows &aFile.
     * On error the file is closed and aIndex is cleared. */
    static TInt OpenIndex(RFs& aFs,RFile& aFile,E63BootIndex* aIndex);
    /* Open AND hash-verify raw classes.dex for the index's slot. No class
     * may be executed by simply calling OpenDex. */
    static TInt OpenDex(RFs& aFs,unsigned aSlot,RFile& aFile);
    /* Native class-definition lookup: SHA-256 check on BOTH pinned files,
     * bounded index search, then independent disk DEX class_def confirmation.
     * Only returns a metadata location. Does not execute or instantiate Java. */
    static TInt ResolveClass(RFs& aFs,const char* aDescriptor,
                             E63BootClass* aResult);
    /* First bounded native bytecode path, for static (I...)I methods ONLY.
     * Authenticates index, original /system JAR and /data raw DEX before
     * reading/executing the selected method from an RFile. No Android UI,
     * object heap, JNI, Binder, class initialization or Activity support.
     * The output is cleared on every failure. */
    static TInt CallStaticInt(RFs& aFs,const char* aDescriptor,
                              const char* aMethod,const char* aPrototype,
                              const int32_t* aArguments,unsigned aCount,
                              int32_t* aResult);
    /* Genuine framework Process.myPid()I ACC_NATIVE, registered through the
     * restricted JNI 1.6 vtable and backed by the CURRENT Symbian process.
     * This is not a guest process table, general JNI or Android services. */
    static TInt CallNativeProcessPid(RFs& aFs,int32_t* aResult);
    /* Construct a small real framework/core Java object from authenticated
     * boot DEX, then read up to eight fields. Also rechecks both original
     * system JARs while their pinned RFiles stay open. Still NO Activity,
     * Android UI, JNI or general classloader. Outputs zero on failure. */
    static TInt ConstructObjectFields(RFs& aFs,const char* aDescriptor,
                  const E63ObjectArg* aArguments,unsigned aArgumentCount,
                  E63BootObjectField* aFields,unsigned aFieldCount);
    static TInt ConstructObjectWithStatic(RFs& aFs,const char* aDescriptor,
                  const E63ObjectArg* aArguments,unsigned aArgumentCount,
                  E63BootObjectField* aFields,unsigned aFieldCount,
                  E63BootStaticProbe* aStatic);
    static TInt ProbeObject(RFs& aFs,const char* aDescriptor,
                  const E63ObjectArg* aArguments,unsigned aArgumentCount,
                  E63BootObjectField* aFields,unsigned aFieldCount,
                  E63BootStaticProbe* aStatic,E63BootMethodProbe* aMethod);
    /* Read-at never uses a shared seek cursor; at most 268 bytes per call. */
    static int ReadAt(void* aContext,uint32_t aOffset,uint8_t* aBuffer,
                      size_t aLength);
private:
    E63BootStore();
    };
#endif
