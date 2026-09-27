#include "apk_image_pack.h"
#include "apk_sha256.h"
#include "../android_java_app/apk_pins.h"
#include <string.h>

#define IMAGE_HEADER 16u
#define IMAGE_RECORD 156u
#define IMAGE_LIMIT (1024u*1024u)
static unsigned read16(const uint8_t *p)
    {return (unsigned)p[0] | ((unsigned)p[1]<<8u);}
static uint32_t read32(const uint8_t *p)
    {return (uint32_t)p[0] | ((uint32_t)p[1]<<8u) |
            ((uint32_t)p[2]<<16u) | ((uint32_t)p[3]<<24u);}
static int term_within(const uint8_t *p,size_t length)
    {return memchr(p,0,length)!=0;}
int e63_apk_images_open(E63ApkImages *out,const uint8_t *data,size_t length)
    {
    uint8_t digest[32];
    unsigned count,i;
    if (!out) return 0;
    memset(out,0,sizeof(*out));
    if (!data || length<IMAGE_HEADER || length>IMAGE_LIMIT ||
        memcmp(data,"E63I5651",8u)!=0) return 0;
    count=read32(data+8u);
    if (!count || count>24u || read32(data+12u)!=length ||
        IMAGE_HEADER+(size_t)count*IMAGE_RECORD>length) return 0;
    e63_apk_sha256(data,length,digest);
    if (memcmp(digest,e63_apk_images_sha256,32u)!=0) return 0;
    for (i=0u;i<count;++i) {
        const uint8_t *rec=data+IMAGE_HEADER+(size_t)i*IMAGE_RECORD;
        size_t pos=read32(rec+148u),bytes=read32(rec+152u);
        unsigned w=read16(rec+144u),h=read16(rec+146u);
        if (!term_within(rec,64u) || !term_within(rec+64u,80u) ||
            !w || w>512u || !h || h>512u ||
            bytes!=(size_t)w*h*2u || pos<IMAGE_HEADER+(size_t)count*IMAGE_RECORD ||
            pos>length || bytes>length-pos) return 0;
    }
    out->data=data;out->size=length;out->count=count;
    return 1;
    }
int e63_apk_images_find(const E63ApkImages *images,
                        const char *package_name,const char *asset,
                        E63ApkImage *out)
    {
    unsigned i;
    if (!out) return 0;
    memset(out,0,sizeof(*out));
    if (!images || !images->data || !package_name || !asset) return 0;
    for (i=0u;i<images->count;++i) {
        const uint8_t *entry=images->data+IMAGE_HEADER+(size_t)i*IMAGE_RECORD;
        if (strcmp(package_name,(const char *)entry)==0 &&
            strcmp(asset,(const char *)entry+64u)==0) {
            out->width=read16(entry+144u);
            out->height=read16(entry+146u);
            out->pixels_le=images->data+read32(entry+148u);
            return 1;
        }
    }
    return 0;
    }
