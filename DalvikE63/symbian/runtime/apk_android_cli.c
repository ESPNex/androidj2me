/* PC-only harness for the SAME fixed-pin C99 APK loader, DEX interpreter,
 * and device-service bridge intended for the separate Symbian target.
 * Output is not a Nokia screen/installer, and the backend is deliberately
 * unable to install or change device files. Never claim an E63 hardware run.
 */
#include "apk_android_bridge.h"
#include "apk_sha256.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct Demo { int32_t wifi, clock, installed; } Demo;
static int device(void *context, E63JavaService service,
                  const E63JavaValue *args, unsigned count,
                  int32_t *number, char *text, unsigned capacity)
    {
    Demo *demo=(Demo *)context;
    const char *s=count ? args[0].string : 0;
    (void)text;(void)capacity;
    if (service==E63_SERVICE_IS_INSTALLED) {
        *number=s && strcmp(s,"org.e63.dalvik.files")==0 ? demo->installed : 1;
        return 0;
    }
    if (service==E63_SERVICE_GET_FLAG) {
        *number=s && strcmp(s,"wifi_demo")==0 ? demo->wifi : demo->clock;
        return 0;
    }
    if (service==E63_SERVICE_SET_FLAG) {
        if (!s || count!=2u) return -1;
        if (strcmp(s,"wifi_demo")==0) demo->wifi=args[1].number;
        else demo->clock=args[1].number;
        return 0;
    }
    return -1; /* never pretend to install, list, import or play audio */
    }
static int read_apk(const char *name, uint8_t **bytes, size_t *size)
    {
    FILE *file=fopen(name,"rb");
    long length;
    if (!file) return 0;
    if (fseek(file,0,SEEK_END)!=0 || (length=ftell(file))<=0 ||
        (unsigned long)length>E63_APK_MAX_BYTES || fseek(file,0,SEEK_SET)!=0) {
        fclose(file);return 0;
    }
    *bytes=(uint8_t *)malloc((size_t)length);
    if (!*bytes) {fclose(file);return 0;}
    *size=(size_t)length;
    if (fread(*bytes,1,*size,file)!=*size) {
        free(*bytes);*bytes=0;fclose(file);return 0;
    }
    fclose(file);return 1;
    }
static void dump(const E63AndroidScreen *screen)
    {
    unsigned i;
    printf("TITLE: %s\n",screen->title);
    for (i=0u;i<screen->row_count;++i) {
        const E63AndroidRow *row=&screen->rows[i];
        switch (row->kind) {
            case E63_ANDROID_TEXT_ROW:printf("TEXT: %s\n",row->text);break;
            case E63_ANDROID_IMAGE_ROW:printf("IMAGE: %s\n",row->text);break;
            case E63_ANDROID_OPTION_ROW:
                printf("OPTION: %d %s\n",row->id,row->text);break;
            case E63_ANDROID_INPUT_ROW:
                printf("INPUT: %d %d %s\n",row->id,row->arity,row->text);break;
            case E63_ANDROID_DIALOG_ROW:printf("DIALOG: %s\n",row->text);break;
            default:break;
        }
    }
    if (screen->open_package[0]) printf("NEXT: %s\n",screen->open_package);
    }
int main(int argc, char **argv)
    {
    uint8_t *buffer=0, digest[32];
    size_t length=0;
    E63JavaSession session;
    E63AndroidBackend backend;
    E63AndroidScreen screen;
    E63ActivityState activity;
    E63SessionStatus pin;
    E63JavaStatus vm;
    E63JavaValue a[3];
    Demo demo={0,0,0};
    unsigned i;
    if (argc==3 && strcmp(argv[1],"--sha")==0) {
        e63_apk_sha256((const uint8_t *)argv[2],strlen(argv[2]),digest);
        for (i=0u;i<32u;++i) printf("%02x",digest[i]);
        puts("");return 0;
    }
    if (argc<5 || argc>8 ||
        (strcmp(argv[1],"--run")!=0 && strcmp(argv[1],"--activity")!=0)) {
        fprintf(stderr,"usage: apk_android_cli --sha ascii | "
                       "--run|--activity apk package "
                       "onStart|onSelect|onCommand|onResume "
                       "[index [first second] [--installed]]\n");
        return 2;
    }
    if (!read_apk(argv[2],&buffer,&length)) {fprintf(stderr,"cannot read APK\n");return 2;}
    memset(&session,0,sizeof(session));
    pin=e63_session_open(&session,argv[3],buffer,length);
    if (pin!=E63_SESSION_OK) {
        fprintf(stderr,"PIN/DEX: %s\n",e63_session_status(pin));
        free(buffer);return 1;
    }
    if (argc>5 && strcmp(argv[argc-1],"--installed")==0) demo.installed=1;
    backend.context=&demo;backend.device=device;
    memset(&screen,0,sizeof(screen));
    memset(&activity,0,sizeof(activity));
    if (strcmp(argv[1],"--activity")==0) {
        vm=e63_android_activity_event(&session,&activity,&screen,&backend,
                                       "onCreate",0,0u);
        if (vm==E63_JAVA_OK)
            vm=e63_android_activity_event(&session,&activity,&screen,&backend,
                                           "onStart",0,0u);
        if (vm==E63_JAVA_OK)
            vm=e63_android_activity_event(&session,&activity,&screen,&backend,
                                           "onResume",0,0u);
    } else vm=e63_android_event(&session,&screen,&backend,"onStart",0,0u);
    if (vm==E63_JAVA_OK && strcmp(argv[4],"onSelect")==0 && argc>=6) {
        a[0].type=E63_JAVA_INT;a[0].number=(int32_t)strtol(argv[5],0,10);
        a[0].string=0;
        vm=strcmp(argv[1],"--activity")==0 ?
            e63_android_activity_event(&session,&activity,&screen,&backend,
                                       "choose",a,1u) :
            e63_android_event(&session,&screen,&backend,"onSelect",a,1u);
    } else if (vm==E63_JAVA_OK && strcmp(argv[4],"onCommand")==0 && argc>=8) {
        a[0].type=E63_JAVA_INT;a[0].number=(int32_t)strtol(argv[5],0,10);
        a[0].string=0;
        a[1].type=E63_JAVA_STRING;a[1].number=0;a[1].string=argv[6];
        a[2].type=E63_JAVA_STRING;a[2].number=0;a[2].string=argv[7];
        vm=strcmp(argv[1],"--activity")==0 ?
            e63_android_activity_event(&session,&activity,&screen,&backend,
                                       "command",a,3u) :
            e63_android_event(&session,&screen,&backend,"onCommand",a,3u);
    } else if (vm==E63_JAVA_OK && strcmp(argv[4],"onResume")==0 &&
               strcmp(argv[1],"--activity")==0) {
        vm=e63_android_activity_event(&session,&activity,&screen,&backend,
                                       "onPause",0,0u);
        if (vm==E63_JAVA_OK) vm=e63_android_activity_event(&session,&activity,
                          &screen,&backend,"onStop",0,0u);
        if (vm==E63_JAVA_OK) vm=e63_android_activity_event(&session,&activity,
                          &screen,&backend,"onStart",0,0u);
        if (vm==E63_JAVA_OK) vm=e63_android_activity_event(&session,&activity,
                          &screen,&backend,"onResume",0,0u);
    } else if (strcmp(argv[4],"onStart")!=0) vm=E63_JAVA_BAD_INPUT;
    if (vm==E63_JAVA_OK) {
        printf("PIN_OK: %s, owned assets validated\n",session.package_name);
        if (strcmp(argv[1],"--activity")==0)
            printf("ACTIVITY_DEX: constructed=%u created=%u started=%u "
                   "resumed=%u resumedOnce=%u\n",activity.constructed,
                   activity.created,activity.started,activity.resumed,
                   activity.resumed_once);
        dump(&screen);
    } else fprintf(stderr,"VM: %s\n",e63_java_status(vm));
    free(buffer);
    return vm==E63_JAVA_OK ? 0 : 1;
    }
