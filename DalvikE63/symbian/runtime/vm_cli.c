/* Host-only StoreState bytecode exerciser. Does NOT render MIDP UI or build SIS. */
#include "dex_vm.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define STORE "Landroid/j2me/edition/StoreState;"

static int call(E63VmObject *obj, const char *name, const char *proto,
                const int32_t *args, uint32_t n, int32_t *out)
    {
    E63VmStatus status=e63_vm_call(obj,name,proto,args,n,out);
    if (status!=E63_VM_OK)
        {fprintf(stderr,"DEX %s%s: %s\n",name,proto,e63_vm_status(status));return 0;}
    return 1;
    }

int main(int argc, char **argv)
    {
    FILE *file;
    uint8_t *image=0;
    size_t length;
    long raw_length;
    E63DexView dex;
    E63VmObject *guest=0;
    int32_t saved=0, result, first, wait, open;
    int rc=1;
    if (argc!=2 || !(file=fopen(argv[1],"rb")))
        {fprintf(stderr,"usage: e63_vm_check classes.dex\n");return 2;}
    if (fseek(file,0,SEEK_END)!=0 || (raw_length=ftell(file))<0 ||
        (unsigned long)raw_length>E63_DEX_MAX_BYTES || fseek(file,0,SEEK_SET)!=0)
        {fprintf(stderr,"invalid DEX size\n");goto done;}
    length=(size_t)raw_length;
    image=(uint8_t *)malloc(length ? length : 1u);
    guest=(E63VmObject *)malloc(sizeof(*guest));
    if (!image || !guest || fread(image,1,length,file)!=length)
        {fprintf(stderr,"DEX allocation/read failed\n");goto done;}
    if (e63_dex_open(image,length,&dex)!=E63_DEX_OK ||
        e63_vm_new(&dex,STORE,guest)!=E63_VM_OK)
        {fprintf(stderr,"converted J2ME DEX failed preflight\n");goto done;}
    if (!call(guest,"<init>","(Z)V",&saved,1,0) ||
        !call(guest,"activate","()I",0,0,&first) ||
        !call(guest,"activate","()I",0,0,&wait) ||
        !call(guest,"finishInstall","()V",0,0,0) ||
        !call(guest,"activate","()I",0,0,&open) ||
        !call(guest,"isInstalled","()Z",0,0,&result)) goto done;
    printf("guest StoreState DEX: first=%d waiting=%d after=%d installed=%d\n",
           first,wait,open,result);
    rc=(first==1 && wait==3 && open==2 && result==1) ? 0 : 1;
done:
    free(guest);free(image);fclose(file);
    return rc;
    }
