// WORK IN PROGRESS after the preserved Java-APK 0.2 SISX. The old binary's
// Main/GuestActivity/Program DEX preview, shim UI, and J2ME releases remain
// separate and unchanged. This new source maps guest /system to persistent C:
// and deliberately REQUIRES an executable Android framework dispatcher.
// Candidate AOSP 4.2 boot JARs and real APK object constructors can now be
// executed in bounded native DEX; a restricted JNI native ()I exists, but
// there is NO Activity dispatcher, general JNI, Binder OS or Android services.
// Opening an Activity must still fail visibly rather than use 0.2 Host UI
// shims. Do not ship/relabel this as a working Android 4.2 SISX.
#include <e32base.h>
#include <e32std.h>
#include <e32keys.h>
#include <f32file.h>
#include <fbs.h>
#include <coecntrl.h>
#include <eikstart.h>
#include <eikenv.h>
#include <aknapp.h>
#include <akndoc.h>
#include <aknappui.h>
#include <eikspane.h>
#include <eikbtgpc.h>
#include <w32std.h>
#include <string.h>

#include "../runtime/apk_android_bridge.h"
#include "../runtime/apk_image_pack.h"
#include "../runtime/system_image.h"
#include "e63android_commands.hrh"
#include "e63_file_services.h"
#include "e63_system_store.h"
#include "e63_boot_store.h"
#include "e63_binder_port.h"
#include "e63_ui_store.h"

static const TUid KUidE63Java = { 0xE0B63E04 };
_LIT(KImagePack, "C:\\private\\E0B63E04\\images565.bin");
#define PKG_HOME "org.e63.dalvik.launcher"
#define PKG_FILES "org.e63.dalvik.files"
#define PKG_INSTALLER "org.e63.dalvik.packageinstaller"

/* AOSP Java DEX archives are pinned; primitive static methods and some
 * real app+core constructors run separately. A narrow JNI native method and
 * Binder wire core exist, NOT the full Android VM, Binder OS or services.
 * NULL keeps the strict entry
 * fail-closed; never fall back to the old 0.2 UI shim. */
static E63JavaStatus StrictActivityEvent(const E63JavaSession* aSession,
                 E63ActivityState* aState,E63AndroidScreen* aScreen,
                 const E63AndroidBackend* aBackend,const char* aEvent,
                 const E63JavaValue* aArgs,unsigned aCount)
    {
    return e63_android_activity_event_framework(aSession,aState,aScreen,
                                                   aBackend,0,aEvent,aArgs,aCount);
    }

/* MUTF-8 was validated and decoded to scalar UTF-8 by the DEX VM. Convert
 * the full code points to Symbian's UTF-16 descriptors for actual rendering;
 * supplementary characters become surrogate PAIRS (font coverage varies).
 */
static void DrawUtf8(CWindowGc& aGc,const char* aText,TInt aX,TInt aY,
                     TInt aMaxChars)
    {
    TBuf<64> rendered;
    TInt chars=0;
    const unsigned char* input=reinterpret_cast<const unsigned char*>(aText);
    while (input && *input && chars<aMaxChars &&
           rendered.Length()<rendered.MaxLength()-2)
        {
        TUint32 value;
        unsigned first=*input++;
        if (first<0x80u) value=first;
        else if (first<0xe0u && *input)
            {value=((first&31u)<<6)|(*input++&63u);}
        else if (first<0xf0u && input[0] && input[1])
            {value=((first&15u)<<12)|((input[0]&63u)<<6)|(input[1]&63u);
             input+=2;}
        else if (first<0xf5u && input[0] && input[1] && input[2])
            {value=((first&7u)<<18)|((input[0]&63u)<<12)|
                   ((input[1]&63u)<<6)|(input[2]&63u);input+=3;}
        else {value='?';while (*input && (*input&0xc0u)==0x80u) ++input;}
        if (value<=0xffffu) rendered.Append(static_cast<TUint16>(value));
        else
            {
            value-=0x10000u;
            rendered.Append(static_cast<TUint16>(0xd800u+(value>>10)));
            rendered.Append(static_cast<TUint16>(0xdc00u+(value&1023u)));
            }
        ++chars;
        }
    if (input && *input && rendered.Length()<rendered.MaxLength()-3)
        rendered.Append(_L("..."));
    aGc.DrawText(rendered,TPoint(aX,aY));
    }
static void AddUtf8(char* aText,size_t aCapacity,TUint32 aCode)
    {
    size_t at=strlen(aText);
    unsigned width=aCode<0x80u ? 1u : aCode<0x800u ? 2u : 3u;
    if (aCode<32u || aCode>0xffffu ||
        (aCode>=0xd800u && aCode<=0xdfffu) || at+width>=aCapacity)
        return;
    if (width==1u) aText[at++]=static_cast<char>(aCode);
    else if (width==2u)
        {
        aText[at++]=static_cast<char>(0xc0u|(aCode>>6));
        aText[at++]=static_cast<char>(0x80u|(aCode&63u));
        }
    else
        {
        aText[at++]=static_cast<char>(0xe0u|(aCode>>12));
        aText[at++]=static_cast<char>(0x80u|((aCode>>6)&63u));
        aText[at++]=static_cast<char>(0x80u|(aCode&63u));
        }
    aText[at]=0;
    }
static void PopUtf8(char* aText)
    {
    size_t at=strlen(aText);
    if (!at) return;
    do {--at;} while (at &&
        (static_cast<unsigned char>(aText[at])&0xc0u)==0x80u);
    aText[at]=0;
    }

class CE63JavaView : public CCoeControl
    {
public:
    static CE63JavaView* NewL()
        {
        CE63JavaView* self=new (ELeave) CE63JavaView;
        CleanupStack::PushL(self);
        self->ConstructL();
        CleanupStack::Pop(self);
        return self;
        }
    ~CE63JavaView()
        {
        EndActivity();
        for (unsigned i=0;i<E63_ANDROID_ROWS;++i) delete iThumbs[i];
        delete iImagesFile;delete iArchive;delete iScreen;
        }
    void Report(TInt aError)
        {
        if (aError==KErrNone) return;
        strcpy(iNote,aError==KErrNotSupported ?
               "Activity assente. Premi 0: prova DEX AOSP" :
               "System APK missing or untrusted");
        DrawNow();
        }
    TBool BackL()
        {
        if (iEditing)
            {
            iEditing=EFalse;iPendingImport=EFalse;
            iAllowImport=EFalse;DrawNow();return ETrue;
            }
        if (iHistoryCount)
            {
            char previous[E63_ANDROID_PACKAGE];
            strcpy(previous,iHistory[iHistoryCount-1]);
            OpenL(previous,EFalse);
            --iHistoryCount;
            return ETrue;
            }
        if (strcmp(iPackage,PKG_HOME)!=0)
            {
            OpenL(PKG_HOME,EFalse);
            return ETrue;
            }
        return EFalse; // AppUi may exit the HOME, not by D-pad Left.
        }
    void SelectL()
        {
        if (iEditing) { FinishInputL();return; }
        if (!iScreen || iSelected<0 ||
            iSelected>=static_cast<TInt>(iScreen->row_count)) return;
        const E63AndroidRow& row=iScreen->rows[iSelected];
        if (row.kind==E63_ANDROID_INPUT_ROW)
            {
            iEditing=ETrue;iEditStage=0;iPendingImport=EFalse;
            iInputCode=row.id;iInputArity=row.arity;
            iFirst[0]=0;iSecond[0]=0;
            DrawNow();return;
            }
        if (row.kind!=E63_ANDROID_OPTION_ROW) return;
        E63JavaValue arg;
        arg.type=E63_JAVA_INT;arg.number=row.id;arg.string=0;
        TBool confirmed=EFalse;
        if (strcmp(iPackage,PKG_INSTALLER)==0 && row.id==0 &&
            !iFilesEnabled)
            {
            if (!iPendingEnable)
                {
                iPendingEnable=ETrue;
                strcpy(iNote,"Select again: enable bundled Files, NOT Android install");
                DrawNow();return;
                }
            confirmed=ETrue;
            }
        iPendingEnable=EFalse;
        iAllowEnable=confirmed;
        const unsigned prior=iScreen->row_count;
        const E63JavaStatus result=StrictActivityEvent(
            &iSession,&iActivity,iScreen,&iBackend,"choose",&arg,1u);
        iAllowEnable=EFalse;
        if (result!=E63_JAVA_OK)
            { strcpy(iNote,"Guest Java method unsupported");DrawNow();return; }
        if (iScreen->open_package[0])
            {
            char next[E63_ANDROID_PACKAGE];
            strcpy(next,iScreen->open_package);
            TRAPD(err,OpenL(next,ETrue));
            Report(err);
            }
        else
            {
            // GuestActivity.choose() itself decides whether to redraw by
            // executing its DEX, not a C++ row-count approximation.
            iSelected=FirstInteractive();
            iTopRow=iScreen->row_count>prior && iScreen->row_count>6u ?
                static_cast<TInt>(iScreen->row_count)-6 : 0;
            BuildThumbsL();
            }
        DrawNow();
        }
    virtual TKeyResponse OfferKeyEventL(const TKeyEvent& aEvent,TEventCode aType)
        {
        if (aType!=EEventKey) return EKeyWasNotConsumed;
        if (aEvent.iScanCode==EStdKeyDevice0 ||
            aEvent.iScanCode==EStdKeyDevice1) return EKeyWasNotConsumed;
        TInt key=aEvent.iCode;
        if (aEvent.iScanCode==EStdKeyDevice3 || key==EKeyDevice3)
            key=EKeyEnter;
        if (iEditing)
            {
            if (key==EKeyEnter) SelectL();
            else if (key==EKeyBackspace)
                {
                char* field=iEditStage ? iSecond : iFirst;
                PopUtf8(field);
                DrawNow();
                }
            else if (key>=32 && key<=0xffff)
                {
                char* field=iEditStage ? iSecond : iFirst;
                AddUtf8(field,256u,static_cast<TUint32>(key));
                DrawNow();
                }
            return EKeyWasConsumed;
            }
        /* Deliberately separate diagnostic: 0 runs real pinned AOSP Color
         * bytecode, NEVER substitutes for a missing Android Activity. */
        if (key=='0') { ProbeAospDex();return EKeyWasConsumed; }
        /* Typed (int, null ComponentName) constructor; genuine model data,
         * no AppWidgetHost, Widget View or Android UI is started. */
        if (key=='1') { ProbeAospWidgetModel();return EKeyWasConsumed; }
        /* 2 executes FolderInfo constructors + genuine virtual
         * ArrayList.clear via unbind; reads EmptyArray.OBJECT. Still NO UI. */
        if (key=='2') { ProbeAospFolderGraph();return EKeyWasConsumed; }
        /* 3 runs Point(240,320), offset(10,-20), hashCode and its real
         * Parcelable.Creator initializer in framework.jar. NOT a View. */
        if (key=='3') { ProbeAospFrameworkPoint();return EKeyWasConsumed; }
        /* 4 checks pinned Launcher2 DEX class AND compiled HOME manifest,
         * NOT an Android Activity, rendering or lifecycle execution. */
        if (key=='4') { ProbeAospUiClass();return EKeyWasConsumed; }
        /* Genuine Launcher2 DEX primitive helper; no Activity or View. */
        if (key=='5') { ProbeAospUiMethod();return EKeyWasConsumed; }
        /* Real native DEX object allocation/constructors (Launcher2+core).
         * Their visible text is diagnostic host UI, NOT rendered Java Views. */
        if (key=='6') { ProbeAospUiObject(EFalse);return EKeyWasConsumed; }
        if (key=='7') { ProbeAospUiObject(ETrue);return EKeyWasConsumed; }
        /* Ancestor constructor+field lookup from the genuine Launcher model. */
        if (key=='8') { ProbeAospUiModel(EFalse);return EKeyWasConsumed; }
        if (key=='9') { ProbeAospUiModel(ETrue);return EKeyWasConsumed; }
        /* # interprets one real Launcher2 -> framework -> core Java
         * constructor chain. It does NOT instantiate a View/Activity. */
        if (key=='#') { ProbeAospLinkedLayout();return EKeyWasConsumed; }
        /* * registers Process.myPid against its REAL framework.jar native
         * declaration using the JNI 1.6 ABI. Still no Activity or services. */
        if (key=='*') { ProbeAospNativePid();return EKeyWasConsumed; }
        /* B queries a separate Symbian CServer2 thread via RSessionBase.
         * Missing activity service MUST remain missing, never emulated. */
        if (key=='b' || key=='B')
            { ProbeBinderAbsent();return EKeyWasConsumed; }
        if (aEvent.iScanCode==EStdKeyUpArrow || key==EKeyUpArrow)
            MoveSelection(-1);
        else if (aEvent.iScanCode==EStdKeyDownArrow || key==EKeyDownArrow)
            MoveSelection(1);
        else if (key==EKeyEnter) SelectL();
        else return EKeyWasNotConsumed;
        return EKeyWasConsumed;
        }
private:
    void ProbeAospDex()
        {
        RFs fs;
        TInt error=fs.Connect();
        int32_t value=0;
        const int32_t args[4]={255,31,96,224};
        if (error==KErrNone)
            {
            error=E63BootStore::CallStaticInt(fs,"Landroid/graphics/Color;",
                       "argb","(IIII)I",args,4u,&value);
            fs.Close();
            }
        if (error==KErrNone &&
            static_cast<uint32_t>(value)==0xff1f60e0u)
            strcpy(iNote,"AOSP Color.argb DEX eseguito: FF1F60E0");
        else if (error==KErrNotSupported)
            strcpy(iNote,"DEX AOSP: metodo non supportato");
        else if (error==KErrNone)
            strcpy(iNote,"DEX AOSP: risultato errato");
        else
            strcpy(iNote,"DEX AOSP assente o non autenticato");
        DrawNow();
        }
    void ProbeAospNativePid()
        {
        RFs fs;
        TInt error=fs.Connect();
        int32_t processId=0;
        if (error==KErrNone)
            {
            error=E63BootStore::CallNativeProcessPid(fs,&processId);
            fs.Close();
            }
        if (error==KErrNone && processId>0)
            {
            strcpy(iNote,"Process.myPid JNI E63: ");
            TBuf8<16> digits;
            digits.Num(processId);
            const size_t used=strlen(iNote);
            const size_t length=static_cast<size_t>(digits.Length());
            if (length<sizeof(iNote)-used)
                {
                memcpy(iNote+used,digits.Ptr(),length);
                iNote[used+length]=0;
                }
            }
        else if (error==KErrNotSupported)
            strcpy(iNote,"Process.myPid: JNI non supportata");
        else
            strcpy(iNote,"Process.myPid: DEX/JAR non autentici");
        DrawNow();
        }
    void ProbeBinderAbsent()
        {
        TBool absent=EFalse;
        const TInt error=iBinder.CheckAbsent("activity",absent);
        if (error==KErrNone && absent)
            strcpy(iNote,"Binder IPC: ActivityManager ASSENTE");
        else if (error==KErrNone)
            strcpy(iNote,"Binder IPC: handle inatteso, NO UI");
        else
            strcpy(iNote,"Binder IPC non disponibile");
        DrawNow();
        }
    void ProbeAospUiClass()
        {
        RFs fs;
        TInt error=fs.Connect();
        E63UiClassLocation found;
        Mem::FillZ(&found,sizeof(found));
        TBool classOnly=EFalse;
        if (error==KErrNone)
            {
            error=E63UiStore::ResolveComponent(fs,"com.android.launcher",
                                               &found);
            /* The preserved 40-file diagnostic has no AXML cache. Fall back
             * ONLY as an explicit, non-Activity class-only diagnostic: never
             * silently claim an authentic Android HOME declaration. */
            if (error==KErrNotFound || error==KErrPathNotFound)
                {
                classOnly=ETrue;
                error=E63UiStore::ResolveClass(fs,"com.android.launcher",
                           "Lcom/android/launcher2/Launcher;",&found);
                }
            fs.Close();
            }
        if (error==KErrNone && classOnly && found.dex_bytes>0)
            strcpy(iNote,"Launcher2 DEX valido; AXML non confermato, NO UI");
        else if (error==KErrNone && found.dex_bytes>0 &&
            found.is_service==0u && found.manifest_line>0u &&
            found.matching_filters>0u)
            strcpy(iNote,"Launcher2 DEX e AXML HOME autentici, NO UI");
        else if (error==KErrNone)
            strcpy(iNote,"Launcher2: componente inatteso");
        else
            strcpy(iNote,"Launcher2 APK/indice/AXML assenti o non autentici");
        DrawNow();
        }
    void ProbeAospUiMethod()
        {
        RFs fs;
        TInt error=fs.Connect();
        int32_t result=0;
        if (error==KErrNone)
            {
            const int32_t input=33;
            error=E63UiStore::CallStaticInt(fs,"com.android.launcher",
                "Lcom/android/launcher2/Utilities;","roundToPow2","(I)I",
                &input,1u,&result);
            fs.Close();
            }
        if (error==KErrNone && result==64)
            strcpy(iNote,"Launcher2 DEX roundToPow2(33)=64, NO UI");
        else if (error==KErrNotSupported)
            strcpy(iNote,"Launcher2: metodo DEX non supportato");
        else if (error==KErrNone)
            strcpy(iNote,"Launcher2 DEX: risultato errato");
        else
            strcpy(iNote,"Launcher2 APK/DEX assente o non autenticato");
        DrawNow();
        }
    void ProbeAospUiObject(TBool aDrag)
        {
        E63UiObjectField fields[3];
        fields[0].name=aDrag ? "x" : "id";
        fields[0].type_descriptor=aDrag ? "I" : "J";
        fields[1].name=aDrag ? "y" : "screen";
        fields[1].type_descriptor="I";
        fields[2].name=aDrag ? "deferDragViewCleanupPostAnimation" : "spanX";
        fields[2].type_descriptor=aDrag ? "Z" : "I";
        fields[0].value=fields[1].value=fields[2].value=0u;
        RFs fs;
        TInt error=fs.Connect();
        if (error==KErrNone)
            {
            error=E63UiStore::ConstructObjectFields(fs,"com.android.launcher",
                aDrag ? "Lcom/android/launcher2/DropTarget$DragObject;" :
                        "Lcom/android/launcher2/ItemInfo;",
                aDrag ? 0 : "unbind",fields,3u);
            fs.Close();
            }
        if (error==KErrNone &&
            fields[0].value==(aDrag ? 0xffffffffu : ~static_cast<uint64_t>(0u)) &&
            fields[1].value==0xffffffffu && fields[2].value==1u)
            strcpy(iNote,aDrag ? "DragObject <init> DEX AOSP OK, NO UI" :
                                 "ItemInfo <init>/unbind DEX OK, NO UI");
        else if (error==KErrNotSupported)
            strcpy(iNote,"Oggetto AOSP: DEX non supportato, NO UI");
        else if (error==KErrNone)
            strcpy(iNote,"Oggetto AOSP: campi DEX inattesi, NO UI");
        else
            strcpy(iNote,"Oggetto AOSP: APK/core/DEX non autentici");
        DrawNow();
        }
    void ProbeAospUiModel(TBool aShortcut)
        {
        E63UiObjectField fields[3];
        fields[0].name="id";
        fields[0].type_descriptor="J";
        fields[1].name="itemType";
        fields[1].type_descriptor="I";
        fields[2].name=aShortcut ? "spanX" : "flags";
        fields[2].type_descriptor="I";
        fields[0].value=fields[1].value=fields[2].value=0u;
        RFs fs;
        TInt error=fs.Connect();
        if (error==KErrNone)
            {
            error=E63UiStore::ConstructObjectFields(fs,"com.android.launcher",
                aShortcut ? "Lcom/android/launcher2/ShortcutInfo;" :
                            "Lcom/android/launcher2/ApplicationInfo;",
                "unbind",fields,3u);
            fs.Close();
            }
        if (error==KErrNone && fields[0].value==~static_cast<uint64_t>(0u) &&
            fields[1].value==1u && fields[2].value==(aShortcut ? 1u : 0u))
            strcpy(iNote,aShortcut ? "ShortcutInfo+ItemInfo+core DEX OK, NO UI" :
                                  "ApplicationInfo+ItemInfo+core DEX OK, NO UI");
        else if (error==KErrNotSupported)
            strcpy(iNote,"Modello Launcher: DEX non supportato");
        else if (error==KErrNone)
            strcpy(iNote,"Modello Launcher: campi DEX inattesi");
        else
            strcpy(iNote,"Modello Launcher: APK/core non autentici");
        DrawNow();
        }
    void ProbeAospFrameworkPoint()
        {
        E63ObjectArg arguments[2]={{"I",240u},{"I",320u}};
        E63BootObjectField fields[2]={
            {"x","I",0u},{"y","I",0u}
            };
        E63BootStaticProbe creator={
            "Landroid/graphics/Point;","CREATOR",
            "Landroid/os/Parcelable$Creator;",
            "Landroid/graphics/Point$1;",0u
            };
        E63ObjectArg offsets[2]={{"I",10u},{"I",0xffffffecu}};
        E63BootMethodProbe method={"offset",offsets,2u,"hashCode","I",0};
        RFs fs;
        TInt error=fs.Connect();
        if (error==KErrNone)
            {
            error=E63BootStore::ProbeObject(fs,
                "Landroid/graphics/Point;",arguments,2u,fields,2u,
                &creator,&method);
            fs.Close();
            }
        if (error==KErrNone && fields[0].value==250u &&
            fields[1].value==300u && creator.reference>1u &&
            method.result==8050)
            strcpy(iNote,"Point DEX x250 y300 hash8050 Creator NO UI");
        else if (error==KErrNotSupported)
            strcpy(iNote,"Point: DEX framework non supportato, NO UI");
        else if (error==KErrNone)
            strcpy(iNote,"Point: campi DEX inattesi, NO UI");
        else
            strcpy(iNote,"Point: framework/core non autenticati");
        DrawNow();
        }
    void ProbeAospFolderGraph()
        {
        E63UiObjectField fields[4]={
            {"id","J",0u},{"itemType","I",0u},
            {"contents","Ljava/util/ArrayList;",0u},
            {"listeners","Ljava/util/ArrayList;",0u}
            };
        E63UiObjectGraphField graph[6]={
            {"contents","Ljava/util/ArrayList;","size","I",0u,0u,0u,
                                                    "size","I",0},
            {"listeners","Ljava/util/ArrayList;","size","I",0u,0u,0u,
                                                    "size","I",0},
            {"contents","Ljava/util/ArrayList;","array",
                        "[Ljava/lang/Object;",1u,0u,0u,"isEmpty","Z",0},
            {"listeners","Ljava/util/ArrayList;","array",
                        "[Ljava/lang/Object;",1u,0u,0u,"isEmpty","Z",0},
            {"contents","Ljava/util/ArrayList;","modCount","I",0u,0u,0u,
                                                    0,0,0},
            {"listeners","Ljava/util/ArrayList;","modCount","I",0u,0u,0u,
                                                    0,0,0}
            };
        RFs fs;
        TInt error=fs.Connect();
        if (error==KErrNone)
            {
            error=E63UiStore::ConstructObjectGraphFields(fs,
                "com.android.launcher","Lcom/android/launcher2/FolderInfo;",
                0,0u,"unbind",fields,4u,graph,6u);
            fs.Close();
            }
        if (error==KErrNone &&
            fields[0].value==~static_cast<uint64_t>(0u) &&
            fields[1].value==2u &&
            fields[2].value>1u && fields[3].value>1u &&
            fields[2].value!=fields[3].value &&
            graph[0].value==0u && graph[1].value==0u &&
            graph[2].value>0u && graph[2].value==graph[3].value &&
            graph[2].array_length==0u && graph[3].array_length==0u &&
            graph[4].value==0u && graph[5].value==0u &&
            graph[0].method_result==0 && graph[1].method_result==0 &&
            graph[2].method_result==1 && graph[3].method_result==1)
            strcpy(iNote,"FolderInfo + List.size/isEmpty DEX, NO UI");
        else if (error==KErrNotSupported)
            strcpy(iNote,"FolderInfo: DEX non supportato, NO UI");
        else if (error==KErrNone)
            strcpy(iNote,"FolderInfo: heap DEX inatteso, NO UI");
        else
            strcpy(iNote,"FolderInfo: APK/core/DEX non autentici");
        DrawNow();
        }
    void ProbeAospWidgetModel()
        {
        E63ObjectArg arguments[2];
        arguments[0].type_descriptor="I";
        arguments[0].bits=37u;
        arguments[1].type_descriptor="Landroid/content/ComponentName;";
        arguments[1].bits=0u; // typed Java null, NOT a fake ComponentName
        E63UiObjectField fields[4];
        fields[0].name="appWidgetId";
        fields[0].type_descriptor="I";
        fields[1].name="itemType";
        fields[1].type_descriptor="I";
        fields[2].name="spanX";
        fields[2].type_descriptor="I";
        fields[3].name="providerName";
        fields[3].type_descriptor="Landroid/content/ComponentName;";
        unsigned i;
        for (i=0u;i<4u;++i) fields[i].value=0u;
        RFs fs;
        TInt error=fs.Connect();
        if (error==KErrNone)
            {
            error=E63UiStore::ConstructObjectFieldsWithArgs(fs,
                "com.android.launcher",
                "Lcom/android/launcher2/LauncherAppWidgetInfo;",
                arguments,2u,"unbind",fields,4u);
            fs.Close();
            }
        if (error==KErrNone && fields[0].value==37u &&
            fields[1].value==4u && fields[2].value==0xffffffffu &&
            fields[3].value==0u)
            strcpy(iNote,"WidgetInfo(37,null) DEX eseguito, NO UI");
        else if (error==KErrNotSupported)
            strcpy(iNote,"WidgetInfo: DEX non supportato, NO UI");
        else if (error==KErrNone)
            strcpy(iNote,"WidgetInfo: campi DEX inattesi, NO UI");
        else
            strcpy(iNote,"WidgetInfo: APK/core/DEX non autentici");
        DrawNow();
        }
    void ProbeAospLinkedLayout()
        {
        E63ObjectArg arguments[4]={{"I",1u},{"I",2u},
                                    {"I",3u},{"I",4u}};
        E63ObjectArg margins[4]={{"I",11u},{"I",12u},
                                  {"I",13u},{"I",14u}};
        E63UiObjectField fields[8]={
            {"cellX","I",0u},{"cellY","I",0u},
            {"width","I",0u},{"height","I",0u},
            {"layoutDirection","I",0u},
            {"canReorder","Z",0u},
            {"leftMargin","I",0u},{"rightMargin","I",0u}
            };
        RFs fs;
        TInt error=fs.Connect();
        if (error==KErrNone)
            {
            error=E63UiStore::ConstructLinkedObjectFieldsWithMethod(fs,
                "com.android.launcher",
                "Lcom/android/launcher2/CellLayout$LayoutParams;",
                "Landroid/view/ViewGroup$MarginLayoutParams;",
                arguments,4u,"setMargins",margins,4u,fields,8u);
            fs.Close();
            }
        if (error==KErrNone && fields[0].value==1u &&
            fields[1].value==2u && fields[2].value==0xffffffffu &&
            fields[3].value==0xffffffffu &&
            fields[4].value==0xffffffffu && fields[5].value==1u &&
            fields[6].value==11u && fields[7].value==13u)
            strcpy(iNote,"APK/framework/core setMargins DEX, NO UI");
        else if (error==KErrNotSupported)
            strcpy(iNote,"LayoutParams: DEX non supportato, NO UI");
        else if (error==KErrNone)
            strcpy(iNote,"LayoutParams: campi DEX inattesi, NO UI");
        else
            strcpy(iNote,"LayoutParams: APK/JAR/DEX non autentici");
        DrawNow();
        }
    CE63JavaView() : iArchive(0),iImagesFile(0),iScreen(0),iSelected(-1),
                     iTopRow(0),iHistoryCount(0),iEditing(EFalse),
                     iEditStage(0),iInputCode(0),iInputArity(0),
                     iWifi(0),iClock(0),iFilesEnabled(EFalse),
                     iPendingEnable(EFalse),iAllowEnable(EFalse),
                     iPendingImport(EFalse),iAllowImport(EFalse)
        {
        Mem::FillZ(&iSession,sizeof(iSession));
        Mem::FillZ(&iActivity,sizeof(iActivity));
        Mem::FillZ(&iImages,sizeof(iImages));
        Mem::FillZ(iThumbs,sizeof(iThumbs));
        iPackage[0]=0;iFirst[0]=0;iSecond[0]=0;iNote[0]=0;
        iBackend.context=this;iBackend.device=Device;
        }
    void ConstructL()
        {
        iScreen=new (ELeave) E63AndroidScreen;
        Mem::FillZ(iScreen,sizeof(*iScreen));
        ReadImagesL(); // SHA-256 of offline PNG->RGB565 pack, fail closed
        iFilesEnabled=E63FileServices::EnabledL();
        /* Launch a broker thread, NOT a disk-mapped /dev/binder node.
         * Failure is visible via B; it cannot turn into a fake service. */
        iBinder.Start();
        CreateWindowL();
        SetRect(TRect(TPoint(0,0),TSize(320,240)));
        ActivateL();
        /* Primitive AOSP bytecode can run in a separate diagnostic, but
         * Activity lifecycle execution is still absent. Fail visibly. */
        TRAPD(bootError,OpenL(PKG_HOME,EFalse));
        Report(bootError);
        }
    static TInt Device(void* aContext,E63JavaService aService,
                       const E63JavaValue* aArgs,unsigned aCount,
                       int32_t* aResult,char* aText,unsigned aCapacity)
        {
        CE63JavaView* self=static_cast<CE63JavaView*>(aContext);
        if (aCount==0 || aArgs[0].type!=E63_JAVA_STRING ||
            !aArgs[0].string || !aResult) return -1;
        const char* key=aArgs[0].string;
        if (aService==E63_SERVICE_IS_INSTALLED)
            {
            if (strcmp(key,PKG_FILES)==0)
                {
                TBool enabled=EFalse;
                TRAPD(err,enabled=E63FileServices::EnabledL());
                self->iFilesEnabled=err==KErrNone && enabled;
                *aResult=self->iFilesEnabled ? 1 : 0;
                }
            else *aResult=e63_session_apk_name(key)!=0;
            return 0;
            }
        if (aService==E63_SERVICE_INSTALL)
            {
            if (!self->iAllowEnable || strcmp(self->iPackage,PKG_INSTALLER)!=0 ||
                strcmp(key,PKG_FILES)!=0) return -1;
            TBool enabled=EFalse;
            TRAPD(err,enabled=E63FileServices::EnableBundledL());
            self->iFilesEnabled=err==KErrNone && enabled;
            *aResult=self->iFilesEnabled ? 1 : 0;
            // This only registers an already-bundled, SHA-256 pinned guest APK
            // after TWO Select presses. It is NOT a Symbian/Android install.
            return self->iFilesEnabled ? 0 : -1;
            }
        if (aService==E63_SERVICE_GET_FLAG)
            {
            *aResult=strcmp(key,"wifi_demo")==0 ? self->iWifi : self->iClock;
            return 0;
            }
        if (aService==E63_SERVICE_SET_FLAG && aCount==2u)
            {
            if (strcmp(key,"wifi_demo")==0) self->iWifi=aArgs[1].number;
            else self->iClock=aArgs[1].number;
            return 0; // preview state, no real radio/clock changes
            }
        if (aService==E63_SERVICE_LIST || aService==E63_SERVICE_MKDIR ||
            aService==E63_SERVICE_TOUCH || aService==E63_SERVICE_RENAME ||
            aService==E63_SERVICE_DELETE || aService==E63_SERVICE_IMPORT_FILE)
            {
            if (!self->iFilesEnabled) return -1;
            TInt result=-1;
            TRAPD(err,result=E63FileServices::InvokeL(aService,aArgs,aCount,
                  aResult,aText,aCapacity,self->iAllowImport));
            return err==KErrNone ? result : -1;
            }
        // No invented WAV playback, Nokia Wi-Fi or OS package installer.
        return -1;
        }
    void ReadImagesL()
        {
        RFs fs;
        User::LeaveIfError(fs.Connect());
        CleanupClosePushL(fs);
        RFile file;
        User::LeaveIfError(file.Open(fs,KImagePack,EFileRead|EFileShareReadersOnly));
        CleanupClosePushL(file);
        TInt length=0;
        User::LeaveIfError(file.Size(length));
        if (length<16 || length>1024*1024) User::Leave(KErrCorrupt);
        HBufC8* images=HBufC8::NewLC(length);
        TPtr8 data=images->Des();
        User::LeaveIfError(file.Read(data));
        if (data.Length()!=length ||
            !e63_apk_images_open(&iImages,data.Ptr(),length))
            User::Leave(KErrCorrupt);
        CleanupStack::Pop(images);
        CleanupStack::PopAndDestroy(&file);
        CleanupStack::PopAndDestroy(&fs);
        iImagesFile=images;
        }
    void BuildThumbsL()
        {
        for (unsigned i=0;i<E63_ANDROID_ROWS;++i)
            {delete iThumbs[i];iThumbs[i]=0;}
        for (unsigned i=0;i<iScreen->row_count;++i)
            {
            const E63AndroidRow& row=iScreen->rows[i];
            if (row.kind!=E63_ANDROID_IMAGE_ROW) continue;
            E63ApkImage image;
            if (!e63_session_owns_asset(&iSession,row.text) ||
                !e63_apk_images_find(&iImages,iSession.package_name,
                                     row.text,&image)) User::Leave(KErrCorrupt);
            iThumbs[i]=new (ELeave) CFbsBitmap;
            User::LeaveIfError(iThumbs[i]->Create(TSize(52,21),EColor64K));
            const TInt pitch=CFbsBitmap::ScanLineLength(52,EColor64K);
            if (pitch<104) User::Leave(KErrCorrupt);
            iThumbs[i]->LockHeap();
            TUint8* dst=reinterpret_cast<TUint8*>(iThumbs[i]->DataAddress());
            if (!dst)
                {iThumbs[i]->UnlockHeap();User::Leave(KErrCorrupt);}
            for (TInt y=0;y<21;++y) for (TInt x=0;x<52;++x)
                {
                const unsigned sx=static_cast<unsigned>(x)*image.width/52u;
                const unsigned sy=static_cast<unsigned>(y)*image.height/21u;
                Mem::Copy(dst+y*pitch+x*2,
                          image.pixels_le+(sy*image.width+sx)*2u,2);
                }
            iThumbs[i]->UnlockHeap();
            }
        }
    void OpenL(const char* aPackage,TBool aPush)
        {
        const char* filename=e63_session_apk_name(aPackage);
        const char* guest=e63_system_app_path(aPackage);
        E63SystemFile system_file;
        if (!filename || !guest ||
            e63_system_find(guest,&system_file)!=E63_SYSTEM_OK ||
            strcmp(filename,guest+strlen("/system/app/"))!=0 ||
            (aPush && iHistoryCount>=8) ||
            (strcmp(aPackage,PKG_FILES)==0 && !iFilesEnabled))
            User::Leave(KErrNotSupported);
        /* Indexed /system is persisted on C:. Open and hash in small chunks,
         * not by loading the entire guest system into RAM. */
        RFs fs;
        User::LeaveIfError(fs.Connect());
        CleanupClosePushL(fs);
        RFile file;
        User::LeaveIfError(E63SystemStore::OpenPinned(fs,guest,file,&system_file));
        CleanupClosePushL(file);
        TInt bytes=0;
        User::LeaveIfError(file.Size(bytes));
        if (bytes<112 || static_cast<TUint>(bytes)>E63_APK_MAX_BYTES ||
            static_cast<size_t>(bytes)!=system_file.bytes)
            User::Leave(KErrCorrupt);
        HBufC8* fresh=HBufC8::NewLC(bytes);
        TPtr8 contents=fresh->Des();
        User::LeaveIfError(file.Read(contents));
        if (contents.Length()!=bytes ||
            e63_system_verify(&system_file,contents.Ptr(),
                              static_cast<size_t>(bytes))!=E63_SYSTEM_OK)
            User::Leave(KErrCorrupt);
        CleanupStack::Pop(fresh);
        CleanupStack::PopAndDestroy(&file);
        CleanupStack::PopAndDestroy(&fs);
        E63JavaSession verified;
        if (e63_session_open(&verified,aPackage,fresh->Ptr(),bytes)
            !=E63_SESSION_OK) {delete fresh;User::Leave(KErrCorrupt);}
        E63AndroidScreen next;
        Mem::FillZ(&next,sizeof(next));
        E63ActivityState entering;
        Mem::FillZ(&entering,sizeof(entering));
        if (StrictActivityEvent(&verified,&entering,&next,&iBackend,
                                       "onCreate",0,0u)!=E63_JAVA_OK ||
            StrictActivityEvent(&verified,&entering,&next,&iBackend,
                                       "onStart",0,0u)!=E63_JAVA_OK ||
            StrictActivityEvent(&verified,&entering,&next,&iBackend,
                                       "onResume",0,0u)!=E63_JAVA_OK)
            {delete fresh;User::Leave(KErrNotSupported);}
        if (aPush) strcpy(iHistory[iHistoryCount++],iPackage);
        EndActivity();
        delete iArchive;
        iArchive=fresh;iSession=verified;iActivity=entering;*iScreen=next;
        strcpy(iPackage,aPackage);
        iSelected=FirstInteractive();iTopRow=0;iNote[0]=0;iEditing=EFalse;
        iPendingEnable=EFalse;iPendingImport=EFalse;
        BuildThumbsL();
        DrawNow();
        }
    void EndActivity()
        {
        if (!iArchive || !iScreen || !iActivity.created) return;
        if (iActivity.resumed)
            StrictActivityEvent(&iSession,&iActivity,iScreen,&iBackend,
                                       "onPause",0,0u);
        if (iActivity.started)
            StrictActivityEvent(&iSession,&iActivity,iScreen,&iBackend,
                                       "onStop",0,0u);
        StrictActivityEvent(&iSession,&iActivity,iScreen,&iBackend,
                                   "onDestroy",0,0u);
        }
    TInt FirstInteractive() const
        {
        for (unsigned i=0;i<iScreen->row_count;++i)
            if (Interactive(i)) return static_cast<TInt>(i);
        return -1;
        }
    TBool Interactive(unsigned aRow) const
        {
        return iScreen->rows[aRow].kind==E63_ANDROID_OPTION_ROW ||
               iScreen->rows[aRow].kind==E63_ANDROID_INPUT_ROW;
        }
    void MoveSelection(TInt aDelta)
        {
        if (!iScreen || iSelected<0) return;
        TInt row=iSelected;
        do {
            row+=aDelta;
            if (row<0) row=static_cast<TInt>(iScreen->row_count)-1;
            if (row>=static_cast<TInt>(iScreen->row_count)) row=0;
        } while (row!=iSelected && !Interactive(row));
        iSelected=row;
        if (row<iTopRow) iTopRow=row;
        if (row>=iTopRow+6) iTopRow=row-5;
        DrawNow();
        }
    void FinishInputL()
        {
        if (iInputArity==2 && iEditStage==0)
            {iEditStage=1;DrawNow();return;}
        if (iInputCode==5 && !iPendingImport)
            {
            iPendingImport=ETrue;
            strcpy(iNote,"Select again: import from C:Data or E:Others");
            DrawNow();return;
            }
        iAllowImport=iInputCode==5 && iPendingImport;
        iPendingImport=EFalse;
        E63JavaValue args[3];
        args[0].type=E63_JAVA_INT;args[0].number=iInputCode;args[0].string=0;
        args[1].type=E63_JAVA_STRING;args[1].number=0;args[1].string=iFirst;
        args[2].type=E63_JAVA_STRING;args[2].number=0;args[2].string=iSecond;
        iEditing=EFalse;
        if (StrictActivityEvent(&iSession,&iActivity,iScreen,&iBackend,
                                       "command",args,3u)!=E63_JAVA_OK)
            strcpy(iNote,"Guest Java command unsupported");
        iAllowImport=EFalse;
        if (iScreen->row_count>6u) iTopRow=iScreen->row_count-6u;
        DrawNow();
        }
    void Draw(const TRect&) const
        {
        CWindowGc& gc=SystemGc();
        gc.SetBrushStyle(CGraphicsContext::ESolidBrush);
        gc.SetBrushColor(TRgb(16,16,16));gc.Clear(Rect());
        const CFont* font=CEikonEnv::Static()->NormalFont();
        if (font) gc.UseFont(font);
        gc.SetPenColor(TRgb(210,210,210));
        gc.DrawText(_L("E63 Java DEX"),TPoint(7,14));
        TTime time;time.HomeTime();
        TDateTime now=time.DateTime();
        TBuf<8> clock;
        clock.AppendNumFixedWidth(now.Hour(),EDecimal,2);
        clock.Append(':');
        clock.AppendNumFixedWidth(now.Minute(),EDecimal,2);
        gc.DrawText(clock,TPoint(260,14));
        gc.DrawText(_L("?"),TPoint(309,14)); // actual Nokia battery not wired
        gc.SetBrushColor(TRgb(30,30,30));
        gc.DrawRect(TRect(0,18,320,44));
        gc.SetPenColor(TRgb(51,181,229));
        if (iScreen) DrawUtf8(gc,iScreen->title,7,37,39);
        /* Diagnostic UI, explicitly NOT an Android Activity rendering. */
        if (iScreen && !iScreen->row_count)
            {
            gc.SetPenColor(TRgb(235,235,235));
            gc.DrawText(_L("AOSP 4.2 DEX diagnostic"),TPoint(11,87));
            gc.DrawText(_L("Activity Android: non avviabile"),TPoint(11,123));
            gc.DrawText(_L("0 Color 1 Widget 2 Folder 3 Point"),
                        TPoint(11,148));
            gc.DrawText(_L("4 HOME 5 Helper 6 Item 7 Drag"),TPoint(11,173));
            gc.DrawText(_L("8 App 9 Shortcut # Layout * JNI; NO UI"),
                        TPoint(11,198));
            }
        if (iScreen) for (TInt row=iTopRow;row<iTopRow+6 &&
                          row<static_cast<TInt>(iScreen->row_count);++row)
            {
            const E63AndroidRow& item=iScreen->rows[row];
            const TInt y=46+(row-iTopRow)*27;
            const TBool choice=Interactive(row);
            gc.SetBrushColor(row==iSelected ? TRgb(28,72,91) :
                             choice ? TRgb(36,36,36) : TRgb(20,20,20));
            gc.SetPenColor(row==iSelected ? TRgb(51,181,229) : TRgb(42,42,42));
            gc.DrawRect(TRect(3,y,317,y+25));
            gc.SetPenColor(item.kind==E63_ANDROID_DIALOG_ROW ?
                           TRgb(255,115,115) : TRgb(235,235,235));
            if (item.kind==E63_ANDROID_IMAGE_ROW && iThumbs[row])
                gc.BitBlt(TPoint(8,y+2),iThumbs[row]);
            DrawUtf8(gc,item.text,item.kind==E63_ANDROID_IMAGE_ROW ? 67 : 8,
                      y+17,item.kind==E63_ANDROID_IMAGE_ROW ? 34 : 44);
            }
        gc.SetBrushColor(TRgb(29,29,29));gc.SetPenColor(TRgb(51,181,229));
        gc.DrawRect(TRect(0,210,320,240));
        if (iEditing)
            {
            if (iEditStage) gc.DrawText(_L("TO:"),TPoint(4,229));
            else gc.DrawText(_L("TEXT:"),TPoint(4,229));
            DrawUtf8(gc,iEditStage ? iSecond : iFirst,54,229,35);
            }
        else if (iNote[0]) DrawUtf8(gc,iNote,7,229,43);
        else gc.DrawText(_L("Back               Select"),TPoint(6,229));
        if (font) gc.DiscardFont();
        }
private:
    HBufC8* iArchive; // borrowed by iSession.dex until next package/close
    HBufC8* iImagesFile;
    E63ApkImages iImages;
    CFbsBitmap* iThumbs[E63_ANDROID_ROWS];
    E63JavaSession iSession;
    E63ActivityState iActivity;
    E63AndroidScreen* iScreen;
    E63AndroidBackend iBackend;
    E63BinderPort iBinder; /* Symbian IPC broker, no /dev backing storage */
    char iPackage[E63_ANDROID_PACKAGE];
    char iHistory[8][E63_ANDROID_PACKAGE];
    TInt iSelected,iTopRow,iHistoryCount;
    TBool iEditing;
    TInt iEditStage,iInputCode,iInputArity;
    char iFirst[256],iSecond[256],iNote[96];
    TInt iWifi,iClock;
    TBool iFilesEnabled,iPendingEnable,iAllowEnable;
    TBool iPendingImport,iAllowImport;
    };

class CE63JavaAppUi : public CAknAppUi
    {
public:
    CE63JavaAppUi() : iView(0) {}
    ~CE63JavaAppUi() {if (iView) {RemoveFromStack(iView);delete iView;}}
    void ConstructL()
        {
        BaseConstructL();
        if (StatusPane()) StatusPane()->MakeVisible(EFalse);
        if (Cba()) Cba()->MakeVisible(EFalse);
        iView=CE63JavaView::NewL();
        AddToStackL(iView);iView->SetFocus(ETrue);
        }
    void HandleCommandL(TInt aCommand)
        {
        if (aCommand==EE63JavaBack) {DispatchSoftkey(ETrue);return;}
        if (aCommand==EE63JavaSelect) {DispatchSoftkey(EFalse);return;}
        if (aCommand==EEikCmdExit || aCommand==EAknSoftkeyExit) Exit();
        }
protected:
    virtual void HandleWsEventL(const TWsEvent& aEvent,CCoeControl* aDestination)
        {
        const TInt type=aEvent.Type();
        if (iView && (type==EEventKeyDown || type==EEventKey ||
                      type==EEventKeyUp))
            {
            const TKeyEvent* key=aEvent.Key();
            if (key && (key->iScanCode==EStdKeyDevice0 ||
                        key->iScanCode==EStdKeyDevice1))
                {
                if (type==EEventKeyDown)
                    DispatchSoftkey(key->iScanCode==EStdKeyDevice0);
                return; // Physical left is Back; D-pad Left is NOT Back.
                }
            }
        CAknAppUi::HandleWsEventL(aEvent,aDestination);
        }
private:
    void DispatchSoftkey(TBool aBack)
        {
        if (!iView) return;
        if (aBack)
            {
            TBool handled=ETrue;
            TRAPD(err,handled=iView->BackL());
            if (err==KErrNone && !handled) Exit();
            else iView->Report(err);
            }
        else
            {
            TRAPD(err,iView->SelectL());
            iView->Report(err);
            }
        }
    CE63JavaView* iView;
    };
class CE63JavaDocument : public CAknDocument
    {
public:
    explicit CE63JavaDocument(CEikApplication& aApp):CAknDocument(aApp) {}
    CEikAppUi* CreateAppUiL() {return new (ELeave) CE63JavaAppUi;}
    };
class CE63JavaApplication : public CAknApplication
    {
public:
    TUid AppDllUid() const {return KUidE63Java;}
    CApaDocument* CreateDocumentL()
        {return new (ELeave) CE63JavaDocument(*this);}
    };
static CApaApplication* NewApplication() {return new CE63JavaApplication;}
GLDEF_C TInt E32Main() {return EikStart::RunApplication(NewApplication);}
