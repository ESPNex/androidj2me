#ifndef E63_SYSTEM_STORE_H
#define E63_SYSTEM_STORE_H
/* Backing for read-only guest /system on persistent Nokia C: private storage.
 * Verify entire file with streaming SHA-256 using 4096 bytes of RAM, then
 * leave the RFs handle OPEN at offset zero for the caller. The caller must
 * check content again if it copies the file after verification (TOCTOU).
 * No arbitrary guest filenames or write operations are exposed.
 */
#include <f32file.h>
#include "../runtime/system_image.h"

class E63SystemStore
    {
public:
    /* Returns KErrNone only for an exact, present and SHA-256-pinned file.
     * Caller owns aFile and closes it on success. On error, aFile is closed.
     */
    static TInt OpenPinned(RFs& aFs,const char* aGuest,
                           RFile& aFile,E63SystemFile* aEntry);
private:
    E63SystemStore();
    };
#endif
