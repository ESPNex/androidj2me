/* Host-only smoke-test executable for dex_preflight.c; NOT a phone runtime. */
#include "dex_preflight.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
    {
    FILE *input;
    uint8_t *data;
    long length;
    size_t count;
    E63DexView view;
    E63DexStatus status;
    int ui;
    if (argc!=2) { fprintf(stderr,"usage: e63_dex_check classes.dex\n");return 2; }
    input=fopen(argv[1],"rb");
    if (!input) { perror("open DEX");return 2; }
    if (fseek(input,0,SEEK_END)!=0 || (length=ftell(input))<0 ||
        (unsigned long)length>E63_DEX_MAX_BYTES || fseek(input,0,SEEK_SET)!=0)
        { fclose(input);fprintf(stderr,"DEX too large/seek failed\n");return 2; }
    data=(uint8_t *)malloc(length>0 ? (size_t)length : 1u);
    if (!data) { fclose(input);return 2; }
    count=fread(data,1,(size_t)length,input);
    fclose(input);
    if (count!=(size_t)length)
        { free(data);fprintf(stderr,"short DEX read\n");return 2; }
    status=e63_dex_open(data,count,&view);
    if (status!=E63_DEX_OK)
        { fprintf(stderr,"DEX preflight: %s\n",e63_dex_status(status));free(data);return 1; }
    ui=e63_dex_has_code(&view,"Landroid/j2me/edition/E63Canvas;","paint") &&
       e63_dex_has_code(&view,"Landroid/j2me/edition/E63Midlet;","startApp");
    printf("dex035 classes=%u method_ids=%u with_code=%d guest_ui=%d\n",
           view.classes_count,view.methods_count,e63_dex_count_code(&view),ui);
    free(data);
    return ui ? 0 : 1;
    }
