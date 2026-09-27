/* Desktop verification of the exact pinned per-APK preview image pack.
 * This is a raw RGB565 resource test, not an E63 display screenshot.
 */
#include "apk_image_pack.h"
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char **argv)
    {
    FILE *f;
    long size;
    uint8_t *buffer;
    E63ApkImages pack;
    E63ApkImage image;
    if (argc!=4) {
        fprintf(stderr,"usage: apk_image_cli images565.bin package image.png\n");
        return 2;
    }
    f=fopen(argv[1],"rb");
    if (!f) return 2;
    if (fseek(f,0,SEEK_END)!=0 || (size=ftell(f))<0 || size>1048576 ||
        fseek(f,0,SEEK_SET)!=0) {fclose(f);return 2;}
    buffer=(uint8_t *)malloc(size ? (size_t)size : 1u);
    if (!buffer) {fclose(f);return 2;}
    if (fread(buffer,1,(size_t)size,f)!=(size_t)size)
        {free(buffer);fclose(f);return 2;}
    fclose(f);
    if (!e63_apk_images_open(&pack,buffer,(size_t)size))
        {fprintf(stderr,"image pack pin/format invalid\n");free(buffer);return 1;}
    if (!e63_apk_images_find(&pack,argv[2],argv[3],&image))
        {fprintf(stderr,"package does not own this image\n");free(buffer);return 1;}
    printf("IMAGE: %s %s %ux%u first RGB565 little-endian %02x%02x\n",
           argv[2],argv[3],image.width,image.height,
           image.pixels_le[0],image.pixels_le[1]);
    free(buffer);return 0;
    }
