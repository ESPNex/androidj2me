#include "e63_file_services.h"
#include <f32file.h>
#include <string.h>
#include "../runtime/vfs_mount.h"
#include "../runtime/system_image.h"
#include "e63_system_store.h"
_LIT(KEnabled,"C:\\private\\E0B63E04\\files.enabled");
_LIT(KMedia,"C:\\private\\E0B63E04\\media\\");
_LIT(KImportC,"C:\\Data\\E63Import\\");
_LIT(KImportE,"E:\\Others\\E63Import\\");
_LIT8(KMarker,"E63-GUEST-FILES-1\n");
#define FILE_PACKAGE "org.e63.dalvik.files"

static TBool AppendUtf8(TDes& aTarget,const char* aSource,TBool aSlash)
    {
    const unsigned char* p=reinterpret_cast<const unsigned char*>(aSource);
    if (!p) return EFalse;
    while (*p)
        {
        TUint32 value;
        unsigned first=*p++;
        if (first<0x80u) value=first;
        else if (first>=0xc2u && first<=0xdfu && *p)
            {value=((first&31u)<<6)|(*p++&63u);}
        else if (first>=0xe0u && first<=0xefu && p[0] && p[1])
            {value=((first&15u)<<12)|((p[0]&63u)<<6)|(p[1]&63u);p+=2;}
        else if (first>=0xf0u && first<=0xf4u && p[0] && p[1] && p[2])
            {value=((first&7u)<<18)|((p[0]&63u)<<12)|
                   ((p[1]&63u)<<6)|(p[2]&63u);p+=3;}
        else return EFalse;
        if (value<32u || value==127u ||
            (value>=0xd800u && value<=0xdfffu) || value>0x10ffffu)
            return EFalse;
        if (aTarget.Length()+2>aTarget.MaxLength()) return EFalse;
        if (aSlash && value=='/') value='\\';
        if (value<=0xffffu) aTarget.Append(static_cast<TUint16>(value));
        else
            {
            value-=0x10000u;
            aTarget.Append(static_cast<TUint16>(0xd800u+(value>>10)));
            aTarget.Append(static_cast<TUint16>(0xdc00u+(value&1023u)));
            }
        }
    return ETrue;
    }
static TBool PathForGuest(const char* aGuest,TBool aWrite,TDes& aPath)
    {
    E63MountRoute route;
    if (e63_route_guest_path(aGuest,aWrite,E63_CALLER_FILES,&route)!=
            E63_ROUTE_OK || route.kind!=E63_MOUNT_C_MEDIA ||
        (aWrite && !route.relative[0])) return EFalse;
    aPath.Copy(KMedia);
    return AppendUtf8(aPath,route.relative,ETrue);
    }
static TBool SimpleName(const char* aName)
    {
    size_t i, length;
    if (!aName || (length=strlen(aName))==0 || length>80u ||
        strcmp(aName,".")==0 || strcmp(aName,"..")==0) return EFalse;
    for (i=0;i<length;++i)
        {
        const char c=aName[i];
        if (!((c>='a' && c<='z') || (c>='A' && c<='Z') ||
              (c>='0' && c<='9') || c=='-' || c=='_' || c=='.'))
            return EFalse;
        }
    return aName[length-1u]!='.';
    }
static void AddBytes(char* aOut,unsigned aCap,unsigned& aUsed,
                     const char* aText)
    {
    if (!aOut || !aCap || !aText) return;
    while (*aText && aUsed+1u<aCap)
        aOut[aUsed++]=*aText++;
    aOut[aUsed]=0;
    }
static void AddName(char* aOut,unsigned aCap,unsigned& aUsed,const TDesC& aName)
    {
    for (TInt i=0;i<aName.Length();++i)
        {
        TUint32 cp=aName[i];
        unsigned n;
        if (cp>=0xd800u && cp<=0xdbffu && i+1<aName.Length() &&
            aName[i+1]>=0xdc00u && aName[i+1]<=0xdfffu)
            {
            cp=0x10000u+((cp-0xd800u)<<10)+aName[++i]-0xdc00u;
            }
        else if (cp<32u || cp==127u ||
                 (cp>=0xd800u && cp<=0xdfffu)) cp='?';
        n=cp<0x80u ? 1u : cp<0x800u ? 2u : cp<0x10000u ? 3u : 4u;
        if (aUsed+n>=aCap) return;
        if (n==1u) aOut[aUsed++]=static_cast<char>(cp);
        else if (n==2u)
            {
            aOut[aUsed++]=static_cast<char>(0xc0u|(cp>>6));
            aOut[aUsed++]=static_cast<char>(0x80u|(cp&63u));
            }
        else if (n==3u)
            {
            aOut[aUsed++]=static_cast<char>(0xe0u|(cp>>12));
            aOut[aUsed++]=static_cast<char>(0x80u|((cp>>6)&63u));
            aOut[aUsed++]=static_cast<char>(0x80u|(cp&63u));
            }
        else
            {
            aOut[aUsed++]=static_cast<char>(0xf0u|(cp>>18));
            aOut[aUsed++]=static_cast<char>(0x80u|((cp>>12)&63u));
            aOut[aUsed++]=static_cast<char>(0x80u|((cp>>6)&63u));
            aOut[aUsed++]=static_cast<char>(0x80u|(cp&63u));
            }
        aOut[aUsed]=0;
        }
    }
static TInt EnsureMedia(RFs& aFs)
    {
    TInt result=aFs.MkDirAll(KMedia);
    if (result!=KErrNone && result!=KErrAlreadyExists) return result;
    static const TPtrC names[]={_L("DCIM\\"),_L("Download\\"),
                               _L("Music\\"),_L("Ringtones\\")};
    for (unsigned i=0;i<sizeof(names)/sizeof(names[0]);++i)
        {
        TBuf<128> folder(KMedia);
        folder.Append(names[i]);
        result=aFs.MkDirAll(folder);
        if (result!=KErrNone && result!=KErrAlreadyExists) return result;
        }
    return KErrNone;
    }

TBool E63FileServices::BundledFilePinnedL()
    {
    E63SystemFile sys;
    RFs fs;User::LeaveIfError(fs.Connect());CleanupClosePushL(fs);
    RFile file;TInt err=E63SystemStore::OpenPinned(fs,
                    "/system/app/FileManager.apk",file,&sys);
    if (err!=KErrNone) {CleanupStack::PopAndDestroy(&fs);return EFalse;}
    CleanupClosePushL(file);
    TInt bytes=0;User::LeaveIfError(file.Size(bytes));
    if (bytes<112 || static_cast<TUint>(bytes)>E63_APK_MAX_BYTES ||
        static_cast<size_t>(bytes)!=sys.bytes)
        {CleanupStack::PopAndDestroy(2,&fs);return EFalse;}
    HBufC8* blob=HBufC8::NewLC(bytes);
    TPtr8 data=blob->Des();User::LeaveIfError(file.Read(data));
    E63JavaSession verified;
    const TBool correct=data.Length()==bytes &&
        e63_system_verify(&sys,data.Ptr(),bytes)==E63_SYSTEM_OK &&
        e63_session_open(&verified,FILE_PACKAGE,data.Ptr(),bytes)==E63_SESSION_OK;
    CleanupStack::PopAndDestroy(blob);
    CleanupStack::PopAndDestroy(&file);
    CleanupStack::PopAndDestroy(&fs);
    return correct;
    }
TBool E63FileServices::EnabledL()
    {
    RFs fs;User::LeaveIfError(fs.Connect());CleanupClosePushL(fs);
    RFile file;
    if (file.Open(fs,KEnabled,EFileRead|EFileShareReadersOnly)!=KErrNone)
        {CleanupStack::PopAndDestroy(&fs);return EFalse;}
    CleanupClosePushL(file);
    TInt size=0;TBuf8<32> data;
    TInt err=file.Size(size);
    if (err==KErrNone && size==KMarker().Length()) err=file.Read(data);
    const TBool marked=err==KErrNone && data==KMarker();
    CleanupStack::PopAndDestroy(&file);
    CleanupStack::PopAndDestroy(&fs);
    return marked && BundledFilePinnedL();
    }
TBool E63FileServices::EnableBundledL()
    {
    if (!BundledFilePinnedL()) return EFalse;
    RFs fs;User::LeaveIfError(fs.Connect());CleanupClosePushL(fs);
    if (EnsureMedia(fs)!=KErrNone)
        {CleanupStack::PopAndDestroy(&fs);return EFalse;}
    RFile file;
    TInt err=file.Replace(fs,KEnabled,EFileWrite|EFileShareExclusive);
    if (err!=KErrNone) {CleanupStack::PopAndDestroy(&fs);return EFalse;}
    CleanupClosePushL(file);
    err=file.Write(KMarker());
    CleanupStack::PopAndDestroy(&file);
    if (err!=KErrNone) fs.Delete(KEnabled);
    CleanupStack::PopAndDestroy(&fs);
    return err==KErrNone && EnabledL();
    }
static void CopyCappedL(RFile& aInput,RFile& aOutput,TInt aBytes)
    {
    HBufC8* block=HBufC8::NewLC(8192);
    TPtr8 buffer=block->Des();
    while (aBytes>0)
        {
        buffer.SetLength(0);
        const TInt wanted=aBytes<8192 ? aBytes : 8192;
        User::LeaveIfError(aInput.Read(buffer,wanted));
        if (buffer.Length()==0) User::Leave(KErrCorrupt);
        User::LeaveIfError(aOutput.Write(buffer));
        aBytes-=buffer.Length();
        }
    CleanupStack::PopAndDestroy(block);
    }
TInt E63FileServices::InvokeL(E63JavaService aService,const E63JavaValue* aArgs,
                               unsigned aCount,int32_t* aResult,char* aText,
                               unsigned aCapacity,TBool aConfirmedImport)
    {
    if (!aArgs || !aCount || !aResult ||
        aArgs[0].type!=E63_JAVA_STRING || !aArgs[0].string)
        return -1;
    *aResult=0;
    if (aText && aCapacity) aText[0]=0;
    TBuf<600> path;
    const TBool write=aService!=E63_SERVICE_LIST;
    if (!PathForGuest(aService==E63_SERVICE_IMPORT_FILE && aCount==2u ?
                      aArgs[1].string : aArgs[0].string,write,path)) return -1;
    RFs fs;User::LeaveIfError(fs.Connect());CleanupClosePushL(fs);
    TInt err=EnsureMedia(fs);
    if (err!=KErrNone) {CleanupStack::PopAndDestroy(&fs);return -1;}
    switch (aService)
        {
        case E63_SERVICE_LIST:
            {
            if (!aText || aCapacity<20u)
                {CleanupStack::PopAndDestroy(&fs);return -1;}
            CDir* entries=0;
            TBuf<604> query(path);
            if (query.Length() && query[query.Length()-1]!='\\')
                query.Append(_L("\\"));
            query.Append(_L("*"));
            err=fs.GetDir(query,KEntryAttNormal|KEntryAttDir,ESortByName,entries);
            if (err==KErrNone)
                {
                CleanupStack::PushL(entries);
                unsigned used=0;
                AddBytes(aText,aCapacity,used,"Files: ");
                if (!entries->Count()) AddBytes(aText,aCapacity,used,"(empty)");
                for (TInt i=0;i<entries->Count() && i<12;++i)
                    {
                    if (i) AddBytes(aText,aCapacity,used,", ");
                    AddName(aText,aCapacity,used,(*entries)[i].iName);
                    }
                if (entries->Count()>12) AddBytes(aText,aCapacity,used,", ...");
                CleanupStack::PopAndDestroy(entries);
                }
            break;
            }
        case E63_SERVICE_MKDIR:err=fs.MkDir(path);break;
        case E63_SERVICE_TOUCH:
            {
            RFile file;
            err=file.Create(fs,path,EFileWrite|EFileShareExclusive);
            if (err==KErrNone) file.Close();
            break;
            }
        case E63_SERVICE_RENAME:
            {
            TBuf<600> to;
            TEntry exists;
            if (aCount!=2u || aArgs[1].type!=E63_JAVA_STRING ||
                !PathForGuest(aArgs[1].string,ETrue,to)) err=KErrArgument;
            else if (fs.Entry(to,exists)==KErrNone) err=KErrAlreadyExists;
            else err=fs.Rename(path,to);
            break;
            }
        case E63_SERVICE_DELETE:
            {
            TEntry entry;
            err=fs.Entry(path,entry);
            if (err==KErrNone)
                err=entry.IsDir() ? fs.RmDir(path) : fs.Delete(path);
            break;
            }
        case E63_SERVICE_IMPORT_FILE:
            {
            if (!aConfirmedImport || aCount!=2u || !SimpleName(aArgs[0].string))
                {CleanupStack::PopAndDestroy(&fs);return -1;}
            TBuf<160> from(KImportC);
            AppendUtf8(from,aArgs[0].string,EFalse);
            RFile input;
            err=input.Open(fs,from,EFileRead|EFileShareReadersOnly);
            if (err!=KErrNone)
                {
                from.Copy(KImportE);AppendUtf8(from,aArgs[0].string,EFalse);
                err=input.Open(fs,from,EFileRead|EFileShareReadersOnly);
                }
            if (err!=KErrNone) break;
            CleanupClosePushL(input);
            TInt length=0;
            TEntry source;
            err=fs.Entry(from,source);
            if (err==KErrNone) err=input.Size(length);
            if (err==KErrNone && (source.IsDir() || length<0 ||
                                   length>16*1024*1024)) err=KErrTooBig;
            if (err==KErrNone)
                {
                RFile output;
                err=output.Create(fs,path,EFileWrite|EFileShareExclusive);
                if (err==KErrNone)
                    {
                    CleanupClosePushL(output);
                    TRAPD(copyError,CopyCappedL(input,output,length));
                    err=copyError;
                    CleanupStack::PopAndDestroy(&output);
                    if (err!=KErrNone) fs.Delete(path); // remove partial file
                    }
                }
            CleanupStack::PopAndDestroy(&input);
            break;
            }
        default:CleanupStack::PopAndDestroy(&fs);return -1;
        }
    CleanupStack::PopAndDestroy(&fs);
    if (aService!=E63_SERVICE_LIST && err==KErrNone) *aResult=1;
    return err==KErrNone ? 0 : -1;
    }
