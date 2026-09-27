#include "boot_method.h"
#include <stdlib.h>
#include <string.h>

/* RFile's read_at adapter accepts at most 268 bytes. All offsets stay inside
 * an authenticated <=32 MiB DEX; do not ever copy the entire image into RAM. */
typedef struct DexDisk {
    E63BootReadAt read_at;
    void *context;
    uint32_t bytes, data_at, data_end;
    uint32_t strings, strings_at, types, types_at;
    uint32_t protos, protos_at, fields, fields_at;
    uint32_t methods, methods_at, classes, classes_at;
    int io_error;
} DexDisk;

static uint16_t le16(const uint8_t *p)
    {return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1]<<8u));}
static uint32_t le32(const uint8_t *p)
    {return (uint32_t)p[0] | ((uint32_t)p[1]<<8u) |
            ((uint32_t)p[2]<<16u) | ((uint32_t)p[3]<<24u);}
static int32_t signed8(uint8_t b)
    {return (b&0x80u) ? (int32_t)b-256 : (int32_t)b;}
static int32_t signed16(uint16_t b)
    {return (b&0x8000u) ? (int32_t)b-65536 : (int32_t)b;}
static int32_t signed32(uint32_t b)
    {return (int32_t)((b&0x80000000u) ? (int64_t)b-0x100000000LL : b);}
static int within(uint64_t at,uint64_t length,uint64_t end)
    {return at<=end && length<=end-at;}
static int disk_read(DexDisk *d,uint64_t at,uint8_t *dst,size_t size)
    {
    size_t copied=0;
    if (!size || !dst || !within(at,size,d->bytes)) return 0;
    while (copied<size)
        {
        size_t block=size-copied;
        if (block>256u) block=256u;
        if (!d->read_at(d->context,(uint32_t)(at+copied),dst+copied,block))
            {d->io_error=1;return 0;}
        copied+=block;
        }
    return 1;
    }
static int get32(DexDisk *d,uint64_t at,uint32_t *out)
    {
    uint8_t buf[4];
    if (!disk_read(d,at,buf,sizeof(buf))) return 0;
    *out=le32(buf);return 1;
    }
static int get16(DexDisk *d,uint64_t at,uint16_t *out)
    {
    uint8_t buf[2];
    if (!disk_read(d,at,buf,sizeof(buf))) return 0;
    *out=le16(buf);return 1;
    }
static int table(DexDisk *d,uint32_t count,uint32_t offset,
                 uint32_t stride,uint32_t limit)
    {
    if (count>limit) return 0;
    if (!count) return offset==0u;
    return offset>=112u && (offset&3u)==0u &&
           within(offset,(uint64_t)count*stride,d->bytes);
    }
static int header(DexDisk *d,E63BootReadAt read_at,void *ctx,size_t size)
    {
    uint8_t raw[112];
    memset(d,0,sizeof(*d));
    d->read_at=read_at;d->context=ctx;d->bytes=(uint32_t)size;
    if (!disk_read(d,0u,raw,sizeof(raw))) return 0;
    if ((memcmp(raw,"dex\n035\0",8u)!=0 &&
         memcmp(raw,"dex\n036\0",8u)!=0) ||
        le32(raw+32u)!=size || le32(raw+36u)!=112u ||
        le32(raw+40u)!=0x12345678u) return 0;
    d->strings=le32(raw+56u); d->strings_at=le32(raw+60u);
    d->types=le32(raw+64u); d->types_at=le32(raw+68u);
    d->protos=le32(raw+72u); d->protos_at=le32(raw+76u);
    d->fields=le32(raw+80u); d->fields_at=le32(raw+84u);
    d->methods=le32(raw+88u); d->methods_at=le32(raw+92u);
    d->classes=le32(raw+96u); d->classes_at=le32(raw+100u);
    d->data_at=le32(raw+108u);
    if (!table(d,d->strings,d->strings_at,4u,1000000u) ||
        !table(d,d->types,d->types_at,4u,65535u) ||
        !table(d,d->protos,d->protos_at,12u,65535u) ||
        !table(d,d->fields,d->fields_at,8u,65535u) ||
        !table(d,d->methods,d->methods_at,8u,65535u) ||
        !table(d,d->classes,d->classes_at,32u,10000u) ||
        d->data_at<112u ||
        !within(d->data_at,le32(raw+104u),d->bytes)) return 0;
    d->data_end=d->data_at+le32(raw+104u);
    return d->data_end>d->data_at;
    }
/* Only the ASCII target identifier is copied. Nonmatching MUTF-8 strings
 * aren't interpreted as names and can never match the caller's ASCII name. */
static int uleb(DexDisk *d,uint32_t *at,uint32_t *value)
    {
    unsigned i;
    uint32_t v=0;
    for (i=0u;i<5u;++i)
        {
        uint8_t b;
        if (!within(*at,1u,d->data_end) || *at<d->data_at ||
            !disk_read(d,*at,&b,1u) || (i==4u && (b&0xf0u))) return 0;
        ++*at;
        v|=(uint32_t)(b&127u)<<(7u*i);
        if (!(b&128u)) {*value=v;return 1;}
        }
    return 0;
    }
static int string_is(DexDisk *d,uint32_t index,const char *target)
    {
    uint32_t at,units;
    size_t size=strlen(target);
    uint8_t raw[256];
    if (!size || size>255u || index>=d->strings ||
        !get32(d,d->strings_at+(uint64_t)index*4u,&at) ||
        at<d->data_at || at>=d->data_end ||
        !uleb(d,&at,&units) || units!=size ||
        !within(at,size+1u,d->data_end) ||
        !disk_read(d,at,raw,size+1u)) return 0;
    return raw[size]==0u && memcmp(raw,target,size)==0;
    }
static int type_is(DexDisk *d,uint32_t type,const char *descriptor)
    {
    uint32_t str;
    return type<d->types &&
           get32(d,d->types_at+(uint64_t)type*4u,&str) &&
           string_is(d,str,descriptor);
    }
static int proto_is(DexDisk *d,uint16_t index,unsigned count)
    {
    uint8_t raw[12];
    uint32_t params;
    unsigned i;
    if (index>=d->protos ||
        !disk_read(d,d->protos_at+(uint64_t)index*12u,raw,sizeof(raw)) ||
        !type_is(d,le32(raw+4u),"I")) return 0;
    params=le32(raw+8u);
    if (!count) return params==0u;
    if (params<d->data_at || (params&3u)!=0u ||
        !within(params,4u+(uint64_t)count*2u,d->data_end)) return 0;
    {
    uint32_t size;
    if (!get32(d,params,&size) || size!=count) return 0;
    }
    for (i=0u;i<count;++i)
        {
        uint16_t type;
        if (!get16(d,params+4u+i*2u,&type) || !type_is(d,type,"I"))
            return 0;
        }
    return 1;
    }

static uint16_t word(const uint8_t *code,uint32_t pc)
    {return le16(code+(size_t)pc*2u);}
static unsigned width(unsigned op)
    {
    if (op==0x00u || op==0x01u || op==0x0fu || op==0x12u || op==0x28u ||
        (op>=0xb0u && op<=0xbau)) return 1u;
    if (op==0x02u || op==0x13u || op==0x15u || op==0x29u ||
        (op>=0x32u && op<=0x3du) ||
        (op>=0x90u && op<=0x9au) ||
        (op>=0xd0u && op<=0xd7u) ||
        (op>=0xd8u && op<=0xe2u)) return 2u;
    if (op==0x03u || op==0x14u || op==0x2au) return 3u;
    return 0u;
    }
static int reg_ok(unsigned reg,unsigned regs)
    {return reg<regs;}
static int branch_target(const uint8_t *code,uint32_t pc,unsigned op,
                         uint32_t words,const uint8_t *starts)
    {
    uint16_t first=word(code,pc);
    int64_t delta=(op==0x28u) ? signed8((uint8_t)(first>>8u)) :
                  (op==0x2au) ? signed32((uint32_t)word(code,pc+1u) |
                                         ((uint32_t)word(code,pc+2u)<<16u)) :
                                 signed16(word(code,pc+1u));
    int64_t target=(int64_t)pc+delta;
    return target>=0 && target<(int64_t)words && starts[(size_t)target];
    }
/* Preflight ENTIRE method; unsupported/unreachable opcodes cannot be hidden
 * in a branch, and jumps cannot land inside multiword instructions. */
static E63BootMethodStatus validate(const uint8_t *code,uint32_t words,
                                    unsigned regs,uint8_t *starts)
    {
    uint32_t pc;
    int returns=0;
    memset(starts,0,words);
    for (pc=0u;pc<words;)
        {
        uint16_t first=word(code,pc);
        unsigned op=first&255u,a=first>>8u,step=width(op),second=0;
        if (!step) return E63_BOOT_METHOD_UNSUPPORTED;
        if (step>words-pc) return E63_BOOT_METHOD_UNTRUSTED;
        starts[pc]=1u;
        if (step>=2u) second=word(code,pc+1u);
        if ((op==0x03u || op==0x2au) && a!=0u)
            return E63_BOOT_METHOD_UNTRUSTED; /* reserved high byte */
        if (op==0x00u) {
            if (first!=0u) return E63_BOOT_METHOD_UNSUPPORTED;
        } else if (op==0x01u || (op>=0xb0u && op<=0xbau) ||
                   (op>=0x32u && op<=0x37u) ||
                   (op>=0xd0u && op<=0xd7u)) {
            if (!reg_ok(a&15u,regs) || !reg_ok(a>>4u,regs))
                return E63_BOOT_METHOD_UNTRUSTED;
        } else if (op==0x02u) {
            if (!reg_ok(a,regs) || !reg_ok(second,regs))
                return E63_BOOT_METHOD_UNTRUSTED;
        } else if (op==0x03u) {
            if (!reg_ok(second,regs) || !reg_ok(word(code,pc+2u),regs))
                return E63_BOOT_METHOD_UNTRUSTED;
        } else if (op==0x12u) {
            if (!reg_ok(a&15u,regs)) return E63_BOOT_METHOD_UNTRUSTED;
        } else if (op==0x0fu || op==0x13u || op==0x14u || op==0x15u ||
                   (op>=0x38u && op<=0x3du)) {
            if (!reg_ok(a,regs)) return E63_BOOT_METHOD_UNTRUSTED;
            if (op==0x0fu) returns=1;
        } else if (op>=0x90u && op<=0x9au) {
            if (!reg_ok(a,regs) || !reg_ok(second&255u,regs) ||
                !reg_ok(second>>8u,regs)) return E63_BOOT_METHOD_UNTRUSTED;
        } else if (op>=0xd8u && op<=0xe2u) {
            if (!reg_ok(a,regs) || !reg_ok(second&255u,regs))
                return E63_BOOT_METHOD_UNTRUSTED;
        }
        pc+=step;
        }
    if (!returns) return E63_BOOT_METHOD_UNSUPPORTED;
    for (pc=0u;pc<words;)
        {
        unsigned op=word(code,pc)&255u;
        if ((op>=0x28u && op<=0x2au) || (op>=0x32u && op<=0x3du))
            if (!branch_target(code,pc,op,words,starts))
                return E63_BOOT_METHOD_UNTRUSTED;
        pc+=width(op);
        }
    return E63_BOOT_METHOD_OK;
    }
static uint32_t arshift(uint32_t v,unsigned shift)
    {
    shift&=31u;
    if (!shift) return v;
    return (v>>shift) | ((v&0x80000000u) ? ~(uint32_t)0<<(32u-shift) : 0u);
    }
static int binop(unsigned kind,uint32_t x,uint32_t y,uint32_t *out)
    {
    switch(kind)
        {
        case 0u:*out=x+y;return 1;               /* add */
        case 1u:*out=x-y;return 1;               /* sub */
        case 2u:*out=x*y;return 1;               /* mul */
        case 3u: /* div, Java MIN/-1 wraps, no C undefined behavior */
            if (!y) return 0;
            *out=(x==0x80000000u && y==0xffffffffu) ? 0x80000000u :
                 (uint32_t)(signed32(x)/signed32(y));return 1;
        case 4u:
            if (!y) return 0;
            *out=(x==0x80000000u && y==0xffffffffu) ? 0u :
                 (uint32_t)(signed32(x)%signed32(y));return 1;
        case 5u:*out=x&y;return 1;
        case 6u:*out=x|y;return 1;
        case 7u:*out=x^y;return 1;
        case 8u:*out=x<<(y&31u);return 1;
        case 9u:*out=arshift(x,y);return 1;
        case 10u:*out=x>>(y&31u);return 1;
        default:return 0;
        }
    }
static E63BootMethodStatus execute(const uint8_t *code,uint32_t words,
                                   uint16_t registers,const int32_t *args,
                                   unsigned count,int32_t *output)
    {
    uint8_t *starts=(uint8_t *)malloc(words);
    uint8_t initialized[E63_BOOT_METHOD_MAX_REGISTERS];
    uint32_t regs[E63_BOOT_METHOD_MAX_REGISTERS];
    uint32_t pc=0u,steps=0u;
    E63BootMethodStatus status;
    unsigned i;
    if (!starts) return E63_BOOT_METHOD_UNSUPPORTED;
    status=validate(code,words,registers,starts);
    if (status!=E63_BOOT_METHOD_OK) {free(starts);return status;}
    memset(regs,0,sizeof(regs));memset(initialized,0,sizeof(initialized));
    for (i=0u;i<count;++i)
        {regs[registers-count+i]=(uint32_t)args[i];
         initialized[registers-count+i]=1u;}
    while (pc<words && steps++<E63_BOOT_METHOD_STEP_LIMIT)
        {
        uint16_t w=word(code,pc);
        unsigned op=w&255u,a=w>>8u,b=0u,c=0u,dest=0u,other=0u;
        uint32_t next=pc+width(op),value=0u;
        if (op==0x00u) { /* nop */ }
        else if (op==0x01u || op==0x02u || op==0x03u)
            {
            dest=op==0x03u ? word(code,pc+1u) : op==0x02u ? a : a&15u;
            b=op==0x03u ? word(code,pc+2u) : op==0x02u ?
              word(code,pc+1u) : a>>4u;
            if (!initialized[b]) {status=E63_BOOT_METHOD_UNTRUSTED;break;}
            regs[dest]=regs[b];initialized[dest]=1u;
            }
        else if (op==0x0fu)
            {
            if (!initialized[a]) {status=E63_BOOT_METHOD_UNTRUSTED;break;}
            *output=signed32(regs[a]);free(starts);return E63_BOOT_METHOD_OK;
            }
        else if (op==0x12u || op==0x13u || op==0x14u || op==0x15u)
            {
            dest=op==0x12u ? a&15u : a;
            if (op==0x12u) value=(uint32_t)((int32_t)(a>>4u)-
                                            ((a&0x80u) ? 16 : 0));
            else if (op==0x13u) value=(uint32_t)signed16(word(code,pc+1u));
            else if (op==0x14u) value=(uint32_t)word(code,pc+1u) |
                                       ((uint32_t)word(code,pc+2u)<<16u);
            else value=(uint32_t)word(code,pc+1u)<<16u;
            regs[dest]=value;initialized[dest]=1u;
            }
        else if ((op>=0x28u && op<=0x2au) ||
                 (op>=0x32u && op<=0x3du))
            {
            int take=1;
            if (op>=0x32u && op<=0x3du)
                {
                int32_t left,right;
                if (op<=0x37u) {b=a&15u;c=a>>4u;}
                else {b=a;c=0u;}
                if (!initialized[b] || (op<=0x37u && !initialized[c]))
                    {status=E63_BOOT_METHOD_UNTRUSTED;break;}
                left=signed32(regs[b]);
                right=op<=0x37u ? signed32(regs[c]) : 0;
                switch ((op-0x32u)%6u)
                    {
                    case 0u:take=(left==right);break;
                    case 1u:take=(left!=right);break;
                    case 2u:take=(left<right);break;
                    case 3u:take=(left>=right);break;
                    case 4u:take=(left>right);break;
                    default:take=(left<=right);break;
                    }
                }
            if (take) {
                int64_t delta=op==0x28u ? signed8((uint8_t)a) :
                        op==0x2au ? signed32((uint32_t)word(code,pc+1u) |
                                                  ((uint32_t)word(code,pc+2u)<<16u)) :
                                    signed16(word(code,pc+1u));
                next=(uint32_t)((int64_t)pc+delta); /* preflighted boundary */
            }
            }
        else if ((op>=0x90u && op<=0x9au) ||
                 (op>=0xb0u && op<=0xbau) ||
                 (op>=0xd0u && op<=0xe2u))
            {
            unsigned kind;
            uint16_t w2=op>=0xb0u && op<=0xbau ? 0u : word(code,pc+1u);
            if (op<=0x9au)
                {dest=a;b=w2&255u;c=w2>>8u;kind=op-0x90u;}
            else if (op<=0xbau)
                {dest=a&15u;b=dest;c=a>>4u;kind=op-0xb0u;}
            else if (op<=0xd7u)
                {dest=a&15u;b=a>>4u;kind=op-0xd0u;
                 value=(uint32_t)signed16(w2);}
            else
                {dest=a;b=w2&255u;kind=op-0xd8u;
                 value=(uint32_t)signed8((uint8_t)(w2>>8u));}
            if (!initialized[b] || ((op<=0xbau) && !initialized[c]))
                {status=E63_BOOT_METHOD_UNTRUSTED;break;}
            if (op>=0xd0u)
                {
                if (kind==1u) { /* rsub-int/lit16 or /lit8 */
                    other=(uint32_t)(value-regs[b]);
                    regs[dest]=other;initialized[dest]=1u;
                    pc=next;continue;
                }
                /* Lit16 0xd0..d7: add, rsub, mul, div, rem, and, or, xor.
                 * Lit8 0xd8..e2 additionally: shl, shr, ushr. */
                if (!binop(kind,regs[b],value,&other))
                    {status=E63_BOOT_METHOD_UNSUPPORTED;break;}
                }
            else if (!binop(kind,regs[b],regs[c],&other))
                {status=E63_BOOT_METHOD_UNSUPPORTED;break;}
            regs[dest]=other;initialized[dest]=1u;
            }
        else {status=E63_BOOT_METHOD_UNSUPPORTED;break;}
        pc=next;
        }
    if (status==E63_BOOT_METHOD_OK)
        status=pc<words ? E63_BOOT_METHOD_BUDGET : E63_BOOT_METHOD_UNSUPPORTED;
    free(starts);
    return status;
    }

static E63BootMethodStatus disk_failure(const DexDisk *d)
    {return d->io_error ? E63_BOOT_METHOD_IO_ERROR : E63_BOOT_METHOD_UNTRUSTED;}

E63BootMethodStatus e63_boot_call_static_int(
    const E63BootClass *where,const char *descriptor,const char *name,
    const char *prototype,const int32_t *arguments,unsigned argument_count,
    E63BootReadAt dex_read_at,void *dex_context,size_t dex_bytes,int32_t *output)
    {
    DexDisk d;
    uint8_t cls[32];
    uint32_t class_type,class_data,at,counts[4],i,j,method_idx=0u;
    size_t length,proto_len;
    E63BootStatus confirmed;
    if (!output) return E63_BOOT_METHOD_BAD_INPUT;
    *output=0;
    if (!where || !descriptor || !name || !prototype || !dex_read_at ||
        dex_bytes<112u || dex_bytes>32u*1024u*1024u ||
        argument_count>E63_BOOT_METHOD_MAX_ARGUMENTS ||
        (argument_count && !arguments) ||
        where->dex_slot>=E63_BOOT_DEX_SLOTS ||
        (length=strlen(descriptor))<3u || length>=256u ||
        descriptor[0]!='L' || descriptor[length-1u]!=';' ||
        (length=strlen(name))<1u || length>127u ||
        (proto_len=strlen(prototype))!=argument_count+3u ||
        prototype[0]!='(' || prototype[proto_len-2u]!=')' ||
        prototype[proto_len-1u]!='I') return E63_BOOT_METHOD_BAD_INPUT;
    for (i=0;i<argument_count;++i)
        if (prototype[1u+i]!='I') return E63_BOOT_METHOD_BAD_INPUT;
    confirmed=e63_boot_confirm_class(where,descriptor,dex_read_at,
                                      dex_context,dex_bytes);
    if (confirmed!=E63_BOOT_OK)
        return confirmed==E63_BOOT_IO_ERROR ? E63_BOOT_METHOD_IO_ERROR :
               E63_BOOT_METHOD_UNTRUSTED;
    if (!header(&d,dex_read_at,dex_context,dex_bytes)) return disk_failure(&d);
    if (where->class_def_index>=d.classes ||
        !disk_read(&d,d.classes_at+(uint64_t)where->class_def_index*32u,
                   cls,sizeof(cls))) return disk_failure(&d);
    class_type=le32(cls);
    class_data=le32(cls+24u);
    if (class_type>=d.types || !type_is(&d,class_type,descriptor))
        return disk_failure(&d);
    if (!class_data) return E63_BOOT_METHOD_NOT_FOUND;
    if (class_data<d.data_at || class_data>=d.data_end)
        return E63_BOOT_METHOD_UNTRUSTED;
    at=class_data;
    for (i=0u;i<4u;++i)
        if (!uleb(&d,&at,&counts[i])) return disk_failure(&d);
    if (counts[0]>d.fields || counts[1]>d.fields ||
        counts[2]>d.methods || counts[3]>d.methods ||
        (uint64_t)counts[0]+counts[1]>d.fields ||
        (uint64_t)counts[2]+counts[3]>d.methods)
        return E63_BOOT_METHOD_UNTRUSTED;
    for (i=0u;i<2u;++i)
        {
        uint32_t field=0u;
        for (j=0u;j<counts[i];++j)
            {
            uint32_t delta,flags;
            if (!uleb(&d,&at,&delta) || !uleb(&d,&at,&flags) ||
                delta>=d.fields || field>=d.fields-delta)
                return disk_failure(&d);
            field+=delta;
            }
        }
    for (i=0u;i<counts[2];++i)
        {
        uint32_t delta,flags,code_at;
        uint8_t method[8],info[16];
        uint32_t name_id,insns,regs,ins,tries;
        uint8_t *code;
        E63BootMethodStatus result;
        if (!uleb(&d,&at,&delta) || !uleb(&d,&at,&flags) ||
            !uleb(&d,&at,&code_at) || delta>=d.methods ||
            method_idx>=d.methods-delta) return disk_failure(&d);
        method_idx+=delta;
        if (!disk_read(&d,d.methods_at+(uint64_t)method_idx*8u,
                       method,sizeof(method))) return disk_failure(&d);
        if (le16(method)!=class_type) return E63_BOOT_METHOD_UNTRUSTED;
        name_id=le32(method+4u);
        if (name_id>=d.strings || le16(method+2u)>=d.protos)
            return E63_BOOT_METHOD_UNTRUSTED;
        if (!string_is(&d,name_id,name)) {
            if (d.io_error) return E63_BOOT_METHOD_IO_ERROR;
            continue;
        }
        if (!proto_is(&d,le16(method+2u),argument_count)) {
            if (d.io_error) return E63_BOOT_METHOD_IO_ERROR;
            continue;
        }
        if (!(flags&8u) || !code_at) return E63_BOOT_METHOD_UNSUPPORTED;
        if ((code_at&3u)!=0u || code_at<d.data_at ||
            !within(code_at,16u,d.data_end) ||
            !disk_read(&d,code_at,info,sizeof(info)))
            return disk_failure(&d);
        regs=le16(info);ins=le16(info+2u);tries=le16(info+6u);
        insns=le32(info+12u);
        if (ins!=argument_count || regs<ins || !regs ||
            regs>E63_BOOT_METHOD_MAX_REGISTERS || tries ||
            !insns || insns>E63_BOOT_METHOD_MAX_CODE_WORDS ||
            !within((uint64_t)code_at+16u,(uint64_t)insns*2u,d.data_end))
            return E63_BOOT_METHOD_UNSUPPORTED;
        code=(uint8_t *)malloc((size_t)insns*2u);
        if (!code) return E63_BOOT_METHOD_UNSUPPORTED;
        if (!disk_read(&d,(uint64_t)code_at+16u,code,(size_t)insns*2u))
            {free(code);return disk_failure(&d);}
        result=execute(code,insns,(uint16_t)regs,arguments,
                       argument_count,output);
        free(code);
        return result;
        }
    return E63_BOOT_METHOD_NOT_FOUND;
    }

E63BootMethodStatus e63_boot_inspect_native_static_int(
    const E63BootClass *where,const char *descriptor,const char *name,
    const char *prototype,E63BootReadAt dex_read_at,void *dex_context,
    size_t dex_bytes)
    {
    DexDisk d;
    uint8_t cls[32];
    uint32_t class_type,at,counts[4],i,j,method_idx=0u;
    size_t length;
    E63BootStatus confirmed;
    if (!where || !descriptor || !name || !prototype || !dex_read_at ||
        dex_bytes<112u || dex_bytes>32u*1024u*1024u ||
        where->dex_slot>=E63_BOOT_DEX_SLOTS ||
        (length=strlen(descriptor))<3u || length>=256u ||
        descriptor[0]!='L' || descriptor[length-1u]!=';' ||
        (length=strlen(name))<1u || length>127u ||
        strcmp(prototype,"()I")!=0)
        return E63_BOOT_METHOD_BAD_INPUT;
    confirmed=e63_boot_confirm_class(where,descriptor,dex_read_at,
                                      dex_context,dex_bytes);
    if (confirmed!=E63_BOOT_OK)
        return confirmed==E63_BOOT_IO_ERROR ? E63_BOOT_METHOD_IO_ERROR :
               E63_BOOT_METHOD_UNTRUSTED;
    if (!header(&d,dex_read_at,dex_context,dex_bytes)) return disk_failure(&d);
    if (where->class_def_index>=d.classes ||
        !disk_read(&d,d.classes_at+(uint64_t)where->class_def_index*32u,
                   cls,sizeof(cls))) return disk_failure(&d);
    class_type=le32(cls);
    at=le32(cls+24u);
    if (!at) return E63_BOOT_METHOD_NOT_FOUND;
    if (class_type>=d.types || !type_is(&d,class_type,descriptor) ||
        at<d.data_at || at>=d.data_end) return E63_BOOT_METHOD_UNTRUSTED;
    for (i=0u;i<4u;++i)
        if (!uleb(&d,&at,&counts[i])) return disk_failure(&d);
    if (counts[0]>d.fields || counts[1]>d.fields ||
        counts[2]>d.methods || counts[3]>d.methods ||
        (uint64_t)counts[0]+counts[1]>d.fields ||
        (uint64_t)counts[2]+counts[3]>d.methods)
        return E63_BOOT_METHOD_UNTRUSTED;
    for (i=0u;i<2u;++i)
        {
        uint32_t field=0u;
        for (j=0u;j<counts[i];++j)
            {
            uint32_t delta,flags;
            if (!uleb(&d,&at,&delta) || !uleb(&d,&at,&flags) ||
                delta>=d.fields || field>=d.fields-delta)
                return disk_failure(&d);
            field+=delta;
            }
        }
    for (i=0u;i<counts[2];++i)
        {
        uint32_t delta,flags,code_at;
        uint8_t method[8];
        uint32_t method_name;
        if (!uleb(&d,&at,&delta) || !uleb(&d,&at,&flags) ||
            !uleb(&d,&at,&code_at) || delta>=d.methods ||
            method_idx>=d.methods-delta) return disk_failure(&d);
        method_idx+=delta;
        if (!disk_read(&d,d.methods_at+(uint64_t)method_idx*8u,
                       method,sizeof(method))) return disk_failure(&d);
        if (le16(method)!=class_type || le16(method+2u)>=d.protos)
            return E63_BOOT_METHOD_UNTRUSTED;
        method_name=le32(method+4u);
        if (method_name>=d.strings) return E63_BOOT_METHOD_UNTRUSTED;
        if (!string_is(&d,method_name,name))
            {if (d.io_error) return E63_BOOT_METHOD_IO_ERROR;continue;}
        if (!proto_is(&d,le16(method+2u),0u))
            {if (d.io_error) return E63_BOOT_METHOD_IO_ERROR;continue;}
        return ((flags&0x108u)==0x108u && !(flags&0x400u) && !code_at) ?
               E63_BOOT_METHOD_OK : E63_BOOT_METHOD_UNSUPPORTED;
        }
    return E63_BOOT_METHOD_NOT_FOUND;
    }

const char *e63_boot_method_status(E63BootMethodStatus status)
    {
    switch(status)
        {
        case E63_BOOT_METHOD_OK: return "real AOSP DEX static int method executed";
        case E63_BOOT_METHOD_BAD_INPUT: return "invalid boot method request";
        case E63_BOOT_METHOD_UNTRUSTED: return "invalid class/method DEX metadata";
        case E63_BOOT_METHOD_NOT_FOUND: return "method not in class DEX";
        case E63_BOOT_METHOD_UNSUPPORTED: return "bytecode/prototype not supported";
        case E63_BOOT_METHOD_IO_ERROR: return "pinned DEX read failed";
        case E63_BOOT_METHOD_BUDGET: return "method step budget exceeded";
        default: return "unknown boot method status";
        }
    }
