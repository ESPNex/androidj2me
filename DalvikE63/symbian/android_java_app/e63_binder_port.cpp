#include "e63_binder_port.h"
#include "../runtime/binder_ipc.h"
#include "../runtime/vfs_mount.h"
#include <e32std.h>
#include <string.h>

_LIT(KE63BinderServerName,"E63BinderIPC.E0B63E04");
_LIT(KE63BinderThreadName,"E63BinderBroker.E0B63E04");
static const TInt KE63BrokerStack=0x8000;
static const TInt KE63BrokerMinHeap=0x10000;
static const TInt KE63BrokerMaxHeap=0x100000;
static const TUint32 KE63BinderSecureId=0xE0B63E04u;
enum TE63BrokerRequest { EBrokerTransact=1, EBrokerStop=2 };

class CE63BrokerServer;
class CE63BrokerSession : public CSession2
    {
public:
    explicit CE63BrokerSession(CE63BrokerServer& aServer);
    ~CE63BrokerSession();
    void CreateL();
    void ServiceL(const RMessage2& aMessage);
private:
    CE63BrokerServer& iServer;
    E63BinderClient* iClient;
    };
class CE63BrokerServer : public CServer2
    {
public:
    static CE63BrokerServer* NewL()
        {
        CE63BrokerServer* self=new(ELeave) CE63BrokerServer;
        CleanupStack::PushL(self);
        self->iDomain=e63_binder_new();
        if (!self->iDomain) User::Leave(KErrNoMemory);
        self->StartL(KE63BinderServerName);
        CleanupStack::Pop(self);
        return self;
        }
    ~CE63BrokerServer() {e63_binder_free(iDomain);}
    E63BinderDomain* Domain() const {return iDomain;}
private:
    CE63BrokerServer() : CServer2(EPriorityStandard),iDomain(0) {}
    CSession2* NewSessionL(const TVersion& aVersion,
                           const RMessage2& aMessage) const
        {
        if (!User::QueryVersionSupported(TVersion(1,0,0),aVersion) ||
            aMessage.SecureId()!=TSecureId(KE63BinderSecureId))
            User::Leave(KErrPermissionDenied);
        return new(ELeave) CE63BrokerSession(
                           *const_cast<CE63BrokerServer*>(this));
        }
    E63BinderDomain* iDomain;
    };
CE63BrokerSession::CE63BrokerSession(CE63BrokerServer& aServer)
    : iServer(aServer),iClient(0) {}
void CE63BrokerSession::CreateL()
    {
    RProcess process;
    /* A guest UID is scoped to this authenticated native application
     * session. This does NOT emulate Android's process/UID management. */
    iClient=e63_binder_connect(iServer.Domain(),process.Id().Id(),10042u);
    if (!iClient) User::Leave(KErrNoMemory);
    }
CE63BrokerSession::~CE63BrokerSession() {e63_binder_disconnect(iClient);}
void CE63BrokerSession::ServiceL(const RMessage2& aMessage)
    {
    if (aMessage.Function()==EBrokerStop)
        {
        aMessage.Complete(KErrNone);
        CActiveScheduler::Stop();
        return;
        }
    if (aMessage.Function()!=EBrokerTransact || !iClient ||
        aMessage.GetDesLength(2)!=static_cast<TInt>(sizeof(E63BinderParcel)) ||
        aMessage.GetDesMaxLength(3)<static_cast<TInt>(sizeof(E63BinderParcel)))
        {aMessage.Complete(KErrArgument);return;}
    E63BinderParcel request,reply;
    memset(&request,0,sizeof(request));
    TPtr8 bytes(reinterpret_cast<TUint8*>(&request),0,sizeof(request));
    TRAPD(readError,aMessage.ReadL(2,bytes));
    if (readError!=KErrNone || bytes.Length()!=sizeof(request))
        {aMessage.Complete(readError==KErrNone ? KErrCorrupt : readError);
         return;}
    const E63BinderResult result=e63_binder_transact(iClient,
              static_cast<uint32_t>(aMessage.Int0()),
              static_cast<uint32_t>(aMessage.Int1()),&request,&reply);
    if (result!=E63_BINDER_OK)
        {aMessage.Complete(result==E63_BINDER_NOT_FOUND ? KErrNotFound :
                           result==E63_BINDER_DENIED ? KErrPermissionDenied :
                           KErrNotSupported);
         return;}
    const TPtrC8 output(reinterpret_cast<const TUint8*>(&reply),sizeof(reply));
    TRAPD(writeError,aMessage.WriteL(3,output));
    aMessage.Complete(writeError);
    }

static TInt E63BrokerThread(void*)
    {
    CTrapCleanup* cleanup=CTrapCleanup::New();
    if (!cleanup) {RThread().Rendezvous(KErrNoMemory);return KErrNoMemory;}
    TInt error=KErrNone;
    TRAP(error,
        {
        CActiveScheduler* scheduler=new(ELeave) CActiveScheduler;
        CleanupStack::PushL(scheduler);
        CActiveScheduler::Install(scheduler);
        CE63BrokerServer* server=CE63BrokerServer::NewL();
        CleanupStack::PushL(server);
        RThread().Rendezvous(KErrNone);
        CActiveScheduler::Start();
        CleanupStack::PopAndDestroy(server);
        CActiveScheduler::Install(0);
        CleanupStack::PopAndDestroy(scheduler);
        });
    delete cleanup;
    return error;
    }

class RE63BinderSession : public RSessionBase
    {
public:
    TInt Connect()
        {return CreateSession(KE63BinderServerName,TVersion(1,0,0),2);}
    TInt Transact(TUint aHandle,TUint aCode,
                  const E63BinderParcel& aRequest,E63BinderParcel& aReply)
        {
        const TPtrC8 input(reinterpret_cast<const TUint8*>(&aRequest),
                           sizeof(aRequest));
        TPtr8 output(reinterpret_cast<TUint8*>(&aReply),0,sizeof(aReply));
        return SendReceive(EBrokerTransact,
                           TIpcArgs(aHandle,aCode,&input,&output));
        }
    TInt Stop() {return SendReceive(EBrokerStop,TIpcArgs());}
    };

E63BinderPort::E63BinderPort() : iStarted(EFalse) {}
E63BinderPort::~E63BinderPort() {Stop();}
TInt E63BinderPort::Start()
    {
    if (iStarted) return KErrNone;
    E63MountRoute virtualNode;
    if (e63_route_guest_path("/dev/binder",0,E63_CALLER_OS,
                             &virtualNode)!=E63_ROUTE_OK ||
        virtualNode.kind!=E63_MOUNT_IPC || virtualNode.relative[0])
        return KErrNotSupported;
    TInt error=iThread.Create(KE63BinderThreadName,E63BrokerThread,
                             KE63BrokerStack,KE63BrokerMinHeap,
                             KE63BrokerMaxHeap,0);
    if (error!=KErrNone) return error;
    TRequestStatus ready;
    iThread.Rendezvous(ready);
    if (ready!=KRequestPending)
        iThread.Kill(KErrGeneral);
    else iThread.Resume();
    User::WaitForRequest(ready);
    error=ready.Int();
    if (error!=KErrNone) {iThread.Close();return error;}
    iStarted=ETrue;
    return KErrNone;
    }
void E63BinderPort::Stop()
    {
    if (!iStarted) return;
    RE63BinderSession session;
    if (session.Connect()==KErrNone)
        {session.Stop();session.Close();}
    /* Ensure the broker no longer refers to callbacks, heap or sessions
     * before unloading this executable. Do not write an IPC device to C:. */
    TRequestStatus exitStatus;
    iThread.Logon(exitStatus);
    User::WaitForRequest(exitStatus);
    iThread.Close();
    iStarted=EFalse;
    }
TInt E63BinderPort::CheckAbsent(const char* aServiceName,TBool& aAbsent)
    {
    aAbsent=EFalse;
    if (!iStarted || !aServiceName) return KErrNotReady;
    E63BinderParcel request,reply;
    e63_binder_parcel_reset(&request);
    e63_binder_parcel_reset(&reply);
    if (e63_binder_write_token(&request,E63_BINDER_SERVICE_INTERFACE)!=
          E63_BINDER_OK ||
        e63_binder_write_string(&request,aServiceName)!=E63_BINDER_OK)
        return KErrArgument;
    RE63BinderSession session;
    TInt error=session.Connect();
    if (error!=KErrNone) return error;
    error=session.Transact(E63_BINDER_CONTEXT_HANDLE,
                          E63_BINDER_SERVICE_CHECK,request,reply);
    session.Close();
    if (error!=KErrNone) return error;
    uint32_t handle=0xffffffffu;
    if (e63_binder_parcel_validate(&reply)!=E63_BINDER_OK ||
        e63_binder_read_handle(&reply,&handle)!=E63_BINDER_OK ||
        reply.cursor!=reply.length)
        return KErrCorrupt;
    aAbsent=handle==0u;
    return KErrNone;
    }
