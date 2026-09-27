/* PC smoke test for the portable C99 APK -> original D8 DEX parser.
 * NOT an Android installation, cryptographic signature check or E63 run.
 */
#include "apk_dex_loader.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
    {
    FILE *file;
    uint8_t *buffer;
    long length;
    E63DexView dex;
    E63DexMethod method;
    E63ApkStatus status;
    if (argc!=3)
        { fprintf(stderr,"usage: apk_dex_cli app.apk Lpackage/Program;\n"); return 2; }
    file=fopen(argv[1],"rb");
    if (!file) { perror("open APK");return 2; }
    if (fseek(file,0,SEEK_END)!=0 || (length=ftell(file))<0 ||
        (unsigned long)length>E63_APK_MAX_BYTES || fseek(file,0,SEEK_SET)!=0)
        { fclose(file);return 2; }
    buffer=(uint8_t *)malloc(length>0 ? (size_t)length : 1u);
    if (!buffer) { fclose(file);return 2; }
    if (fread(buffer,1,(size_t)length,file)!=(size_t)length)
        { fclose(file);free(buffer);return 2; }
    fclose(file);
    status=e63_apk_dex_open(buffer,(size_t)length,&dex);
    if (status!=E63_APK_OK)
        { fprintf(stderr,"APK DEX: %s\n",e63_apk_status(status));free(buffer);return 1; }
    if (e63_dex_find_code(&dex,argv[2],"onStart","()V",&method)!=1 ||
        e63_dex_find_code(&dex,argv[2],"onSelect","(I)V",&method)!=1)
        { fprintf(stderr,"APK lacks Java Program entry code\n");free(buffer);return 1; }
    printf("stored APK DEX: classes=%u methods=%u Program bytecode=%u words; "
           "CRC/DEX preflight OK (APK signature NOT verified here)\n",
           dex.classes_count,dex.methods_count,method.words_count);
    free(buffer);
    return 0;
    }
