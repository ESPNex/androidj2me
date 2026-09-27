/* PC-only proof: the native C99 VM executes actual D8 Java Program methods
 * extracted from SIX Android APKs. Printed Host services are TEST STUBS, not
 * real Android UI, Symbian display, package management or APK trust.
 */
#include "apk_dex_loader.h"
#include "apk_java_vm.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct DemoHost { int wifi, installed; } DemoHost;
static int invoke(void *context, E63JavaService service,
                  const E63JavaValue *a, unsigned count, E63JavaValue *out)
    {
    DemoHost *h=(DemoHost *)context;
    const char *s=count && a[0].type==E63_JAVA_STRING ? a[0].string : "";
    out->type=E63_JAVA_INT;out->number=0;out->string=0;
    switch(service) {
        case E63_SERVICE_TITLE: printf("TITLE: %s\n",s);return 0;
        case E63_SERVICE_TEXT: printf("TEXT: %s\n",s);return 0;
        case E63_SERVICE_IMAGE: printf("IMAGE: %s\n",s);return 0;
        case E63_SERVICE_OPTION:printf("OPTION: %d %s\n",a[0].number,a[1].string);return 0;
        case E63_SERVICE_INPUT:printf("INPUT: %d %s\n",a[0].number,a[1].string);return 0;
        case E63_SERVICE_DIALOG:printf("DIALOG: %s\n",s);return 0;
        case E63_SERVICE_OPEN:printf("OPEN: %s\n",s);return 0;
        case E63_SERVICE_LIST:printf("LIST: %s\n",s);return 0;
        case E63_SERVICE_GET_FLAG:
            out->number=strcmp(s,"wifi_demo")==0 ? h->wifi : 0;return 0;
        case E63_SERVICE_SET_FLAG:
            if (strcmp(s,"wifi_demo")==0) h->wifi=a[1].number;
            printf("SETFLAG: %s=%d\n",s,a[1].number);return 0;
        case E63_SERVICE_IS_INSTALLED:
            out->number=h->installed;return 0;
        case E63_SERVICE_SEARCH_FILE:
            out->number=strstr(s,"file")!=0 || strstr(s,"FILE")!=0;return 0;
        case E63_SERVICE_INSTALL:
            printf("INSTALL REQUEST: %s\n",s);out->number=1;return 0;
        case E63_SERVICE_WAV:printf("WAV: %s\n",s);out->number=1;return 0;
        case E63_SERVICE_MKDIR: case E63_SERVICE_TOUCH: case E63_SERVICE_DELETE:
        case E63_SERVICE_RENAME: case E63_SERVICE_IMPORT_FILE:
            printf("FILE COMMAND: %d %s\n",service,s);
            out->number=1;return 0;
        default:return 1;
    }
    }

int main(int argc, char **argv)
    {
    FILE *file;
    long length;
    uint8_t *buffer;
    E63DexView dex;
    E63JavaHost host;
    E63JavaStatus result;
    E63JavaValue args[3];
    DemoHost context={0,0};
    const char *method, *proto;
    unsigned count=0;
    if (argc<4 || argc>7) {
        fprintf(stderr,"usage: apk_java_cli app.apk Lpackage/Program; "
                       "onStart|onSelect|onCommand [number [arg1 arg2]]\n");
        return 2;
    }
    method=argv[3];
    memset(args,0,sizeof(args));
    if (strcmp(method,"onStart")==0 && argc==4) proto="()V";
    else if (strcmp(method,"onSelect")==0 && argc==5) {
        proto="(I)V";count=1;args[0].type=E63_JAVA_INT;
        args[0].number=(int32_t)strtol(argv[4],0,10);
    } else if (strcmp(method,"onCommand")==0 && argc==7) {
        proto="(ILjava/lang/String;Ljava/lang/String;)V";count=3;
        args[0].type=E63_JAVA_INT;args[0].number=(int32_t)strtol(argv[4],0,10);
        args[1].type=E63_JAVA_STRING;args[1].string=argv[5];
        args[2].type=E63_JAVA_STRING;args[2].string=argv[6];
    } else {fprintf(stderr,"invalid entry prototype\n");return 2;}
    file=fopen(argv[1],"rb");
    if (!file) { perror("open APK");return 2; }
    if (fseek(file,0,SEEK_END)!=0 || (length=ftell(file))<0 ||
        (unsigned long)length>E63_APK_MAX_BYTES || fseek(file,0,SEEK_SET)!=0)
        {fclose(file);return 2;}
    buffer=(uint8_t *)malloc(length>0 ? (size_t)length : 1u);
    if (!buffer) {fclose(file);return 2;}
    if (fread(buffer,1,(size_t)length,file)!=(size_t)length)
        {fclose(file);free(buffer);return 2;}
    fclose(file);
    if (e63_apk_dex_open(buffer,(size_t)length,&dex)!=E63_APK_OK)
        {fprintf(stderr,"APK DEX invalid\n");free(buffer);return 1;}
    host.context=&context;host.invoke=invoke;
    result=e63_java_run(&dex,argv[2],method,proto,args,count,&host);
    if (result!=E63_JAVA_OK) fprintf(stderr,"VM: %s\n",e63_java_status(result));
    free(buffer);
    return result==E63_JAVA_OK ? 0 : 1;
    }
