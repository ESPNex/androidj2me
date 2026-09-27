#include "apk_android_bridge.h"
#include "apk_activity_vm.h"
#include "vfs_mount.h"
#include <string.h>

typedef struct BridgeCall {
    const E63JavaSession *session;
    const E63AndroidBackend *backend;
    E63AndroidScreen *screen;
    unsigned navigated;
} BridgeCall;

static int copy_bounded(char *dst, unsigned capacity, const char *src)
    {
    size_t length;
    if (!src || !dst || !capacity) return 0;
    length=strlen(src); /* VM has already bounded all argument strings to 512 */
    if (length>=capacity) return 0;
    memcpy(dst,src,length+1u);
    return 1;
    }
static int add_row(E63AndroidScreen *screen, E63AndroidKind kind,
                   const char *label, int32_t id, int32_t arity)
    {
    E63AndroidRow *row;
    if (!screen || screen->row_count>=E63_ANDROID_ROWS) return 0;
    row=&screen->rows[screen->row_count];
    if (!copy_bounded(row->text,sizeof(row->text),label)) return 0;
    row->id=id;row->arity=arity;row->kind=kind;
    ++screen->row_count;
    return 1;
    }
static int simple_name(const char *name)
    {
    size_t i;
    if (!name || !*name || strlen(name)>80u ||
        strcmp(name,".")==0 || strcmp(name,"..")==0) return 0;
    for (i=0u;name[i];++i) {
        char c=name[i];
        if (!((c>='a' && c<='z') || (c>='A' && c<='Z') ||
              (c>='0' && c<='9') || c=='_' || c=='-' || c=='.')) return 0;
    }
    return 1;
    }
static int media_path(const char *path, int write)
    {
    E63MountRoute route;
    return path && e63_route_guest_path(path,write,E63_CALLER_FILES,&route)
                       ==E63_ROUTE_OK && route.kind==E63_MOUNT_C_MEDIA;
    }
static int file_query(const char *input)
    {
    char query[64];
    const char *last;
    size_t len;
    if (!input) return 0;
    while (*input==' ' || *input=='\t') ++input;
    len=strlen(input);
    while (len && (input[len-1u]==' ' || input[len-1u]=='\t')) --len;
    if (len>=sizeof(query)) return 0;
    for (last=input;last<input+len;++last) {
        char c=*last;
        query[last-input]=(char)(c>='A' && c<='Z' ? c-'A'+'a' : c);
    }
    query[len]=0;
    return strcmp(query,"file")==0 || strcmp(query,"file man")==0 ||
           strcmp(query,"file manager")==0;
    }
static int call_device(BridgeCall *call, E63JavaService service,
                       const E63JavaValue *args, unsigned count,
                       int32_t *out, char *text, unsigned capacity)
    {
    if (out) *out=0;
    if (text && capacity) text[0]=0;
    return call->backend && call->backend->device ?
        call->backend->device(call->backend->context,service,args,count,
                              out,text,capacity) : -1;
    }
static int installed(BridgeCall *call, const char *package_name)
    {
    E63JavaValue arg;
    int32_t result=0;
    if (!e63_session_apk_name(package_name)) return 0;
    arg.type=E63_JAVA_STRING;arg.number=0;arg.string=package_name;
    if (call_device(call,E63_SERVICE_IS_INSTALLED,&arg,1u,&result,0,0u)!=0)
        return 0;
    return result==1;
    }
static int unconnected(BridgeCall *call, const char *reason)
    {
    call->navigated=1u; /* Preserve an honest service error on screen. */
    return add_row(call->screen,E63_ANDROID_TEXT_ROW,reason,0,0);
    }
static int invoke(void *context, E63JavaService service,
                  const E63JavaValue *args, unsigned count,
                  E63JavaValue *result)
    {
    BridgeCall *call=(BridgeCall *)context;
    E63AndroidScreen *screen=call->screen;
    const char *s=count && args[0].type==E63_JAVA_STRING ? args[0].string : "";
    int32_t number=0;
    char text[E63_ANDROID_TEXT];
    int ok=0;
    result->type=E63_JAVA_INT;result->number=0;result->string=0;
    switch (service) {
    case E63_SERVICE_TITLE:
        return copy_bounded(screen->title,sizeof(screen->title),s) ? 0 : -1;
    case E63_SERVICE_TEXT:
        return add_row(screen,E63_ANDROID_TEXT_ROW,s,0,0) ? 0 : -1;
    case E63_SERVICE_OPTION:
        return args[0].number>=0 && args[0].number<=63 &&
            add_row(screen,E63_ANDROID_OPTION_ROW,args[1].string,
                    args[0].number,0) ? 0 : -1;
    case E63_SERVICE_IMAGE:
        return e63_session_owns_asset(call->session,s) && simple_name(s) &&
            add_row(screen,E63_ANDROID_IMAGE_ROW,s,0,0) ? 0 : -1;
    case E63_SERVICE_INPUT:
        return args[0].number>=0 && args[0].number<=63 &&
            (args[2].number==1 || args[2].number==2) &&
            add_row(screen,E63_ANDROID_INPUT_ROW,args[1].string,
                    args[0].number,args[2].number) ? 0 : -1;
    case E63_SERVICE_DIALOG:
        call->navigated=1u;
        return add_row(screen,E63_ANDROID_DIALOG_ROW,s,0,0) ? 0 : -1;
    case E63_SERVICE_OPEN:
        if (!e63_session_apk_name(s) ||
            (strcmp(s,"org.e63.dalvik.files")==0 && !installed(call,s)))
            return unconnected(call,"App not installed or not trusted") ? 0 : -1;
        if (!copy_bounded(screen->open_package,
                          sizeof(screen->open_package),s)) return -1;
        call->navigated=1u;return 0;
    case E63_SERVICE_IS_INSTALLED:
        result->number=installed(call,s);return 0;
    case E63_SERVICE_GET_FLAG:
        if (strcmp(s,"wifi_demo")!=0 && strcmp(s,"adjust_clock")!=0) return -1;
        ok=call_device(call,service,args,count,&number,0,0u);
        result->number=ok==0 && number==1 ? 1 : 0;
        return 0;
    case E63_SERVICE_SET_FLAG:
        if ((strcmp(s,"wifi_demo")!=0 && strcmp(s,"adjust_clock")!=0) ||
            (args[1].number!=0 && args[1].number!=1)) return -1;
        if (call_device(call,service,args,count,&number,0,0u)!=0)
            return unconnected(call,"Settings backend unavailable") ? 0 : -1;
        return 0;
    case E63_SERVICE_SEARCH_FILE:
        result->number=file_query(s);return 0;
    case E63_SERVICE_INSTALL:
        if (strcmp(s,"org.e63.dalvik.files")!=0 ||
            strcmp(call->session->package_name,
                   "org.e63.dalvik.packageinstaller")!=0 ||
            !e63_session_owns_asset(call->session,"packages/FileManager.apk"))
            return -1;
        ok=call_device(call,service,args,count,&number,0,0u);
        if (ok!=0 || number!=1)
            return unconnected(call,"Installation/enable unavailable") ? 0 : -1;
        result->number=1; /* ONLY after verified host install or guest enable */
        return 0;
    case E63_SERVICE_LIST:
        if (strcmp(call->session->package_name,"org.e63.dalvik.files")!=0 ||
            !media_path(s,0)) return -1;
        if (call_device(call,service,args,count,&number,text,
                        sizeof(text))!=0 || !text[0])
            return unconnected(call,"Storage not connected") ? 0 : -1;
        return add_row(screen,E63_ANDROID_TEXT_ROW,text,0,0) ? 0 : -1;
    case E63_SERVICE_MKDIR:
    case E63_SERVICE_TOUCH:
    case E63_SERVICE_DELETE:
        if (strcmp(call->session->package_name,"org.e63.dalvik.files")!=0 ||
            !media_path(s,1)) return -1;
        ok=call_device(call,service,args,count,&number,0,0u);
        result->number=ok==0 && number==1;
        if (ok!=0 || !result->number)
            return unconnected(call,"Storage operation failed") ? 0 : -1;
        return 0;
    case E63_SERVICE_RENAME:
        if (strcmp(call->session->package_name,"org.e63.dalvik.files")!=0 ||
            !media_path(s,1) || !media_path(args[1].string,1)) return -1;
        ok=call_device(call,service,args,count,&number,0,0u);
        result->number=ok==0 && number==1;
        if (ok!=0 || !result->number)
            return unconnected(call,"Rename failed") ? 0 : -1;
        return 0;
    case E63_SERVICE_IMPORT_FILE:
        if (strcmp(call->session->package_name,"org.e63.dalvik.files")!=0 ||
            !simple_name(s) || !media_path(args[1].string,1)) return -1;
        ok=call_device(call,service,args,count,&number,0,0u);
        result->number=ok==0 && number==1;
        if (ok!=0 || !result->number)
            return unconnected(call,"Import failed or source missing") ? 0 : -1;
        return 0;
    case E63_SERVICE_WAV:
        if (strcmp(s,"/sdcard/Music/music.wav")==0) {
            if (!e63_session_owns_asset(call->session,"music.wav")) return -1;
        } else if (strcmp(s,"/system/media/audio/ui/lowbattery.wav")==0) {
            if (!e63_session_owns_asset(call->session,"lowbattery.wav")) return -1;
        } else return -1;
        ok=call_device(call,service,args,count,&number,0,0u);
        result->number=ok==0 && number==1;
        if (ok!=0) return unconnected(call,"Audio backend unavailable") ? 0 : -1;
        return 0;
    default:return -1;
    }
    }

E63JavaStatus e63_android_event(const E63JavaSession *session,
                                 E63AndroidScreen *screen,
                                 const E63AndroidBackend *backend,
                                 const char *method_name,
                                 const E63JavaValue *args, unsigned count)
    {
    E63AndroidScreen next;
    E63JavaHost host;
    BridgeCall context;
    const char *proto;
    E63JavaStatus status;
    unsigned i;
    E63AndroidKind expected;
    if (!session || !screen || !method_name) return E63_JAVA_BAD_INPUT;
    if (strcmp(method_name,"onStart")==0) {
        proto="()V";
        if (count) return E63_JAVA_BAD_INPUT;
        memset(&next,0,sizeof(next));
    } else {
        next=*screen;
        next.open_package[0]=0;
        if (strcmp(method_name,"onSelect")==0 && count==1u && args &&
            args[0].type==E63_JAVA_INT) {
            proto="(I)V";expected=E63_ANDROID_OPTION_ROW;
        } else if (strcmp(method_name,"onCommand")==0 && count==3u && args &&
                   args[0].type==E63_JAVA_INT) {
            proto="(ILjava/lang/String;Ljava/lang/String;)V";
            expected=E63_ANDROID_INPUT_ROW;
        } else return E63_JAVA_BAD_INPUT;
        for (i=0u;i<screen->row_count;++i)
            if (screen->rows[i].kind==expected &&
                screen->rows[i].id==args[0].number) break;
        if (i==screen->row_count) return E63_JAVA_BAD_INPUT;
    }
    context.session=session;context.backend=backend;context.screen=&next;
    context.navigated=0u;
    host.context=&context;host.invoke=invoke;
    status=e63_session_run(session,method_name,proto,args,count,&host);
    if (status==E63_JAVA_OK) *screen=next;
    return status;
    }

static int activity_begin(void *context)
    {
    BridgeCall *call=(BridgeCall *)context;
    memset(call->screen,0,sizeof(*call->screen));
    call->navigated=0u;
    return 0;
    }
static int activity_navigated(void *context)
    {return ((BridgeCall *)context)->navigated ? 1 : 0;}

static E63JavaStatus android_activity_inner(const E63JavaSession *session,
                                          E63ActivityState *state,
                                          E63AndroidScreen *screen,
                                          const E63AndroidBackend *backend,
                                          const E63FrameworkDispatch *framework,
                                          unsigned strict,
                                          const char *event,
                                          const E63JavaValue *args,
                                          unsigned count)
    {
    E63AndroidScreen next;
    BridgeCall call;
    E63JavaHost service_host;
    E63ActivityHost activity_host;
    E63JavaStatus status;
    E63AndroidKind expected;
    unsigned i;
    if (!session || !state || !screen || !event) return E63_JAVA_BAD_INPUT;
    if (strict && (!framework || !framework->invoke))
        return E63_JAVA_UNSUPPORTED;
    next=*screen;
    if (strcmp(event,"choose")==0 || strcmp(event,"command")==0) {
        if (!args || !count || args[0].type!=E63_JAVA_INT)
            return E63_JAVA_BAD_INPUT;
        expected=strcmp(event,"choose")==0 ? E63_ANDROID_OPTION_ROW :
                 E63_ANDROID_INPUT_ROW;
        for (i=0u;i<screen->row_count;++i)
            if (screen->rows[i].kind==expected &&
                screen->rows[i].id==args[0].number) break;
        if (i==screen->row_count) return E63_JAVA_BAD_INPUT;
        next.open_package[0]=0;
    }
    call.session=session;call.backend=backend;call.screen=&next;
    call.navigated=0u;
    service_host.context=&call;service_host.invoke=invoke;
    activity_host.context=&call;
    activity_host.begin=activity_begin;
    activity_host.navigated=activity_navigated;
    activity_host.program_host=&service_host;
    status=strict ?
        e63_activity_event_framework(session,state,&activity_host,framework,
                                     event,args,count) :
        e63_activity_event(session,state,&activity_host,event,args,count);
    if (status==E63_JAVA_OK) *screen=next;
    return status;
    }

E63JavaStatus e63_android_activity_event(const E63JavaSession *session,
                                          E63ActivityState *state,
                                          E63AndroidScreen *screen,
                                          const E63AndroidBackend *backend,
                                          const char *event,
                                          const E63JavaValue *args,
                                          unsigned count)
    {
    return android_activity_inner(session,state,screen,backend,0,0u,
                                  event,args,count);
    }
E63JavaStatus e63_android_activity_event_framework(
                                          const E63JavaSession *session,
                                          E63ActivityState *state,
                                          E63AndroidScreen *screen,
                                          const E63AndroidBackend *backend,
                                          const E63FrameworkDispatch *framework,
                                          const char *event,
                                          const E63JavaValue *args,
                                          unsigned count)
    {
    return android_activity_inner(session,state,screen,backend,framework,1u,
                                  event,args,count);
    }
