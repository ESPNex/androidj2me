#ifndef E63_APK_IMAGE_PACK_H
#define E63_APK_IMAGE_PACK_H
/* SHA-256-pinned RGB565 thumbnails from each *owning* Android Java APK.
 * PNGs are decoded offline from those exact APKs; a dynamic PNG decoder and
 * full Android graphics stack are NOT present on E63. Byte buffer borrowed.
 */
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct E63ApkImages {
    const uint8_t *data;
    size_t size;
    unsigned count;
} E63ApkImages;
typedef struct E63ApkImage {
    const uint8_t *pixels_le;
    unsigned width,height;
} E63ApkImage;
int e63_apk_images_open(E63ApkImages *out,const uint8_t *data,size_t length);
int e63_apk_images_find(const E63ApkImages *images,
                        const char *package_name,const char *asset,
                        E63ApkImage *out);
#ifdef __cplusplus
}
#endif
#endif
