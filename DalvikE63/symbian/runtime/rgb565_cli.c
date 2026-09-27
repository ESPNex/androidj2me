/* C99-only, sanitizer-friendly smoke for the portable RGB565 compositor.
 * Synthetic asset/glyph bytes exercise the raster API without Python; the
 * DEX-driven pixel-parity test separately supplies real APK/font resources.
 */
#include "rgb565_painter.h"
#include <stdio.h>
#include <string.h>

static const uint8_t icon[16]={
    255,0,0,128, 0,255,0,255,
    0,0,255,255, 255,255,255,0
};
static const uint8_t letter_x[9]={255,0,255, 0,255,0, 255,0,255};
static int image(void *unused,int32_t id,E63RgbaResource *out) {
    (void)unused;
    if (id!=1) return 1;
    out->pixels=icon;out->size=sizeof(icon);out->stride=8u;
    out->width=2;out->height=2;
    return 0;
}
static int font(void *unused,int32_t size,const char *text,E63GlyphResource *out) {
    (void)unused;
    if (size!=8 || strcmp(text,"X")!=0) return 1;
    out->alpha=letter_x;out->size=sizeof(letter_x);
    out->stride=3u;out->width=3;out->height=3;
    out->left=0;out->top=0;
    return 0;
}
static uint16_t rgb565(uint32_t color) {
    return (uint16_t)(((color>>19u)&31u)<<11u |
                      ((color>>10u)&63u)<<5u | ((color>>3u)&31u));
}
typedef struct DisplayCheck { uint32_t calls; } DisplayCheck;
static E63Result present(void *context,const uint16_t *pixels,
                         uint16_t width,uint16_t height) {
    DisplayCheck *display=(DisplayCheck *)context;
    if (!pixels || width!=64u || height!=64u ||
        pixels[0]!=rgb565(0xff0000u)) return E63_INVALID;
    display->calls++;
    return E63_OK;
}
int main(void) {
    E63Rgb565Resources resources={0,image,font};
    E63Rgb565Painter *p=e63_rgb565_new(64u,64u,&resources);
    E63DeviceOps device;
    DisplayCheck display={0u};
    E63UiPaintOp ops[8],bad[3];
    const uint16_t *pixels;
    uint16_t color_before;
    int rc=1;
    if (!p) return 2;
    memset(&device,0,sizeof(device));device.context=&display;
    device.present_frame=present;
    if (e63_rgb565_present(p,&device)!=E63_UNAVAILABLE || display.calls!=0u)
        goto done;
    memset(ops,0,sizeof(ops));
    ops[0].code=E63_UI_SET_COLOR;ops[0].a=0x112233;
    ops[1].code=E63_UI_FILL_RECT;ops[1].a=0;ops[1].b=0;
    ops[1].c=64;ops[1].d=64;
    ops[2].code=E63_UI_SET_COLOR;ops[2].a=0xff0000;
    ops[3].code=E63_UI_FILL_RECT;ops[3].a=5;ops[3].b=5;
    ops[3].c=6;ops[3].d=6;
    ops[4].code=E63_UI_DRAW_LINE;ops[4].a=0;ops[4].b=0;
    ops[4].c=3;ops[4].d=0;
    ops[5].code=E63_UI_SET_FONT;ops[5].a=8;
    ops[6].code=E63_UI_DRAW_STRING;ops[6].a=10;ops[6].b=8;
    ops[6].c=20;memcpy(ops[6].text,"X",2u);
    ops[7].code=E63_UI_DRAW_IMAGE;ops[7].a=1;ops[7].b=20;
    ops[7].c=10;ops[7].d=20;
    if (e63_rgb565_commit(p,ops,8u)!=0 || e63_rgb565_frames(p)!=1u ||
        e63_rgb565_present(p,&device)!=E63_OK || display.calls!=1u)
        goto done;
    pixels=e63_rgb565_pixels(p);
    if (!pixels || pixels[0]!=rgb565(0xff0000u) ||
        pixels[63u*64u+63u]!=rgb565(0x112233u) ||
        pixels[5u*64u+5u]!=rgb565(0xff0000u) ||
        pixels[8u*64u+10u]!=rgb565(0xff0000u) ||
        pixels[10u*64u+21u]!=rgb565(0x00ff00u) ||
        pixels[11u*64u+21u]!=rgb565(0x112233u)) goto done;
    color_before=pixels[10u*64u+20u]; /* semitransparent red icon pixel */
    if (color_before==rgb565(0xff0000u) ||
        color_before==rgb565(0x112233u)) goto done;
    memcpy(bad,ops,sizeof(bad));
    bad[0].code=E63_UI_SET_COLOR;bad[0].a=0x00ff00;
    bad[1].code=E63_UI_FILL_RECT;bad[1].a=0;bad[1].b=0;
    bad[1].c=64;bad[1].d=64;
    bad[2].code=99;
    if (e63_rgb565_commit(p,bad,3u)==0 ||
        e63_rgb565_commit(p,bad,E63_UI_MAX_DRAW_OPS+1u)==0 ||
        e63_rgb565_frames(p)!=1u ||
        e63_rgb565_pixels(p)[10u*64u+20u]!=color_before ||
        e63_rgb565_pixels(p)[0]!=rgb565(0xff0000u) ||
        e63_rgb565_present(p,&device)!=E63_OK || display.calls!=2u)
        goto done;
    puts("C99 RGB565: pixels and atomic rollback OK");
    rc=0;
done:
    if (rc) fprintf(stderr,"C99 RGB565 proof failed\n");
    e63_rgb565_free(p);
    return rc;
}
