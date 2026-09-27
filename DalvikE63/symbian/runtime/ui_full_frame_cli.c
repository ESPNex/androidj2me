/* Standalone C99 host-boundary proof, built/run under ASan+UBSan on PC.
 * Reads the original DEX, executes Canvas.paint for seven guest screens,
 * rasterizes a full 320x240 RGB565 frame and calls a MOCK present_frame.
 * Font glyphs and PNGs are intentionally 1-color/1-pixel test substitutes;
 * this checks memory safety and wiring, NOT Nokia pixels or a SIS. The Python
 * reference tests separately check exact full-frame parity with APK assets.
 */
#include "dex_preflight.h"
#include "ui_event_vm.h"
#include "rgb565_painter.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MIDLET "Landroid/j2me/edition/E63Midlet;"
#define CANVAS "Landroid/j2me/edition/E63Canvas;"
#define STORE "Landroid/j2me/edition/StoreState;"
#define FONT "Ljavax/microedition/lcdui/Font;"
#define IMAGE "Ljavax/microedition/lcdui/Image;"
#define GRAPHICS "Ljavax/microedition/lcdui/Graphics;"
#define PAINT "(Ljavax/microedition/lcdui/Graphics;)V"

static uint8_t solid_mask[160u*7u*10u];
static const uint8_t icon_pixel[4]={40,180,225,255};

typedef struct Proof {
    uint32_t presented;
} Proof;

static int font_height(void *unused,int32_t size,int32_t *out) {
    (void)unused;
    if (!out || (size!=0 && size!=8 && size!=16)) return 1;
    *out=size==8 ? 12 : size==16 ? 18 : 14;
    return 0;
}
static int font_width(void *unused,int32_t size,const char *text,int32_t *out) {
    size_t n;
    (void)unused;
    if (!out || !text || (size!=0 && size!=8 && size!=16)) return 1;
    n=strlen(text);
    if (n>E63_UI_MAX_TEXT_BYTES) return 1;
    *out=(int32_t)(n*7u);
    return 0;
}
static int image_bounds(void *unused,int32_t id,int32_t *w,int32_t *h) {
    (void)unused;
    if (id<1 || id>11 || !w || !h) return 1;
    *w=*h=1;
    return 0;
}
static int image_rgba(void *unused,int32_t id,E63RgbaResource *out) {
    (void)unused;
    if (id<1 || id>11 || !out) return 1;
    out->pixels=icon_pixel;out->size=sizeof(icon_pixel);
    out->stride=4u;out->width=1;out->height=1;
    return 0;
}
static int glyph_mask(void *unused,int32_t size,const char *text,
                      E63GlyphResource *out) {
    size_t n;
    (void)unused;
    if (!out || !text || (size!=0 && size!=8 && size!=16)) return 1;
    n=strlen(text);
    if (n>E63_UI_MAX_TEXT_BYTES) return 1;
    out->alpha=solid_mask;out->size=sizeof(solid_mask);
    out->stride=(uint32_t)(n*7u);
    out->width=(int32_t)(n*7u);out->height=n ? 10 : 0;
    out->left=0;out->top=0;
    return 0;
}
static int local_clock(void *unused,int32_t *hour,int32_t *minute) {
    (void)unused;
    if (!hour || !minute) return 1;
    *hour=9;*minute=7;
    return 0;
}
static E63Result present_frame(void *context,const uint16_t *pixels,
                               uint16_t width,uint16_t height) {
    Proof *p=(Proof *)context;
    size_t i;
    uint32_t lit=0;
    if (!p || !pixels || width!=320u || height!=240u) return E63_INVALID;
    for (i=0;i<(size_t)width*height;i++) if (pixels[i]) ++lit;
    if (lit<200u) return E63_INVALID;
    p->presented++;
    return E63_OK;
}
static int set_ref(const E63DexView *dex,E63UiVm *vm,uint32_t obj,
                   const char *owner,const char *name,const char *type,
                   uint32_t ref) {
    int field=e63_dex_field_id(dex,owner,name,type);
    return field>=0 && e63_ui_set_ref(vm,obj,(uint32_t)field,ref)==E63_UI_OK;
}
static int set_int(const E63DexView *dex,E63UiVm *vm,uint32_t obj,
                   const char *owner,const char *name,const char *type,
                   int32_t number) {
    int field=e63_dex_field_id(dex,owner,name,type);
    return field>=0 && e63_ui_set_int(vm,obj,(uint32_t)field,number)==E63_UI_OK;
}

int main(int argc,char **argv) {
    static const char *images[11]={
        "storeIcon","settingsIcon","fileIcon","navBack","navHome",
        "navRecent","wifiStatus","wall","drawerIcon","wifiIcon",
        "settingsMini"};
    static const int screens[7]={1,10,13,14,15,16,17};
    FILE *input=0;
    uint8_t *dex_data=0;
    long length;
    E63DexView dex;
    E63UiVm *vm=0;
    E63Rgb565Painter *raster=0;
    E63Rgb565Resources resources;
    E63UiPaintHost paint;
    E63DeviceOps device;
    Proof proof;
    uint32_t midlet,canvas,store,graphics,small,medium,large,selected;
    uint32_t icon;
    int field,rc=1,i;
    if (argc!=2 || !(input=fopen(argv[1],"rb"))) {
        fputs("usage: e63_ui_full_frame_check classes.dex\n",stderr);
        return 2;
    }
    if (fseek(input,0,SEEK_END)!=0 || (length=ftell(input))<0 ||
        (unsigned long)length>E63_DEX_MAX_BYTES ||
        fseek(input,0,SEEK_SET)!=0) goto done;
    dex_data=(uint8_t *)malloc(length ? (size_t)length : 1u);
    if (!dex_data || fread(dex_data,1,(size_t)length,input)!=(size_t)length ||
        e63_dex_open(dex_data,(size_t)length,&dex)!=E63_DEX_OK) goto done;
    memset(solid_mask,255,sizeof(solid_mask));
    memset(&proof,0,sizeof(proof));
    memset(&resources,0,sizeof(resources));
    resources.image_rgba=image_rgba;resources.text_mask=glyph_mask;
    raster=e63_rgb565_new(320u,240u,&resources);
    vm=e63_ui_new(&dex,0,0);
    if (!vm || !raster) goto done;
    memset(&paint,0,sizeof(paint));
    paint.font_height=font_height;paint.font_width=font_width;
    paint.image_bounds=image_bounds;paint.commit=e63_rgb565_commit;
    paint.context=raster;
    paint.local_clock=local_clock;
    memset(&device,0,sizeof(device));
    device.context=&proof;device.present_frame=present_frame;
    if (e63_ui_set_viewport(vm,320u,240u)!=E63_UI_OK ||
        e63_ui_set_paint_host(vm,&paint)!=E63_UI_OK ||
        e63_ui_object(vm,MIDLET,&midlet)!=E63_UI_OK ||
        e63_ui_object(vm,CANVAS,&canvas)!=E63_UI_OK ||
        e63_ui_object(vm,STORE,&store)!=E63_UI_OK ||
        e63_ui_host_object(vm,GRAPHICS,0,&graphics)!=E63_UI_OK ||
        e63_ui_host_object(vm,FONT,8,&small)!=E63_UI_OK ||
        e63_ui_host_object(vm,FONT,0,&medium)!=E63_UI_OK ||
        e63_ui_host_object(vm,FONT,16,&large)!=E63_UI_OK ||
        !set_ref(&dex,vm,canvas,CANVAS,"app",MIDLET,midlet) ||
        !set_ref(&dex,vm,midlet,MIDLET,"canvas",CANVAS,canvas) ||
        !set_ref(&dex,vm,midlet,MIDLET,"store",STORE,store) ||
        !set_ref(&dex,vm,canvas,CANVAS,"small",FONT,small) ||
        !set_ref(&dex,vm,canvas,CANVAS,"medium",FONT,medium) ||
        !set_ref(&dex,vm,canvas,CANVAS,"large",FONT,large)) goto done;
    for (i=0;i<11;i++) {
        if (e63_ui_host_object(vm,IMAGE,i+1,&icon)!=E63_UI_OK ||
            !set_ref(&dex,vm,canvas,CANVAS,images[i],IMAGE,icon)) goto done;
    }
    if (e63_ui_int_array(vm,18u,&selected)!=E63_UI_OK) goto done;
    field=e63_dex_field_id(&dex,MIDLET,"selected","[I");
    if (field<0 || e63_ui_set_array(vm,midlet,(uint32_t)field,selected)!=E63_UI_OK ||
        !set_int(&dex,vm,store,STORE,"installed","Z",1) ||
        !set_int(&dex,vm,midlet,MIDLET,"battery","I",57) ||
        !set_int(&dex,vm,midlet,MIDLET,"wifiOn","Z",1) ||
        !set_int(&dex,vm,midlet,MIDLET,"adjustClock","Z",1)) goto done;
    for (i=0;i<7;i++) {
        if (!set_int(&dex,vm,midlet,MIDLET,"screen","I",screens[i]) ||
            e63_ui_call_ref(vm,canvas,"paint",PAINT,graphics)!=E63_UI_OK ||
            e63_rgb565_frames(raster)!=(uint32_t)i+1u ||
            e63_rgb565_present(raster,&device)!=E63_OK ||
            proof.presented!=(uint32_t)i+1u) goto done;
    }
    /* Exercise real guest input -> guest screen selection -> paint, too. */
    if (!set_int(&dex,vm,midlet,MIDLET,"screen","I",1)) goto done;
    for (i=0;i<3;i++) {
        int32_t params[2]={i==0 ? 49 : i==1 ? 57 : 160,220};
        if (e63_ui_call(vm,canvas,i<2 ? "keyPressed" : "pointerPressed",
                        i<2 ? "(I)V" : "(II)V",params,i<2 ? 1u : 2u,0)!=E63_UI_OK ||
            e63_ui_call_ref(vm,canvas,"paint",PAINT,graphics)!=E63_UI_OK ||
            e63_rgb565_frames(raster)!=(uint32_t)i+8u ||
            e63_rgb565_present(raster,&device)!=E63_OK ||
            proof.presented!=(uint32_t)i+8u) goto done;
    }
    puts("C99 original DEX: 7 complete RGB565 frames + 3 guest-input frames,"
         " mock device present OK");
    rc=0;
done:
    if (rc) fputs("C99 full-frame standalone proof failed\n",stderr);
    e63_ui_free(vm);e63_rgb565_free(raster);free(dex_data);
    if (input) fclose(input);
    return rc;
}
