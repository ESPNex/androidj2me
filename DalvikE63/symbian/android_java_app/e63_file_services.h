#ifndef E63_FILE_SERVICES_H
#define E63_FILE_SERVICES_H
/* Symbian RFs backend: real, narrowly confined C: private media storage.
 * This is NOT Android's PackageManager or a mount of the entire Nokia disk.
 * Explicit import reads ONLY <simple filename> from two public drop folders.
 */
#include <e32base.h>
#include "../runtime/apk_java_runtime.h"

class E63FileServices
    {
public:
    static TBool EnabledL();
    static TBool EnableBundledL(); // requires separate on-screen confirmation
    /* 0 = service handled, result 1 only for an operation that succeeded;
     * -1 = unavailable/invalid. LIST writes a bounded UTF-8 listing. */
    static TInt InvokeL(E63JavaService aService,const E63JavaValue* aArgs,
                        unsigned aCount,int32_t* aResult,char* aText,
                        unsigned aCapacity,TBool aConfirmedImport);
private:
    static TBool BundledFilePinnedL();
    };
#endif
