// Simple AppArc menu launcher for the separate console TCP bridge server.
// The server itself (e63bridge.exe) owns the PIN and listens ONLY on loopback.
// Process launch and console visibility must still be checked on a real E63.
#include <e32base.h>
#include <eikstart.h>
#include <aknapp.h>
#include <akndoc.h>
#include <aknappui.h>
#include <coecntrl.h>
#include <gdi.h>
#include <e32std.h>

static const TUid KUidLauncher = { 0xE0B63E03 };
_LIT(KServerName, "e63bridge.exe");

class CE63LauncherView : public CCoeControl
    {
public:
    static CE63LauncherView* NewL(const TRect& aRect)
        {
        CE63LauncherView* self = new (ELeave) CE63LauncherView;
        CleanupStack::PushL(self);
        self->CreateWindowL();
        self->SetRect(aRect);
        self->ActivateL();
        CleanupStack::Pop(self);
        return self;
        }
    void SetError(TInt aError) { iError = aError; DrawNow(); }
private:
    CE63LauncherView() : iError(KErrNone) {}
    void Draw(const TRect&) const
        {
        CWindowGc& gc = SystemGc();
        gc.SetBrushColor(TRgb(19, 23, 27));
        gc.SetBrushStyle(CGraphicsContext::ESolidBrush);
        gc.Clear(Rect());
        gc.SetPenColor(TRgb(75, 184, 229));
        _LIT(KTitle, "E63 local bridge");
        gc.DrawText(KTitle, TPoint(10, 25));
        gc.SetPenColor(TRgb(220, 224, 228));
        if (iError == KErrNone)
            {
            _LIT(KInfo, "Server starting on 127.0.0.1:27463");
            _LIT(KPin, "Read PAIR code on server console.");
            gc.DrawText(KInfo, TPoint(10, 53));
            gc.DrawText(KPin, TPoint(10, 74));
            }
        else
            {
            _LIT(KFailure, "Could not launch the bridge server.");
            gc.DrawText(KFailure, TPoint(10, 53));
            }
        }
private:
    TInt iError;
    };

class CE63LauncherUi : public CAknAppUi
    {
public:
    CE63LauncherUi() : iView(0) {}
    ~CE63LauncherUi() { if (iView) { RemoveFromStack(iView); delete iView; } }
    void ConstructL()
        {
        BaseConstructL();
        iView = CE63LauncherView::NewL(ClientRect());
        AddToStackL(iView);
        RProcess process;
        TInt error = process.Create(KServerName, KNullDesC);
        if (error == KErrNone)
            {
            process.Resume();
            process.Close();
            }
        iView->SetError(error);
        }
    void HandleCommandL(TInt aCommand)
        {
        if (aCommand == EEikCmdExit || aCommand == EAknSoftkeyExit) Exit();
        }
private:
    CE63LauncherView* iView;
    };

class CE63LauncherDocument : public CAknDocument
    {
public:
    explicit CE63LauncherDocument(CEikApplication& aApp) : CAknDocument(aApp) {}
    CEikAppUi* CreateAppUiL() { return new (ELeave) CE63LauncherUi; }
    };

class CE63LauncherApp : public CAknApplication
    {
public:
    TUid AppDllUid() const { return KUidLauncher; }
    CApaDocument* CreateDocumentL() { return new (ELeave) CE63LauncherDocument(*this); }
    };

static CApaApplication* NewApplication() { return new CE63LauncherApp; }
GLDEF_C TInt E32Main() { return EikStart::RunApplication(NewApplication); }
