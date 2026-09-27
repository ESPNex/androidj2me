/* Host-only C99 smoke on ORIGINAL converted J2ME DEX, NOT a SIS or renderer.
 * Boot -> HOME, numeric 8 -> Settings focus, numeric 5 -> SETTINGS: all
 * screen/focus decisions come from E63Canvas/E63Midlet methods in the DEX.
 * This prototype seeds fields that a future startApp native port must create.
 */
#include "ui_event_vm.h"
#include <stdio.h>
#include <stdlib.h>

#define MIDLET "Landroid/j2me/edition/E63Midlet;"
#define CANVAS "Landroid/j2me/edition/E63Canvas;"
#define STORE "Landroid/j2me/edition/StoreState;"

static int game_action(void *unused, int32_t key, int32_t *out) {
    (void)unused;
    /* Minimal host key primitive: digit keys are not MIDP D-pad actions. */
    *out=key==-1 ? 1 : key==-2 ? 6 : 0;
    return 0;
}
static int guest_call(E63UiVm *vm, uint32_t canvas, int32_t key) {
    E63UiStatus st=e63_ui_call(vm,canvas,"keyPressed","(I)V",&key,1u,0);
    if (st!=E63_UI_OK) {
        fprintf(stderr,"native guest key %d: %s\n",(int)key,e63_ui_status(st));
        return 0;
    }
    return 1;
}
static int field(const E63DexView *d, const char *owner,
                 const char *name, const char *type) {
    int id=e63_dex_field_id(d,owner,name,type);
    if (id<0) fprintf(stderr,"field absent: %s->%s:%s\n",owner,name,type);
    return id;
}
int main(int argc, char **argv) {
    FILE *source=0;
    uint8_t *bytes=0;
    E63DexView dex;
    E63UiVm *vm=0;
    uint32_t midlet,canvas,store,selected;
    int app,screen,choice,store_id;
    int32_t next_screen=-1,focus=-1;
    int32_t touch[2]={160,220};
    int rc=1;
    size_t size;
    long raw;
    if (argc!=2 || !(source=fopen(argv[1],"rb"))) {
        fprintf(stderr,"usage: e63_ui_event_check classes.dex\n");return 2;
    }
    if (fseek(source,0,SEEK_END)!=0 || (raw=ftell(source))<0 ||
        (unsigned long)raw>E63_DEX_MAX_BYTES || fseek(source,0,SEEK_SET)!=0)
        goto done;
    size=(size_t)raw;
    bytes=(uint8_t *)malloc(size ? size : 1u);
    if (!bytes || fread(bytes,1,size,source)!=size ||
        e63_dex_open(bytes,size,&dex)!=E63_DEX_OK) {
        fprintf(stderr,"DEX preflight/reading failed\n");goto done;
    }
    vm=e63_ui_new(&dex,game_action,0);
    if (!vm || e63_ui_set_viewport(vm,320u,240u)!=E63_UI_OK ||
        e63_ui_object(vm,MIDLET,&midlet)!=E63_UI_OK ||
        e63_ui_object(vm,CANVAS,&canvas)!=E63_UI_OK ||
        e63_ui_object(vm,STORE,&store)!=E63_UI_OK ||
        e63_ui_int_array(vm,18u,&selected)!=E63_UI_OK) goto done;
    app=field(&dex,CANVAS,"app",MIDLET);
    screen=field(&dex,MIDLET,"screen","I");
    choice=field(&dex,MIDLET,"selected","[I");
    store_id=field(&dex,MIDLET,"store",STORE);
    if (app<0 || screen<0 || choice<0 || store_id<0 ||
        e63_ui_set_ref(vm,canvas,(uint32_t)app,midlet)!=E63_UI_OK ||
        e63_ui_set_ref(vm,midlet,(uint32_t)store_id,store)!=E63_UI_OK ||
        e63_ui_set_array(vm,midlet,(uint32_t)choice,selected)!=E63_UI_OK)
        goto done;
    /* navigate()/move() call Canvas.repaint via this typed guest field. */
    app=field(&dex,MIDLET,"canvas",CANVAS);
    if (app<0 || e63_ui_set_ref(vm,midlet,(uint32_t)app,canvas)!=E63_UI_OK)
        goto done;
    if (!guest_call(vm,canvas,53) || !guest_call(vm,canvas,56) ||
        !guest_call(vm,canvas,53) ||
        e63_ui_get_int(vm,midlet,(uint32_t)screen,&next_screen)!=E63_UI_OK ||
        e63_ui_array_get(vm,selected,1u,&focus)!=E63_UI_OK) goto done;
    printf("original Canvas/Midlet DEX: screen=%d focus_home=%d redraw=%d\n",
           (int)next_screen,(int)focus,e63_ui_repaint_pending(vm));
    if (next_screen!=2 || focus!=1 || !e63_ui_repaint_pending(vm) ||
        e63_ui_call(vm,canvas,"pointerPressed","(II)V",touch,2u,0)!=E63_UI_OK ||
        e63_ui_get_int(vm,midlet,(uint32_t)screen,&next_screen)!=E63_UI_OK)
        goto done;
    printf("original Canvas pointer DEX: home_screen=%d\n",(int)next_screen);
    rc=next_screen==1 ? 0 : 1;
done:
    e63_ui_free(vm);free(bytes);fclose(source);
    return rc;
}
