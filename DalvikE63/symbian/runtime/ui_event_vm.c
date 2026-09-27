#include "ui_event_vm.h"
#include <limits.h>
#include <stdlib.h>
#include <string.h>

/* S60 FP1 libc has no snprintf. Convert exactly an int32_t with a fixed
 * bound; unsigned subtraction also handles INT32_MIN without overflow. */
static int decimal32(char *out, size_t capacity, int32_t n) {
    char reversed[10];
    uint32_t value = (uint32_t)n;
    size_t length = 0, written = 0;
    int negative = n < 0;
    if (!out) return -1;
    if (negative) value = 0u - value;
    do {
        reversed[length++] = (char)('0' + value % 10u);
        value /= 10u;
    } while (value);
    if (length + (negative ? 1u : 0u) >= capacity) return -1;
    if (negative) out[written++] = '-';
    while (length) out[written++] = reversed[--length];
    out[written] = '\0';
    return 0;
}

/* No cast of DEX bytes to unaligned uint16_t*: E63/ARM may fault. */
static uint16_t le16(const uint8_t *p) {
    return (uint16_t)((uint16_t)p[0] | (uint16_t)((uint16_t)p[1]<<8));
}
static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1]<<8) |
           ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24);
}
static uint16_t w16(const E63DexMethod *m, uint32_t pc) {
    return le16(m->words_le+(size_t)pc*2u);
}
static int32_t signed16(uint16_t n) {
    return n>=0x8000u ? (int32_t)n-65536 : (int32_t)n;
}
static int32_t signed8(uint32_t n) {
    return n>=128u ? (int32_t)n-256 : (int32_t)n;
}
static int32_t signed4(uint32_t n) {
    return n>=8u ? (int32_t)n-16 : (int32_t)n;
}
static int32_t arithmetic_shr(int32_t n, uint32_t shift) {
    uint32_t distance=shift&31u;
    uint32_t result=(uint32_t)n>>distance;
    if (n<0 && distance) result|=~(UINT32_MAX>>distance);
    return (int32_t)result;
}
static int span(const E63DexView *v, uint64_t at, uint64_t size) {
    return at<=v->size && size<=v->size-at;
}

typedef enum ValueKind {
    UI_EMPTY=0, UI_INT=1, UI_REF=2, UI_ARRAY=3, UI_STRING=4,
    UI_VOID=5, UI_DYNSTRING=6, UI_LONG=7, UI_WIDE_HIGH=8
} ValueKind;
typedef struct UiValue {
    int32_t bits;
    ValueKind kind;
    int64_t wide; /* only UI_LONG uses this; its next register is UI_WIDE_HIGH */
} UiValue;
typedef enum HostKind {
    HOST_NONE=0, HOST_GRAPHICS=1, HOST_FONT=2, HOST_IMAGE=3,
    HOST_STRINGBUFFER=4, HOST_CALENDAR=5
} HostKind;
typedef struct UiObject {
    uint32_t type_index;
    HostKind host_kind;
    int32_t native_id;
    char descriptor[128];
    char text[E63_UI_MAX_TEXT_BYTES+1u]; /* bounded StringBuffer, not UI logic */
    UiValue fields[E63_UI_MAX_FIELDS];
} UiObject;
typedef struct UiArray {
    uint32_t count, type_index;
    ValueKind element_kind; /* UI_INT for int/byte, UI_ARRAY for [[B */
    int32_t items[E63_UI_MAX_ARRAY_ITEMS];
} UiArray;
typedef struct UiString {
    char ascii[E63_UI_MAX_TEXT_BYTES+1u];
} UiString;
struct E63UiVm {
    const E63DexView *dex;     /* borrowed; immutable after e63_dex_open */
    E63UiGameAction action;
    void *context;
    E63UiTimeMillis time_millis;
    void *time_context;
    UiObject objects[E63_UI_MAX_OBJECTS];
    UiArray arrays[E63_UI_MAX_ARRAYS];
    UiString strings[E63_UI_MAX_STRINGS];
    UiValue static_fields[E63_UI_MAX_FIELDS];
    uint32_t object_count, array_count, string_count, steps, depth;
    int canvas_initialized;
    uint16_t width, height;
    int repaint_pending;
    E63UiPaintHost paint_host;
    E63UiPaintOp *paint_ops; /* allocated only when a paint host is attached */
    uint32_t paint_count;
};

static UiValue value(ValueKind kind, int32_t bits) {
    UiValue v;
    v.kind=kind;v.bits=bits;v.wide=0;
    return v;
}
static UiValue long_value(int64_t number) {
    UiValue v=value(UI_LONG,0);
    v.wide=number;
    return v;
}
static int long_register(const UiValue *regs, uint32_t count, uint32_t index) {
    return index+1u<count && regs[index].kind==UI_LONG &&
           regs[index+1u].kind==UI_WIDE_HIGH;
}
static void set_long_register(UiValue *regs, uint32_t index, int64_t number) {
    regs[index]=long_value(number);
    regs[index+1u]=value(UI_WIDE_HIGH,0);
}
static UiObject *object(E63UiVm *vm, uint32_t handle) {
    return vm && handle>0 && handle<=vm->object_count ?
           &vm->objects[handle-1u] : 0;
}
static const UiObject *object_ro(const E63UiVm *vm, uint32_t handle) {
    return vm && handle>0 && handle<=vm->object_count ?
           &vm->objects[handle-1u] : 0;
}
static UiArray *array(E63UiVm *vm, uint32_t handle) {
    return vm && handle>0 && handle<=vm->array_count ?
           &vm->arrays[handle-1u] : 0;
}
static const UiArray *array_ro(const E63UiVm *vm, uint32_t handle) {
    return vm && handle>0 && handle<=vm->array_count ?
           &vm->arrays[handle-1u] : 0;
}

/* DEX type string begins after ULEB(UTF-16 length); dex_open already checked
 * all type indices and all terminated string_data, but recheck offsets here. */
static const uint8_t *type_start(const E63DexView *d, uint32_t index) {
    uint32_t string_id, off;
    uint32_t k;
    if (!d || index>=d->types_count) return 0;
    string_id=le32(d->data+d->types_off+(size_t)index*4u);
    if (string_id>=d->strings_count) return 0;
    off=le32(d->data+d->strings_off+(size_t)string_id*4u);
    for (k=0;k<5;k++) {
        uint8_t b;
        if (!span(d,off,1)) return 0;
        b=d->data[off++];
        if (!(b & 0x80u)) return span(d,off,1) ? d->data+off : 0;
    }
    return 0;
}
static int find_type(const E63DexView *dex, const char *descriptor) {
    uint32_t i;
    if (!dex || !descriptor) return -1;
    for (i=0;i<dex->types_count;i++) {
        const uint8_t *type=type_start(dex,i);
        if (type && strcmp((const char *)type,descriptor)==0) return (int)i;
    }
    return -1;
}

static int field_kind(const E63DexView *d, uint32_t index,
                      uint32_t *owner, uint32_t *type) {
    const uint8_t *entry, *text;
    if (!d || index>=d->fields_count) return UI_EMPTY;
    entry=d->data+d->fields_off+(size_t)index*8u;
    *owner=le16(entry);*type=le16(entry+2u);
    text=type_start(d,*type);
    if (!text) return UI_EMPTY;
    if (text[0]=='I' && text[1]==0) return UI_INT;
    if (text[0]=='Z' && text[1]==0) return UI_INT;
    if (text[0]=='J' && text[1]==0) return UI_LONG;
    if (text[0]=='[') return UI_ARRAY;
    if (text[0]=='L') return UI_REF;
    return UI_EMPTY;
}
static E63UiStatus field_access(const E63UiVm *vm, uint32_t receiver,
                                uint32_t field, int expected, UiObject **out,
                                uint32_t *field_type) {
    uint32_t owner, type;
    UiObject *obj=object((E63UiVm *)vm,receiver);
    int kind;
    if (!obj || !vm->dex || field>=E63_UI_MAX_FIELDS) return E63_UI_INVALID;
    kind=field_kind(vm->dex,field,&owner,&type);
    if (kind!=expected || owner!=obj->type_index) return E63_UI_UNSUPPORTED;
    *out=obj;
    if (field_type) *field_type=type;
    return E63_UI_OK;
}

static E63UiStatus run(E63UiVm *vm, const E63DexMethod *m,
                       const UiValue *args, uint32_t argc, UiValue *result);

E63UiVm *e63_ui_new(const E63DexView *dex, E63UiGameAction action, void *context) {
    E63UiVm *vm;
    if (!dex || !dex->data || dex->fields_count>E63_UI_MAX_FIELDS) return 0;
    vm=(E63UiVm *)calloc(1,sizeof(*vm));
    if (vm) {vm->dex=dex;vm->action=action;vm->context=context;}
    return vm;
}
void e63_ui_free(E63UiVm *vm) {
    if (vm) {free(vm->paint_ops);free(vm);}
}
E63UiStatus e63_ui_set_time_host(E63UiVm *vm, E63UiTimeMillis clock,
                                void *context) {
    if (!vm) return E63_UI_INVALID;
    vm->time_millis=clock;
    vm->time_context=context;
    return E63_UI_OK;
}
E63UiStatus e63_ui_set_paint_host(E63UiVm *vm,
                                  const E63UiPaintHost *host) {
    if (!vm) return E63_UI_INVALID;
    if (!host) {
        memset(&vm->paint_host,0,sizeof(vm->paint_host));
        free(vm->paint_ops);vm->paint_ops=0;vm->paint_count=0;
        return E63_UI_OK;
    }
    if (!host->font_height || !host->font_width || !host->commit)
        return E63_UI_INVALID;
    if (!vm->paint_ops) {
        vm->paint_ops=(E63UiPaintOp *)calloc(E63_UI_MAX_DRAW_OPS,
                                             sizeof(*vm->paint_ops));
        if (!vm->paint_ops) return E63_UI_LIMIT;
    }
    vm->paint_host=*host;
    vm->paint_count=0;
    return E63_UI_OK;
}
E63UiStatus e63_ui_set_viewport(E63UiVm *vm, uint16_t width, uint16_t height) {
    if (!vm || width<64u || width>1024u || height<64u || height>1024u)
        return E63_UI_INVALID;
    vm->width=width;vm->height=height;
    return E63_UI_OK;
}
E63UiStatus e63_ui_object(E63UiVm *vm, const char *descriptor, uint32_t *handle) {
    int idx;
    size_t length;
    UiObject *dst;
    if (!vm || !descriptor || !handle) return E63_UI_INVALID;
    length=strlen(descriptor);
    if (length<3 || length>=sizeof(vm->objects[0].descriptor)) return E63_UI_INVALID;
    idx=e63_dex_class_index(vm->dex,descriptor);
    if (idx<0) return E63_UI_NO_METHOD;
    if (vm->object_count==E63_UI_MAX_OBJECTS) return E63_UI_LIMIT;
    if (strcmp(descriptor,"Landroid/j2me/edition/E63Canvas;")==0 &&
        !vm->canvas_initialized) {
        E63DexMethod initializer;
        UiValue result=value(UI_EMPTY,0);
        int found=e63_dex_find_code(vm->dex,descriptor,"<clinit>",
                                    "()V",&initializer);
        uint32_t old_count=vm->array_count;
        E63UiStatus st;
        if (found!=1) return E63_UI_UNSUPPORTED;
        vm->steps=0;vm->depth=0;
        st=run(vm,&initializer,0,0,&result);
        if (st!=E63_UI_OK) {
            vm->array_count=old_count;
            memset(vm->static_fields,0,sizeof(vm->static_fields));
            return st;
        }
        vm->canvas_initialized=1;
    }
    dst=&vm->objects[vm->object_count++];
    memset(dst,0,sizeof(*dst));
    dst->type_index=(uint32_t)idx;
    memcpy(dst->descriptor,descriptor,length+1u);
    *handle=vm->object_count;
    return E63_UI_OK;
}
E63UiStatus e63_ui_host_object(E63UiVm *vm, const char *descriptor,
                               int32_t native_id, uint32_t *handle) {
    HostKind host_kind;
    uint32_t i;
    size_t len;
    UiObject *dst;
    if (!vm || !descriptor || !handle) return E63_UI_INVALID;
    len=strlen(descriptor);
    if (len>=sizeof(vm->objects[0].descriptor)) return E63_UI_INVALID;
    if (strcmp(descriptor,"Ljavax/microedition/lcdui/Graphics;")==0 &&
        native_id==0) host_kind=HOST_GRAPHICS;
    else if (strcmp(descriptor,"Ljavax/microedition/lcdui/Font;")==0 &&
             (native_id==0 || native_id==8 || native_id==16))
        host_kind=HOST_FONT;
    else if (strcmp(descriptor,"Ljavax/microedition/lcdui/Image;")==0 &&
             native_id>=1 && native_id<=32)
        host_kind=HOST_IMAGE;
    else return E63_UI_UNSUPPORTED;
    if (vm->object_count>=E63_UI_MAX_OBJECTS) return E63_UI_LIMIT;
    for (i=0;i<vm->dex->types_count;i++) {
        const uint8_t *type=type_start(vm->dex,i);
        if (type && strcmp((const char *)type,descriptor)==0) break;
    }
    if (i==vm->dex->types_count) return E63_UI_NO_METHOD;
    dst=&vm->objects[vm->object_count++];
    memset(dst,0,sizeof(*dst));
    dst->type_index=i;dst->host_kind=host_kind;dst->native_id=native_id;
    memcpy(dst->descriptor,descriptor,len+1u);
    *handle=vm->object_count;
    return E63_UI_OK;
}
E63UiStatus e63_ui_int_array(E63UiVm *vm, uint32_t count, uint32_t *handle) {
    int typ;
    UiArray *dst;
    if (!vm || !handle || !count) return E63_UI_INVALID;
    if (count>E63_UI_MAX_ARRAY_ITEMS || vm->array_count==E63_UI_MAX_ARRAYS)
        return E63_UI_LIMIT;
    typ=find_type(vm->dex,"[I");
    if (typ<0) return E63_UI_NO_METHOD;
    dst=&vm->arrays[vm->array_count++];
    memset(dst,0,sizeof(*dst));
    dst->count=count;dst->type_index=(uint32_t)typ;
    dst->element_kind=UI_INT;
    *handle=vm->array_count;
    return E63_UI_OK;
}
E63UiStatus e63_ui_set_int(E63UiVm *vm, uint32_t receiver,
                           uint32_t field, int32_t number) {
    UiObject *obj;
    uint32_t owner,type;
    E63UiStatus st=field_access(vm,receiver,field,UI_INT,&obj,0);
    if (st!=E63_UI_OK) return st;
    (void)field_kind(vm->dex,field,&owner,&type);
    if (type_start(vm->dex,type)[0]=='Z' && number!=0 && number!=1)
        return E63_UI_INVALID;
    obj->fields[field]=value(UI_INT,number);
    return E63_UI_OK;
}
E63UiStatus e63_ui_get_int(const E63UiVm *vm, uint32_t receiver,
                           uint32_t field, int32_t *number) {
    UiObject *obj;
    E63UiStatus st;
    if (!number) return E63_UI_INVALID;
    st=field_access(vm,receiver,field,UI_INT,&obj,0);
    if (st!=E63_UI_OK) return st;
    if (obj->fields[field].kind!=UI_EMPTY && obj->fields[field].kind!=UI_INT)
        return E63_UI_INVALID;
    *number=obj->fields[field].bits;
    return E63_UI_OK;
}
E63UiStatus e63_ui_set_ref(E63UiVm *vm, uint32_t receiver,
                           uint32_t field, uint32_t reference) {
    UiObject *obj;
    uint32_t field_type;
    E63UiStatus st=field_access(vm,receiver,field,UI_REF,&obj,&field_type);
    if (st!=E63_UI_OK) return st;
    if (reference && (!object(vm,reference) ||
                      object(vm,reference)->type_index!=field_type)) return E63_UI_INVALID;
    obj->fields[field]=value(UI_REF,(int32_t)reference);
    return E63_UI_OK;
}
E63UiStatus e63_ui_set_array(E63UiVm *vm, uint32_t receiver,
                             uint32_t field, uint32_t handle) {
    UiObject *obj;
    E63UiStatus st=field_access(vm,receiver,field,UI_ARRAY,&obj,0);
    if (st!=E63_UI_OK) return st;
    if (handle && (!array(vm,handle) ||
                   array(vm,handle)->type_index!=
                       le16(vm->dex->data+vm->dex->fields_off+(size_t)field*8u+2u)))
        return E63_UI_INVALID;
    obj->fields[field]=value(UI_ARRAY,(int32_t)handle);
    return E63_UI_OK;
}
E63UiStatus e63_ui_array_set(E63UiVm *vm, uint32_t handle,
                             uint32_t index, int32_t number) {
    UiArray *a=array(vm,handle);
    if (!a || index>=a->count ||
        (int)a->type_index!=find_type(vm->dex,"[I")) return E63_UI_INVALID;
    a->items[index]=number;
    return E63_UI_OK;
}
E63UiStatus e63_ui_array_get(const E63UiVm *vm, uint32_t handle,
                             uint32_t index, int32_t *number) {
    const UiArray *a=array_ro(vm,handle);
    if (!a || !number || index>=a->count ||
        (int)a->type_index!=find_type(vm->dex,"[I")) return E63_UI_INVALID;
    *number=a->items[index];
    return E63_UI_OK;
}
int e63_ui_repaint_pending(const E63UiVm *vm) {
    return vm ? vm->repaint_pending : 0;
}
void e63_ui_clear_repaint(E63UiVm *vm) {
    if (vm) vm->repaint_pending=0;
}

/* Width decoder recognizes legal Dalvik formats. A known but unsupported
 * instruction may be skipped during validation, but fails if EXECUTED.
 * Unknown/reserved opcodes anywhere fail validation. */
static uint32_t width(const E63DexMethod *m, uint32_t pc) {
    uint16_t w=w16(m,pc);
    uint8_t op=(uint8_t)w;
    uint64_t n=0;
    if (w==0x0100 || w==0x0200 || w==0x0300) {
        if (pc+4u>m->words_count) return 0;
        if (w==0x0100) n=4u+2u*(uint64_t)w16(m,pc+1u);
        else if (w==0x0200) n=2u+4u*(uint64_t)w16(m,pc+1u);
        else n=4u+((uint64_t)w16(m,pc+1u)*
                      (uint64_t)w16(m,pc+2u) +
                      ((uint64_t)w16(m,pc+3u)<<16u)*w16(m,pc+1u)+1u)/2u;
    } else if (op==0x00) n=w==0 ? 1u : 0u;
    else if (op==0x01 || op==0x04 || op==0x07 ||
             (op>=0x0a && op<=0x12) || op==0x1d || op==0x1e ||
             op==0x21 || op==0x27 || op==0x28 ||
             (op>=0x7b && op<=0x8f) || (op>=0xb0 && op<=0xcf)) n=1u;
    else if (op==0x02 || op==0x05 || op==0x08 ||
             op==0x13 || op==0x15 || op==0x16 || op==0x19 ||
             op==0x1a || op==0x1c || op==0x1f || op==0x20 ||
             op==0x22 || op==0x23 || op==0x29 ||
             (op>=0x2d && op<=0x3d) ||
             (op>=0x44 && op<=0x6d) ||
             (op>=0x90 && op<=0xaf) || (op>=0xd0 && op<=0xe2)) n=2u;
    else if (op==0x03 || op==0x06 || op==0x09 || op==0x14 ||
             op==0x17 || op==0x1b || (op>=0x24 && op<=0x26) ||
             (op>=0x2a && op<=0x2c) || (op>=0x6e && op<=0x72) ||
             (op>=0x74 && op<=0x78)) n=3u;
    else if (op==0x18) n=5u;
    return n && n<=m->words_count-pc ? (uint32_t)n : 0;
}

static int target_inst(const E63DexMethod *m, const uint8_t *starts,
                       int64_t pc) {
    return pc>=0 && pc<(int64_t)m->words_count && starts[pc]==1;
}
static int target_payload(const E63DexMethod *m, const uint8_t *starts,
                          int64_t pc, uint16_t tag) {
    return pc>=0 && pc<(int64_t)m->words_count && starts[pc]==2 &&
           w16(m,(uint32_t)pc)==tag;
}
static int read_uleb(const E63DexView *v, size_t *at, uint32_t *out) {
    uint32_t i, result=0;
    for (i=0;i<5u;i++) {
        uint8_t b;
        if (!span(v,*at,1)) return 0;
        b=v->data[(*at)++];
        if (i==4 && (b & 0xf0u)) return 0;
        result |= (uint32_t)(b & 127u)<<(i*7u);
        if (!(b & 0x80u)) {*out=result;return 1;}
    }
    return 0;
}
static int read_sleb(const E63DexView *v, size_t *at, int32_t *out) {
    uint32_t i,result=0,shift=0;
    uint8_t b=0;
    for (i=0;i<5;i++) {
        if (!span(v,*at,1)) return 0;
        b=v->data[(*at)++];
        if (i==4 && (b & 0x70u)) return 0;
        result|=(uint32_t)(b & 127u)<<(i*7u);
        shift+=7u;
        if (!(b & 0x80u)) {
            if ((b & 0x40u) && shift<32u) result|=~((1u<<shift)-1u);
            *out=(int32_t)result;
            return 1;
        }
    }
    return 0;
}
static E63UiStatus verify_tries(const E63DexView *v, const E63DexMethod *m,
                                const uint8_t *starts) {
    uint32_t offsets[128];
    uint32_t count,i,j;
    size_t first,at;
    if (!m->tries) return E63_UI_OK;
    if (m->tries>128u) return E63_UI_LIMIT;
    first=(size_t)m->code_off+16u+(size_t)m->words_count*2u+
          ((m->words_count & 1u) ? 2u : 0u);
    if (!span(v,first,(size_t)m->tries*8u+1u)) return E63_UI_INVALID;
    at=first+(size_t)m->tries*8u;
    first=at; /* encoded_catch_handler_list start, offsets relative to it */
    if (!read_uleb(v,&at,&count) || count>128u) return E63_UI_INVALID;
    for (i=0;i<count;i++) {
        int32_t how_many;
        uint32_t n,discard,addr;
        if (at-first>65535u) return E63_UI_INVALID;
        offsets[i]=(uint32_t)(at-first); /* start of handler's SLEB */
        if (!read_sleb(v,&at,&how_many) || how_many<-64 || how_many>64)
            return E63_UI_INVALID;
        n=(uint32_t)(how_many<0 ? -how_many : how_many);
        for (j=0;j<n;j++) {
            if (!read_uleb(v,&at,&discard) || discard>=v->types_count ||
                !read_uleb(v,&at,&addr) || !target_inst(m,starts,addr))
                return E63_UI_INVALID;
        }
        if (how_many<=0 && (!read_uleb(v,&at,&addr) ||
                            !target_inst(m,starts,addr))) return E63_UI_INVALID;
    }
    for (i=0;i<m->tries;i++) {
        const uint8_t *item=v->data+(size_t)m->code_off+16u+
            (size_t)m->words_count*2u+((m->words_count & 1u)?2u:0u)+i*8u;
        uint32_t start=le32(item),len=le16(item+4u),handler=le16(item+6u);
        int found=0;
        if (!len || !target_inst(m,starts,start) ||
            (uint64_t)start+len>m->words_count ||
            (start+len<m->words_count && !target_inst(m,starts,start+len)))
            return E63_UI_INVALID;
        for (j=0;j<count;j++) if (offsets[j]==handler) found=1;
        if (!found) return E63_UI_INVALID;
    }
    return E63_UI_OK;
}

static E63UiStatus validate(const E63DexView *v, const E63DexMethod *m,
                            uint8_t *starts) {
    uint32_t pc=0;
    E63UiStatus st;
    if (!m->registers || m->registers>E63_UI_MAX_REGISTERS ||
        m->ins>m->registers || !m->words_count ||
        m->words_count>E63_UI_MAX_WORDS) return E63_UI_LIMIT;
    memset(starts,0,m->words_count);
    while (pc<m->words_count) {
        uint32_t n=width(m,pc);
        uint16_t w=w16(m,pc);
        if (!n) return E63_UI_UNSUPPORTED;
        starts[pc]=(w==0x0100 || w==0x0200 || w==0x0300) ? 2u : 1u;
        pc+=n;
    }
    for (pc=0;pc<m->words_count;pc++) {
        uint16_t w;
        uint8_t op;
        int64_t at;
        if (starts[pc]!=1) continue;
        w=w16(m,pc);op=(uint8_t)w;
        if (op==0x28) at=(int64_t)pc+signed8(w>>8u);
        else if (op==0x29 || (op>=0x32 && op<=0x3d))
            at=(int64_t)pc+signed16(w16(m,pc+1u));
        else if (op==0x2a) at=(int64_t)pc+
             (int32_t)((uint32_t)w16(m,pc+1u)|((uint32_t)w16(m,pc+2u)<<16u));
        else if (op==0x2b || op==0x2c || op==0x26) {
            uint32_t n,j,entries;
            at=(int64_t)pc+(int32_t)((uint32_t)w16(m,pc+1u)|
                                      ((uint32_t)w16(m,pc+2u)<<16u));
            if (!target_payload(m,starts,at,op==0x2b ? 0x0100u :
                                  op==0x2c ? 0x0200u : 0x0300u))
                return E63_UI_INVALID;
            if (op==0x26) continue;
            n=w16(m,(uint32_t)at+1u);
            entries=op==0x2b ? (uint32_t)at+4u : (uint32_t)at+2u+n*2u;
            for (j=0;j<n;j++) {
                uint32_t where=entries+2u*j;
                int32_t offset=(int32_t)((uint32_t)w16(m,where)|
                                ((uint32_t)w16(m,where+1u)<<16u));
                if (!target_inst(m,starts,(int64_t)pc+offset)) return E63_UI_INVALID;
            }
            continue;
        } else continue;
        if (!target_inst(m,starts,at)) return E63_UI_INVALID;
    }
    st=verify_tries(v,m,starts);
    return st;
}

static int method_signature(const E63DexView *v, uint32_t method_id,
                            uint32_t *params, ValueKind *returns) {
    const uint8_t *id,*proto,*text;
    uint32_t n=0,i,at;
    if (method_id>=v->methods_count) return 0;
    id=v->data+v->methods_off+(size_t)method_id*8u;
    at=le16(id+2u);
    if (at>=v->protos_count) return 0;
    proto=v->data+v->protos_off+(size_t)at*12u;
    text=type_start(v,le32(proto+4u));
    if (!text) return 0;
    *returns=(text[0]=='V' && !text[1]) ? UI_VOID :
             ((text[0]=='I' || text[0]=='Z' || text[0]=='C') && !text[1]) ? UI_INT :
             (text[0]=='J' && !text[1]) ? UI_LONG :
             text[0]=='L' ? UI_REF : text[0]=='[' ? UI_ARRAY : UI_EMPTY;
    if (*returns==UI_EMPTY) return 0;
    at=le32(proto+8u);
    if (at) {
        n=le32(v->data+at);
        if (n>8u) return 0; /* bounded: up to 9 receiver+args via 3rc */
        for (i=0;i<n;i++) {
            text=type_start(v,le16(v->data+at+4u+(size_t)i*2u));
            if (!text || (!((text[0]=='I' || text[0]=='Z') && !text[1]) &&
                          text[0]!='L' && text[0]!='[')) return 0;
        }
    }
    *params=n;
    return 1;
}

static int expect_reg(const UiValue *r, uint32_t count, uint32_t idx) {
    return idx<count && r[idx].kind!=UI_EMPTY;
}
static E63UiStatus literal_ascii(const E63DexView *v, uint32_t index,
                                 char *out, size_t capacity) {
    size_t at,n=0;
    uint32_t utf16;
    if (!out || !capacity || index>=v->strings_count) return E63_UI_INVALID;
    at=le32(v->data+v->strings_off+(size_t)index*4u);
    if (at<v->data_off || !read_uleb(v,&at,&utf16)) return E63_UI_INVALID;
    while (span(v,at,1) && v->data[at]) {
        uint8_t byte=v->data[at++];
        if (byte>=128u) return E63_UI_UNSUPPORTED;
        if (n+1u>=capacity) return E63_UI_LIMIT;
        out[n++]=(char)byte;
    }
    if (!span(v,at,1) || utf16!=n) return E63_UI_INVALID;
    out[n]=0;
    return E63_UI_OK;
}
static E63UiStatus string_ascii(const E63UiVm *vm, UiValue str,
                                char *out, size_t capacity) {
    size_t len;
    if (str.kind==UI_STRING)
        return literal_ascii(vm->dex,(uint32_t)str.bits,out,capacity);
    if (str.kind!=UI_DYNSTRING || str.bits<1 ||
        (uint32_t)str.bits>vm->string_count) return E63_UI_INVALID;
    len=strlen(vm->strings[str.bits-1].ascii);
    if (len>=capacity) return E63_UI_LIMIT;
    memcpy(out,vm->strings[str.bits-1].ascii,len+1u);
    return E63_UI_OK;
}
static E63UiStatus new_string(E63UiVm *vm, const char *text, UiValue *out) {
    size_t len=strlen(text);
    if (len>E63_UI_MAX_TEXT_BYTES || vm->string_count>=E63_UI_MAX_STRINGS)
        return E63_UI_LIMIT;
    memcpy(vm->strings[vm->string_count].ascii,text,len+1u);
    *out=value(UI_DYNSTRING,(int32_t)++vm->string_count);
    return E63_UI_OK;
}
static E63UiStatus append_string(UiObject *target, const char *text) {
    size_t len=strlen(target->text), extra=strlen(text);
    if (extra>E63_UI_MAX_TEXT_BYTES-len) return E63_UI_LIMIT;
    memcpy(target->text+len,text,extra+1u);
    return E63_UI_OK;
}
static E63UiStatus new_managed(E63UiVm *vm, const char *desc,
                               HostKind kind, int32_t native_id,
                               UiValue *out) {
    int idx=find_type(vm->dex,desc);
    UiObject *dst;
    size_t len=strlen(desc);
    if (idx<0 || len>=sizeof(vm->objects[0].descriptor))
        return E63_UI_UNSUPPORTED;
    if (vm->object_count>=E63_UI_MAX_OBJECTS) return E63_UI_LIMIT;
    dst=&vm->objects[vm->object_count++];
    memset(dst,0,sizeof(*dst));
    dst->type_index=(uint32_t)idx;dst->host_kind=kind;
    dst->native_id=native_id;
    memcpy(dst->descriptor,desc,len+1u);
    *out=value(UI_REF,(int32_t)vm->object_count);
    return E63_UI_OK;
}
static E63UiStatus stage(E63UiVm *vm, E63UiPaintCode code,
                         int32_t a, int32_t b, int32_t c, int32_t d,
                         const char *text) {
    E63UiPaintOp *op;
    if (!vm->paint_ops || !vm->paint_host.commit) return E63_UI_UNSUPPORTED;
    if (vm->paint_count>=E63_UI_MAX_DRAW_OPS) return E63_UI_LIMIT;
    op=&vm->paint_ops[vm->paint_count++];
    op->code=(int32_t)code;op->a=a;op->b=b;op->c=c;op->d=d;
    op->text[0]=0;
    if (text) {
        size_t len=strlen(text);
        if (len>E63_UI_MAX_TEXT_BYTES) return E63_UI_LIMIT;
        memcpy(op->text,text,len+1u);
    }
    return E63_UI_OK;
}
static E63UiStatus host_paint(E63UiVm *vm, uint32_t method_id,
                              const UiValue *args, uint32_t count,
                              ValueKind returns, UiValue *out) {
    const E63DexView *dex=vm->dex;
    const UiObject *receiver=object_ro(vm,(uint32_t)args[0].bits);
    int32_t result;
    char text[E63_UI_MAX_TEXT_BYTES+1u];
    E63UiStatus st;
    if (!receiver) return E63_UI_INVALID;
    if (receiver->host_kind==HOST_FONT) {
        if (!vm->paint_host.font_height || !vm->paint_host.font_width)
            return E63_UI_UNSUPPORTED;
        if (count==1u && returns==UI_INT &&
            e63_dex_method_ref_is(dex,method_id,
                "Ljavax/microedition/lcdui/Font;","getHeight","()I")) {
            if (vm->paint_host.font_height(vm->paint_host.context,
                    receiver->native_id,&result)!=0 || result<1 || result>512)
                return E63_UI_UNSUPPORTED;
            *out=value(UI_INT,result);return E63_UI_OK;
        }
        if (count==2u && returns==UI_INT &&
            (args[1].kind==UI_STRING || args[1].kind==UI_DYNSTRING) &&
            e63_dex_method_ref_is(dex,method_id,
                "Ljavax/microedition/lcdui/Font;","stringWidth",
                "(Ljava/lang/String;)I")) {
            st=string_ascii(vm,args[1],text,sizeof(text));
            if (st!=E63_UI_OK) return st;
            if (vm->paint_host.font_width(vm->paint_host.context,
                    receiver->native_id,text,&result)!=0 ||
                result<0 || result>4096) return E63_UI_UNSUPPORTED;
            *out=value(UI_INT,result);return E63_UI_OK;
        }
    }
    if (receiver->host_kind==HOST_IMAGE && count==1u &&
        returns==UI_INT && vm->paint_host.image_bounds &&
        (e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Image;","getWidth","()I") ||
         e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Image;","getHeight","()I"))) {
        int32_t w=0,h=0;
        if (vm->paint_host.image_bounds(vm->paint_host.context,
              receiver->native_id,&w,&h)!=0 || w<1 || w>512 ||
            h<1 || h>512) return E63_UI_UNSUPPORTED;
        *out=value(UI_INT,e63_dex_method_ref_is(dex,method_id,
              "Ljavax/microedition/lcdui/Image;","getWidth","()I") ? w : h);
        return E63_UI_OK;
    }
    if (receiver->host_kind!=HOST_GRAPHICS || returns!=UI_VOID)
        return E63_UI_UNSUPPORTED;
    *out=value(UI_VOID,0);
    if (count==2u && args[1].kind==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Graphics;","setColor","(I)V"))
        return stage(vm,E63_UI_SET_COLOR,args[1].bits,0,0,0,0);
    if (count==5u && args[1].kind==UI_INT && args[2].kind==UI_INT &&
        args[3].kind==UI_INT && args[4].kind==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Graphics;","setClip","(IIII)V"))
        return stage(vm,E63_UI_SET_CLIP,args[1].bits,args[2].bits,
                     args[3].bits,args[4].bits,0);
    if (count==5u && args[1].kind==UI_INT && args[2].kind==UI_INT &&
        args[3].kind==UI_INT && args[4].kind==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Graphics;","fillRect","(IIII)V"))
        return stage(vm,E63_UI_FILL_RECT,args[1].bits,args[2].bits,
                     args[3].bits,args[4].bits,0);
    if (count==5u && args[1].kind==UI_INT && args[2].kind==UI_INT &&
        args[3].kind==UI_INT && args[4].kind==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Graphics;","drawRect","(IIII)V"))
        return stage(vm,E63_UI_DRAW_RECT,args[1].bits,args[2].bits,
                     args[3].bits,args[4].bits,0);
    if (count==5u && args[1].kind==UI_INT && args[2].kind==UI_INT &&
        args[3].kind==UI_INT && args[4].kind==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Graphics;","drawLine","(IIII)V"))
        return stage(vm,E63_UI_DRAW_LINE,args[1].bits,args[2].bits,
                     args[3].bits,args[4].bits,0);
    if (count==7u && args[1].kind==UI_INT && args[2].kind==UI_INT &&
        args[3].kind==UI_INT && args[4].kind==UI_INT &&
        args[5].kind==UI_INT && args[6].kind==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Graphics;","drawArc","(IIIIII)V")) {
        if (args[5].bits!=0 || args[6].bits!=360)
            return E63_UI_UNSUPPORTED;
        return stage(vm,E63_UI_DRAW_ELLIPSE,args[1].bits,args[2].bits,
                     args[3].bits,args[4].bits,0);
    }
    if (count==2u && args[1].kind==UI_REF &&
        e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Graphics;","setFont",
            "(Ljavax/microedition/lcdui/Font;)V")) {
        const UiObject *font=object_ro(vm,(uint32_t)args[1].bits);
        if (!font || font->host_kind!=HOST_FONT) return E63_UI_INVALID;
        return stage(vm,E63_UI_SET_FONT,font->native_id,0,0,0,0);
    }
    if (count==5u && args[1].kind==UI_REF &&
        args[2].kind==UI_INT && args[3].kind==UI_INT &&
        args[4].kind==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Graphics;","drawImage",
            "(Ljavax/microedition/lcdui/Image;III)V")) {
        const UiObject *img=object_ro(vm,(uint32_t)args[1].bits);
        if (!img || img->host_kind!=HOST_IMAGE) return E63_UI_INVALID;
        return stage(vm,E63_UI_DRAW_IMAGE,img->native_id,
                     args[2].bits,args[3].bits,args[4].bits,0);
    }
    if (count==5u &&
        (args[1].kind==UI_STRING || args[1].kind==UI_DYNSTRING) &&
        args[2].kind==UI_INT && args[3].kind==UI_INT &&
        args[4].kind==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Graphics;","drawString",
            "(Ljava/lang/String;III)V")) {
        st=string_ascii(vm,args[1],text,sizeof(text));
        if (st!=E63_UI_OK) return st;
        return stage(vm,E63_UI_DRAW_STRING,args[2].bits,args[3].bits,
                     args[4].bits,0,text);
    }
    return E63_UI_UNSUPPORTED;
}

static E63UiStatus invoke(E63UiVm *vm, const E63DexMethod *caller,
                          uint32_t pc, const UiValue *regs, UiValue *out) {
    uint16_t w=w16(caller,pc), method_id=w16(caller,pc+1u);
    uint32_t i,slot,params;
    uint32_t op=w&255u;
    uint32_t count=(op==0x74 || op==0x76) ? w>>8u : (w>>12u)&15u;
    int is_static=op==0x71;
    UiValue args[9]={{0,UI_EMPTY,0}};
    ValueKind returns;
    E63DexMethod guest;
    int found;
    const E63DexView *dex=vm->dex;
    if (!method_signature(dex,method_id,&params,&returns) ||
        count>9u || count>caller->outs ||
        count!=params+(is_static ? 0u : 1u) ||
        ((op==0x6e || op==0x70 || is_static) && count>5u))
        return E63_UI_UNSUPPORTED;
    for (i=0;i<count;i++) {
        if (op==0x74 || op==0x76) {
            slot=(uint32_t)w16(caller,pc+2u)+i;
        } else {
            uint16_t raw=w16(caller,pc+2u);
            slot=i==4u ? (w>>8u)&15u : (raw>>(i*4u))&15u;
        }
        if (!expect_reg(regs,caller->registers,slot)) return E63_UI_INVALID;
        args[i]=regs[slot];
    }
    if (is_static) {
        if (count==0u && returns==UI_LONG &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/System;",
                                  "currentTimeMillis","()J")) {
            int64_t milliseconds;
            if (!vm->time_millis ||
                vm->time_millis(vm->time_context,&milliseconds)!=0 ||
                milliseconds<0) return E63_UI_UNSUPPORTED;
            *out=long_value(milliseconds);
            return E63_UI_OK;
        }
        if (count==0u && returns==UI_REF &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/util/Calendar;", 
                                  "getInstance","()Ljava/util/Calendar;")) {
            int32_t hour,minute;
            if (!vm->paint_host.local_clock ||
                vm->paint_host.local_clock(vm->paint_host.context,&hour,&minute)!=0 ||
                hour<0 || hour>=24 || minute<0 || minute>=60)
                return E63_UI_UNSUPPORTED;
            return new_managed(vm,"Ljava/util/Calendar;",HOST_CALENDAR,
                               hour*60+minute,out);
        }
        if (count==1u && returns==UI_REF &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/String;",
                                  "valueOf","(I)Ljava/lang/String;") &&
            args[0].kind==UI_INT) {
            char digits[32];
            if (decimal32(digits,sizeof(digits),args[0].bits)!=0)
                return E63_UI_UNSUPPORTED;
            return new_string(vm,digits,out);
        }
        if (count==1u && returns==UI_REF &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/String;",
                                  "valueOf","(Ljava/lang/Object;)Ljava/lang/String;")) {
            if (args[0].kind==UI_STRING || args[0].kind==UI_DYNSTRING) {
                *out=args[0];return E63_UI_OK;
            }
            if (args[0].kind==UI_INT && args[0].bits==0)
                return new_string(vm,"null",out);
        }
        return E63_UI_UNSUPPORTED;
    }
    if (count>0u && (args[0].kind==UI_STRING ||
                     args[0].kind==UI_DYNSTRING)) {
        char lhs[E63_UI_MAX_TEXT_BYTES+1u];
        E63UiStatus st=string_ascii(vm,args[0],lhs,sizeof(lhs));
        if (st!=E63_UI_OK) return st;
        if (count==1u && returns==UI_REF &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/String;",
                                  "toUpperCase","()Ljava/lang/String;")) {
            size_t i;
            for (i=0;lhs[i];i++)
                if (lhs[i]>='a' && lhs[i]<='z') lhs[i]=(char)(lhs[i]-'a'+'A');
            return new_string(vm,lhs,out);
        }
        if (count==2u && returns==UI_INT &&
            (args[1].kind==UI_STRING || args[1].kind==UI_DYNSTRING) &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/String;",
                                  "indexOf","(Ljava/lang/String;)I")) {
            char rhs[E63_UI_MAX_TEXT_BYTES+1u];
            const char *found;
            st=string_ascii(vm,args[1],rhs,sizeof(rhs));
            if (st!=E63_UI_OK) return st;
            found=strstr(lhs,rhs);
            *out=value(UI_INT,found ? (int32_t)(found-lhs) : -1);
            return E63_UI_OK;
        }
        if (count==1u && returns==UI_INT &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/String;",
                                  "length","()I")) {
            *out=value(UI_INT,(int32_t)strlen(lhs));return E63_UI_OK;
        }
        if (count==2u && returns==UI_INT && args[1].kind==UI_INT &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/String;",
                                  "charAt","(I)C")) {
            if (args[1].bits<0 || (size_t)args[1].bits>=strlen(lhs))
                return E63_UI_INVALID;
            *out=value(UI_INT,(uint8_t)lhs[args[1].bits]);return E63_UI_OK;
        }
        if (count==2u && returns==UI_INT &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/String;","equals",
                                  "(Ljava/lang/Object;)Z")) {
            char rhs[E63_UI_MAX_TEXT_BYTES+1u];
            if (args[1].kind==UI_STRING || args[1].kind==UI_DYNSTRING) {
                st=string_ascii(vm,args[1],rhs,sizeof(rhs));
                if (st!=E63_UI_OK) return st;
                *out=value(UI_INT,strcmp(lhs,rhs)==0);
            } else if (args[1].kind==UI_REF ||
                       (args[1].kind==UI_INT && args[1].bits==0))
                *out=value(UI_INT,0);
            else return E63_UI_INVALID;
            return E63_UI_OK;
        }
        return E63_UI_UNSUPPORTED;
    }
    if (count==0u || args[0].kind!=UI_REF ||
        !object(vm,(uint32_t)args[0].bits)) return E63_UI_INVALID;
    if (object_ro(vm,(uint32_t)args[0].bits)->host_kind==HOST_CALENDAR &&
        count==2u && args[1].kind==UI_INT && returns==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,"Ljava/util/Calendar;","get","(I)I")) {
        const UiObject *cal=object_ro(vm,(uint32_t)args[0].bits);
        if (args[1].bits!=11 && args[1].bits!=12)
            return E63_UI_UNSUPPORTED;
        *out=value(UI_INT,args[1].bits==11 ? cal->native_id/60 :
                         cal->native_id%60);
        return E63_UI_OK;
    }
    if (object_ro(vm,(uint32_t)args[0].bits)->host_kind==HOST_STRINGBUFFER) {
        UiObject *buffer=object(vm,(uint32_t)args[0].bits);
        if (count==2u && returns==UI_VOID &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/StringBuffer;",
                              "<init>","(Ljava/lang/String;)V") &&
            (args[1].kind==UI_STRING || args[1].kind==UI_DYNSTRING)) {
            buffer->text[0]=0;
            return string_ascii(vm,args[1],buffer->text,sizeof(buffer->text));
        }
        if (count==2u && returns==UI_REF &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/StringBuffer;",
                              "append","(I)Ljava/lang/StringBuffer;") &&
            args[1].kind==UI_INT) {
            char digits[32];
            if (decimal32(digits,sizeof(digits),args[1].bits)!=0)
                return E63_UI_UNSUPPORTED;
            if (append_string(buffer,digits)!=E63_UI_OK) return E63_UI_LIMIT;
            *out=args[0];return E63_UI_OK;
        }
        if (count==2u && returns==UI_REF &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/StringBuffer;",
                              "append","(Ljava/lang/String;)Ljava/lang/StringBuffer;") &&
            (args[1].kind==UI_STRING || args[1].kind==UI_DYNSTRING)) {
            char piece[E63_UI_MAX_TEXT_BYTES+1u];
            E63UiStatus st=string_ascii(vm,args[1],piece,sizeof(piece));
            if (st!=E63_UI_OK) return st;
            st=append_string(buffer,piece);
            if (st!=E63_UI_OK) return st;
            *out=args[0];return E63_UI_OK;
        }
        if (count==1u && returns==UI_REF &&
            e63_dex_method_ref_is(dex,method_id,"Ljava/lang/StringBuffer;",
                              "toString","()Ljava/lang/String;"))
            return new_string(vm,buffer->text,out);
        return E63_UI_UNSUPPORTED;
    }
    found=e63_dex_find_code_id(dex,method_id,&guest);
    if (found<0) return E63_UI_INVALID;
    if (found==1) {
        const UiObject *receiver=object_ro(vm,(uint32_t)args[0].bits);
        if (guest.class_index!=receiver->type_index || guest.ins!=count)
            return E63_UI_UNSUPPORTED;
        return run(vm,&guest,args,count,out);
    }
    /* MIDP drawing/font primitives are separated from app navigation. A
     * bounded command batch is committed only after the guest method succeeds. */
    if (object_ro(vm,(uint32_t)args[0].bits)->host_kind!=HOST_NONE)
        return host_paint(vm,method_id,args,count,returns,out);
    /* Existing pure Canvas services: no host screen/layout decisions. */
    if (strcmp(object_ro(vm,(uint32_t)args[0].bits)->descriptor,
               "Landroid/j2me/edition/E63Canvas;")!=0) return E63_UI_UNSUPPORTED;
    if (count==2u && returns==UI_REF && args[1].kind==UI_INT &&
        e63_dex_method_ref_is(dex,method_id,
             "Ljavax/microedition/lcdui/Canvas;","getKeyName",
             "(I)Ljava/lang/String;")) {
        /* Host platform key names, NOT guest UI. Prevent accidental HOME or
         * SOFT-key matches for the explicitly mapped directional sentinels. */
        const char *name=0;
        switch (args[1].bits) {
            case -1001: case -1: name="UP"; break;
            case -1002: case -2: name="DOWN"; break;
            case -1003: case -3: name="LEFT"; break;
            case -1004: case -4: name="RIGHT"; break;
            case -1005: case -5: name="FIRE"; break;
            case -6: name="SOFT1"; break;
            case -7: name="SOFT2"; break;
            default: return E63_UI_UNSUPPORTED;
        }
        return new_string(vm,name,out);
    }
    if (e63_dex_method_ref_is(dex,method_id,
             "Ljavax/microedition/lcdui/Canvas;","repaint","()V") &&
        count==1u && returns==UI_VOID) {
        vm->repaint_pending=1;
        *out=value(UI_VOID,0);
        return E63_UI_OK;
    }
    if (returns==UI_INT && count==1u && vm->width && vm->height) {
        if (e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Displayable;","getWidth","()I")) {
            *out=value(UI_INT,vm->width);return E63_UI_OK;
        }
        if (e63_dex_method_ref_is(dex,method_id,
            "Ljavax/microedition/lcdui/Displayable;","getHeight","()I")) {
            *out=value(UI_INT,vm->height);return E63_UI_OK;
        }
    }
    if (e63_dex_method_ref_is(dex,method_id,
             "Ljavax/microedition/lcdui/Canvas;","getGameAction","(I)I") &&
        count==2u && returns==UI_INT && args[1].kind==UI_INT && vm->action) {
        int32_t game;
        if (vm->action(vm->context,args[1].bits,&game)!=0) return E63_UI_UNSUPPORTED;
        *out=value(UI_INT,game);
        return E63_UI_OK;
    }
    return E63_UI_UNSUPPORTED;
}

static E63UiStatus run(E63UiVm *vm, const E63DexMethod *m,
                       const UiValue *args, uint32_t argc, UiValue *result) {
    UiValue *regs=0,pending=value(UI_EMPTY,0);
    uint8_t *starts=0;
    uint32_t pc=0,i;
    int monitor=0;
    ValueKind returns;
    uint32_t params;
    E63UiStatus status=E63_UI_INVALID;
    if (vm->depth>=E63_UI_MAX_DEPTH) return E63_UI_BUDGET;
    if (!method_signature(vm->dex,m->method_index,&params,&returns) ||
        (argc!=params+1u && !(argc==0u && params==0u)) ||
        m->ins!=argc) return E63_UI_UNSUPPORTED;
    starts=(uint8_t *)malloc(m->words_count ? m->words_count : 1u);
    if (!starts) return E63_UI_LIMIT;
    status=validate(vm->dex,m,starts);
    if (status!=E63_UI_OK) goto done;
    regs=(UiValue *)calloc(m->registers,sizeof(*regs));
    if (!regs) {status=E63_UI_LIMIT;goto done;}
    for (i=0;i<argc;i++) regs[m->registers-m->ins+i]=args[i];
    vm->depth++;
    while (pc<m->words_count) {
        uint16_t w=w16(m,pc);
        uint32_t op=w&255u,a=w>>8u,next=pc+width(m,pc);
        uint32_t x,y,field_id,owner,type;
        UiObject *obj;
        UiValue v;
        int kind;
        status=E63_UI_INVALID;
        if (starts[pc]!=1u || ++vm->steps>E63_UI_STEP_BUDGET) {
            status=vm->steps>E63_UI_STEP_BUDGET ? E63_UI_BUDGET:E63_UI_INVALID;
            goto endframe;
        }
        if (op!=0x0a && op!=0x0c && op!=0x0b) pending=value(UI_EMPTY,0);
        if (op==0x00) {
            /* A payload has starts[pc]=2; plain NOP is legal. */
        } else if (op==0x01 || op==0x07 || op==0x02 || op==0x08) {
            /* move/move-object 12x or move/from16 22x */
            x=(op==0x02 || op==0x08) ? a : a&15u;
            y=(op==0x02 || op==0x08) ? w16(m,pc+1u) : a>>4u;
            if (x>=m->registers || !expect_reg(regs,m->registers,y)) goto endframe;
            regs[x]=regs[y];
        } else if (op==0x0a || op==0x0c) { /* move-result / -object */
            if (a>=m->registers ||
                (op==0x0a ? pending.kind!=UI_INT :
                 (pending.kind!=UI_REF && pending.kind!=UI_ARRAY &&
                  pending.kind!=UI_STRING && pending.kind!=UI_DYNSTRING)))
                goto endframe;
            regs[a]=pending;pending=value(UI_EMPTY,0);
        } else if (op==0x0b) { /* move-result-wide: checked two-register J */
            if (a+1u>=m->registers || pending.kind!=UI_LONG) goto endframe;
            set_long_register(regs,a,pending.wide);
            pending=value(UI_EMPTY,0);
        } else if (op==0x16) { /* const-wide/16: guest Back debounce */
            if (a+1u>=m->registers) goto endframe;
            set_long_register(regs,a,(int64_t)signed16(w16(m,pc+1u)));
        } else if (op==0x12) { /* const/4 */
            x=a&15u;
            if (x>=m->registers) goto endframe;
            regs[x]=value(UI_INT,signed4(a>>4u));
        } else if (op==0x13) { /* const/16 */
            if (a>=m->registers) goto endframe;
            regs[a]=value(UI_INT,signed16(w16(m,pc+1u)));
        } else if (op==0x14) { /* const/32 */
            if (a>=m->registers) goto endframe;
            regs[a]=value(UI_INT,(int32_t)((uint32_t)w16(m,pc+1u)|
                    ((uint32_t)w16(m,pc+2u)<<16u)));
        } else if (op==0x1a) { /* const-string from checked DEX, not a UI stub */
            if (a>=m->registers || w16(m,pc+1u)>=vm->dex->strings_count)
                goto endframe;
            regs[a]=value(UI_STRING,(int32_t)w16(m,pc+1u));
        } else if (op==0x22) { /* new-instance: bounded host StringBuffer */
            const uint8_t *typ=type_start(vm->dex,w16(m,pc+1u));
            if (a>=m->registers || !typ ||
                strcmp((const char *)typ,"Ljava/lang/StringBuffer;")!=0) {
                status=E63_UI_UNSUPPORTED;goto endframe;
            }
            status=new_managed(vm,(const char *)typ,HOST_STRINGBUFFER,0,&regs[a]);
            if (status!=E63_UI_OK) goto endframe;
        } else if (op==0x21) { /* array-length */
            UiArray *arr;
            x=a&15u;y=a>>4u;
            if (x>=m->registers || !expect_reg(regs,m->registers,y) ||
                regs[y].kind!=UI_ARRAY ||
                !(arr=array(vm,(uint32_t)regs[y].bits))) goto endframe;
            regs[x]=value(UI_INT,(int32_t)arr->count);
        } else if (op==0x23) { /* new-array: original [[B/[B class data */
            const uint8_t *typ=type_start(vm->dex,w16(m,pc+1u));
            UiArray *dst;
            x=a&15u;y=a>>4u;
            if (!typ || (strcmp((const char *)typ,"[[B")!=0 &&
                         strcmp((const char *)typ,"[B")!=0)) {
                status=E63_UI_UNSUPPORTED;goto endframe;
            }
            if (x>=m->registers || !expect_reg(regs,m->registers,y) ||
                regs[y].kind!=UI_INT || regs[y].bits<0) goto endframe;
            if ((uint32_t)regs[y].bits>E63_UI_MAX_ARRAY_ITEMS ||
                vm->array_count>=E63_UI_MAX_ARRAYS) {
                status=E63_UI_LIMIT;goto endframe;
            }
            dst=&vm->arrays[vm->array_count++];
            memset(dst,0,sizeof(*dst));
            dst->count=(uint32_t)regs[y].bits;
            dst->type_index=w16(m,pc+1u);
            dst->element_kind=typ[1]=='[' ? UI_ARRAY : UI_INT;
            regs[x]=value(UI_ARRAY,(int32_t)vm->array_count);
        } else if (op==0x26) { /* fill-array-data with validated byte payload */
            int64_t at=(int64_t)pc+(int32_t)((uint32_t)w16(m,pc+1u)|
                                           ((uint32_t)w16(m,pc+2u)<<16u));
            UiArray *dst;
            uint32_t j,payload,count;
            if (a>=m->registers || regs[a].kind!=UI_ARRAY ||
                !(dst=array(vm,(uint32_t)regs[a].bits)) ||
                (int)dst->type_index!=find_type(vm->dex,"[B") ||
                !target_payload(m,starts,at,0x0300u)) goto endframe;
            payload=(uint32_t)at;
            count=(uint32_t)w16(m,payload+2u)|
                  ((uint32_t)w16(m,payload+3u)<<16u);
            if (w16(m,payload+1u)!=1u || count!=dst->count ||
                (uint64_t)payload+4u+(count+1u)/2u>m->words_count)
                goto endframe;
            for (j=0;j<count;j++) {
                uint16_t word=w16(m,payload+4u+j/2u);
                uint8_t byte=(uint8_t)(j&1u ? word>>8u : word);
                dst->items[j]=signed8(byte);
            }
        } else if (op==0x62 || op==0x69) { /* sget/sput-object [[B */
            field_id=w16(m,pc+1u);
            if (a>=m->registers || field_id>=E63_UI_MAX_FIELDS ||
                !e63_dex_field_is(vm->dex,field_id,
                  (uint32_t)find_type(vm->dex,"Landroid/j2me/edition/E63Canvas;"),
                  "[[B")) {
                status=E63_UI_UNSUPPORTED;goto endframe;
            }
            if (op==0x62) {
                v=vm->static_fields[field_id];
                if (v.kind!=UI_ARRAY || !array(vm,(uint32_t)v.bits))
                    goto endframe;
                regs[a]=v;
            } else {
                v=regs[a];
                if (v.kind!=UI_ARRAY || !array(vm,(uint32_t)v.bits) ||
                    (int)array(vm,(uint32_t)v.bits)->type_index!=
                         find_type(vm->dex,"[[B")) goto endframe;
                vm->static_fields[field_id]=v;
            }
        } else if (op==0x53 || op==0x5a) { /* iget-wide/iput-wide J */
            field_id=w16(m,pc+1u);x=a&15u;y=a>>4u;
            if (x+1u>=m->registers || !expect_reg(regs,m->registers,y) ||
                regs[y].kind!=UI_REF || field_id>=E63_UI_MAX_FIELDS)
                goto endframe;
            obj=object(vm,(uint32_t)regs[y].bits);
            kind=field_kind(vm->dex,field_id,&owner,&type);
            if (!obj || owner!=obj->type_index || kind!=UI_LONG ||
                type_start(vm->dex,type)[0]!='J') {
                status=E63_UI_UNSUPPORTED;goto endframe;
            }
            if (op==0x53) {
                v=obj->fields[field_id];
                if (v.kind==UI_EMPTY) v=long_value(0);
                if (v.kind!=UI_LONG) goto endframe;
                set_long_register(regs,x,v.wide);
            } else {
                if (!long_register(regs,m->registers,x)) goto endframe;
                obj->fields[field_id]=regs[x];
            }
        } else if (op==0x52 || op==0x54 || op==0x55 ||
                   op==0x59 || op==0x5b || op==0x5c) { /* iget/iput */
            field_id=w16(m,pc+1u);x=a&15u;y=a>>4u;
            if (x>=m->registers || !expect_reg(regs,m->registers,y) ||
                regs[y].kind!=UI_REF || field_id>=E63_UI_MAX_FIELDS) goto endframe;
            obj=object(vm,(uint32_t)regs[y].bits);
            kind=field_kind(vm->dex,field_id,&owner,&type);
            if (!obj || owner!=obj->type_index ||
                kind!=(op==0x52 || op==0x55 || op==0x59 || op==0x5c ? UI_INT :
                      kind==UI_ARRAY ? UI_ARRAY : UI_REF) ||
                ((op==0x52 || op==0x59) && type_start(vm->dex,type)[0]!='I') ||
                ((op==0x55 || op==0x5c) && type_start(vm->dex,type)[0]!='Z')) {
                status=E63_UI_UNSUPPORTED;goto endframe;
            }
            if (op==0x52 || op==0x54 || op==0x55) {
                v=obj->fields[field_id];
                if (v.kind==UI_EMPTY) v=value((ValueKind)kind,0);
                if (v.kind!=(ValueKind)kind) goto endframe;
                regs[x]=v;
            } else {
                v=regs[x];
                if (!expect_reg(regs,m->registers,x)) goto endframe;
                if (kind==UI_INT && (v.kind!=UI_INT ||
                    (op==0x5c && v.bits!=0 && v.bits!=1))) goto endframe;
                if (kind==UI_ARRAY && v.kind==UI_INT && v.bits==0)
                    v=value(UI_ARRAY,0);
                if (kind==UI_REF && v.kind==UI_INT && v.bits==0)
                    v=value(UI_REF,0);
                if ((ValueKind)kind!=v.kind ||
                    (kind==UI_REF && v.bits!=0 &&
                     (!object(vm,(uint32_t)v.bits) ||
                      object(vm,(uint32_t)v.bits)->type_index!=type)) ||
                    (kind==UI_ARRAY && v.bits!=0 &&
                     (!array(vm,(uint32_t)v.bits) ||
                      array(vm,(uint32_t)v.bits)->type_index!=type)))
                    goto endframe;
                obj->fields[field_id]=v;
            }
        } else if (op==0x44 || op==0x46 || op==0x48 ||
                   op==0x4b || op==0x4d || op==0x4f) {
            /* aget/aput int, object-array, byte; enforce DEX array type. */
            uint16_t bc=w16(m,pc+1u);
            UiArray *arr;
            int array_type;
            x=a;y=bc&255u;
            if (x>=m->registers || !expect_reg(regs,m->registers,y) ||
                regs[y].kind!=UI_ARRAY || !expect_reg(regs,m->registers,bc>>8u) ||
                regs[bc>>8u].kind!=UI_INT) goto endframe;
            arr=array(vm,(uint32_t)regs[y].bits);
            if (!arr || regs[bc>>8u].bits<0 ||
                (uint32_t)regs[bc>>8u].bits>=arr->count) goto endframe;
            array_type=(op==0x44 || op==0x4b) ? find_type(vm->dex,"[I") :
                       (op==0x46 || op==0x4d) ? find_type(vm->dex,"[[B") :
                                                    find_type(vm->dex,"[B");
            if (array_type<0 || arr->type_index!=(uint32_t)array_type ||
                ((arr->element_kind==UI_ARRAY) != (op==0x46 || op==0x4d)))
                goto endframe;
            if (op==0x44 || op==0x46 || op==0x48) {
                regs[x]=value(op==0x46 ? UI_ARRAY : UI_INT,
                              arr->items[regs[bc>>8u].bits]);
            } else {
                if (!expect_reg(regs,m->registers,x)) goto endframe;
                if (op==0x4d) {
                    UiArray *item;
                    if (regs[x].kind!=UI_ARRAY ||
                        !(item=array(vm,(uint32_t)regs[x].bits)) ||
                        (int)item->type_index!=find_type(vm->dex,"[B"))
                        goto endframe;
                    arr->items[regs[bc>>8u].bits]=regs[x].bits;
                } else {
                    if (regs[x].kind!=UI_INT) goto endframe;
                    arr->items[regs[bc>>8u].bits]=op==0x4f ?
                        signed8((uint8_t)regs[x].bits) : regs[x].bits;
                }
            }
        } else if (op==0x28 || op==0x29 || op==0x2a) { /* goto */
            int64_t dest=(int64_t)pc+(op==0x28 ? signed8(a) :
                op==0x29 ? signed16(w16(m,pc+1u)) :
                (int32_t)((uint32_t)w16(m,pc+1u)|
                          ((uint32_t)w16(m,pc+2u)<<16u)));
            if (!target_inst(m,starts,dest)) goto endframe;
            next=(uint32_t)dest;
        } else if (op==0x2b || op==0x2c) { /* packed/sparse switch */
            uint32_t payload,n,j;
            int64_t at=(int64_t)pc+(int32_t)((uint32_t)w16(m,pc+1u)|
                                           ((uint32_t)w16(m,pc+2u)<<16u));
            if (a>=m->registers || regs[a].kind!=UI_INT ||
                !target_payload(m,starts,at,op==0x2b ? 0x0100u:0x0200u))
                goto endframe;
            payload=(uint32_t)at;n=w16(m,payload+1u);
            for (j=0;j<n;j++) {
                uint32_t keypos=op==0x2b ? payload+2u : payload+2u+j*2u;
                int32_t key=(int32_t)((uint32_t)w16(m,keypos)|
                                      ((uint32_t)w16(m,keypos+1u)<<16u));
                uint32_t offpos=op==0x2b ? payload+4u+j*2u : payload+2u+2u*n+j*2u;
                int32_t off=(int32_t)((uint32_t)w16(m,offpos)|
                                      ((uint32_t)w16(m,offpos+1u)<<16u));
                if (op==0x2b) key=(int32_t)(
                    ((uint32_t)w16(m,payload+2u)|
                     ((uint32_t)w16(m,payload+3u)<<16u))+(uint32_t)j);
                if (key==regs[a].bits) {next=(uint32_t)((int64_t)pc+off);break;}
            }
        } else if (op==0x31) { /* cmp-long vAA,vBB,vCC */
            uint16_t bc=w16(m,pc+1u);
            x=bc&255u;y=bc>>8u;
            if (a>=m->registers || !long_register(regs,m->registers,x) ||
                !long_register(regs,m->registers,y)) goto endframe;
            regs[a]=value(UI_INT,regs[x].wide<regs[y].wide ? -1 :
                         regs[x].wide>regs[y].wide ? 1 : 0);
        } else if (op>=0x32 && op<=0x3d) { /* if-test / if-testz */
            int take=0;
            if (op<=0x37) {
                x=a&15u;y=a>>4u;
                if (!expect_reg(regs,m->registers,x) ||
                    !expect_reg(regs,m->registers,y)) goto endframe;
                if (op>=0x34 && (regs[x].kind!=UI_INT || regs[y].kind!=UI_INT))
                    goto endframe;
                if (op==0x32 || op==0x33) {
                    if (regs[x].kind!=regs[y].kind &&
                        !((regs[x].bits==0 && regs[x].kind==UI_INT) ||
                          (regs[y].bits==0 && regs[y].kind==UI_INT)))
                        goto endframe;
                }
                take=(op==0x32 ? regs[x].bits==regs[y].bits :
                      op==0x33 ? regs[x].bits!=regs[y].bits :
                      op==0x34 ? regs[x].bits<regs[y].bits :
                      op==0x35 ? regs[x].bits>=regs[y].bits :
                      op==0x36 ? regs[x].bits>regs[y].bits :
                                 regs[x].bits<=regs[y].bits);
            } else {
                if (!expect_reg(regs,m->registers,a)) goto endframe;
                if (op>=0x3a && regs[a].kind!=UI_INT) goto endframe;
                take=(op==0x38 ? regs[a].bits==0 :
                      op==0x39 ? regs[a].bits!=0 :
                      op==0x3a ? regs[a].bits<0 :
                      op==0x3b ? regs[a].bits>=0 :
                      op==0x3c ? regs[a].bits>0 : regs[a].bits<=0);
            }
            if (take) {
                int64_t dest=(int64_t)pc+signed16(w16(m,pc+1u));
                if (!target_inst(m,starts,dest)) goto endframe;
                next=(uint32_t)dest;
            }
        } else if (op==0x1d || op==0x1e) { /* one owner monitor, single VM thread */
            if (!expect_reg(regs,m->registers,a) || regs[a].kind!=UI_REF ||
                !object(vm,(uint32_t)regs[a].bits)) goto endframe;
            monitor+=(op==0x1d ? 1 : -1);
            if (monitor<0 || monitor>1) goto endframe;
        } else if (op==0x6e || op==0x70 || op==0x71 ||
                   op==0x74 || op==0x76) {
            /* invoke-virtual/direct/static 35c or virtual/direct/range */
            status=invoke(vm,m,pc,regs,&pending);
            if (status!=E63_UI_OK) goto endframe;
            status=E63_UI_INVALID;
        } else if (op==0x9c) { /* sub-long vAA,vBB,vCC, modulo 2^64 */
            uint16_t bc=w16(m,pc+1u);
            uint64_t bits;
            int64_t difference;
            x=bc&255u;y=bc>>8u;
            if (a+1u>=m->registers || !long_register(regs,m->registers,x) ||
                !long_register(regs,m->registers,y)) goto endframe;
            bits=(uint64_t)regs[x].wide-(uint64_t)regs[y].wide;
            difference=(bits & ((uint64_t)1<<63u)) ?
                -1-(int64_t)(~bits) : (int64_t)bits;
            set_long_register(regs,a,difference);
        } else if (op>=0x90 && op<=0x93) { /* add/sub/mul/div-int 23x */
            uint16_t bc=w16(m,pc+1u);
            int32_t lhs,rhs;
            x=a;y=bc&255u;
            if (x>=m->registers || !expect_reg(regs,m->registers,y) ||
                !expect_reg(regs,m->registers,bc>>8u) ||
                regs[y].kind!=UI_INT || regs[bc>>8u].kind!=UI_INT) goto endframe;
            lhs=regs[y].bits;rhs=regs[bc>>8u].bits;
            if (op==0x93 && (!rhs || (lhs==INT_MIN && rhs==-1))) goto endframe;
            regs[x]=value(UI_INT, op==0x90 ?
                 (int32_t)((uint32_t)lhs+(uint32_t)rhs) : op==0x91 ?
                 (int32_t)((uint32_t)lhs-(uint32_t)rhs) : op==0x92 ?
                 (int32_t)((uint32_t)lhs*(uint32_t)rhs) : lhs/rhs);
        } else if ((op>=0xb0 && op<=0xb5) || op==0xb9) {
            /* add/sub/mul/div/rem/and and arithmetic shr-int/2addr */
            int32_t lhs,rhs;
            x=a&15u;y=a>>4u;
            if (!expect_reg(regs,m->registers,x) ||
                !expect_reg(regs,m->registers,y) ||
                regs[x].kind!=UI_INT || regs[y].kind!=UI_INT) goto endframe;
            lhs=regs[x].bits;rhs=regs[y].bits;
            if ((op==0xb3 || op==0xb4) &&
                (!rhs || (lhs==INT_MIN && rhs==-1))) goto endframe;
            regs[x].bits=op==0xb0 ? (int32_t)((uint32_t)lhs+(uint32_t)rhs) :
                         op==0xb1 ? (int32_t)((uint32_t)lhs-(uint32_t)rhs) :
                         op==0xb2 ? (int32_t)((uint32_t)lhs*(uint32_t)rhs) :
                         op==0xb3 ? lhs/rhs : op==0xb4 ? lhs%rhs :
                         op==0xb5 ? lhs&rhs :
                                    arithmetic_shr(lhs,(uint32_t)rhs);
        } else if (op==0xd8 || op==0xd9 || op==0xda ||
                   op==0xdb || op==0xdc) {
            /* add/rsub/mul/div/rem-int/lit8, including guest clock */
            uint16_t bc=w16(m,pc+1u);
            int32_t lhs,rhs=signed8(bc>>8u);
            x=a;y=bc&255u;
            if (x>=m->registers || !expect_reg(regs,m->registers,y) ||
                regs[y].kind!=UI_INT) goto endframe;
            lhs=regs[y].bits;
            if ((op==0xdb || op==0xdc) &&
                (!rhs || (lhs==INT_MIN && rhs==-1))) goto endframe;
            regs[x]=value(UI_INT,op==0xd8 ?
                (int32_t)((uint32_t)lhs+(uint32_t)rhs) :
                op==0xd9 ? (int32_t)((uint32_t)rhs-(uint32_t)lhs) :
                op==0xda ? (int32_t)((uint32_t)lhs*(uint32_t)rhs) :
                op==0xdb ? lhs/rhs : lhs%rhs);
        } else if (op==0x0e || op==0x0f || op==0x11) {
            if (monitor!=0 || (op==0x0e && returns!=UI_VOID)) goto endframe;
            if (op==0x0f && (returns!=UI_INT || a>=m->registers ||
                             regs[a].kind!=UI_INT)) goto endframe;
            if (op==0x11 && (returns!=UI_REF || a>=m->registers ||
                (regs[a].kind!=UI_REF && regs[a].kind!=UI_STRING &&
                 regs[a].kind!=UI_DYNSTRING))) goto endframe;
            *result=op==0x0e ? value(UI_VOID,0) : regs[a];
            status=E63_UI_OK;
            goto endframe;
        } else {
            status=E63_UI_UNSUPPORTED;goto endframe;
        }
        if (!target_inst(m,starts,next)) goto endframe;
        pc=next;
    }
endframe:
    vm->depth--;
done:
    free(regs);free(starts);
    return status;
}

static int primitive_proto(const char *p, uint32_t *n, int *has_result) {
    size_t i,len;
    if (!p || (len=strlen(p))<3u || len>256u || p[0]!='(') return 0;
    *n=0;
    for (i=1;p[i] && p[i]!=')';i++) {
        if (p[i]!='I' && p[i]!='Z') return 0;
        ++*n;
    }
    if (i+2u!=len || p[i]!=')' ||
        (p[i+1]!='I' && p[i+1]!='Z' && p[i+1]!='V')) return 0;
    *has_result=p[i+1]!='V';
    return 1;
}
/* Shared transactional call boundary for numeric events and one Graphics ref.
 * No draw command reaches the host until the guest method returns normally. */
static E63UiStatus call_typed(E63UiVm *vm, uint32_t receiver,
                              const char *method, const char *proto,
                              const UiValue *args, uint32_t count,
                              int want_result, int32_t *out, int commit_paint) {
    E63DexMethod code;
    UiValue result=value(UI_EMPTY,0);
    struct Snapshot {
        UiObject objects[E63_UI_MAX_OBJECTS];
        UiArray arrays[E63_UI_MAX_ARRAYS];
        UiValue static_fields[E63_UI_MAX_FIELDS];
    } *backup;
    const UiObject *obj=object_ro(vm,receiver);
    uint32_t old_objects,old_arrays,old_strings;
    int found,redraw;
    E63UiStatus st;
    if (!obj || obj->host_kind!=HOST_NONE || !method || !proto ||
        !args || !count || args[0].kind!=UI_REF ||
        (uint32_t)args[0].bits!=receiver || (want_result && !out))
        return E63_UI_INVALID;
    found=e63_dex_find_code(vm->dex,obj->descriptor,method,proto,&code);
    if (found!=1) return found<0 ? E63_UI_INVALID : E63_UI_NO_METHOD;
    if (code.class_index!=obj->type_index || code.ins!=count)
        return E63_UI_INVALID;
    backup=(struct Snapshot *)malloc(sizeof(*backup));
    if (!backup) return E63_UI_LIMIT;
    memcpy(backup->objects,vm->objects,sizeof(vm->objects));
    memcpy(backup->arrays,vm->arrays,sizeof(vm->arrays));
    memcpy(backup->static_fields,vm->static_fields,sizeof(vm->static_fields));
    old_objects=vm->object_count;
    old_arrays=vm->array_count;
    old_strings=vm->string_count;
    redraw=vm->repaint_pending;
    vm->steps=0u;vm->depth=0u;vm->paint_count=0u;
    st=run(vm,&code,args,count,&result);
    if (st==E63_UI_OK && want_result && result.kind!=UI_INT)
        st=E63_UI_INVALID;
    if (st==E63_UI_OK && vm->paint_count) {
        if (!commit_paint || !vm->paint_host.commit ||
            vm->paint_host.commit(vm->paint_host.context,vm->paint_ops,
                                  vm->paint_count)!=0)
            st=E63_UI_UNSUPPORTED;
    }
    if (st!=E63_UI_OK) {
        memcpy(vm->objects,backup->objects,sizeof(vm->objects));
        memcpy(vm->arrays,backup->arrays,sizeof(vm->arrays));
        memcpy(vm->static_fields,backup->static_fields,
               sizeof(vm->static_fields));
        vm->array_count=old_arrays;
        vm->repaint_pending=redraw;
    } else if (want_result) *out=result.bits;
    /* Neither supported guest events nor paint may retain managed host
     * StringBuffer/Calendar objects or dynamic strings in typed fields. */
    vm->object_count=old_objects;
    vm->string_count=old_strings;
    vm->paint_count=0u;
    free(backup);
    return st;
}
E63UiStatus e63_ui_call(E63UiVm *vm, uint32_t receiver, const char *method,
                        const char *proto, const int32_t *parameters,
                        uint32_t param_count, int32_t *out) {
    UiValue args[9];
    uint32_t count,i;
    int want_result;
    if (!vm || !primitive_proto(proto,&count,&want_result) ||
        count>8u || count!=param_count || (count && !parameters) ||
        (want_result && !out)) return E63_UI_INVALID;
    args[0]=value(UI_REF,(int32_t)receiver);
    for (i=0;i<count;i++) args[i+1u]=value(UI_INT,parameters[i]);
    return call_typed(vm,receiver,method,proto,args,count+1u,
                      want_result,out,0);
}
E63UiStatus e63_ui_call_ref(E63UiVm *vm, uint32_t receiver,
                            const char *method, const char *proto,
                            uint32_t graphics) {
    UiValue args[2];
    const UiObject *g=object_ro(vm,graphics);
    if (!g || g->host_kind!=HOST_GRAPHICS || !vm->paint_ops ||
        !proto || strcmp(proto,"(Ljavax/microedition/lcdui/Graphics;)V")!=0)
        return E63_UI_INVALID;
    args[0]=value(UI_REF,(int32_t)receiver);
    args[1]=value(UI_REF,(int32_t)graphics);
    return call_typed(vm,receiver,method,proto,args,2u,0,0,1);
}
const char *e63_ui_status(E63UiStatus st) {
    switch (st) {
        case E63_UI_OK:return "ok";
        case E63_UI_INVALID:return "invalid DEX/register/object";
        case E63_UI_NO_METHOD:return "guest method not found";
        case E63_UI_UNSUPPORTED:return "unsupported reached DEX/MIDP operation";
        case E63_UI_BUDGET:return "DEX instruction/depth budget exhausted";
        case E63_UI_LIMIT:return "native UI event memory limit";
        default:return "unknown UI event status";
    }
}
