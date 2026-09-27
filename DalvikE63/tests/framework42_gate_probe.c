/* Deferred final-phase PC probe: missing real framework MUST NOT succeed. */
#include "apk_android_bridge.h"
#include <string.h>
int main(void)
    {
    E63JavaSession session;
    E63ActivityState state;
    E63AndroidScreen screen;
    E63JavaStatus status;
    memset(&session,0,sizeof(session));
    memset(&state,0,sizeof(state));
    memset(&screen,0,sizeof(screen));
    status=e63_android_activity_event_framework(&session,&state,&screen,0,0,
                                                  "onCreate",0,0);
    return status==E63_JAVA_UNSUPPORTED &&
           !state.constructed && !state.created && !screen.row_count ? 0 : 1;
    }
