#include "e63_system_store.h"
#include "../runtime/apk_sha256.h"
#include <e32base.h>
#include <string.h>

_LIT(KPrivateRoot,"C:\\private\\E0B63E04\\");

TInt E63SystemStore::OpenPinned(RFs& aFs,const char* aGuest,
                                RFile& aFile,E63SystemFile* aEntry)
    {
    E63SystemFile entry;
    if (e63_system_find(aGuest,&entry)!=E63_SYSTEM_OK ||
        !entry.relative_on_c || !entry.sha256 || !entry.bytes ||
        entry.bytes>100u*1024u*1024u)
        return KErrNotFound;
    const size_t relativeLength=strlen(entry.relative_on_c);
    TBuf<192> path(KPrivateRoot);
    if (relativeLength>static_cast<size_t>(path.MaxLength()-path.Length()))
        return KErrOverflow;
    /* The index's exact ASCII relative path is preapproved, not guest input. */
    for (size_t i=0;i<relativeLength;++i)
        path.Append(static_cast<TUint16>(entry.relative_on_c[i]));
    TInt error=aFile.Open(aFs,path,EFileRead|EFileShareReadersOnly);
    if (error!=KErrNone) return error;
    TInt size=0;
    error=aFile.Size(size);
    if (error!=KErrNone || size<0 || static_cast<size_t>(size)!=entry.bytes)
        {aFile.Close();return error==KErrNone ? KErrCorrupt : error;}
    E63Sha256Context context;
    e63_sha256_init(&context);
    TBuf8<4096> chunk;
    size_t remaining=entry.bytes;
    while (remaining)
        {
        const TInt wanted=remaining>static_cast<size_t>(chunk.MaxLength()) ?
                chunk.MaxLength() : static_cast<TInt>(remaining);
        chunk.Zero();
        error=aFile.Read(chunk,wanted);
        if (error!=KErrNone || chunk.Length()!=wanted)
            {aFile.Close();return error==KErrNone ? KErrCorrupt : error;}
        e63_sha256_update(&context,chunk.Ptr(),static_cast<size_t>(wanted));
        remaining-=static_cast<size_t>(wanted);
        }
    TUint8 digest[32];
    e63_sha256_final(&context,digest);
    if (memcmp(digest,entry.sha256,sizeof(digest))!=0)
        {aFile.Close();return KErrCorrupt;}
    TInt zero=0;
    error=aFile.Seek(ESeekStart,zero);
    if (error!=KErrNone) {aFile.Close();return error;}
    if (aEntry) *aEntry=entry;
    return KErrNone;
    }
