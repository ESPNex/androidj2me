#include "aosp_object_vm.h"
#include <stdlib.h>
#include <string.h>

#define OBJECT_DESC "Ljava/lang/Object;"
#define VM_MAX_ARGS 5u
#define VM_MAX_DEPTH 4u
#define VM_NAME_BYTES 256u
#define VM_MAX_CLASSES 4u /* per-object APK/framework/core ancestry, then Object */
#define VM_INIT_CLASSES 8u
#define VM_IMAGE_APP 0u
#define VM_IMAGE_FRAMEWORK 1u
#define VM_IMAGE_CORE 2u

/* All offsets are into separately SHA-pinned read-only DEX files. The entire
 * 16-MB Launcher2 APK or 2.7-MB core DEX is NEVER copied into target RAM. */
typedef struct VmImage {
    E63ObjectSource source;
    uint32_t bytes, data_start, data_end;
    uint32_t strings, strings_at, types, types_at;
    uint32_t protos, protos_at, fields, fields_at;
    uint32_t methods, methods_at, classes, classes_at;
    E63ObjectStatus error;
} VmImage;
typedef struct VmField {
    uint32_t id, owner;
    uint64_t bits;
    uint8_t kind, image; /* I, Z, J, R; DEX image owning field_id */
} VmField;
typedef struct VmClass {
    uint32_t type,super_type,class_data,interfaces;
    uint8_t image; /* each type index lives ONLY in its own DEX */
} VmClass;
typedef struct VmCode {
    VmImage *image;
    uint32_t offset, words, owner;
    uint16_t registers, ins, outs;
    unsigned arguments,argument_words;
    uint8_t result_kind; /* V for void, I or Z for primitive int/boolean */
    char method_name[VM_NAME_BYTES];
} VmCode;
typedef struct VmImageKey {
    E63BootReadAt read_at;
    void *context;
    uint32_t bytes;
} VmImageKey;
typedef struct VmStaticField {
    VmImageKey image;
    uint32_t field_id, reference; /* reference OR raw 32-bit I/Z value */
    uint8_t kind; /* R, I or Z; keyed by verified DEX image + field_id */
} VmStaticField;
typedef struct VmClassInit {
    VmImageKey image;
    uint32_t type;
    uint8_t state; /* 1 initializing, 2 ready; recursion fails closed */
} VmClassInit;
typedef struct VmHeap {
    E63ObjectVm *objects[E63_OBJECT_MAX_HEAP_HANDLES+1u];
    char array_types[E63_OBJECT_MAX_HEAP_HANDLES+1u][VM_NAME_BYTES];
    uint32_t array_lengths[E63_OBJECT_MAX_HEAP_HANDLES+1u];
    VmStaticField statics[E63_OBJECT_MAX_STATIC_FIELDS];
    VmClassInit initialized[VM_INIT_CLASSES];
    unsigned used,static_count,init_count,steps;
} VmHeap;
struct E63ObjectVm {
    VmImage app,framework,core;
    unsigned has_framework;
    char descriptor[VM_NAME_BYTES];
    uint32_t core_type,core_class_data;
    VmClass classes[VM_MAX_CLASSES]; /* most derived first */
    unsigned class_count;
    VmField fields[E63_OBJECT_MAX_FIELDS];
    unsigned field_count,super_called,steps,ready;
    VmHeap *heap;
    uint32_t handle;
};
typedef struct VmRegister {
    uint32_t bits;
    uint8_t kind; /* 0 = uninitialized; I = int, R = receiver, L/H = wide */
} VmRegister;
static void vm_destroy(E63ObjectVm *vm)
    {
    unsigned i;
    if (!vm) return;
    if (vm->heap && vm->handle==1u)
        {
        VmHeap *heap=vm->heap;
        for (i=2u;i<=heap->used;++i)
            if (heap->objects[i])
                {memset(heap->objects[i],0,sizeof(*vm));
                 free(heap->objects[i]);}
        memset(heap,0,sizeof(*heap));free(heap);
        }
    memset(vm,0,sizeof(*vm));free(vm);
    }

static uint16_t le16(const uint8_t *p)
    {return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1]<<8u));}
static uint32_t le32(const uint8_t *p)
    {return (uint32_t)p[0] | ((uint32_t)p[1]<<8u) |
            ((uint32_t)p[2]<<16u) | ((uint32_t)p[3]<<24u);}
static int within(uint64_t at,uint64_t n,uint64_t end)
    {return at<=end && n<=end-at;}
static VmImageKey image_key(const VmImage *d)
    {
    VmImageKey key;
    key.read_at=d->source.read_at;
    key.context=d->source.context;
    key.bytes=d->bytes;
    return key;
    }
static int same_image_key(VmImageKey key,const VmImage *d)
    {
    return key.read_at==d->source.read_at &&
           key.context==d->source.context && key.bytes==d->bytes;
    }
static int bounded_name(const char *s)
    {
    unsigned i;
    if (!s) return 0;
    for (i=0u;i<VM_NAME_BYTES;++i)
        if (!s[i]) return i>0u;
    return 0;
    }
static int read_part(VmImage *d,uint64_t at,uint8_t *dst,size_t n)
    {
    size_t done=0u;
    if (!dst || !n || !within(at,n,d->bytes))
        {d->error=E63_OBJECT_UNTRUSTED;return 0;}
    while (done<n)
        {
        size_t count=n-done;
        if (count>256u) count=256u;
        if (!d->source.read_at(d->source.context,(uint32_t)(at+done),
                               dst+done,count))
            {d->error=E63_OBJECT_IO;return 0;}
        done+=count;
        }
    return 1;
    }
static int get32(VmImage *d,uint64_t at,uint32_t *value)
    {
    uint8_t raw[4];
    if (!read_part(d,at,raw,4u)) return 0;
    *value=le32(raw);return 1;
    }
static int valid_table(VmImage *d,uint32_t count,uint32_t at,
                       uint32_t width,uint32_t limit)
    {
    if (count>limit) return 0;
    if (!count) return at==0u;
    return at>=112u && (at&3u)==0u &&
           within(at,(uint64_t)count*width,d->bytes);
    }
static int open_image(VmImage *d,const E63ObjectSource *input)
    {
    uint8_t raw[112];
    memset(d,0,sizeof(*d));
    d->error=E63_OBJECT_UNTRUSTED;
    if (!input || !input->read_at || input->dex_bytes<112u ||
        input->dex_bytes>32u*1024u*1024u) return 0;
    d->source=*input;d->bytes=(uint32_t)input->dex_bytes;
    if (!read_part(d,0u,raw,112u)) return 0;
    if ((memcmp(raw,"dex\n035\0",8u)!=0 &&
         memcmp(raw,"dex\n036\0",8u)!=0) ||
        le32(raw+32u)!=d->bytes || le32(raw+36u)!=112u ||
        le32(raw+40u)!=0x12345678u) return 0;
    d->strings=le32(raw+56u);d->strings_at=le32(raw+60u);
    d->types=le32(raw+64u);d->types_at=le32(raw+68u);
    d->protos=le32(raw+72u);d->protos_at=le32(raw+76u);
    d->fields=le32(raw+80u);d->fields_at=le32(raw+84u);
    d->methods=le32(raw+88u);d->methods_at=le32(raw+92u);
    d->classes=le32(raw+96u);d->classes_at=le32(raw+100u);
    d->data_start=le32(raw+108u);
    if (!valid_table(d,d->strings,d->strings_at,4u,1000000u) ||
        !valid_table(d,d->types,d->types_at,4u,65535u) ||
        !valid_table(d,d->protos,d->protos_at,12u,65535u) ||
        !valid_table(d,d->fields,d->fields_at,8u,65535u) ||
        !valid_table(d,d->methods,d->methods_at,8u,65535u) ||
        !valid_table(d,d->classes,d->classes_at,32u,10000u) ||
        d->data_start<112u ||
        !within(d->data_start,le32(raw+104u),d->bytes) ||
        !le32(raw+104u)) return 0;
    d->data_end=d->data_start+le32(raw+104u);
    d->error=E63_OBJECT_OK;
    return 1;
    }
static int uleb(VmImage *d,uint32_t *at,uint32_t *out)
    {
    uint32_t result=0u;
    unsigned i;
    for (i=0u;i<5u;++i)
        {
        uint8_t b;
        if (*at<d->data_start || !within(*at,1u,d->data_end))
            {d->error=E63_OBJECT_UNTRUSTED;return 0;}
        if (!read_part(d,*at,&b,1u)) return 0;
        ++*at;
        if (i==4u && (b&0xf0u))
            {d->error=E63_OBJECT_UNTRUSTED;return 0;}
        result|=(uint32_t)(b&127u)<<(i*7u);
        if (!(b&128u)) {*out=result;return 1;}
        }
    d->error=E63_OBJECT_UNTRUSTED;
    return 0;
    }
static int string_is(VmImage *d,uint32_t index,const char *wanted)
    {
    uint32_t at,units;
    uint8_t data[VM_NAME_BYTES];
    size_t length=strlen(wanted);
    if (!length || length>=VM_NAME_BYTES || index>=d->strings ||
        !get32(d,d->strings_at+(uint64_t)index*4u,&at) ||
        at<d->data_start || at>=d->data_end ||
        !uleb(d,&at,&units) || units!=length ||
        !within(at,length+1u,d->data_end) ||
        !read_part(d,at,data,length+1u)) return 0;
    return data[length]==0u && memcmp(data,wanted,length)==0;
    }
static int string_copy(VmImage *d,uint32_t index,char result[VM_NAME_BYTES])
    {
    uint32_t at,units;
    uint8_t text[VM_NAME_BYTES];
    unsigned i;
    result[0]=0;
    if (index>=d->strings ||
        !get32(d,d->strings_at+(uint64_t)index*4u,&at) ||
        at<d->data_start || at>=d->data_end ||
        !uleb(d,&at,&units) || !units || units>=VM_NAME_BYTES ||
        !within(at,units+1u,d->data_end) ||
        !read_part(d,at,text,units+1u) || text[units]!=0u) return 0;
    /* Class/field/array descriptors are ASCII in the supported subset;
     * do not silently reinterpret Android MUTF-8 names as host UTF-8. */
    for (i=0u;i<units;++i)
        if (text[i]<32u || text[i]>126u) return 0;
    memcpy(result,text,units);
    result[units]=0;
    return 1;
    }
static int type_copy(VmImage *d,uint32_t index,char result[VM_NAME_BYTES])
    {
    uint32_t str;
    return index<d->types &&
           get32(d,d->types_at+(uint64_t)index*4u,&str) &&
           string_copy(d,str,result);
    }
static int type_is(VmImage *d,uint32_t index,const char *wanted)
    {
    uint32_t str;
    return index<d->types && get32(d,d->types_at+(uint64_t)index*4u,&str) &&
           str<d->strings && string_is(d,str,wanted);
    }
static VmImage *vm_image(E63ObjectVm *vm,unsigned slot)
    {
    if (slot==VM_IMAGE_APP) return &vm->app;
    if (slot==VM_IMAGE_FRAMEWORK && vm->has_framework)
        return &vm->framework;
    if (slot==VM_IMAGE_CORE) return &vm->core;
    return 0;
    }
static unsigned vm_image_slot(E63ObjectVm *vm,const VmImage *d)
    {
    if (d==&vm->app) return VM_IMAGE_APP;
    if (vm->has_framework && d==&vm->framework) return VM_IMAGE_FRAMEWORK;
    if (d==&vm->core) return VM_IMAGE_CORE;
    return 255u;
    }
static uint8_t field_kind(VmImage *d,uint16_t type)
    {
    uint32_t str,at,len;
    uint8_t first;
    if (type>=d->types ||
        !get32(d,d->types_at+(uint64_t)type*4u,&str) ||
        str>=d->strings ||
        !get32(d,d->strings_at+(uint64_t)str*4u,&at) ||
        at<d->data_start || at>=d->data_end || !uleb(d,&at,&len) ||
        !len || !within(at,1u,d->data_end) ||
        !read_part(d,at,&first,1u)) return 0u;
    if (first=='I' || first=='Z' || first=='J') return first;
    if (first=='L' || first=='[') return 'R';
    return 0u;
    }
static int proto_arguments_typed(VmImage *d,uint16_t index,
                           const E63ObjectArg *arguments,unsigned count,
                           const char *return_type,unsigned *words)
    {
    uint8_t raw[12];
    uint8_t list[4u+2u*VM_MAX_ARGS];
    uint32_t parameters,i;
    unsigned slots=0u;
    if (count>4u || (count && !arguments) || index>=d->protos ||
        !return_type ||
        (strcmp(return_type,"V")!=0 && strcmp(return_type,"I")!=0 &&
         strcmp(return_type,"Z")!=0) ||
        !read_part(d,d->protos_at+(uint64_t)index*12u,raw,12u) ||
        !type_is(d,le32(raw+4u),return_type)) return 0;
    parameters=le32(raw+8u);
    if (!count) {if (words) *words=0u;return parameters==0u;}
    if (parameters<d->data_start ||
        !within(parameters,4u+count*2u,d->data_end) ||
        !read_part(d,parameters,list,4u+count*2u) ||
        le32(list)!=count) return 0;
    for (i=0u;i<count;++i)
        {
        const char *type=arguments[i].type_descriptor;
        const uint64_t bits=arguments[i].bits;
        if (!bounded_name(type) ||
            !type_is(d,le16(list+4u+i*2u),type)) return 0;
        if (strcmp(type,"I")==0)
            {
            if ((bits>>32u)!=0u &&
                !((bits>>32u)==0xffffffffu &&
                  ((uint32_t)bits&0x80000000u))) return 0;
            ++slots;
            }
        else if (strcmp(type,"Z")==0)
            {if (bits>1u) return 0; ++slots;}
        else if (strcmp(type,"J")==0) slots+=2u;
        else if ((type[0]=='L' && type[strlen(type)-1u]==';') ||
                 type[0]=='[')
            {if (bits!=0u) return 0; ++slots;}
        else return 0;
        if (slots+1u>VM_MAX_ARGS) return 0;
        }
    if (words) *words=slots;
    return 1;
    }
static int proto_void_zero(VmImage *d,uint16_t index)
    {return proto_arguments_typed(d,index,0,0u,"V",0);}
/* Validate the shape of a call site even when a static method is in an
 * unexecuted branch. The interpreter NEVER replaces that call with a native
 * implementation: if reached, unsupported static dispatch fails closed. */
static int proto_void_register_words(VmImage *d,uint16_t index,
                                      unsigned requested)
    {
    uint8_t raw[12],list[4u+2u*VM_MAX_ARGS];
    uint32_t start,count,i;
    unsigned words=0u;
    if (index>=d->protos ||
        !read_part(d,d->protos_at+(uint64_t)index*12u,raw,12u) ||
        !type_is(d,le32(raw+4u),"V")) return 0;
    start=le32(raw+8u);
    if (!start) return requested==0u;
    if (start<d->data_start ||
        !within(start,4u,d->data_end) ||
        !read_part(d,start,list,4u)) return 0;
    count=le32(list);
    if (!count || count>VM_MAX_ARGS ||
        !within(start,4u+count*2u,d->data_end) ||
        !read_part(d,start,list,4u+count*2u)) return 0;
    for (i=0u;i<count;++i)
        {
        uint8_t kind=field_kind(d,le16(list+4u+i*2u));
        if (!kind) return 0;
        words+=kind=='J' ? 2u : 1u;
        }
    return words==requested;
    }
/* Decode the actual call-site registers against the method's DEX proto.
 * This is argument forwarding to real Java constructors, NOT a stubbed
 * superclass constructor. Non-null cross-method references still fail closed
 * until the object verifier and cross-image class loader can type them. */
static E63ObjectStatus call_arguments(VmImage *d,uint16_t proto,
          uint16_t reglist,unsigned input_words,const VmRegister *registers,
          E63ObjectArg args[4],char names[4][VM_NAME_BYTES],unsigned *count)
    {
    uint8_t row[12],list[4u+2u*4u];
    uint32_t start,n,i;
    unsigned pos=1u;
    *count=0u;
    if (!d || !registers || !args || !names || !count ||
        !input_words || input_words>VM_MAX_ARGS || proto>=d->protos ||
        !read_part(d,d->protos_at+(uint64_t)proto*12u,row,12u) ||
        !type_is(d,le32(row+4u),"V")) return E63_OBJECT_UNTRUSTED;
    start=le32(row+8u);
    if (!start) return input_words==1u ? E63_OBJECT_OK :
                                       E63_OBJECT_UNTRUSTED;
    if (start<d->data_start || !within(start,4u,d->data_end) ||
        !read_part(d,start,list,4u)) return E63_OBJECT_UNTRUSTED;
    n=le32(list);
    if (!n || n>4u || !within(start,4u+2u*n,d->data_end) ||
        !read_part(d,start,list,4u+2u*n)) return E63_OBJECT_UNTRUSTED;
    for (i=0u;i<n;++i)
        {
        uint32_t bits;
        const VmRegister *reg;
        if (pos>=input_words ||
            !type_copy(d,le16(list+4u+i*2u),names[i]))
            return E63_OBJECT_UNTRUSTED;
        reg=&registers[(reglist>>(pos*4u))&15u];
        if (strcmp(names[i],"I")==0 || strcmp(names[i],"Z")==0)
            {
            if (reg->kind!='I' ||
                (names[i][0]=='Z' && reg->bits>1u))
                return E63_OBJECT_UNTRUSTED;
            bits=reg->bits;
            args[i].bits=bits;
            ++pos;
            }
        else if (strcmp(names[i],"J")==0)
            {
            const VmRegister *upper;
            if (pos+1u>=input_words || reg->kind!='L')
                return E63_OBJECT_UNTRUSTED;
            upper=&registers[(reglist>>((pos+1u)*4u))&15u];
            if (upper->kind!='H') return E63_OBJECT_UNTRUSTED;
            args[i].bits=(uint64_t)reg->bits |
                         ((uint64_t)upper->bits<<32u);
            pos+=2u;
            }
        else if ((names[i][0]=='L' &&
                  names[i][strlen(names[i])-1u]==';') ||
                 names[i][0]=='[')
            {
            if (!(reg->kind=='N' ||
                  (reg->kind=='I' && reg->bits==0u)))
                return E63_OBJECT_UNSUPPORTED;
            args[i].bits=0u;
            ++pos;
            }
        else return E63_OBJECT_UNSUPPORTED;
        args[i].type_descriptor=names[i];
        }
    if (pos!=input_words) return E63_OBJECT_UNTRUSTED;
    *count=n;
    return E63_OBJECT_OK;
    }

static int class_row(VmImage *d,const E63BootClass *where,
                     const char *descriptor,uint32_t *type,
                     uint32_t *data,uint32_t *super,uint32_t *interfaces)
    {
    uint8_t row[32];
    if (!where || where->class_def_index>=d->classes ||
        !read_part(d,d->classes_at+(uint64_t)where->class_def_index*32u,
                   row,32u)) return 0;
    *type=le32(row);*super=le32(row+8u);*data=le32(row+24u);
    if (interfaces) *interfaces=le32(row+12u);
    return *type<d->types && type_is(d,*type,descriptor) &&
           (le32(row+4u)&(0x200u|0x400u))==0u &&
           *data>=d->data_start && *data<d->data_end;
    }
static int parent_row(VmImage *d,uint32_t wanted,VmClass *parent)
    {
    uint32_t i;
    uint8_t row[32];
    if (wanted>=d->types) return 0;
    for (i=0u;i<d->classes;++i)
        {
        if (!read_part(d,d->classes_at+(uint64_t)i*32u,row,32u)) return 0;
        if (le32(row)==wanted)
            {
            /* An abstract class IS a valid superclass of a concrete object;
             * reject interfaces here, but not AbstractList/Collection. */
            if ((le32(row+4u)&0x200u)!=0u ||
                le32(row+24u)<d->data_start ||
                le32(row+24u)>=d->data_end) return 0;
            parent->type=wanted;
            parent->super_type=le32(row+8u);
            parent->class_data=le32(row+24u);
            parent->interfaces=le32(row+12u);
            return 1;
            }
        }
    return 0;
    }
static int class_by_descriptor(VmImage *d,const char *descriptor,
                               VmClass *result)
    {
    uint32_t lo=0u,hi=d->types,mid,typ,row_type;
    char candidate[VM_NAME_BYTES];
    uint8_t row[32];
    if (!bounded_name(descriptor)) return 0;
    while (lo<hi)
        {
        mid=lo+(hi-lo)/2u;
        if (!type_copy(d,mid,candidate)) return 0;
        if (strcmp(candidate,descriptor)<0) lo=mid+1u;
        else hi=mid;
        }
    if (lo==d->types || !type_copy(d,lo,candidate) ||
        strcmp(candidate,descriptor)!=0) return 0;
    typ=lo;
    /* These authentic locally-built dx DEX class_defs are NOT ordered by
     * class_idx (ArrayList's class_def_index=896, type_idx=876). Never
     * binary-search an unsorted table and then invent a missing class. */
    for (lo=0u;lo<d->classes;++lo)
        {
        if (!get32(d,d->classes_at+(uint64_t)lo*32u,&row_type))
            return 0;
        if (row_type==typ) break;
        }
    if (lo==d->classes ||
        !read_part(d,d->classes_at+(uint64_t)lo*32u,row,32u) ||
        le32(row)!=typ || (le32(row+4u)&(0x200u|0x400u))!=0u ||
        le32(row+24u)<d->data_start ||
        le32(row+24u)>=d->data_end) return 0;
    result->type=typ;
    result->super_type=le32(row+8u);
    result->class_data=le32(row+24u);
    result->interfaces=le32(row+12u);
    return 1;
    }
/* A child may have a real framework superclass while it lives in an
 * independently signed Launcher APK. Class identity is descriptor +
 * authenticated DEX, NEVER an integer type_idx shared across DEX files.
 * The optional framework image is still a bounded explicit dependency, not
 * a replacement for the eventual ten-JAR bootclasspath class loader. */
static int find_parent(E63ObjectVm *vm,VmImage *from,uint32_t type,
                       VmClass *out)
    {
    char name[VM_NAME_BYTES];
    VmImage *candidate;
    unsigned slot,from_slot=vm_image_slot(vm,from);
    if (from_slot>VM_IMAGE_CORE || type>=from->types) return 0;
    if (parent_row(from,type,out))
        {out->image=(uint8_t)from_slot;return 1;}
    if (from->error==E63_OBJECT_IO || !type_copy(from,type,name)) return 0;
    for (slot=0u;slot<3u;++slot)
        {
        const unsigned desired=VM_IMAGE_CORE-slot;
        candidate=vm_image(vm,desired);
        if (!candidate || desired==from_slot) continue;
        if (class_by_descriptor(candidate,name,out))
            {out->image=(uint8_t)desired;return 1;}
        if (candidate->error==E63_OBJECT_IO) return 0;
        }
    return 0;
    }
static const VmClass *owned_class(const E63ObjectVm *vm,
                                  VmImage *from,uint32_t type)
    {
    unsigned i;
    char name[VM_NAME_BYTES];
    E63ObjectVm *mutable_vm=(E63ObjectVm *)vm;
    if (!type_copy(from,type,name)) return 0;
    for (i=0u;i<vm->class_count;++i)
        {
        VmImage *image=vm_image(mutable_vm,vm->classes[i].image);
        if (image && type_is(image,vm->classes[i].type,name))
            return &vm->classes[i];
        }
    return 0;
    }
static int class_counts(VmImage *d,uint32_t data,uint32_t counts[4],
                        uint32_t *at)
    {
    unsigned i;
    *at=data;
    if (*at<d->data_start || *at>=d->data_end) return 0;
    for (i=0u;i<4u;++i)
        if (!uleb(d,at,&counts[i])) return 0;
    return (uint64_t)counts[0]+counts[1]<=d->fields &&
           (uint64_t)counts[2]+counts[3]<=d->methods;
    }
static int skip_fields(VmImage *d,uint32_t *at,uint32_t count,
                       uint32_t owner,int static_fields,
                       E63ObjectVm *vm)
    {
    uint32_t i,index=0u;
    for (i=0u;i<count;++i)
        {
        uint32_t delta,flags;
        uint8_t raw[8];
        if (!uleb(d,at,&delta) || !uleb(d,at,&flags) ||
            delta>=d->fields || index>=d->fields-delta)
            return 0;
        index+=delta;
        if (!read_part(d,d->fields_at+(uint64_t)index*8u,raw,8u) ||
            le16(raw)!=owner || le16(raw+2u)>=d->types ||
            le32(raw+4u)>=d->strings ||
            (!!(flags&8u) != !!static_fields)) return 0;
        if (!static_fields)
            {
            unsigned j;
            uint8_t kind=field_kind(d,le16(raw+2u));
            if (!kind) return 0;
            if (vm)
                {
                if (vm->field_count>=E63_OBJECT_MAX_FIELDS) return 0;
                const unsigned slot=vm_image_slot(vm,d);
                if (slot>VM_IMAGE_CORE) return 0;
                for (j=0u;j<vm->field_count;++j)
                    if (vm->fields[j].id==index &&
                        vm->fields[j].image==slot) return 0;
                vm->fields[vm->field_count].id=index;
                vm->fields[vm->field_count].owner=owner;
                vm->fields[vm->field_count].kind=kind;
                vm->fields[vm->field_count].image=(uint8_t)slot;
                vm->fields[vm->field_count].bits=0u;
                ++vm->field_count;
                }
            }
        }
    return 1;
    }
static int method_reference(VmImage *d,uint32_t id,
                            uint16_t *owner,uint16_t *proto,
                            uint32_t *name)
    {
    uint8_t raw[8];
    if (id>=d->methods ||
        !read_part(d,d->methods_at+(uint64_t)id*8u,raw,8u)) return 0;
    *owner=le16(raw);*proto=le16(raw+2u);*name=le32(raw+4u);
    return *owner<d->types && *proto<d->protos && *name<d->strings;
    }
static E63ObjectStatus find_method_typed(VmImage *d,uint32_t class_data,
                                   uint32_t class_type,const char *name,
                                   int direct,const E63ObjectArg *arguments,
                                   unsigned argument_count,
                                   const char *return_type,VmCode *out)
    {
    uint32_t at,counts[4],i,section;
    unsigned found=0u;
    memset(out,0,sizeof(*out));
    if (!class_counts(d,class_data,counts,&at) ||
        !skip_fields(d,&at,counts[0],class_type,1,0) ||
        !skip_fields(d,&at,counts[1],class_type,0,0))
        return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                         E63_OBJECT_UNTRUSTED;
    for (section=2u;section<=3u;++section)
        {
        uint32_t idx=0u;
        for (i=0u;i<counts[section];++i)
            {
            uint32_t delta,flags,code_at,method_name;
            uint16_t owner,proto;
            if (!uleb(d,&at,&delta) || !uleb(d,&at,&flags) ||
                !uleb(d,&at,&code_at) || delta>=d->methods ||
                idx>=d->methods-delta)
                return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                                 E63_OBJECT_UNTRUSTED;
            idx+=delta;
            if (!method_reference(d,idx,&owner,&proto,&method_name) ||
                owner!=class_type || (section==2u && !!(flags&8u) &&
                                      string_is(d,method_name,"<init>")))
                return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                                 E63_OBJECT_UNTRUSTED;
            if (section!=((direct!=0) ? 2u : 3u) ||
                !string_is(d,method_name,name))
                continue;
            {
            unsigned words=0u;
            if (!proto_arguments_typed(d,proto,arguments,argument_count,
                                       return_type,&words))
                continue;
            if (found++) return E63_OBJECT_UNTRUSTED;
            out->arguments=argument_count;
            out->argument_words=words;
            out->result_kind=(uint8_t)return_type[0];
            }
            if (!code_at || (code_at&3u) || code_at<d->data_start ||
                !within(code_at,16u,d->data_end))
                return E63_OBJECT_UNSUPPORTED;
            {
            uint8_t code[16];
            if (!read_part(d,code_at,code,16u)) return E63_OBJECT_IO;
            out->registers=le16(code);out->ins=le16(code+2u);
            out->outs=le16(code+4u);
            out->words=le32(code+12u);out->offset=code_at+16u;
            out->image=d;out->owner=class_type;
            /* The method name is copied while the caller's buffer is valid. */
            if (!bounded_name(name)) return E63_OBJECT_BAD_INPUT;
            strcpy(out->method_name,name);
            if (le16(code+6u) ||
                out->ins!=(strcmp(name,"<clinit>")==0 ? 0u : 1u)+
                          out->argument_words ||
                !out->registers || out->registers>E63_OBJECT_MAX_REGISTERS ||
                out->registers<out->ins || out->outs>VM_MAX_ARGS ||
                !out->words || out->words>E63_OBJECT_MAX_CODE_WORDS ||
                !within(out->offset,(uint64_t)out->words*2u,d->data_end))
                return E63_OBJECT_UNSUPPORTED;
            }
            }
        }
    return found ? E63_OBJECT_OK : E63_OBJECT_NOT_FOUND;
    }
static E63ObjectStatus find_method(VmImage *d,uint32_t class_data,
                                   uint32_t class_type,const char *name,
                                   int direct,const E63ObjectArg *arguments,
                                   unsigned argument_count,VmCode *out)
    {
    return find_method_typed(d,class_data,class_type,name,direct,arguments,
                             argument_count,"V",out);
    }
static E63ObjectStatus collect_fields(E63ObjectVm *vm,
                                       const VmClass *klass)
    {
    VmImage *d=vm_image(vm,klass->image);
    uint32_t counts[4],at,i,index=0u;
    if (!d) return E63_OBJECT_UNTRUSTED;
    if (!class_counts(d,klass->class_data,counts,&at) ||
        counts[1]>E63_OBJECT_MAX_FIELDS-vm->field_count ||
        !skip_fields(d,&at,counts[0],klass->type,1,0) ||
        !skip_fields(d,&at,counts[1],klass->type,0,vm))
        return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                         E63_OBJECT_UNTRUSTED;
    for (i=0u;i<counts[2];++i)
        {
        uint32_t delta,flags,code_at,name;
        uint16_t owner,proto;
        if (!uleb(d,&at,&delta) || !uleb(d,&at,&flags) ||
            !uleb(d,&at,&code_at) || delta>=d->methods ||
            index>=d->methods-delta)
            return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                             E63_OBJECT_UNTRUSTED;
        index+=delta;
        if (!method_reference(d,index,&owner,&proto,&name) ||
            owner!=klass->type)
            return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                             E63_OBJECT_UNTRUSTED;
        /* Static initialization is run before construction, never silently
         * discarded. Unknown bytecode in <clinit> still fails closed. */
        }
    return E63_OBJECT_OK;
    }
static E63ObjectStatus ensure_static_class(E63ObjectVm *vm,VmImage *d,
                                            uint16_t owner_type);
static E63ObjectStatus execute(E63ObjectVm *vm,const VmCode *method,
                                unsigned depth,const E63ObjectArg *arguments,
                                unsigned count,uint32_t *result);
static E63ObjectStatus heap_new_instance(E63ObjectVm *current,
                                         VmImage *referencing_dex,
                                         uint32_t type_id,uint32_t *handle)
    {
    VmImage *source;
    VmClass found;
    E63ObjectVm *child;
    E63ObjectStatus status=E63_OBJECT_OK;
    unsigned i;
    char descriptor[VM_NAME_BYTES];
    VmHeap *heap=current->heap;
    *handle=0u;
    if (!heap || heap->used>=E63_OBJECT_MAX_HEAP_HANDLES)
        return E63_OBJECT_BUDGET;
    if (!type_copy(referencing_dex,type_id,descriptor) ||
        descriptor[0]!='L' ||
        descriptor[strlen(descriptor)-1u]!=';')
        return E63_OBJECT_UNTRUSTED;
    /* Resolve an actual class_def in an already SHA-verified source; never
     * invent an implementation for a referenced but missing boot class. */
    source=&current->app;
    if (!class_by_descriptor(source,descriptor,&found))
        {
        if (source->error==E63_OBJECT_IO) return E63_OBJECT_IO;
        source=current->has_framework ? &current->framework : &current->core;
        if (!class_by_descriptor(source,descriptor,&found))
            {
            if (source->error==E63_OBJECT_IO) return E63_OBJECT_IO;
            if (!current->has_framework) return E63_OBJECT_UNSUPPORTED;
            source=&current->core;
            if (!class_by_descriptor(source,descriptor,&found))
                return source->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                                      E63_OBJECT_UNSUPPORTED;
            }
        }
    status=ensure_static_class(current,source,(uint16_t)found.type);
    if (status!=E63_OBJECT_OK) return status;
    if (heap->used>=E63_OBJECT_MAX_HEAP_HANDLES)
        return E63_OBJECT_BUDGET;
    child=(E63ObjectVm *)calloc(1u,sizeof(*child));
    if (!child) return E63_OBJECT_NO_MEMORY;
    child->heap=heap;
    child->handle=heap->used+1u;
    child->core=current->core;
    child->framework=current->framework;
    child->has_framework=current->has_framework;
    child->core_type=current->core_type;
    child->core_class_data=current->core_class_data;
    child->app=*source;
    child->classes[0]=found;
    child->classes[0].image=VM_IMAGE_APP; /* child's selected source */
    child->class_count=1u;
    strcpy(child->descriptor,descriptor);
    while (1)
        {
        VmClass *previous=&child->classes[child->class_count-1u];
        VmImage *from=vm_image(child,previous->image);
        VmClass *parent;
        unsigned j;
        if (!from) {status=E63_OBJECT_UNTRUSTED;goto fail;}
        if (type_is(from,previous->super_type,OBJECT_DESC)) break;
        if (child->class_count>=VM_MAX_CLASSES)
            {status=E63_OBJECT_UNSUPPORTED;goto fail;}
        parent=&child->classes[child->class_count];
        if (!find_parent(child,from,previous->super_type,parent))
            {status=from->error==E63_OBJECT_IO ||
                child->framework.error==E63_OBJECT_IO ||
                child->core.error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                                  E63_OBJECT_UNSUPPORTED;
             goto fail;}
        for (j=0u;j<child->class_count;++j)
            if (child->classes[j].image==parent->image &&
                child->classes[j].type==parent->type)
                {status=E63_OBJECT_UNTRUSTED;goto fail;}
        ++child->class_count;
        }
    for (i=0u;i<child->class_count && status==E63_OBJECT_OK;++i)
        status=collect_fields(child,&child->classes[i]);
    if (status!=E63_OBJECT_OK) goto fail;
    heap->objects[child->handle]=child;
    heap->used=child->handle;
    *handle=child->handle;
    return E63_OBJECT_OK;
fail:
    memset(child,0,sizeof(*child));free(child);
    return status;
    }
static E63ObjectStatus heap_new_empty_array(E63ObjectVm *current,
                                             VmImage *d,uint32_t type_id,
                                             uint32_t *handle)
    {
    char descriptor[VM_NAME_BYTES];
    VmHeap *heap=current->heap;
    *handle=0u;
    if (!heap || heap->used>=E63_OBJECT_MAX_HEAP_HANDLES)
        return E63_OBJECT_BUDGET;
    if (!type_copy(d,type_id,descriptor) || descriptor[0]!='[' ||
        !descriptor[1]) return E63_OBJECT_UNTRUSTED;
    /* Only zero-length arrays: no element storage/aliasing or fake contents.
     * EmptyArray.<clinit> really allocates the Android singleton arrays. */
    ++heap->used;
    strcpy(heap->array_types[heap->used],descriptor);
    heap->array_lengths[heap->used]=0u;
    *handle=heap->used;
    return E63_OBJECT_OK;
    }
static const char *heap_type(const E63ObjectVm *current,uint32_t handle)
    {
    const VmHeap *heap=current->heap;
    if (!heap || !handle || handle>heap->used) return 0;
    return heap->objects[handle] ? heap->objects[handle]->descriptor :
           heap->array_types[handle][0] ? heap->array_types[handle] : 0;
    }
/* Check Java reference assignment through verified class_def superclass and
 * direct interfaces, not by accepting every host-side handle as Object.
 * Transitive interface inheritance and array covariance remain unsupported. */
static int reference_assignable(E63ObjectVm *current,uint32_t ref,
                                const char *declared)
    {
    E63ObjectVm *object;
    VmImage *d;
    const char *actual=heap_type(current,ref);
    unsigned i;
    if (!actual || !bounded_name(declared)) return 0;
    if (strcmp(actual,declared)==0 ||
        strcmp(declared,OBJECT_DESC)==0) return 1;
    object=current->heap->objects[ref];
    if (!object) return 0; /* no guessing array/interface covariance */
    for (i=0u;i<object->class_count;++i)
        {
        const VmClass *klass=&object->classes[i];
        uint32_t count,j;
        d=vm_image(object,klass->image);
        if (!d) return 0;
        if (type_is(d,klass->type,declared)) return 1;
        if (!klass->interfaces) continue;
        if (klass->interfaces<d->data_start ||
            !within(klass->interfaces,4u,d->data_end) ||
            !get32(d,klass->interfaces,&count) || count>32u ||
            !within(klass->interfaces,4u+(uint64_t)count*2u,d->data_end))
            return 0;
        for (j=0u;j<count;++j)
            {
            uint8_t raw[2];
            if (!read_part(d,klass->interfaces+4u+(uint64_t)j*2u,raw,2u))
                return 0;
            if (type_is(d,le16(raw),declared)) return 1;
            }
        }
    return 0;
    }
static VmField *resolve_field(E63ObjectVm *vm,VmImage *image,uint32_t id)
    {
    unsigned i,j,owner_at;
    uint8_t requested[8],declared[8];
    char owner[VM_NAME_BYTES],type[VM_NAME_BYTES],name[VM_NAME_BYTES];
    if (id>=image->fields ||
        !read_part(image,image->fields_at+(uint64_t)id*8u,requested,8u) ||
        !type_copy(image,le16(requested),owner) ||
        !type_copy(image,le16(requested+2u),type) ||
        !string_copy(image,le32(requested+4u),name)) return 0;
    /* The referenced owner may be the child although the declaration lives
     * in a separately pinned superclass DEX. Match name AND field type,
     * using the declaring image's own field table, not shared type indices. */
    for (owner_at=0u;owner_at<vm->class_count;++owner_at)
        {
        const VmClass *klass=&vm->classes[owner_at];
        VmImage *d=vm_image(vm,klass->image);
        if (d && type_is(d,klass->type,owner)) break;
        }
    if (owner_at==vm->class_count) return 0;
    for (j=owner_at;j<vm->class_count;++j)
        {
        const VmClass *klass=&vm->classes[j];
        VmImage *d=vm_image(vm,klass->image);
        if (!d) return 0;
        for (i=0u;i<vm->field_count;++i)
            {
            VmField *field=&vm->fields[i];
            if (field->image!=klass->image ||
                field->owner!=klass->type) continue;
            if (!read_part(d,d->fields_at+(uint64_t)field->id*8u,
                           declared,8u)) return 0;
            if (le16(declared)==klass->type &&
                string_is(d,le32(declared+4u),name) &&
                type_is(d,le16(declared+2u),type)) return field;
            }
        }
    return 0;
    }
static int static_ref_field(VmImage *d,uint32_t id,
                             uint16_t *owner,char type[VM_NAME_BYTES])
    {
    uint8_t row[8];
    if (id>=d->fields ||
        !read_part(d,d->fields_at+(uint64_t)id*8u,row,8u) ||
        !type_copy(d,le16(row+2u),type) ||
        (type[0]!='L' && type[0]!='[')) return 0;
    *owner=le16(row);
    return *owner<d->types;
    }
static int static_int_field(VmImage *d,uint32_t id,
                            uint16_t *owner,uint8_t *kind)
    {
    uint8_t row[8];
    if (id>=d->fields ||
        !read_part(d,d->fields_at+(uint64_t)id*8u,row,8u)) return 0;
    *owner=le16(row);
    *kind=field_kind(d,le16(row+2u));
    return *owner<d->types && (*kind=='I' || *kind=='Z');
    }
static E63ObjectStatus ensure_static_class(E63ObjectVm *vm,VmImage *d,
                                            uint16_t owner_type)
    {
    VmHeap *heap=vm->heap;
    VmClass klass;
    VmCode init;
    E63ObjectStatus status;
    uint8_t *code;
    uint32_t pc;
    unsigned i,at,has_return=0u;
    VmRegister registers[E63_OBJECT_MAX_REGISTERS];
    char descriptor[VM_NAME_BYTES];
    if (!heap || !d || owner_type>=d->types)
        return E63_OBJECT_UNTRUSTED;
    for (i=0u;i<heap->init_count;++i)
        if (heap->initialized[i].type==owner_type &&
            same_image_key(heap->initialized[i].image,d))
            return heap->initialized[i].state==2u ? E63_OBJECT_OK :
                                                   E63_OBJECT_UNSUPPORTED;
    if (!type_copy(d,owner_type,descriptor) ||
        (!class_by_descriptor(d,descriptor,&klass) &&
         !parent_row(d,owner_type,&klass)))
        return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                         E63_OBJECT_UNSUPPORTED;
    /* Record INITIALIZING before visiting the superclass: even corrupt
     * cyclic class_def ancestry must fail with bounded stack/steps. */
    if (heap->init_count>=VM_INIT_CLASSES) return E63_OBJECT_BUDGET;
    at=heap->init_count++;
    heap->initialized[at].image=image_key(d);
    heap->initialized[at].type=owner_type;
    heap->initialized[at].state=1u;
    /* Java initializes an actual superclass first. No boot-JAR class is
     * conjured into this two-DEX subset when a parent is not present. */
    if (!type_is(d,klass.super_type,OBJECT_DESC))
        {
        VmClass parent;
        VmImage *source;
        if (klass.super_type>=d->types ||
            klass.super_type==owner_type) return E63_OBJECT_UNTRUSTED;
        if (!find_parent(vm,d,klass.super_type,&parent))
            return d->error==E63_OBJECT_IO ||
                   vm->framework.error==E63_OBJECT_IO ||
                   vm->core.error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                                   E63_OBJECT_UNSUPPORTED;
        source=vm_image(vm,parent.image);
        if (!source) return E63_OBJECT_UNTRUSTED;
        status=ensure_static_class(vm,source,(uint16_t)parent.type);
        if (status!=E63_OBJECT_OK) return status;
        }
    status=find_method(d,klass.class_data,klass.type,
                       "<clinit>",1,0,0u,&init);
    if (status==E63_OBJECT_NOT_FOUND)
        {heap->initialized[at].state=2u;return E63_OBJECT_OK;}
    if (status!=E63_OBJECT_OK) return status;
    code=(uint8_t *)malloc((size_t)init.words*2u);
    if (!code) return E63_OBJECT_NO_MEMORY;
    if (!read_part(d,init.offset,code,(size_t)init.words*2u))
        {free(code);return d->error;}
    /* Scan EVERY instruction before executing even one. In particular a
     * Rect <clinit> calling Pattern.compile must fail rather than assigning
     * a fabricated regex or Parcelable.Creator on Symbian. */
    for (pc=0u;pc<init.words;)
        {
        const uint16_t w=le16(code+2u*pc);
        const unsigned op=w&255u,reg=w>>8u;
        if (op==0x0eu && w==0x000eu)
            {++has_return;++pc;continue;}
        if (op==0x12u && (reg&15u)<init.registers)
            {++pc;continue;}
        if ((op==0x23u && (reg&15u)<init.registers &&
             (reg>>4u)<init.registers) ||
            (op==0x22u && reg<init.registers) ||
            ((op==0x69u || op==0x67u) && reg<init.registers))
            {
            uint16_t index,type_owner;
            char type[VM_NAME_BYTES];
            if (pc+2u>init.words) {status=E63_OBJECT_UNTRUSTED;goto fail;}
            index=le16(code+(size_t)(pc+1u)*2u);
            if (op==0x23u || op==0x22u)
                {
                if (!type_copy(d,index,type) ||
                    type[0]!=(op==0x23u ? '[' : 'L') ||
                    (op==0x22u && type[strlen(type)-1u]!=';'))
                    {status=E63_OBJECT_UNTRUSTED;goto fail;}
                }
            else if (op==0x69u &&
                     (!static_ref_field(d,index,&type_owner,type) ||
                      type_owner!=owner_type))
                {status=E63_OBJECT_UNTRUSTED;goto fail;}
            else if (op==0x67u)
                {
                uint8_t kind;
                if (!static_int_field(d,index,&type_owner,&kind) ||
                    type_owner!=owner_type)
                    {status=E63_OBJECT_UNTRUSTED;goto fail;}
                }
            pc+=2u;continue;
            }
        if (op==0x70u)
            {
            uint16_t id,owner,proto,reglist;
            uint32_t name;
            if (pc+3u>init.words || (reg>>4u)!=1u ||
                (reg&15u)!=0u || init.outs<1u)
                {status=E63_OBJECT_UNTRUSTED;goto fail;}
            id=le16(code+(size_t)(pc+1u)*2u);
            reglist=le16(code+(size_t)(pc+2u)*2u);
            if ((reglist&0xfff0u)!=0u ||
                (reglist&15u)>=init.registers ||
                !method_reference(d,id,&owner,&proto,&name) ||
                !string_is(d,name,"<init>") || !proto_void_zero(d,proto))
                {status=E63_OBJECT_UNSUPPORTED;goto fail;}
            pc+=3u;continue;
            }
        status=E63_OBJECT_UNSUPPORTED;goto fail;
        }
    if (has_return!=1u || le16(code+(init.words-1u)*2u)!=0x000eu)
        {status=E63_OBJECT_UNSUPPORTED;goto fail;}
    memset(registers,0,sizeof(registers));
    for (pc=0u;pc<init.words;)
        {
        const uint16_t w=le16(code+2u*pc);
        const unsigned op=w&255u,reg=w>>8u;
        if (++heap->steps>E63_OBJECT_STEP_BUDGET)
            {status=E63_OBJECT_BUDGET;goto fail;}
        if (op==0x0eu) break;
        if (op==0x12u)
            {
            const unsigned dest=reg&15u;
            const int32_t n=(int32_t)(reg>>4u)-
                            ((reg&0x80u) ? 16 : 0);
            registers[dest].bits=(uint32_t)n;
            registers[dest].kind='I';
            ++pc;
            }
        else if (op==0x23u)
            {
            const unsigned dest=reg&15u,size=reg>>4u;
            uint32_t handle=0u;
            if (registers[size].kind!='I' || registers[size].bits!=0u)
                {status=E63_OBJECT_UNSUPPORTED;goto fail;}
            status=heap_new_empty_array(vm,d,
                    le16(code+(size_t)(pc+1u)*2u),&handle);
            if (status!=E63_OBJECT_OK) goto fail;
            registers[dest].bits=handle;registers[dest].kind='R';
            pc+=2u;
            }
        else if (op==0x22u)
            {
            uint32_t handle=0u;
            status=heap_new_instance(vm,d,
                    le16(code+(size_t)(pc+1u)*2u),&handle);
            if (status!=E63_OBJECT_OK) goto fail;
            registers[reg].bits=handle;registers[reg].kind='R';
            pc+=2u;
            }
        else if (op==0x70u)
            {
            const uint16_t id=le16(code+(size_t)(pc+1u)*2u);
            const unsigned arg=le16(code+(size_t)(pc+2u)*2u)&15u;
            uint16_t target_type,proto;
            uint32_t name;
            char owner_desc[VM_NAME_BYTES];
            const uint32_t handle=registers[arg].bits;
            E63ObjectVm *child;
            VmCode ctor;
            if (registers[arg].kind!='R' || !handle ||
                handle>heap->used || !(child=heap->objects[handle]) ||
                child->ready ||
                !method_reference(d,id,&target_type,&proto,&name) ||
                !type_copy(d,target_type,owner_desc) ||
                strcmp(child->descriptor,owner_desc)!=0)
                {status=E63_OBJECT_UNSUPPORTED;goto fail;}
            status=find_method(&child->app,child->classes[0].class_data,
                    child->classes[0].type,"<init>",1,0,0u,&ctor);
            if (status!=E63_OBJECT_OK) goto fail;
            status=execute(child,&ctor,0u,0,0u,0);
            if (status!=E63_OBJECT_OK) goto fail;
            if (!child->super_called)
                {status=E63_OBJECT_UNTRUSTED;goto fail;}
            child->ready=1u;
            pc+=3u;
            }
        else if (op==0x69u || op==0x67u)
            {
            const uint16_t id=le16(code+(size_t)(pc+1u)*2u);
            uint16_t target_type;
            uint8_t kind='R';
            char type[VM_NAME_BYTES];
            if (op==0x69u)
                {
                if (registers[reg].kind!='R' ||
                    !static_ref_field(d,id,&target_type,type) ||
                    !reference_assignable(vm,registers[reg].bits,type))
                    {status=E63_OBJECT_UNTRUSTED;goto fail;}
                }
            else if (registers[reg].kind!='I' ||
                !static_int_field(d,id,&target_type,&kind) ||
                (kind=='Z' && registers[reg].bits>1u))
                {status=E63_OBJECT_UNTRUSTED;goto fail;}
            if (target_type!=owner_type ||
                heap->static_count>=E63_OBJECT_MAX_STATIC_FIELDS)
                {status=E63_OBJECT_UNTRUSTED;goto fail;}
            for (i=0u;i<heap->static_count;++i)
                if (heap->statics[i].field_id==id &&
                    same_image_key(heap->statics[i].image,d))
                    {status=E63_OBJECT_UNTRUSTED;goto fail;}
            heap->statics[heap->static_count].image=image_key(d);
            heap->statics[heap->static_count].field_id=id;
            heap->statics[heap->static_count].reference=registers[reg].bits;
            heap->statics[heap->static_count].kind=kind;
            ++heap->static_count;pc+=2u;
            }
        }
    heap->initialized[at].state=2u;
    free(code);
    return E63_OBJECT_OK;
fail:
    free(code);
    return status;
    }
static E63ObjectStatus static_object_get(E63ObjectVm *vm,VmImage *d,
                                          uint16_t field,uint32_t *handle)
    {
    uint16_t owner;
    char type[VM_NAME_BYTES];
    unsigned i;
    E63ObjectStatus status;
    *handle=0u;
    if (!static_ref_field(d,field,&owner,type))
        return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                         E63_OBJECT_UNTRUSTED;
    status=ensure_static_class(vm,d,owner);
    if (status!=E63_OBJECT_OK) return status;
    for (i=0u;i<vm->heap->static_count;++i)
        if (vm->heap->statics[i].field_id==field &&
            same_image_key(vm->heap->statics[i].image,d))
            {
            const VmStaticField *slot=&vm->heap->statics[i];
            if (slot->kind!='R' ||
                !reference_assignable(vm,slot->reference,type))
                return E63_OBJECT_UNTRUSTED;
            *handle=slot->reference;
            return E63_OBJECT_OK;
            }
    /* Java static reference fields default to null when no put occurred. */
    return E63_OBJECT_OK;
    }
static E63ObjectStatus static_int_get(E63ObjectVm *vm,VmImage *d,
                                       uint16_t field,uint32_t *out)
    {
    uint16_t owner;
    uint8_t kind;
    unsigned i;
    E63ObjectStatus status;
    *out=0u;
    if (!static_int_field(d,field,&owner,&kind))
        return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                         E63_OBJECT_UNTRUSTED;
    status=ensure_static_class(vm,d,owner);
    if (status!=E63_OBJECT_OK) return status;
    for (i=0u;i<vm->heap->static_count;++i)
        if (vm->heap->statics[i].field_id==field &&
            same_image_key(vm->heap->statics[i].image,d))
            {
            const VmStaticField *slot=&vm->heap->statics[i];
            if (slot->kind!=kind ||
                (kind=='Z' && slot->reference>1u))
                return E63_OBJECT_UNTRUSTED;
            *out=slot->reference;
            return E63_OBJECT_OK;
            }
    /* Java default for a primitive static field is zero. */
    return E63_OBJECT_OK;
    }
static uint16_t word(const uint8_t *code,uint32_t pc)
    {return le16(code+(size_t)pc*2u);}
static unsigned insn_width(unsigned op)
    {
    if (op==0x0eu || op==0x0fu || op==0x12u || op==0x01u ||
        op==0x07u || op==0x28u || op==0xb0u) return 1u;
    if (op==0x13u || op==0x15u || op==0x16u || op==0x22u ||
        op==0x38u || op==0x39u || op==0x60u ||
        op==0x52u || op==0x54u || op==0x62u || op==0xd8u ||
        op==0xdau ||
        (op>=0x59u && op<=0x5cu)) return 2u;
    if (op==0x70u || op==0x6fu || op==0x6eu || op==0x71u)
        return 3u;
    return 0u;
    }
static E63ObjectStatus preflight(E63ObjectVm *vm,const VmCode *method,
                                  const uint8_t *code)
    {
    uint32_t pc=0u;
    uint8_t boundaries[(E63_OBJECT_MAX_CODE_WORDS+7u)/8u];
    unsigned returns=0u;
    memset(boundaries,0,sizeof(boundaries));
    while (pc<method->words)
        {
        uint16_t first=word(code,pc);
        unsigned op=first&255u,a=first>>8u,width=insn_width(op);
        if (!width) return E63_OBJECT_UNSUPPORTED;
        if (width>method->words-pc) return E63_OBJECT_UNTRUSTED;
        boundaries[pc>>3u]|=(uint8_t)(1u<<(pc&7u));
        if (op==0x0eu || op==0x0fu)
            {
            if (op==0x0eu)
                {
                if (first!=0x000eu) return E63_OBJECT_UNTRUSTED;
                if (method->result_kind!='V') return E63_OBJECT_UNSUPPORTED;
                }
            else if (method->result_kind!='I' &&
                     method->result_kind!='Z')
                return E63_OBJECT_UNSUPPORTED;
            if (op==0x0fu && a>=method->registers)
                return E63_OBJECT_UNTRUSTED;
            ++returns;
            }
        else if (op==0x28u)
            {if (!(int8_t)a) return E63_OBJECT_UNTRUSTED;}
        else if (op==0x12u)
            {if ((a&15u)>=method->registers) return E63_OBJECT_UNTRUSTED;}
        else if (op==0x13u || op==0x15u || op==0x16u)
            {if (a>=method->registers ||
                 (op==0x16u && a+1u>=method->registers))
                 return E63_OBJECT_UNTRUSTED;}
        else if (op==0x01u || op==0x07u || op==0xb0u)
            {if ((a&15u)>=method->registers ||
                 (a>>4u)>=method->registers)
                 return E63_OBJECT_UNTRUSTED;}
        else if (op==0x22u)
            {
            char descriptor[VM_NAME_BYTES];
            if (a>=method->registers ||
                !type_copy(method->image,word(code,pc+1u),descriptor) ||
                descriptor[0]!='L' ||
                descriptor[strlen(descriptor)-1u]!=';')
                return E63_OBJECT_UNTRUSTED;
            }
        else if (op==0x60u || op==0x62u)
            {
            uint16_t owner;
            uint8_t kind;
            char type[VM_NAME_BYTES];
            if (a>=method->registers ||
                (op==0x60u &&
                 !static_int_field(method->image,word(code,pc+1u),
                                   &owner,&kind)) ||
                (op==0x62u &&
                 !static_ref_field(method->image,word(code,pc+1u),
                                   &owner,type)))
                return E63_OBJECT_UNTRUSTED;
            }
        else if (op==0x52u || op==0x54u)
            {
            const VmField *field=resolve_field(vm,method->image,
                                                word(code,pc+1u));
            if ((a&15u)>=method->registers ||
                (a>>4u)>=method->registers || !field ||
                field->kind!=(op==0x52u ? 'I' : 'R'))
                return E63_OBJECT_UNTRUSTED;
            }
        else if (op==0x38u || op==0x39u)
            {if (a>=method->registers ||
                 !word(code,pc+1u)) return E63_OBJECT_UNTRUSTED;}
        else if (op==0xd8u || op==0xdau)
            {if (a>=method->registers ||
                 (word(code,pc+1u)&255u)>=method->registers)
                 return E63_OBJECT_UNTRUSTED;}
        else if (op>=0x59u && op<=0x5cu)
            {
            const uint32_t id=word(code,pc+1u);
            const VmField *field=resolve_field(vm,method->image,id);
            if ((a&15u)>=method->registers ||
                (a>>4u)>=method->registers ||
                (op==0x5au && (a&15u)+1u>=method->registers) ||
                !field || (op==0x59u && field->kind!='I') ||
                (op==0x5au && field->kind!='J') ||
                (op==0x5bu && field->kind!='R') ||
                (op==0x5cu && field->kind!='Z'))
                return E63_OBJECT_UNTRUSTED;
            }
        else if (op==0x6eu || op==0x71u)
            {
            const unsigned n=a>>4u;
            const uint16_t reglist=word(code,pc+2u);
            uint16_t owner,proto;
            uint32_t name;
            char owner_desc[VM_NAME_BYTES];
            unsigned i;
            if (!n || n>4u || (a&15u)!=0u || method->outs<n ||
                (reglist>>(n*4u))!=0u ||
                !method_reference(method->image,word(code,pc+1u),
                                  &owner,&proto,&name) ||
                !type_copy(method->image,owner,owner_desc) ||
                owner_desc[0]!='L' ||
                owner_desc[strlen(owner_desc)-1u]!=';')
                return E63_OBJECT_UNTRUSTED;
            for (i=0u;i<n;++i)
                if (((reglist>>(i*4u))&15u)>=method->registers)
                    return E63_OBJECT_UNTRUSTED;
            if (op==0x6eu)
                {
                if (n!=1u || !proto_void_zero(method->image,proto) ||
                    string_is(method->image,name,"<init>") ||
                    string_is(method->image,name,"<clinit>"))
                    return E63_OBJECT_UNSUPPORTED;
                }
            else if (!proto_void_register_words(method->image,proto,n))
                return E63_OBJECT_UNSUPPORTED;
            }
        else if (op==0x70u || op==0x6fu)
            {
            const unsigned n=a>>4u;
            const uint16_t reglist=word(code,pc+2u);
            uint16_t owner,proto;
            uint32_t name;
            const VmClass *decl=owned_class(vm,method->image,method->owner);
            unsigned i;
            if (!n || n>VM_MAX_ARGS || (a&15u)!=0u ||
                (reglist>>(n*4u))!=0u || method->outs<n ||
                !method_reference(method->image,word(code,pc+1u),
                                  &owner,&proto,&name))
                return E63_OBJECT_UNTRUSTED;
            for (i=0u;i<n;++i)
                if (((reglist>>(i*4u))&15u)>=method->registers)
                    return E63_OBJECT_UNTRUSTED;
            if (vm_image_slot(vm,method->image)>VM_IMAGE_CORE || !decl ||
                (op==0x70u &&
                 !string_is(method->image,name,"<init>")) ||
                (op==0x6fu &&
                 (owner!=decl->super_type ||
                  !owned_class(vm,method->image,owner) ||
                  !string_is(method->image,name,method->method_name))) ||
                (op==0x6fu && n!=1u) ||
                !proto_void_register_words(method->image,proto,n-1u))
                return E63_OBJECT_UNSUPPORTED;
            if (op==0x70u && owner==decl->super_type)
                {
                if (!type_is(method->image,owner,OBJECT_DESC) &&
                    !owned_class(vm,method->image,owner)) return E63_OBJECT_UNSUPPORTED;
                }
            else if (op==0x70u)
                {
                char name_of_class[VM_NAME_BYTES];
                if (!type_copy(method->image,owner,name_of_class) ||
                    name_of_class[0]!='L' ||
                    name_of_class[strlen(name_of_class)-1u]!=';')
                    return E63_OBJECT_UNSUPPORTED;
                /* Receiver may be a just-allocated object. Runtime must
                 * confirm the heap handle's actual class & constructor. */
                }
            }
        pc+=width;
        }
    if (!returns || (method->result_kind=='V' &&
        (returns!=1u || word(code,method->words-1u)!=0x000eu)))
        return E63_OBJECT_UNSUPPORTED;
    for (pc=0u;pc<method->words;)
        {
        unsigned op=word(code,pc)&255u;
        if (op==0x38u || op==0x39u || op==0x28u)
            {
            int32_t target=(int32_t)pc+
                (op==0x28u ? (int8_t)(word(code,pc)>>8u) :
                             (int16_t)word(code,pc+1u));
            if (target<0 || (uint32_t)target>=method->words ||
                !(boundaries[(uint32_t)target>>3u]&
                          (1u<<((uint32_t)target&7u))))
                return E63_OBJECT_UNTRUSTED;
            }
        pc+=insn_width(op);
        }
    return E63_OBJECT_OK;
    }
static E63ObjectStatus execute(E63ObjectVm *vm,const VmCode *method,
                                unsigned depth,
                                const E63ObjectArg *arguments,unsigned count,
                                uint32_t *result)
    {
    VmRegister registers[E63_OBJECT_MAX_REGISTERS];
    uint8_t *code;
    uint32_t pc=0u;
    E63ObjectStatus status;
    if (result) *result=0u;
    if (depth>VM_MAX_DEPTH || !method || !method->image)
        return E63_OBJECT_BUDGET;
    if (count!=method->arguments || (count && !arguments) ||
        (method->result_kind!='V' && !result))
        return E63_OBJECT_BAD_INPUT;
    code=(uint8_t *)malloc((size_t)method->words*2u);
    if (!code) return E63_OBJECT_NO_MEMORY;
    if (!read_part(method->image,method->offset,code,(size_t)method->words*2u))
        {free(code);return method->image->error;}
    status=preflight(vm,method,code);
    if (status!=E63_OBJECT_OK) {free(code);return status;}
    memset(registers,0,sizeof(registers));
    {
    unsigned i,at=method->registers-method->ins;
    registers[at].bits=vm->handle;
    registers[at++].kind='R';
    for (i=0u;i<count;++i)
        {
        const char *type=arguments[i].type_descriptor;
        const uint64_t bits=arguments[i].bits;
        if (strcmp(type,"J")==0)
            {
            registers[at].bits=(uint32_t)bits; registers[at++].kind='L';
            registers[at].bits=(uint32_t)(bits>>32u);
            registers[at++].kind='H';
            }
        else if (type[0]=='L' || type[0]=='[')
            {registers[at].bits=0u;registers[at++].kind='N';}
        else
            {registers[at].bits=(uint32_t)bits;
             registers[at++].kind='I';}
        }
    if (at!=method->registers)
        {free(code);return E63_OBJECT_UNTRUSTED;}
    }
    while (pc<method->words)
        {
        uint16_t w=word(code,pc);
        unsigned op=w&255u,a=w>>8u,width=insn_width(op);
        if (!vm->heap || ++vm->heap->steps>E63_OBJECT_STEP_BUDGET)
            {status=E63_OBJECT_BUDGET;break;}
        if (op==0x0eu)
            {status=E63_OBJECT_OK;break;}
        if (op==0x0fu)
            {
            if (registers[a].kind!='I' ||
                (method->result_kind=='Z' && registers[a].bits>1u))
                {status=E63_OBJECT_UNTRUSTED;break;}
            *result=registers[a].bits;
            status=E63_OBJECT_OK;break;
            }
        if (op==0x28u)
            {pc=(uint32_t)((int32_t)pc+(int8_t)a);continue;}
        if (op==0x12u || op==0x13u || op==0x15u)
            {
            unsigned dest=op==0x12u ? a&15u : a;
            int32_t v=(op==0x12u) ? (int32_t)(a>>4u)-
                                   ((a&0x80u) ? 16 : 0) :
                                   (int32_t)(int16_t)word(code,pc+1u);
            registers[dest].bits=op==0x15u ?
                 ((uint32_t)(uint16_t)word(code,pc+1u)<<16u) :
                 (uint32_t)v;
            registers[dest].kind='I';
            }
        else if (op==0x16u)
            {
            int32_t value=(int16_t)word(code,pc+1u);
            registers[a].bits=(uint32_t)value;registers[a].kind='L';
            registers[a+1u].bits=value<0 ? 0xffffffffu : 0u;
            registers[a+1u].kind='H';
            }
        else if (op==0x01u || op==0x07u)
            {
            unsigned dest=a&15u,src=a>>4u;
            if ((op==0x01u && registers[src].kind!='I') ||
                (op==0x07u && registers[src].kind!='R' &&
                 registers[src].kind!='N'))
                {status=E63_OBJECT_UNTRUSTED;break;}
            registers[dest]=registers[src];
            }
        else if (op==0xb0u)
            {
            const unsigned dest=a&15u,src=a>>4u;
            if (registers[dest].kind!='I' || registers[src].kind!='I')
                {status=E63_OBJECT_UNTRUSTED;break;}
            registers[dest].bits+=registers[src].bits;
            }
        else if (op==0x22u)
            {
            uint32_t handle=0u;
            status=heap_new_instance(vm,method->image,
                         word(code,pc+1u),&handle);
            if (status!=E63_OBJECT_OK) break;
            registers[a].bits=handle;
            registers[a].kind='R';
            }
        else if (op==0x60u || op==0x62u)
            {
            uint32_t value=0u;
            status=op==0x60u ?
                static_int_get(vm,method->image,word(code,pc+1u),&value) :
                static_object_get(vm,method->image,word(code,pc+1u),&value);
            if (status!=E63_OBJECT_OK) break;
            registers[a].bits=value;
            registers[a].kind=op==0x60u ? 'I' :
                               (value ? 'R' : 'N');
            }
        else if (op==0x52u || op==0x54u)
            {
            unsigned dest=a&15u,obj=a>>4u;
            VmField *f=resolve_field(vm,method->image,word(code,pc+1u));
            if (registers[obj].kind!='R' ||
                registers[obj].bits!=vm->handle || !f)
                {status=E63_OBJECT_UNTRUSTED;break;}
            if (op==0x54u && f->bits &&
                (!heap_type(vm,(uint32_t)f->bits) || f->bits>0xffffffffu))
                {status=E63_OBJECT_UNTRUSTED;break;}
            registers[dest].bits=(uint32_t)f->bits;
            registers[dest].kind=op==0x52u ? 'I' :
                                 f->bits ? 'R' : 'N';
            }
        else if (op==0x38u || op==0x39u)
            {
            if (registers[a].kind!='I' && registers[a].kind!='R' &&
                registers[a].kind!='N')
                {status=E63_OBJECT_UNTRUSTED;break;}
            if ((registers[a].bits==0u)==(op==0x38u))
                {pc=(uint32_t)((int32_t)pc+
                        (int16_t)word(code,pc+1u));continue;}
            }
        else if (op==0xd8u || op==0xdau)
            {
            uint16_t source=word(code,pc+1u);
            const unsigned src=source&255u;
            const uint32_t literal=(uint32_t)(int32_t)(int8_t)(source>>8u);
            if (registers[src].kind!='I')
                {status=E63_OBJECT_UNTRUSTED;break;}
            registers[a].bits=op==0xd8u ? registers[src].bits+literal :
                                           registers[src].bits*literal;
            registers[a].kind='I';
            }
        else if (op>=0x59u && op<=0x5cu)
            {
            unsigned src=a&15u,obj=a>>4u;
            VmField *f=resolve_field(vm,method->image,word(code,pc+1u));
            if (registers[obj].kind!='R' ||
                registers[obj].bits!=vm->handle || !f)
                {status=E63_OBJECT_UNTRUSTED;break;}
            if (op==0x5au)
                {
                if (registers[src].kind!='L' ||
                    registers[src+1u].kind!='H')
                    {status=E63_OBJECT_UNTRUSTED;break;}
                f->bits=(uint64_t)registers[src].bits |
                        ((uint64_t)registers[src+1u].bits<<32u);
                }
            else if (op==0x5bu)
                {
                if (registers[src].kind=='R')
                    {
                    uint8_t row[8];
                    char declared_type[VM_NAME_BYTES];
                    const uint16_t index=word(code,pc+1u);
                    if (!read_part(method->image,
                            method->image->fields_at+(uint64_t)index*8u,
                            row,8u) ||
                        !type_copy(method->image,le16(row+2u),
                                   declared_type) ||
                        !reference_assignable(vm,registers[src].bits,
                                              declared_type))
                        {status=E63_OBJECT_UNSUPPORTED;break;}
                    f->bits=registers[src].bits;
                    }
                else if ((registers[src].kind=='I' ||
                          registers[src].kind=='N') &&
                         registers[src].bits==0u)
                    f->bits=0u;
                else {status=E63_OBJECT_UNSUPPORTED;break;}
                }
            else
                {
                if (registers[src].kind!='I' ||
                    (op==0x5cu && registers[src].bits>1u))
                    {status=E63_OBJECT_UNTRUSTED;break;}
                f->bits=registers[src].bits;
                }
            }
        else if (op==0x6eu || op==0x71u)
            {
            /* A parsed static call in a dead branch is NOT simulated. If
             * actually reached, it must await a real static DEX executor. */
            if (op==0x71u) {status=E63_OBJECT_UNSUPPORTED;break;}
            {
            const uint16_t id=word(code,pc+1u);
            const unsigned receiver_reg=word(code,pc+2u)&15u;
            uint16_t owner,proto;
            uint32_t name;
            char owner_desc[VM_NAME_BYTES],method_name[VM_NAME_BYTES];
            E63ObjectVm *target;
            VmCode callee;
            unsigned i;
            int matches=0;
            const uint32_t ref=registers[receiver_reg].bits;
            if (registers[receiver_reg].kind!='R' || !ref ||
                ref>vm->heap->used ||
                !(target=vm->heap->objects[ref]) || !target->ready ||
                !method_reference(method->image,id,&owner,&proto,&name) ||
                !type_copy(method->image,owner,owner_desc) ||
                !string_copy(method->image,name,method_name))
                {status=E63_OBJECT_UNSUPPORTED;break;}
            for (i=0u;i<target->class_count;++i)
                {
                VmImage *klass_image=vm_image(target,target->classes[i].image);
                if (klass_image &&
                    type_is(klass_image,target->classes[i].type,owner_desc))
                    {matches=1;break;}
                }
            if (!matches) {status=E63_OBJECT_UNSUPPORTED;break;}
            status=E63_OBJECT_NOT_FOUND;
            for (i=0u;i<target->class_count;++i)
                {
                VmImage *klass_image=vm_image(target,target->classes[i].image);
                if (!klass_image) {status=E63_OBJECT_UNTRUSTED;break;}
                status=find_method(klass_image,
                   target->classes[i].class_data,target->classes[i].type,
                   method_name,0,0,0u,&callee);
                if (status!=E63_OBJECT_NOT_FOUND) break;
                }
            if (status!=E63_OBJECT_OK) break;
            status=execute(target,&callee,depth+1u,0,0u,0);
            if (status!=E63_OBJECT_OK) break;
            }
            }
        else if (op==0x70u || op==0x6fu)
            {
            const uint16_t id=word(code,pc+1u);
            const uint16_t reglist=word(code,pc+2u);
            const unsigned arg=reglist&15u;
            const unsigned input_words=a>>4u;
            E63ObjectArg passed[4];
            char types[4][VM_NAME_BYTES];
            unsigned count=0u;
            VmCode parent_ctor;
            uint16_t owner,proto;
            uint32_t name;
            const VmClass *parent;
            const uint32_t receiver=registers[arg].bits;
            if (registers[arg].kind!='R' || !receiver ||
                !method_reference(method->image,id,&owner,&proto,&name))
                {status=E63_OBJECT_UNTRUSTED;break;}
            status=call_arguments(method->image,proto,reglist,input_words,
                                  registers,passed,types,&count);
            if (status!=E63_OBJECT_OK) break;
            if (receiver!=vm->handle)
                {
                E63ObjectVm *child;
                char owner_desc[VM_NAME_BYTES];
                if (op!=0x70u || receiver>vm->heap->used ||
                    !(child=vm->heap->objects[receiver]) || child->ready ||
                    !type_copy(method->image,owner,owner_desc) ||
                    strcmp(child->descriptor,owner_desc)!=0)
                    {status=E63_OBJECT_UNSUPPORTED;break;}
                status=find_method(&child->app,child->classes[0].class_data,
                       child->classes[0].type,"<init>",1,passed,count,
                       &parent_ctor);
                if (status!=E63_OBJECT_OK) break;
                status=execute(child,&parent_ctor,depth+1u,passed,count,0);
                if (status!=E63_OBJECT_OK) break;
                if (!child->super_called)
                    {status=E63_OBJECT_UNTRUSTED;break;}
                child->ready=1u;
                }
            else
                {
                parent=owned_class(vm,method->image,owner);
                if (owner!=owned_class(vm,method->image,method->owner)->super_type)
                    {status=E63_OBJECT_UNSUPPORTED;break;}
                if (type_is(method->image,owner,OBJECT_DESC))
                    {
                    /* This invokes the actual core Object DEX code item. */
                    status=find_method(&vm->core,vm->core_class_data,
                          vm->core_type,"<init>",1,passed,count,
                          &parent_ctor);
                    }
                else if (parent)
                    {
                    VmImage *parent_image=vm_image(vm,parent->image);
                    status=parent_image ?
                        find_method(parent_image,parent->class_data,
                          parent->type,op==0x70u ? "<init>" :
                                  method->method_name,op==0x70u ? 1 : 0,
                                  passed,count,&parent_ctor) :
                        E63_OBJECT_UNTRUSTED;
                    }
                else status=E63_OBJECT_UNSUPPORTED;
                if (status!=E63_OBJECT_OK) break;
                status=execute(vm,&parent_ctor,depth+1u,passed,count,0);
                if (status!=E63_OBJECT_OK) break;
                if (op==0x70u && !parent) vm->super_called=1u;
                }
            }
        else {status=E63_OBJECT_UNSUPPORTED;break;}
        pc+=width;
        }
    if (pc>=method->words) status=E63_OBJECT_UNTRUSTED;
    free(code);
    return status;
    }

typedef struct VmSnapshot {
    VmField *fields;
    VmStaticField statics[E63_OBJECT_MAX_STATIC_FIELDS];
    VmClassInit initialized[VM_INIT_CLASSES];
    unsigned used,static_count,init_count;
} VmSnapshot;
static E63ObjectStatus begin_snapshot(E63ObjectVm *root,VmSnapshot *state)
    {
    unsigned i;
    VmHeap *heap=root->heap;
    memset(state,0,sizeof(*state));
    if (!heap || !heap->used || heap->used>E63_OBJECT_MAX_HEAP_HANDLES)
        return E63_OBJECT_UNTRUSTED;
    state->used=heap->used;
    state->fields=(VmField *)calloc(state->used,sizeof(root->fields));
    if (!state->fields) return E63_OBJECT_NO_MEMORY;
    for (i=1u;i<=state->used;++i)
        if (heap->objects[i])
            memcpy(state->fields+(size_t)(i-1u)*E63_OBJECT_MAX_FIELDS,
                   heap->objects[i]->fields,sizeof(root->fields));
    memcpy(state->statics,heap->statics,sizeof(state->statics));
    memcpy(state->initialized,heap->initialized,sizeof(state->initialized));
    state->static_count=heap->static_count;
    state->init_count=heap->init_count;
    heap->steps=0u;
    return E63_OBJECT_OK;
    }
static void end_snapshot(E63ObjectVm *root,VmSnapshot *state,
                         E63ObjectStatus status)
    {
    unsigned i;
    VmHeap *heap=root->heap;
    if (status!=E63_OBJECT_OK)
        {
        /* Caller can inspect the SAME heap after failure. Transactional
         * rollback covers fields of every object, new handles and statics. */
        for (i=1u;i<=state->used;++i)
            if (heap->objects[i])
                memcpy(heap->objects[i]->fields,
                       state->fields+(size_t)(i-1u)*E63_OBJECT_MAX_FIELDS,
                       sizeof(root->fields));
        for (i=state->used+1u;i<=heap->used;++i)
            {
            if (heap->objects[i]) vm_destroy(heap->objects[i]);
            heap->objects[i]=0;
            memset(heap->array_types[i],0,VM_NAME_BYTES);
            heap->array_lengths[i]=0u;
            }
        heap->used=state->used;
        memcpy(heap->statics,state->statics,sizeof(state->statics));
        memcpy(heap->initialized,state->initialized,
               sizeof(state->initialized));
        heap->static_count=state->static_count;
        heap->init_count=state->init_count;
        }
    free(state->fields);
    memset(state,0,sizeof(*state));
    }

static E63ObjectStatus new_object_internal(
    E63ObjectVm **out,const E63ObjectSource *app_dex,
    const E63BootClass *app_class,const char *class_descriptor,
    const E63ObjectSource *framework_dex,
    const E63BootClass *framework_parent_class,
    const E63ObjectSource *core_dex,
    const E63BootClass *core_object_class,
    const E63ObjectArg *arguments,unsigned argument_count)
    {
    E63ObjectVm *vm;
    E63BootStatus verified;
    E63ObjectStatus status;
    VmCode constructor;
    uint32_t super;
    size_t length;
    if (!out) return E63_OBJECT_BAD_INPUT;
    *out=0;
    if (!app_dex || !core_dex || !app_class || !core_object_class ||
        argument_count>4u || (argument_count && !arguments) ||
        !bounded_name(class_descriptor) ||
        (length=strlen(class_descriptor))<3u ||
        class_descriptor[0]!='L' || class_descriptor[length-1u]!=';' ||
        strcmp(class_descriptor,OBJECT_DESC)==0 ||
        app_class->dex_slot>=E63_BOOT_DEX_SLOTS ||
        core_object_class->dex_slot!=0u ||
        !!framework_dex!=!!framework_parent_class ||
        (framework_parent_class && framework_parent_class->dex_slot!=4u))
        return E63_OBJECT_BAD_INPUT;
    vm=(E63ObjectVm *)calloc(1u,sizeof(*vm));
    if (!vm) return E63_OBJECT_NO_MEMORY;
    vm->heap=(VmHeap *)calloc(1u,sizeof(VmHeap));
    if (!vm->heap) {free(vm);return E63_OBJECT_NO_MEMORY;}
    vm->handle=1u;vm->heap->used=1u;vm->heap->objects[1]=vm;
    memcpy(vm->descriptor,class_descriptor,length+1u);
    vm->has_framework=framework_dex!=0;
    if (!open_image(&vm->app,app_dex) ||
        !open_image(&vm->core,core_dex) ||
        (framework_dex && !open_image(&vm->framework,framework_dex)))
        {status=vm->app.error!=E63_OBJECT_OK ? vm->app.error :
                vm->core.error!=E63_OBJECT_OK ? vm->core.error :
                vm->framework.error;
         vm_destroy(vm);return status;}
    verified=e63_boot_confirm_class(app_class,class_descriptor,
        app_dex->read_at,app_dex->context,app_dex->dex_bytes);
    if (verified!=E63_BOOT_OK)
        {vm_destroy(vm);return verified==E63_BOOT_IO_ERROR ?
                         E63_OBJECT_IO : E63_OBJECT_UNTRUSTED;}
    verified=e63_boot_confirm_class(core_object_class,OBJECT_DESC,
        core_dex->read_at,core_dex->context,core_dex->dex_bytes);
    if (verified!=E63_BOOT_OK)
        {vm_destroy(vm);return verified==E63_BOOT_IO_ERROR ?
                         E63_OBJECT_IO : E63_OBJECT_UNTRUSTED;}
    if (!class_row(&vm->app,app_class,class_descriptor,&vm->classes[0].type,
                   &vm->classes[0].class_data,&vm->classes[0].super_type,
                   &vm->classes[0].interfaces) ||
        !class_row(&vm->core,core_object_class,OBJECT_DESC,&vm->core_type,
                   &vm->core_class_data,&super,0) || super!=0xffffffffu)
        {status=vm->app.error==E63_OBJECT_IO || vm->core.error==E63_OBJECT_IO ?
                 E63_OBJECT_IO : E63_OBJECT_UNSUPPORTED;
         vm_destroy(vm);return status;}
    vm->classes[0].image=VM_IMAGE_APP;
    if (framework_dex)
        {
        char immediate[VM_NAME_BYTES];
        if (!type_copy(&vm->app,vm->classes[0].super_type,immediate) ||
            strcmp(immediate,OBJECT_DESC)==0)
            {vm_destroy(vm);return E63_OBJECT_UNTRUSTED;}
        verified=e63_boot_confirm_class(framework_parent_class,immediate,
            framework_dex->read_at,framework_dex->context,
            framework_dex->dex_bytes);
        if (verified!=E63_BOOT_OK)
            {vm_destroy(vm);return verified==E63_BOOT_IO_ERROR ?
                             E63_OBJECT_IO : E63_OBJECT_UNTRUSTED;}
        }
    vm->class_count=1u;
    while (1)
        {
        VmClass *previous=&vm->classes[vm->class_count-1u];
        VmImage *from=vm_image(vm,previous->image);
        VmClass *parent;
        unsigned i;
        if (!from) {vm_destroy(vm);return E63_OBJECT_UNTRUSTED;}
        if (type_is(from,previous->super_type,OBJECT_DESC)) break;
        if (vm->class_count>=VM_MAX_CLASSES)
            {vm_destroy(vm);return E63_OBJECT_UNSUPPORTED;}
        parent=&vm->classes[vm->class_count];
        if (!find_parent(vm,from,previous->super_type,parent))
            {status=vm->app.error==E63_OBJECT_IO ||
                    vm->framework.error==E63_OBJECT_IO ||
                    vm->core.error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                                   E63_OBJECT_UNSUPPORTED;
             vm_destroy(vm);return status;}
        for (i=0u;i<vm->class_count;++i)
            if (vm->classes[i].type==parent->type &&
                vm->classes[i].image==parent->image)
                {vm_destroy(vm);return E63_OBJECT_UNTRUSTED;}
        ++vm->class_count;
        }
    if (framework_dex &&
        (vm->class_count<2u ||
         vm->classes[1].image!=VM_IMAGE_FRAMEWORK))
        {vm_destroy(vm);return E63_OBJECT_UNTRUSTED;}
    status=E63_OBJECT_OK;
    {
    unsigned i;
    for (i=0u;i<vm->class_count && status==E63_OBJECT_OK;++i)
        status=collect_fields(vm,&vm->classes[i]);
    }
    if (status==E63_OBJECT_OK)
        status=ensure_static_class(vm,&vm->app,
                                   (uint16_t)vm->classes[0].type);
    if (status==E63_OBJECT_OK)
        status=find_method(&vm->app,vm->classes[0].class_data,
                           vm->classes[0].type,"<init>",1,
                           arguments,argument_count,&constructor);
    if (status==E63_OBJECT_OK)
        status=execute(vm,&constructor,0u,arguments,argument_count,0);
    if (status!=E63_OBJECT_OK || !vm->super_called)
        {vm_destroy(vm);return status==E63_OBJECT_OK ?
                          E63_OBJECT_UNTRUSTED : status;}
    vm->ready=1u;*out=vm;
    return E63_OBJECT_OK;
    }
E63ObjectStatus e63_object_vm_new_args(
    E63ObjectVm **out,const E63ObjectSource *app_dex,
    const E63BootClass *app_class,const char *class_descriptor,
    const E63ObjectSource *core_dex,
    const E63BootClass *core_object_class,
    const E63ObjectArg *args,unsigned argument_count)
    {
    return new_object_internal(out,app_dex,app_class,class_descriptor,
                               0,0,core_dex,core_object_class,
                               args,argument_count);
    }
E63ObjectStatus e63_object_vm_new_linked_args(
    E63ObjectVm **out,const E63ObjectSource *app_dex,
    const E63BootClass *app_class,const char *class_descriptor,
    const E63ObjectSource *framework_dex,
    const E63BootClass *framework_parent_class,
    const E63ObjectSource *core_dex,
    const E63BootClass *core_object_class,
    const E63ObjectArg *args,unsigned argument_count)
    {
    return new_object_internal(out,app_dex,app_class,class_descriptor,
                               framework_dex,framework_parent_class,
                               core_dex,core_object_class,args,argument_count);
    }
E63ObjectStatus e63_object_vm_new(
    E63ObjectVm **out,const E63ObjectSource *app_dex,
    const E63BootClass *app_class,const char *class_descriptor,
    const E63ObjectSource *core_dex,
    const E63BootClass *core_object_class)
    {
    return e63_object_vm_new_args(out,app_dex,app_class,class_descriptor,
                                  core_dex,core_object_class,0,0u);
    }
E63ObjectStatus e63_object_vm_field(const E63ObjectVm *vm,
                                     const char *field_name,
                                     const char *type_descriptor,
                                     uint64_t *out)
    {
    unsigned i;
    VmImage *d;
    if (out) *out=0u;
    if (!out || !vm || !vm->ready ||
        !bounded_name(field_name) || !bounded_name(type_descriptor))
        return E63_OBJECT_BAD_INPUT;
    for (i=0u;i<vm->field_count;++i)
        {
        uint8_t raw[8];uint32_t name;
        const VmField *field=&vm->fields[i];
        d=vm_image((E63ObjectVm *)vm,field->image);
        if (!d) return E63_OBJECT_UNTRUSTED;
        if (!read_part(d,d->fields_at+(uint64_t)field->id*8u,raw,8u))
            return d->error;
        name=le32(raw+4u);
        if (le16(raw)!=field->owner || name>=d->strings ||
            le16(raw+2u)>=d->types) return E63_OBJECT_UNTRUSTED;
        if (string_is(d,name,field_name) &&
            type_is(d,le16(raw+2u),type_descriptor))
            {*out=field->bits;return E63_OBJECT_OK;}
        }
    return vm->app.error==E63_OBJECT_IO ||
           vm->framework.error==E63_OBJECT_IO ||
           vm->core.error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                           E63_OBJECT_NOT_FOUND;
    }
E63ObjectStatus e63_object_vm_heap_field(const E63ObjectVm *vm,
                                          uint32_t reference,
                                          const char *field_name,
                                          const char *type_descriptor,
                                          uint64_t *out)
    {
    const E63ObjectVm *object;
    if (out) *out=0u;
    if (!out || !vm || !vm->ready || !vm->heap || !reference ||
        reference>vm->heap->used ||
        !(object=vm->heap->objects[reference]) || !object->ready)
        return E63_OBJECT_BAD_INPUT;
    return e63_object_vm_field(object,field_name,type_descriptor,out);
    }
E63ObjectStatus e63_object_vm_array_length(const E63ObjectVm *vm,
                                             uint32_t reference,
                                             uint32_t *out)
    {
    if (out) *out=0u;
    if (!out || !vm || !vm->ready || !vm->heap || !reference ||
        reference>vm->heap->used ||
        vm->heap->objects[reference] ||
        !vm->heap->array_types[reference][0])
        return E63_OBJECT_BAD_INPUT;
    *out=vm->heap->array_lengths[reference];
    return E63_OBJECT_OK;
    }
E63ObjectStatus e63_object_vm_static_ref(const E63ObjectVm *vm,
                                         const char *owner_descriptor,
                                         const char *field_name,
                                         const char *type_descriptor,
                                         uint32_t *out_reference)
    {
    unsigned i;
    if (out_reference) *out_reference=0u;
    if (!out_reference || !vm || !vm->ready || !vm->heap ||
        !bounded_name(owner_descriptor) || !bounded_name(field_name) ||
        !bounded_name(type_descriptor)) return E63_OBJECT_BAD_INPUT;
    for (i=0u;i<vm->heap->static_count;++i)
        {
        const VmStaticField *slot=&vm->heap->statics[i];
        VmImage *d;
        uint8_t row[8];
        if (same_image_key(slot->image,&vm->app)) d=(VmImage *)&vm->app;
        else if (vm->has_framework &&
                 same_image_key(slot->image,&vm->framework))
            d=(VmImage *)&vm->framework;
        else if (same_image_key(slot->image,&vm->core))
            d=(VmImage *)&vm->core;
        else return E63_OBJECT_UNTRUSTED;
        if (slot->field_id>=d->fields ||
            !read_part(d,d->fields_at+(uint64_t)slot->field_id*8u,row,8u))
            return d->error==E63_OBJECT_IO ? E63_OBJECT_IO :
                                             E63_OBJECT_UNTRUSTED;
        if (!type_is(d,le16(row),owner_descriptor) ||
            !string_is(d,le32(row+4u),field_name) ||
            !type_is(d,le16(row+2u),type_descriptor)) continue;
        if (slot->kind!='R' || !slot->reference ||
            !reference_assignable((E63ObjectVm *)vm,slot->reference,
                                  type_descriptor))
            return E63_OBJECT_UNTRUSTED;
        *out_reference=slot->reference;
        return E63_OBJECT_OK;
        }
    return E63_OBJECT_NOT_FOUND; /* no fabricated/uninitialized static */
    }
E63ObjectStatus e63_object_vm_ref_type(const E63ObjectVm *vm,
                                       uint32_t reference,
                                       char *out,size_t out_bytes)
    {
    const char *type;
    size_t length;
    if (out && out_bytes) out[0]=0;
    if (!vm || !vm->ready || !vm->heap || !out || !out_bytes ||
        !(type=heap_type(vm,reference))) return E63_OBJECT_BAD_INPUT;
    length=strlen(type);
    if (length>=out_bytes) return E63_OBJECT_BAD_INPUT;
    memcpy(out,type,length+1u);
    return E63_OBJECT_OK;
    }
E63ObjectStatus e63_object_vm_call_void_args(E63ObjectVm *vm,
                              uint32_t reference,const char *method_name,
                              const E63ObjectArg *arguments,
                              unsigned argument_count)
    {
    E63ObjectVm *target;
    VmCode method;
    VmSnapshot state;
    E63ObjectStatus status=E63_OBJECT_NOT_FOUND;
    unsigned i;
    if (!vm || !vm->ready || !vm->heap || !bounded_name(method_name) ||
        strcmp(method_name,"<init>")==0 ||
        strcmp(method_name,"<clinit>")==0 ||
        argument_count>4u || (argument_count && !arguments) ||
        reference>vm->heap->used ||
        !(target=vm->heap->objects[reference ? reference : 1u]) ||
        !target->ready)
        return E63_OBJECT_BAD_INPUT;
    for (i=0u;i<target->class_count;++i)
        {
        VmImage *d=vm_image(target,target->classes[i].image);
        if (!d) return E63_OBJECT_UNTRUSTED;
        status=find_method(d,target->classes[i].class_data,
                           target->classes[i].type,method_name,0,
                           arguments,argument_count,&method);
        if (status!=E63_OBJECT_NOT_FOUND) break;
        }
    if (status!=E63_OBJECT_OK) return status;
    status=begin_snapshot(vm,&state);
    if (status!=E63_OBJECT_OK) return status;
    status=execute(target,&method,0u,arguments,argument_count,0);
    end_snapshot(vm,&state,status);
    return status;
    }
E63ObjectStatus e63_object_vm_call_void(E63ObjectVm *vm,
                                        const char *method_name)
    {
    return e63_object_vm_call_void_args(vm,0u,method_name,0,0u);
    }
E63ObjectStatus e63_object_vm_call_int(E63ObjectVm *vm,
                                        uint32_t reference,
                                        const char *method_name,
                                        const char *return_type,
                                        int32_t *out)
    {
    E63ObjectVm *target;
    VmCode method;
    VmSnapshot state;
    E63ObjectStatus status=E63_OBJECT_NOT_FOUND;
    uint32_t result=0u;
    unsigned i;
    if (out) *out=0;
    if (!out || !vm || !vm->ready || !vm->heap ||
        !bounded_name(method_name) || !bounded_name(return_type) ||
        (strcmp(return_type,"I")!=0 && strcmp(return_type,"Z")!=0) ||
        strcmp(method_name,"<init>")==0 ||
        strcmp(method_name,"<clinit>")==0 ||
        reference>vm->heap->used ||
        !(target=vm->heap->objects[reference ? reference : 1u]) ||
        !target->ready)
        return E63_OBJECT_BAD_INPUT;
    for (i=0u;i<target->class_count;++i)
        {
        VmImage *d=vm_image(target,target->classes[i].image);
        if (!d) return E63_OBJECT_UNTRUSTED;
        status=find_method_typed(d,
            target->classes[i].class_data,target->classes[i].type,
            method_name,0,0,0u,return_type,&method);
        if (status!=E63_OBJECT_NOT_FOUND) break;
        }
    if (status!=E63_OBJECT_OK) return status;
    status=begin_snapshot(vm,&state);
    if (status!=E63_OBJECT_OK) return status;
    status=execute(target,&method,0u,0,0u,&result);
    end_snapshot(vm,&state,status);
    if (status==E63_OBJECT_OK) *out=(int32_t)result;
    return status;
    }
void e63_object_vm_free(E63ObjectVm *vm)
    {
    vm_destroy(vm);
    }
const char *e63_object_vm_status(E63ObjectStatus status)
    {
    switch(status)
        {
        case E63_OBJECT_OK:return "bounded DEX object operation completed";
        case E63_OBJECT_BAD_INPUT:return "invalid object VM request";
        case E63_OBJECT_UNTRUSTED:return "corrupt DEX/class/field metadata";
        case E63_OBJECT_NOT_FOUND:return "method or field not in verified DEX";
        case E63_OBJECT_UNSUPPORTED:return "unsupported Java/DEX semantics";
        case E63_OBJECT_IO:return "verified DEX read failed";
        case E63_OBJECT_NO_MEMORY:return "small method/object allocation failed";
        case E63_OBJECT_BUDGET:return "DEX instruction/depth budget exceeded";
        default:return "unknown AOSP object VM status";
        }
    }
