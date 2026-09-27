/* GCC-only proof: original E63Canvas.paintAppDrawer DEX -> MIDP Graphics ops.
 * No baked-in screen/layout code; image IDs are typed resources from the APK.
 * This CLI records commands, not raster pixels or Symbian framebuffer output.
 */
#include "ui_event_vm.h"
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

typedef struct Proof {
    uint32_t commits,ops,images,labels,widgets;
    int fail_metrics,reject_commit;
} Proof;
static int key_action(void *unused, int32_t key, int32_t *out) {
    (void)unused;(void)key;*out=0;return 0;
}
static int font_height(void *context, int32_t size, int32_t *out) {
    Proof *p=(Proof *)context;
    if (p->fail_metrics || (size!=0 && size!=8 && size!=16)) return 1;
    *out=size==8 ? 12 : size==16 ? 18 : 14;
    return 0;
}
static int font_width(void *context, int32_t size, const char *text,
                      int32_t *out) {
    Proof *p=(Proof *)context;
    if (p->fail_metrics || (size!=0 && size!=8 && size!=16)) return 1;
    *out=(int32_t)(strlen(text)*7u); /* device font metric, not layout */
    return 0;
}
static int image_bounds(void *unused, int32_t id,
                        int32_t *width, int32_t *height) {
    (void)unused;
    if (id<1 || id>3) return 1; /* verified APK host resource map */
    *width=34;*height=33;
    return 0;
}
static int commit(void *context, const E63UiPaintOp *ops, uint32_t count) {
    Proof *p=(Proof *)context;
    uint32_t i,images=0,labels=0,widgets=0;
    if (p->reject_commit || !ops || !count || count>E63_UI_MAX_DRAW_OPS)
        return 1; /* previous visible frame would remain untouched */
    for (i=0;i<count;i++) {
        if (ops[i].code==E63_UI_DRAW_IMAGE) images++;
        if (ops[i].code==E63_UI_DRAW_STRING) {
            if (!strcmp(ops[i].text,"Play Store") ||
                !strcmp(ops[i].text,"File Manager") ||
                !strcmp(ops[i].text,"Settings")) labels++;
            if (!strcmp(ops[i].text,"No widgets installed")) widgets++;
        }
        if (ops[i].code<E63_UI_SET_COLOR || ops[i].code>E63_UI_DRAW_LINE)
            return 1;
    }
    p->images=images;p->labels=labels;p->widgets=widgets;p->ops=count;
    p->commits++;
    return 0;
}
static int set_ref(const E63DexView *dex, E63UiVm *vm, uint32_t object,
                   const char *owner, const char *field, const char *kind,
                   uint32_t value) {
    int id=e63_dex_field_id(dex,owner,field,kind);
    return id>=0 && e63_ui_set_ref(vm,object,(uint32_t)id,value)==E63_UI_OK;
}
static int set_int(const E63DexView *dex, E63UiVm *vm, uint32_t object,
                   const char *owner, const char *field, const char *kind,
                   int32_t value) {
    int id=e63_dex_field_id(dex,owner,field,kind);
    return id>=0 && e63_ui_set_int(vm,object,(uint32_t)id,value)==E63_UI_OK;
}
int main(int argc, char **argv) {
    FILE *f=0;
    uint8_t *data=0;
    E63DexView dex;
    E63UiVm *vm=0;
    uint32_t midlet,canvas,store,graphics,small,medium,files,shop,settings,selection;
    E63UiPaintHost paint;
    Proof proof;
    long length;
    int rc=1,field,installed,tab;
    if (argc!=2 || !(f=fopen(argv[1],"rb"))) {
        fprintf(stderr,"usage: e63_ui_paint_check classes.dex\n");return 2;
    }
    if (fseek(f,0,SEEK_END)!=0 || (length=ftell(f))<0 ||
        (unsigned long)length>E63_DEX_MAX_BYTES ||
        fseek(f,0,SEEK_SET)!=0) goto done;
    data=(uint8_t *)malloc(length ? (size_t)length : 1u);
    if (!data || fread(data,1,(size_t)length,f)!=(size_t)length ||
        e63_dex_open(data,(size_t)length,&dex)!=E63_DEX_OK) goto done;
    memset(&proof,0,sizeof(proof));memset(&paint,0,sizeof(paint));
    paint.context=&proof;paint.font_height=font_height;
    paint.font_width=font_width;paint.image_bounds=image_bounds;
    paint.commit=commit;
    vm=e63_ui_new(&dex,key_action,0);
    if (!vm || e63_ui_set_viewport(vm,320u,240u)!=E63_UI_OK ||
        e63_ui_set_paint_host(vm,&paint)!=E63_UI_OK ||
        e63_ui_object(vm,MIDLET,&midlet)!=E63_UI_OK ||
        e63_ui_object(vm,CANVAS,&canvas)!=E63_UI_OK ||
        e63_ui_object(vm,STORE,&store)!=E63_UI_OK ||
        e63_ui_host_object(vm,GRAPHICS,0,&graphics)!=E63_UI_OK ||
        e63_ui_host_object(vm,FONT,8,&small)!=E63_UI_OK ||
        e63_ui_host_object(vm,FONT,0,&medium)!=E63_UI_OK ||
        e63_ui_host_object(vm,IMAGE,1,&shop)!=E63_UI_OK ||
        e63_ui_host_object(vm,IMAGE,2,&settings)!=E63_UI_OK ||
        e63_ui_host_object(vm,IMAGE,3,&files)!=E63_UI_OK ||
        e63_ui_int_array(vm,18u,&selection)!=E63_UI_OK ||
        !set_ref(&dex,vm,canvas,CANVAS,"app",MIDLET,midlet) ||
        !set_ref(&dex,vm,midlet,MIDLET,"store",STORE,store) ||
        !set_ref(&dex,vm,canvas,CANVAS,"small",FONT,small) ||
        !set_ref(&dex,vm,canvas,CANVAS,"medium",FONT,medium) ||
        !set_ref(&dex,vm,canvas,CANVAS,"storeIcon",IMAGE,shop) ||
        !set_ref(&dex,vm,canvas,CANVAS,"settingsIcon",IMAGE,settings) ||
        !set_ref(&dex,vm,canvas,CANVAS,"fileIcon",IMAGE,files) ||
        !set_int(&dex,vm,canvas,CANVAS,"w","I",320) ||
        !set_int(&dex,vm,canvas,CANVAS,"h","I",240)) goto done;
    field=e63_dex_field_id(&dex,MIDLET,"selected","[I");
    if (field<0 || e63_ui_set_array(vm,midlet,(uint32_t)field,selection)!=E63_UI_OK)
        goto done;
    for (tab=0;tab<=1;tab++) for (installed=0;installed<=1;installed++) {
        uint32_t before=proof.commits;
        if (!set_int(&dex,vm,midlet,MIDLET,"widgetsTab","Z",tab) ||
            !set_int(&dex,vm,store,STORE,"installed","Z",installed) ||
            e63_ui_call_ref(vm,canvas,"paintAppDrawer",PAINT,graphics)!=E63_UI_OK ||
            proof.commits!=before+1u ||
            proof.images!=(uint32_t)(tab ? 0 : installed ? 3 : 2) ||
            proof.widgets!=(uint32_t)(tab ? 1 : 0) ||
            (tab==0 && installed==0 && proof.labels!=2u) ||
            (tab==0 && installed==1 && proof.labels!=3u)) goto done;
        printf("original DEX drawer: widgets=%d installed=%d ops=%u images=%u labels=%u\n",
               tab,installed,(unsigned)proof.ops,(unsigned)proof.images,
               (unsigned)proof.labels);
    }
    proof.fail_metrics=1;
    if (e63_ui_call_ref(vm,canvas,"paintAppDrawer",PAINT,graphics)!=
        E63_UI_UNSUPPORTED || proof.commits!=4u) goto done;
    proof.fail_metrics=0;proof.reject_commit=1;
    if (e63_ui_call_ref(vm,canvas,"paintAppDrawer",PAINT,graphics)!=
        E63_UI_UNSUPPORTED || proof.commits!=4u) goto done;
    puts("font fault/atomic frame rejection: no partial commit");
    rc=0;
done:
    if (rc) fprintf(stderr,"original native paint proof failed\n");
    e63_ui_free(vm);free(data);fclose(f);
    return rc;
}
