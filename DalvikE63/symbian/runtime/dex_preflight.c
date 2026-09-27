#include "dex_preflight.h"
#include <string.h>

static uint16_t rd16(const uint8_t *p)
    { return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8)); }
static uint32_t rd32(const uint8_t *p)
    { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
             ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
static int inside(size_t limit, uint64_t offset, uint64_t bytes)
    { return offset <= limit && bytes <= limit - offset; }

static uint32_t adler32_dex(const uint8_t *bytes, size_t length)
    {
    uint32_t a=1, b=0;
    size_t i;
    for (i=0; i<length; ++i)
        {
        a += bytes[i];
        if (a>=65521u) a -= 65521u;
        b += a;
        if (b>=65521u) b -= 65521u;
        }
    return (b << 16) | a;
    }

static int table(const E63DexView *v, uint32_t count, uint32_t offset,
                 uint32_t entry_size, uint32_t maximum)
    {
    if (count>maximum) return 0;
    if (!count) return offset==0;
    return offset>=0x70u && (offset & 3u)==0 &&
           inside(v->size,offset,(uint64_t)count * entry_size);
    }

static int uleb(const E63DexView *v, size_t *at, uint32_t *out)
    {
    unsigned shift;
    uint32_t result=0;
    for (shift=0; shift<=28; shift+=7)
        {
        uint8_t b;
        if (!inside(v->size,*at,1)) return 0;
        b=v->data[(*at)++];
        if (shift==28 && (b & 0x70u)) return 0;
        result |= (uint32_t)(b & 127u) << shift;
        if (!(b & 128u)) { *out=result; return 1; }
        }
    return 0;
    }

/* A DEX string is a sequence of UTF-16 code units encoded in *modified*
 * UTF-8, terminated by a raw 00. Decode one unit (including surrogate code
 * units) without ever reading beyond the bounded DEX buffer. Reject normal
 * four-byte UTF-8 and all noncanonical encodings except C0 80 for U+0000.
 */
static int mutf_unit(const E63DexView *v, size_t *at, uint16_t *unit)
    {
    uint8_t first, second, third;
    size_t p=*at;
    if (!inside(v->size,p,1)) return 0;
    first=v->data[p];
    if (first>=1u && first<=0x7fu)
        { *unit=first;*at=p+1u;return 1; }
    if (!inside(v->size,p,2)) return 0;
    second=v->data[p+1u];
    if (first==0xc0u && second==0x80u)
        { *unit=0;*at=p+2u;return 1; }
    if (first>=0xc2u && first<=0xdfu && (second & 0xc0u)==0x80u)
        {
        *unit=(uint16_t)(((first & 31u)<<6) | (second & 63u));
        *at=p+2u;return 1;
        }
    if (first<0xe0u || first>0xefu || !inside(v->size,p,3)) return 0;
    third=v->data[p+2u];
    if ((second & 0xc0u)!=0x80u || (third & 0xc0u)!=0x80u ||
        (first==0xe0u && second<0xa0u)) return 0;
    *unit=(uint16_t)(((first & 15u)<<12) |
                     ((second & 63u)<<6) | (third & 63u));
    *at=p+3u;
    return 1;
    }

static int string_at(const E63DexView *v, uint32_t index,
                     const uint8_t **text, size_t *length)
    {
    size_t at, begin;
    uint32_t units, j;
    uint16_t value;
    if (index>=v->strings_count) return 0;
    at=rd32(v->data+v->strings_off+(size_t)index*4u);
    if (at<v->data_off || !inside(v->size,at,1) ||
        !uleb(v,&at,&units) || units>65535u) return 0;
    begin=at;
    for (j=0;j<units;++j)
        if (!mutf_unit(v,&at,&value)) return 0;
    if (!inside(v->size,at,1) || v->data[at]!=0 || at-begin>196605u)
        return 0;
    *text=v->data+begin;
    *length=at-begin;
    return 1;
    }

/* Convert valid MUTF-8 to Unicode scalar UTF-8. The preflight accepts lone
 * UTF-16 surrogates as legal Java String data; the UTF-8 UI/service bridge
 * cannot represent those, so conversion fails closed. `used` is the number
 * of payload BYTES (possibly including embedded U+0000), excluding the final
 * C terminator. Callers using a C string must reject an embedded NUL.
 */
int e63_dex_string_utf8(const E63DexView *v, uint32_t index,
                        char *dst, size_t capacity, size_t *used)
    {
    const uint8_t *raw;
    size_t encoded, at, end, count=0;
    uint32_t cp;
    uint16_t unit, low;
    if (used) *used=0;
    if (!v || !v->data || !dst || !capacity ||
        !string_at(v,index,&raw,&encoded)) return 0;
    at=(size_t)(raw-v->data);end=at+encoded;
    while (at<end)
        {
        size_t width;
        if (!mutf_unit(v,&at,&unit)) return 0;
        cp=unit;
        if (unit>=0xd800u && unit<=0xdbffu)
            {
            if (at>=end || !mutf_unit(v,&at,&low) ||
                low<0xdc00u || low>0xdfffu) return 0;
            cp=0x10000u+(((uint32_t)unit-0xd800u)<<10)+low-0xdc00u;
            }
        else if (unit>=0xdc00u && unit<=0xdfffu) return 0;
        width=cp<0x80u ? 1u : cp<0x800u ? 2u : cp<0x10000u ? 3u : 4u;
        if (width>=capacity-count) return 0;
        if (width==1u) dst[count]=(char)cp;
        else if (width==2u)
            {dst[count]=(char)(0xc0u | (cp>>6));
             dst[count+1u]=(char)(0x80u | (cp & 63u));}
        else if (width==3u)
            {dst[count]=(char)(0xe0u | (cp>>12));
             dst[count+1u]=(char)(0x80u | ((cp>>6) & 63u));
             dst[count+2u]=(char)(0x80u | (cp & 63u));}
        else
            {dst[count]=(char)(0xf0u | (cp>>18));
             dst[count+1u]=(char)(0x80u | ((cp>>12) & 63u));
             dst[count+2u]=(char)(0x80u | ((cp>>6) & 63u));
             dst[count+3u]=(char)(0x80u | (cp & 63u));}
        count+=width;
        }
    dst[count]=0;
    if (used) *used=count;
    return 1;
    }

static int string_equals(const E63DexView *v, uint32_t index, const char *text)
    {
    const uint8_t *actual;
    size_t length, wanted=strlen(text);
    return string_at(v,index,&actual,&length) && length==wanted &&
           memcmp(actual,text,wanted)==0;
    }

static int class_matches(const E63DexView *v, uint32_t class_index,
                         const char *descriptor)
    {
    uint32_t string_index;
    if (class_index>=v->types_count) return 0;
    string_index=rd32(v->data+v->types_off+(size_t)class_index*4u);
    return string_equals(v,string_index,descriptor);
    }

static int type_equals(const E63DexView *v, uint32_t type_index,
                       const char *descriptor)
    {
    if (type_index>=v->types_count) return 0;
    return string_equals(v,rd32(v->data+v->types_off+(size_t)type_index*4u),
                         descriptor);
    }

static int proto_equals(const E63DexView *v, uint32_t proto_index,
                        const char *prototype)
    {
    const uint8_t *item;
    size_t remaining, pos=0;
    uint32_t params, n=0, i, result_type;
    if (proto_index>=v->protos_count || !prototype || prototype[0]!='(')
        return 0;
    remaining=strlen(prototype);
    if (remaining<3 || remaining>512) return 0;
    item=v->data+v->protos_off+(size_t)proto_index*12u;
    params=rd32(item+8);
    result_type=rd32(item+4);
    if (result_type>=v->types_count || (params &&
        (params<v->data_off || !inside(v->size,params,4)))) return 0;
    if (params)
        {
        n=rd32(v->data+params);
        if (n>256 || !inside(v->size,(uint64_t)params+4u,(uint64_t)n*2u)) return 0;
        }
    pos=1;
    for (i=0; i<n; ++i)
        {
        uint16_t idx=rd16(v->data+params+4u+(size_t)i*2u);
        const uint8_t *text;
        size_t length;
        if (idx>=v->types_count || !string_at(v,rd32(v->data+v->types_off+(size_t)idx*4u),
                                              &text,&length) ||
            length>remaining-pos || memcmp(prototype+pos,text,length)!=0) return 0;
        pos+=length;
        }
    if (pos>=remaining || prototype[pos++]!=')') return 0;
    {
    const uint8_t *text;
    size_t length;
    if (!string_at(v,rd32(v->data+v->types_off+(size_t)result_type*4u),
                   &text,&length) || length!=remaining-pos) return 0;
    return memcmp(prototype+pos,text,length)==0;
    }
    }

static int valid_code(const E63DexView *v, uint32_t offset)
    {
    uint32_t insns;
    if (!offset || (offset & 3u) || offset<v->data_off ||
        !inside(v->size,offset,16)) return 0;
    if (rd16(v->data+offset+2)>rd16(v->data+offset)) return 0; /* ins > registers */
    insns=rd32(v->data+offset+12);
    return insns>0 && inside(v->size,(uint64_t)offset+16u,(uint64_t)insns*2u);
    }

/* -1 = malformed, 0 = valid and not found, >0 = executable definition count.
 * Both direct and virtual method index diffs reset to zero per DEX format.
 */
static int walk(const E63DexView *v, const char *owner, const char *name,
                const char *prototype, uint32_t requested_id, E63DexMethod *found)
    {
    uint32_t c;
    int count=0;
    for (c=0; c<v->classes_count; ++c)
        {
        const uint8_t *cls=v->data+v->classes_off+(size_t)c*32u;
        uint32_t class_index=rd32(cls);
        uint32_t class_data=rd32(cls+24);
        size_t at;
        uint32_t fields_static, fields_instance, direct, virtual, sections[4], section;
        if (class_index>=v->types_count) return -1;
        if (!class_data) continue;
        if (class_data<v->data_off || !inside(v->size,class_data,1)) return -1;
        at=class_data;
        if (!uleb(v,&at,&fields_static) || !uleb(v,&at,&fields_instance) ||
            !uleb(v,&at,&direct) || !uleb(v,&at,&virtual)) return -1;
        if (fields_static>v->fields_count || fields_instance>v->fields_count ||
            direct>v->methods_count || virtual>v->methods_count) return -1;
        sections[0]=fields_static;sections[1]=fields_instance;
        sections[2]=direct;sections[3]=virtual;
        for (section=0; section<4; ++section)
            {
            uint32_t j, delta, flags, method_index=0;
            for (j=0; j<sections[section]; ++j)
                {
                uint32_t code=0;
                if (!uleb(v,&at,&delta) || !uleb(v,&at,&flags)) return -1;
                (void)flags;
                if (section<2)
                    {
                    if (delta>v->fields_count ||
                        method_index>v->fields_count-delta) return -1;
                    method_index+=delta;
                    if (method_index>=v->fields_count ||
                        rd16(v->data+v->fields_off+(size_t)method_index*8u)
                        !=class_index) return -1;
                    continue;
                    }
                if (!uleb(v,&at,&code) ||
                    delta>v->methods_count || method_index>v->methods_count-delta)
                    return -1;
                method_index+=delta;
                if (method_index>=v->methods_count) return -1;
                if (rd16(v->data+v->methods_off+(size_t)method_index*8u)
                    !=class_index) return -1;
                if (code)
                    {
                    const uint8_t *id=v->data+v->methods_off+(size_t)method_index*8u;
                    uint32_t name_idx=rd32(id+4u);
                    if (!valid_code(v,code)) return -1;
                    if ((requested_id==UINT32_MAX || method_index==requested_id) &&
                        (!owner || class_matches(v,class_index,owner)) &&
                        (!name || string_equals(v,name_idx,name)) &&
                        (!prototype || proto_equals(v,rd16(id+2u),prototype)))
                        {
                        ++count;
                        if (found)
                            {
                            const uint8_t *header=v->data+code;
                            found->method_index=method_index;
                            found->class_index=class_index;
                            found->code_off=code;
                            found->registers=rd16(header);
                            found->ins=rd16(header+2u);
                            found->outs=rd16(header+4u);
                            found->tries=rd16(header+6u);
                            found->words_count=rd32(header+12u);
                            found->words_le=header+16u;
                            }
                        }
                    }
                }
            }
        }
    return count;
    }

E63DexStatus e63_dex_open(const uint8_t *bytes, size_t count, E63DexView *out)
    {
    E63DexView v;
    uint32_t i;
    const uint8_t *text;
    size_t length;
    if (!out) return E63_DEX_BAD_INPUT;
    memset(out,0,sizeof(*out));
    if (!bytes || count<0x70u || count>E63_DEX_MAX_BYTES) return E63_DEX_BAD_INPUT;
    if ((memcmp(bytes,"dex\n035\0",8)!=0 &&
         memcmp(bytes,"dex\n036\0",8)!=0) || rd32(bytes+0x20)!=count ||
        rd32(bytes+0x24)!=0x70u || rd32(bytes+0x28)!=0x12345678u)
        return E63_DEX_BAD_HEADER;
    if (adler32_dex(bytes+12,count-12)!=rd32(bytes+8)) return E63_DEX_BAD_CHECKSUM;
    memset(&v,0,sizeof(v));
    v.data=bytes;v.size=count;
    v.strings_count=rd32(bytes+0x38);v.strings_off=rd32(bytes+0x3c);
    v.types_count=rd32(bytes+0x40);v.types_off=rd32(bytes+0x44);
    v.protos_count=rd32(bytes+0x48);v.protos_off=rd32(bytes+0x4c);
    v.fields_count=rd32(bytes+0x50);v.fields_off=rd32(bytes+0x54);
    v.methods_count=rd32(bytes+0x58);v.methods_off=rd32(bytes+0x5c);
    v.classes_count=rd32(bytes+0x60);v.classes_off=rd32(bytes+0x64);
    v.data_count=rd32(bytes+0x68);v.data_off=rd32(bytes+0x6c);
    if (!table(&v,v.strings_count,v.strings_off,4,100000) ||
        !table(&v,v.types_count,v.types_off,4,65535) ||
        !table(&v,v.protos_count,v.protos_off,12,65535) ||
        !table(&v,v.fields_count,v.fields_off,8,65535) ||
        !table(&v,v.methods_count,v.methods_off,8,65535) ||
        !table(&v,v.classes_count,v.classes_off,32,10000) ||
        !inside(count,v.data_off,v.data_count) || v.data_off<0x70u ||
        v.data_count==0 || (v.data_off & 3u)) return E63_DEX_BAD_TABLE;
    for (i=0; i<v.strings_count; ++i)
        if (!string_at(&v,i,&text,&length)) return E63_DEX_BAD_ENCODING;
    for (i=0; i<v.types_count; ++i)
        if (rd32(bytes+v.types_off+(size_t)i*4u)>=v.strings_count)
            return E63_DEX_BAD_TABLE;
    for (i=0; i<v.protos_count; ++i)
        {
        const uint8_t *proto=bytes+v.protos_off+(size_t)i*12u;
        uint32_t params=rd32(proto+8u), n=0, j;
        if (rd32(proto)>=v.strings_count || rd32(proto+4u)>=v.types_count)
            return E63_DEX_BAD_TABLE;
        if (params)
            {
            if (params<v.data_off || (params & 3u) || !inside(count,params,4))
                return E63_DEX_BAD_TABLE;
            n=rd32(bytes+params);
            if (n>256 || !inside(count,(uint64_t)params+4u,(uint64_t)n*2u))
                return E63_DEX_BAD_TABLE;
            for (j=0; j<n; ++j)
                if (rd16(bytes+params+4u+(size_t)j*2u)>=v.types_count)
                    return E63_DEX_BAD_TABLE;
            }
        }
    for (i=0; i<v.methods_count; ++i)
        {
        const uint8_t *id=bytes+v.methods_off+(size_t)i*8u;
        if (rd16(id)>=v.types_count || rd16(id+2)>=v.protos_count ||
            rd32(id+4)>=v.strings_count) return E63_DEX_BAD_TABLE;
        }
    if (walk(&v,0,0,0,UINT32_MAX,0)<0) return E63_DEX_BAD_ENCODING;
    *out=v;
    return E63_DEX_OK;
    }

int e63_dex_has_code(const E63DexView *view, const char *class_descriptor,
                     const char *method_name)
    {
    if (!view || !view->data || !class_descriptor || !method_name) return -1;
    { int count=walk(view,class_descriptor,method_name,0,UINT32_MAX,0);
      return count<0 ? -1 : count>0; }
    }

int e63_dex_count_code(const E63DexView *view)
    {
    if (!view || !view->data) return -1;
    return walk(view,0,0,0,UINT32_MAX,0);
    }

int e63_dex_find_code(const E63DexView *view, const char *class_descriptor,
                      const char *method_name, const char *prototype,
                      E63DexMethod *out)
    {
    int count;
    if (!out) return -1;
    memset(out,0,sizeof(*out));
    if (!view || !view->data || !class_descriptor || !method_name || !prototype)
        return -1;
    count=walk(view,class_descriptor,method_name,prototype,UINT32_MAX,out);
    if (count!=1) { memset(out,0,sizeof(*out));return count==0 ? 0 : -1; }
    return 1;
    }

int e63_dex_find_code_id(const E63DexView *view, uint32_t method_index,
                         E63DexMethod *out)
    {
    int count;
    if (!out) return -1;
    memset(out,0,sizeof(*out));
    if (!view || !view->data || method_index>=view->methods_count) return -1;
    count=walk(view,0,0,0,method_index,out);
    if (count!=1) { memset(out,0,sizeof(*out));return count==0 ? 0 : -1; }
    return 1;
    }

int e63_dex_field_id(const E63DexView *view, const char *class_descriptor,
                     const char *field_name, const char *type_descriptor)
    {
    uint32_t i;
    int found=-1;
    if (!view || !view->data || !class_descriptor || !field_name ||
        !type_descriptor) return -1;
    for (i=0; i<view->fields_count; ++i)
        {
        const uint8_t *entry=view->data+view->fields_off+(size_t)i*8u;
        if (class_matches(view,rd16(entry),class_descriptor) &&
            string_equals(view,rd32(entry+4u),field_name) &&
            type_equals(view,rd16(entry+2u),type_descriptor))
            { if (found>=0) return -1;found=(int)i; }
        }
    return found;
    }

int e63_dex_class_index(const E63DexView *view, const char *class_descriptor)
    {
    uint32_t i;
    if (!view || !view->data || !class_descriptor) return -1;
    for (i=0; i<view->classes_count; ++i)
        {
        uint32_t idx=rd32(view->data+view->classes_off+(size_t)i*32u);
        if (class_matches(view,idx,class_descriptor)) return (int)idx;
        }
    return -1;
    }

int e63_dex_super_is(const E63DexView *view, const char *child,
                     const char *parent)
    {
    uint32_t i;
    if (!view || !view->data || !child || !parent) return 0;
    for (i=0;i<view->classes_count;++i)
        {
        const uint8_t *cls=view->data+view->classes_off+(size_t)i*32u;
        if (class_matches(view,rd32(cls),child))
            return type_equals(view,rd32(cls+8u),parent);
        }
    return 0;
    }

int e63_dex_field_is(const E63DexView *view, uint32_t index,
                     uint32_t owning_class, const char *type_descriptor)
    {
    const uint8_t *item;
    if (!view || !view->data || index>=view->fields_count || !type_descriptor)
        return 0;
    item=view->data+view->fields_off+(size_t)index*8u;
    return rd16(item)==owning_class && type_equals(view,rd16(item+2u),type_descriptor);
    }

int e63_dex_method_ref_is(const E63DexView *view, uint32_t index,
                          const char *class_descriptor, const char *method_name,
                          const char *prototype)
    {
    const uint8_t *item;
    if (!view || !view->data || index>=view->methods_count ||
        !class_descriptor || !method_name || !prototype) return 0;
    item=view->data+view->methods_off+(size_t)index*8u;
    return type_equals(view,rd16(item),class_descriptor) &&
           string_equals(view,rd32(item+4u),method_name) &&
           proto_equals(view,rd16(item+2u),prototype);
    }

const char *e63_dex_status(E63DexStatus status)
    {
    switch (status)
        {
        case E63_DEX_OK:return "ok";
        case E63_DEX_BAD_INPUT:return "bad input/size";
        case E63_DEX_BAD_HEADER:return "not a dex035 header";
        case E63_DEX_BAD_CHECKSUM:return "bad DEX checksum";
        case E63_DEX_BAD_TABLE:return "bad DEX section table";
        case E63_DEX_BAD_ENCODING:return "bad DEX string/class/code encoding";
        default:return "unknown error";
        }
    }
