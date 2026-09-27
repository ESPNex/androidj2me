#ifndef E63_BINDER_PORT_H
#define E63_BINDER_PORT_H
/* Symbian thread/session transport for a bounded virtual /dev/binder core.
 * No physical/logical disk partition is opened for Binder. Only the signed
 * owner process can connect. This exposes a few wire-compatible transactions,
 * NOT Android libbinder's complete kernel protocol or Android services. */
#include <e32base.h>
class E63BinderPort
    {
public:
    E63BinderPort();
    ~E63BinderPort();
    TInt Start();
    void Stop();
    /* Actual RSessionBase/SendReceive to a separate CServer2 broker thread.
     * Returns KErrNone only if the broker replies with a NULL handle for a
     * service that has NOT been published by any real Android service. */
    TInt CheckAbsent(const char* aServiceName,TBool& aAbsent);
private:
    RThread iThread;
    TBool iStarted;
    E63BinderPort(const E63BinderPort&);
    E63BinderPort& operator=(const E63BinderPort&);
    };
#endif
