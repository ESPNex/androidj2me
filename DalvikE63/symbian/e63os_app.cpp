// Symbian 9.2 / E63 native host for the ORIGINAL J2ME E63Canvas.paint DEX.
// No host screen layout: guest methods choose every draw operation. Unported
// guest bytecode fails closed and never becomes a fake native screen.
// GCCE/UREL 0.2.1: Home and Fn numeric shortcuts seen on an E63.
// Physical softkey and D-pad changes below need a fresh phone test.
#include <e32base.h>
#include <e32std.h>
#include <fbs.h>
#include <coecntrl.h>
#include <eikstart.h>
#include <aknapp.h>
#include <akndoc.h>
#include <aknappui.h>
#include <eikspane.h>
#include <eikbtgpc.h>
#include <e32keys.h>
#include <w32std.h>
#include <f32file.h>
#include "e63os_commands.hrh"
#include <string.h>

#include "runtime/dex_preflight.h"
#include "runtime/ui_event_vm.h"
#include "runtime/rgb565_painter.h"

static const TUid KUidE63Os = { 0xE0B63E02 };
_LIT(KDexPath, "C:\\private\\E0B63E02\\classes.dex");
_LIT(KResourcesPath, "C:\\private\\E0B63E02\\e63assets.bin");
#define MIDLET "Landroid/j2me/edition/E63Midlet;"
#define CANVAS "Landroid/j2me/edition/E63Canvas;"
#define STORE "Landroid/j2me/edition/StoreState;"
#define GRAPHICS "Ljavax/microedition/lcdui/Graphics;"
#define FONT "Ljavax/microedition/lcdui/Font;"
#define IMAGE "Ljavax/microedition/lcdui/Image;"
#define PAINT "(Ljavax/microedition/lcdui/Graphics;)V"

static TUint32 Read32(const TUint8* p)
    {
    return static_cast<TUint32>(p[0]) |
           (static_cast<TUint32>(p[1]) << 8) |
           (static_cast<TUint32>(p[2]) << 16) |
           (static_cast<TUint32>(p[3]) << 24);
    }

static HBufC8* ReadBoundedFileL(const TDesC& aPath, TInt aMaximum)
    {
    RFs fs;
    User::LeaveIfError(fs.Connect());
    CleanupClosePushL(fs);
    RFile file;
    User::LeaveIfError(file.Open(fs, aPath, EFileRead | EFileShareReadersOnly));
    CleanupClosePushL(file);
    TInt length = 0;
    User::LeaveIfError(file.Size(length));
    if (length < 112 || length > aMaximum) User::Leave(KErrCorrupt);
    HBufC8* content = HBufC8::NewLC(length);
    TPtr8 data = content->Des();
    User::LeaveIfError(file.Read(data));
    if (data.Length() != length) User::Leave(KErrCorrupt);
    CleanupStack::Pop(content);
    CleanupStack::PopAndDestroy(&file);
    CleanupStack::PopAndDestroy(&fs);
    return content;
    }

class CE63OsView : public CCoeControl
    {
public:
    static CE63OsView* NewL()
        {
        CE63OsView* self = new (ELeave) CE63OsView;
        CleanupStack::PushL(self);
        self->ConstructL();
        CleanupStack::Pop(self);
        return self;
        }
    ~CE63OsView()
        {
        e63_ui_free(iVm);
        e63_rgb565_free(iRaster);
        delete iBitmap;
        delete iAssets;
        delete iDexFile;
        }
    TBool DispatchGuestKey(TInt aKey)
        {
        if (!iVm) return EFalse;
        const int32_t args[1] = { aKey };
        return e63_ui_call(iVm,iCanvas,"keyPressed","(I)V",args,1u,0)
               == E63_UI_OK && PaintGuest();
        }
    TInt GuestScreen() const
        {
        if (!iVm) return -1;
        const TInt field=e63_dex_field_id(&iDex,MIDLET,"screen","I");
        int32_t screen=-1;
        return field>=0 && e63_ui_get_int(iVm,iMidlet,field,&screen)==E63_UI_OK
               ? screen : -1;
        }
    virtual TKeyResponse OfferKeyEventL(const TKeyEvent& aKeyEvent, TEventCode aType)
        {
        if (aType!=EEventKey || !iVm) return EKeyWasNotConsumed;
        // The hidden S60 CBA intercepts softkeys; AppUi routes the physical
        // buttons to guest Back/Select before the CBA can open Options/Exit.
        if (aKeyEvent.iScanCode==EStdKeyDevice0 ||
            aKeyEvent.iScanCode==EStdKeyDevice1) return EKeyWasNotConsumed;
        TInt key=aKeyEvent.iCode;
        switch (aKeyEvent.iScanCode)
            {
            case EStdKeyUpArrow: key=-1001; break;
            case EStdKeyDownArrow: key=-1002; break;
            case EStdKeyLeftArrow: key=-1003; break;
            case EStdKeyRightArrow: key=-1004; break;
            case EStdKeyDevice3: key=-1005; break; // centre selection
            default:
                // Some S60 keyboard maps expose only the translated keycode.
                switch (aKeyEvent.iCode)
                    {
                    case EKeyUpArrow: key=-1001; break;
                    case EKeyDownArrow: key=-1002; break;
                    case EKeyLeftArrow: key=-1003; break;
                    case EKeyRightArrow: key=-1004; break;
                    case EKeyDevice3: key=-1005; break;
                    default: break;
                    }
                break;
            }
        DispatchGuestKey(key);
        return EKeyWasConsumed;
        }
    virtual void HandlePointerEventL(const TPointerEvent& aPointerEvent)
        {
        if (aPointerEvent.iType == TPointerEvent::EButton1Down && iVm)
            {
            const int32_t args[2] = { aPointerEvent.iPosition.iX,
                                      aPointerEvent.iPosition.iY };
            if (e63_ui_call(iVm, iCanvas, "pointerPressed", "(II)V", args, 2u, 0)
                == E63_UI_OK) PaintGuest();
            }
        CCoeControl::HandlePointerEventL(aPointerEvent);
        }
private:
    CE63OsView() : iDexFile(0), iAssets(0), iBitmap(0), iRaster(0), iVm(0),
                    iMidlet(0), iCanvas(0), iGraphics(0), iImageCount(0),
                    iGlyphCount(0) { Mem::FillZ(&iDex, sizeof(iDex)); }
    void ConstructL()
        {
        iDexFile = ReadBoundedFileL(KDexPath, E63_DEX_MAX_BYTES);
        if (e63_dex_open(iDexFile->Ptr(), iDexFile->Length(), &iDex) != E63_DEX_OK)
            User::Leave(KErrCorrupt);
        iAssets = ReadBoundedFileL(KResourcesPath, 8 * 1024 * 1024);
        ValidateResourcesL();
        iBitmap = new (ELeave) CFbsBitmap;
        User::LeaveIfError(iBitmap->Create(TSize(320, 240), EColor64K));
        E63Rgb565Resources resources;
        Mem::FillZ(&resources, sizeof(resources));
        resources.context = this;
        resources.image_rgba = ImageData;
        resources.text_mask = TextMask;
        iRaster = e63_rgb565_new(320, 240, &resources);
        iVm = e63_ui_new(&iDex, GameAction, this);
        if (!iRaster || !iVm) User::Leave(KErrNoMemory);
        if (e63_ui_set_time_host(iVm,CurrentMillis,this)!=E63_UI_OK)
            User::Leave(KErrNotSupported);
        E63UiPaintHost paint;
        Mem::FillZ(&paint, sizeof(paint));
        paint.context = this;
        paint.font_height = FontHeight;
        paint.font_width = FontWidth;
        paint.image_bounds = ImageBounds;
        paint.commit = CommitFrame;
        paint.local_clock = LocalClock;
        if (e63_ui_set_paint_host(iVm, &paint) != E63_UI_OK ||
            e63_ui_set_viewport(iVm, 320, 240) != E63_UI_OK)
            User::Leave(KErrNotSupported);
        SeedOriginalGuestL();
        CreateWindowL();
        // The two bars are drawn by the guest, not by S60 or by this host.
        SetRect(TRect(TPoint(0, 0), TSize(320, 240)));
        ActivateL();
        if (!PaintGuest()) User::Leave(KErrNotSupported);
        }
    void ValidateResourcesL()
        {
        const TUint8* data = iAssets->Ptr();
        const TUint32 length = iAssets->Length();
        if (length < 20 || Mem::Compare(data, 8,
                 reinterpret_cast<const TUint8*>("E63RSC01"), 8) != 0)
            User::Leave(KErrCorrupt);
        iImageCount = Read32(data + 8);
        iGlyphCount = Read32(data + 12);
        const TUint32 start = 20u + iImageCount * 20u + iGlyphCount * 40u;
        if (iImageCount != 11u || iGlyphCount > 8000u ||
            Read32(data + 16) != length || start > length)
            User::Leave(KErrCorrupt);
        for (TUint32 i = 0; i < iImageCount; ++i)
            {
            const TUint8* p = data + 20u + 20u * i;
            const TUint32 id = Read32(p), w = Read32(p+4), h = Read32(p+8);
            const TUint32 off = Read32(p+12), size = Read32(p+16);
            if (id != i+1 || !w || w > 512 || !h || h > 512 ||
                size != w*h*4 || off < start || off > length || size > length-off)
                User::Leave(KErrCorrupt);
            }
        for (TUint32 i = 0; i < iGlyphCount; ++i)
            {
            const TUint8* p = data + 20u + iImageCount*20u + i*40u;
            const TUint32 font = Read32(p), textLen = Read32(p+4);
            const TUint32 advance = Read32(p+8), w = Read32(p+12);
            const TUint32 h = Read32(p+16), textOff = Read32(p+28);
            const TUint32 maskOff = Read32(p+32), maskLen = Read32(p+36);
            if ((font != 0 && font != 8 && font != 16) || textLen > 160 ||
                advance > 4096 || w > 4096 || h > 512 ||
                maskLen != (w ? w : 1u) * (h ? h : 1u) ||
                textOff < start || textOff > length || textLen > length-textOff ||
                maskOff < start || maskOff > length || maskLen > length-maskOff)
                User::Leave(KErrCorrupt);
            }
        }
    const TUint8* ImageRecord(TInt aId) const
        {
        if (aId < 1 || aId > static_cast<TInt>(iImageCount)) return 0;
        return iAssets->Ptr() + 20u + (aId-1)*20u;
        }
    const TUint8* FindGlyph(TInt aFont, const char* aText) const
        {
        if (!aText) return 0;
        size_t len = strlen(aText);
        if (len > E63_UI_MAX_TEXT_BYTES) return 0;
        const TUint8* data = iAssets->Ptr();
        const TUint8* base = data + 20u + iImageCount*20u;
        TUint32 low = 0, high = iGlyphCount;
        while (low < high)
            {
            TUint32 mid = low + (high-low)/2u;
            const TUint8* entry = base + mid*40u;
            const TUint32 font = Read32(entry);
            const TUint32 n = Read32(entry+4);
            TInt cmp = font < static_cast<TUint32>(aFont) ? -1 :
                       font > static_cast<TUint32>(aFont) ? 1 :
                       Mem::Compare(data+Read32(entry+28), n,
                                    reinterpret_cast<const TUint8*>(aText), len);
            if (cmp < 0) low = mid + 1u;
            else high = mid;
            }
        if (low >= iGlyphCount) return 0;
        const TUint8* entry = base + low*40u;
        if (Read32(entry) != static_cast<TUint32>(aFont) ||
            Mem::Compare(data+Read32(entry+28), Read32(entry+4),
                         reinterpret_cast<const TUint8*>(aText), len) != 0) return 0;
        return entry;
        }
    static int ImageBounds(void* aCtx, int32_t aId, int32_t* aW, int32_t* aH)
        {
        CE63OsView* self = static_cast<CE63OsView*>(aCtx);
        const TUint8* rec = self->ImageRecord(aId);
        if (!rec || !aW || !aH) return 1;
        *aW = Read32(rec+4); *aH = Read32(rec+8);
        return 0;
        }
    static int ImageData(void* aCtx, int32_t aId, E63RgbaResource* aOut)
        {
        CE63OsView* self = static_cast<CE63OsView*>(aCtx);
        const TUint8* rec = self->ImageRecord(aId);
        if (!rec || !aOut) return 1;
        aOut->width = Read32(rec+4);
        aOut->height = Read32(rec+8);
        aOut->stride = aOut->width * 4u;
        aOut->size = Read32(rec+16);
        aOut->pixels = self->iAssets->Ptr() + Read32(rec+12);
        return 0;
        }
    static int FontHeight(void*, int32_t aFont, int32_t* aOut)
        {
        if (!aOut || (aFont != 0 && aFont != 8 && aFont != 16)) return 1;
        *aOut = aFont == 8 ? 12 : aFont == 16 ? 18 : 14;
        return 0;
        }
    static int FontWidth(void* aCtx, int32_t aFont,
                         const char* aText, int32_t* aOut)
        {
        CE63OsView* self = static_cast<CE63OsView*>(aCtx);
        const TUint8* rec = self->FindGlyph(aFont, aText);
        if (!rec || !aOut) return 1;
        *aOut = Read32(rec+8); // Pillow DejaVuSans getlength, as PC parity test
        return 0;
        }
    static int TextMask(void* aCtx, int32_t aFont,
                        const char* aText, E63GlyphResource* aOut)
        {
        CE63OsView* self = static_cast<CE63OsView*>(aCtx);
        const TUint8* rec = self->FindGlyph(aFont, aText);
        if (!rec || !aOut) return 1;
        aOut->width  = Read32(rec+12);
        aOut->height = Read32(rec+16);
        aOut->left   = static_cast<TInt32>(Read32(rec+20));
        aOut->top    = static_cast<TInt32>(Read32(rec+24));
        aOut->stride = aOut->width ? aOut->width : 1u;
        aOut->size   = Read32(rec+36);
        aOut->alpha  = self->iAssets->Ptr() + Read32(rec+32);
        return 0;
        }
    static int LocalClock(void*, int32_t* aHour, int32_t* aMinute)
        {
        if (!aHour || !aMinute) return 1;
        TTime time;
        time.HomeTime();
        const TDateTime date = time.DateTime();
        *aHour = date.Hour(); *aMinute = date.Minute();
        return 0;
        }
    static int CurrentMillis(void*, int64_t* aOut)
        {
        if (!aOut) return 1;
        TTime time;
        time.UniversalTime();
        const TTime epoch(TDateTime(1970,EJanuary,0,0,0,0,0));
        const TInt64 microseconds=time.MicroSecondsFrom(epoch).Int64();
        if (microseconds<0) return 1;
        *aOut=static_cast<int64_t>(microseconds/1000);
        return 0;
        }
    static int GameAction(void*, int32_t aKey, int32_t* aOut)
        {
        if (!aOut) return 1;
        switch (aKey)
            {
            case -1001: *aOut = 1; break; // MIDP UP
            case -1002: *aOut = 6; break; // MIDP DOWN
            case -1003: *aOut = 2; break; // MIDP LEFT
            case -1004: *aOut = 5; break; // MIDP RIGHT
            case -1005: *aOut = 8; break; // MIDP FIRE
            default: *aOut = 0; break; // UNKNOWN is a successful lookup
            }
        return 0;
        }
    static int CommitFrame(void* aCtx, const E63UiPaintOp* aOps, uint32_t aCount)
        {
        CE63OsView* self = static_cast<CE63OsView*>(aCtx);
        return e63_rgb565_commit(self->iRaster, aOps, aCount);
        }
    TBool SeedRef(const char* aOwner, const char* aField, const char* aType,
                  uint32_t aObject, uint32_t aRef)
        {
        const TInt id = e63_dex_field_id(&iDex, aOwner, aField, aType);
        return id >= 0 && e63_ui_set_ref(iVm, aObject, id, aRef) == E63_UI_OK;
        }
    TBool SeedInt(const char* aOwner, const char* aField, const char* aType,
                  uint32_t aObject, TInt aValue)
        {
        const TInt id = e63_dex_field_id(&iDex, aOwner, aField, aType);
        return id >= 0 && e63_ui_set_int(iVm, aObject, id, aValue) == E63_UI_OK;
        }
    void SeedOriginalGuestL()
        {
        uint32_t store=0,small=0,medium=0,large=0,icon=0,selected=0;
        if (e63_ui_object(iVm, MIDLET, &iMidlet) != E63_UI_OK ||
            e63_ui_object(iVm, CANVAS, &iCanvas) != E63_UI_OK ||
            e63_ui_object(iVm, STORE, &store) != E63_UI_OK ||
            e63_ui_host_object(iVm, GRAPHICS, 0, &iGraphics) != E63_UI_OK ||
            e63_ui_host_object(iVm, FONT, 8, &small) != E63_UI_OK ||
            e63_ui_host_object(iVm, FONT, 0, &medium) != E63_UI_OK ||
            e63_ui_host_object(iVm, FONT, 16, &large) != E63_UI_OK ||
            !SeedRef(CANVAS,"app",MIDLET,iCanvas,iMidlet) ||
            !SeedRef(MIDLET,"canvas",CANVAS,iMidlet,iCanvas) ||
            !SeedRef(MIDLET,"store",STORE,iMidlet,store) ||
            !SeedRef(CANVAS,"small",FONT,iCanvas,small) ||
            !SeedRef(CANVAS,"medium",FONT,iCanvas,medium) ||
            !SeedRef(CANVAS,"large",FONT,iCanvas,large))
            User::Leave(KErrNotSupported);
        const char* names[11] = { "storeIcon", "settingsIcon", "fileIcon",
            "navBack", "navHome", "navRecent", "wifiStatus", "wall",
            "drawerIcon", "wifiIcon", "settingsMini" };
        for (TInt n=0; n<11; ++n)
            {
            if (e63_ui_host_object(iVm, IMAGE, n+1, &icon) != E63_UI_OK ||
                !SeedRef(CANVAS,names[n],IMAGE,iCanvas,icon))
                User::Leave(KErrNotSupported);
            }
        const TInt field = e63_dex_field_id(&iDex, MIDLET, "selected", "[I");
        if (field < 0 || e63_ui_int_array(iVm, 18u, &selected) != E63_UI_OK ||
            e63_ui_set_array(iVm,iMidlet,field,selected) != E63_UI_OK ||
            !SeedInt(MIDLET,"screen","I",iMidlet,1) || // HOME; startApp is not yet ported
            !SeedInt(MIDLET,"battery","I",iMidlet,-1) || // '?' until real Nokia reading
            !SeedInt(MIDLET,"wifiOn","Z",iMidlet,0) ||
            !SeedInt(MIDLET,"adjustClock","Z",iMidlet,0) ||
            !SeedInt(STORE,"installed","Z",store,0))
            User::Leave(KErrNotSupported);
        }
    TBool PaintGuest()
        {
        if (e63_ui_call_ref(iVm,iCanvas,"paint",PAINT,iGraphics) != E63_UI_OK)
            return EFalse;
        const uint16_t* pixels = e63_rgb565_pixels(iRaster);
        if (!pixels || !iBitmap) return EFalse;
        const TInt pitch = CFbsBitmap::ScanLineLength(320,EColor64K);
        if (pitch < 320*2) return EFalse;
        iBitmap->LockHeap();
        TUint8* dst = reinterpret_cast<TUint8*>(iBitmap->DataAddress());
        if (!dst) { iBitmap->UnlockHeap(); return EFalse; }
        for (TInt y=0; y<240; ++y)
            Mem::Copy(dst + y*pitch, pixels + y*320, 320*2);
        iBitmap->UnlockHeap();
        DrawNow();
        return ETrue;
        }
    void Draw(const TRect&) const
        {
        if (iBitmap) SystemGc().BitBlt(TPoint(0,0),iBitmap);
        }
private:
    HBufC8* iDexFile;
    HBufC8* iAssets;
    CFbsBitmap* iBitmap;
    E63DexView iDex;
    E63Rgb565Painter* iRaster;
    E63UiVm* iVm;
    uint32_t iMidlet, iCanvas, iGraphics;
    TUint32 iImageCount, iGlyphCount;
    };

class CE63OsAppUi : public CAknAppUi
    {
public:
    CE63OsAppUi() : iView(0) {}
    ~CE63OsAppUi() { if (iView) { RemoveFromStack(iView); delete iView; } }
    void ConstructL()
        {
        BaseConstructL();
        if (StatusPane()) StatusPane()->MakeVisible(EFalse);
        if (Cba()) Cba()->MakeVisible(EFalse);
        iView=CE63OsView::NewL();
        AddToStackL(iView);
        iView->SetFocus(ETrue);
        }
    void HandleCommandL(TInt aCommand)
        {
        // Fallback if S60 turns a hidden CBA softkey into a command rather
        // than a raw key. The CBA IDs are ours, never Options/Exit.
        if (aCommand==EE63SoftkeyBack) { DispatchSoftkey(-6); return; }
        if (aCommand==EE63SoftkeySelect) { DispatchSoftkey(-7); return; }
        if (aCommand==EEikCmdExit || aCommand==EAknSoftkeyExit) Exit();
        }
protected:
    virtual void HandleWsEventL(const TWsEvent& aEvent,
                                CCoeControl* aDestination)
        {
        // S60 routes physical softkeys through the CBA, not reliably through
        // a view's OfferKeyEventL. Capture only OUR foreground softkeys before
        // the hidden CBA; the D-pad remains directional navigation in the view.
        const TInt type=aEvent.Type();
        if (iView && (type==EEventKeyDown || type==EEventKey ||
                      type==EEventKeyUp))
            {
            const TKeyEvent* key=aEvent.Key();
            if (key && (key->iScanCode==EStdKeyDevice0 ||
                        key->iScanCode==EStdKeyDevice1))
                {
                if (type==EEventKeyDown)
                    DispatchSoftkey(key->iScanCode==EStdKeyDevice0 ? -6 : -7);
                return; // Do not deliver a second command to the native CBA.
                }
            }
        CAknAppUi::HandleWsEventL(aEvent,aDestination);
        }
private:
    void DispatchSoftkey(TInt aGuestKey)
        {
        if (!iView) return;
        const TInt screen=aGuestKey==-6 ? iView->GuestScreen() : -1;
        if (!iView->DispatchGuestKey(aGuestKey) &&
            aGuestKey==-6 && screen==1)
            Exit(); // Only the guest's unported Home-exit lifecycle falls back.
        }
    CE63OsView* iView;
    };

class CE63OsDocument : public CAknDocument
    {
public:
    explicit CE63OsDocument(CEikApplication& aApp) : CAknDocument(aApp) {}
    CEikAppUi* CreateAppUiL() { return new (ELeave) CE63OsAppUi; }
    };

class CE63OsApplication : public CAknApplication
    {
public:
    TUid AppDllUid() const { return KUidE63Os; }
    CApaDocument* CreateDocumentL() { return new (ELeave) CE63OsDocument(*this); }
    };

static CApaApplication* NewApplication() { return new CE63OsApplication; }
GLDEF_C TInt E32Main() { return EikStart::RunApplication(NewApplication); }
