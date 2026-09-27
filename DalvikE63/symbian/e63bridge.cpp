// S60 3rd Edition FP1 / Symbian 9.2 CONSOLE SERVER SOURCE, not yet built.
// Bind only 127.0.0.1:27463. Authenticated, read-only PING; no filesystem API.
// This adapter uses the tested portable bridge_protocol.c. It requires the
// actual S60 3rd FP1 SDK to compile and must be tested on a physical E63.
#include <e32base.h>
#include <e32cons.h>
#include <es_sock.h>
#include <in_sock.h>
#include "bridge_protocol.h"

static const TInt KPort = 27463;
static const TInt KMaxLine = 96;

// Six-digit, session-local pairing code: adequate only for a loopback PING
// demonstrator plus a three-failure lockout, NOT a cryptographic secret.
// Replace with the platform CSPRNG + stronger auth before adding file ops.
static void MakeCode(char aPin[7], TDes8& aScreenCode)
    {
    TUint n = (User::FastCounter() ^ User::TickCount()) % 1000000u;
    aScreenCode.Format(_L8("%06u"), n);
    for (TInt i=0; i<6; ++i) aPin[i] = static_cast<char>(aScreenCode[i]);
    aPin[6] = '\0';
    }

static TInt HandleClient(RSocket& aClient, const char aPin[7])
    {
    TBuf8<KMaxLine> line;
    for (;;) {
        if (line.Length() >= KMaxLine) return -1;
        TBuf8<1> chunk;
        TSockXfrLength received;
        TRequestStatus status;
        aClient.RecvOneOrMore(chunk, 0, status, received);
        User::WaitForRequest(status);
        if (status.Int() != KErrNone || received() < 1 || chunk.Length() < 1)
            return -1;
        line.Append(chunk[0]);
        if (chunk[0] == '\n') break;
        }
    unsigned char result[96];
    const TInt length = e63_reply(line.Ptr(), line.Length(), aPin, result, sizeof(result));
    if (length == 0) return -1;
    const TInt bytes = length < 0 ? -length : length;
    TPtrC8 response(result, bytes);
    TRequestStatus sendStatus;
    aClient.Send(response, 0, sendStatus);
    User::WaitForRequest(sendStatus);
    return sendStatus.Int() == KErrNone && length > 0 ? 1 : -1;
    }

static void ServeL(CConsoleBase& aConsole)
    {
    RSocketServ sockets;
    User::LeaveIfError(sockets.Connect());
    CleanupClosePushL(sockets);
    RSocket listener;
    User::LeaveIfError(listener.Open(sockets, KAfInet, KSockStream, KProtocolInetTcp));
    CleanupClosePushL(listener);
    TInetAddr address(KInetAddrLoop, KPort);  // NEVER KInetAddrAny
    User::LeaveIfError(listener.Bind(address));
    User::LeaveIfError(listener.Listen(2));
    char pin[7];
    TBuf8<8> screenCode;
    MakeCode(pin, screenCode);
    TBuf<8> wideCode;
    wideCode.Copy(screenCode);
    aConsole.Printf(_L("E63 J2ME <-> SIS bridge\n127.0.0.1:27463\nPAIR: %S\n"), &wideCode);
    aConsole.Printf(_L("Only PING. 3 failed attempts stop server.\n"));
    TInt failures = 0;
    while (failures < 3) {
        RSocket peer;
        User::LeaveIfError(peer.Open(sockets));
        CleanupClosePushL(peer);
        TRequestStatus accepted;
        listener.Accept(peer, accepted);
        User::WaitForRequest(accepted);
        TInt verdict = -1;
        if (accepted.Int() == KErrNone) {
            TInetAddr clientAddress;
            // S60 FP1 RSocket::RemoteName(TSockAddr&) returns void.
            peer.RemoteName(clientAddress);
            if (clientAddress.Family() == KAfInet &&
                clientAddress.Address() == KInetAddrLoop)
                verdict = HandleClient(peer, pin);
            }
        if (verdict == 1) aConsole.Printf(_L("Paired PING\n"));
        else { ++failures; aConsole.Printf(_L("Rejected (%d/3)\n"), failures); }
        CleanupStack::PopAndDestroy(&peer);
        }
    aConsole.Printf(_L("Locked. Restart to rotate pairing code.\n"));
    CleanupStack::PopAndDestroy(&listener);
    CleanupStack::PopAndDestroy(&sockets);
    }

GLDEF_C TInt E32Main()
    {
    CTrapCleanup* cleanup = CTrapCleanup::New();
    if (!cleanup) return KErrNoMemory;
    TRAPD(error,
        CConsoleBase* console = Console::NewL(_L("E63 SIS Bridge"),
                                             TSize(KConsFullScreen,KConsFullScreen));
        CleanupStack::PushL(console);
        TRAPD(serverError, ServeL(*console));
        if (serverError != KErrNone) console->Printf(_L("Bridge error: %d\n"), serverError);
        console->Printf(_L("Press key to exit\n"));
        console->Getch();
        CleanupStack::PopAndDestroy(console);
        );
    delete cleanup;
    return error;
    }
