#include "dex_vm.h"
#include <stdlib.h>
#include <string.h>

/* All DEX numbers are little endian, including words that are unaligned in
 * the guest blob. Never cast to uint16_t*: ARM alignment requirements differ.
 */
static uint16_t word_at(const E63DexMethod *m, uint32_t pc)
    {
    const uint8_t *p=m->words_le+(size_t)pc*2u;
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1]<<8));
    }
static int16_t as_i16(uint16_t u)
    { return (int16_t)((u & 0x8000u) ? (int32_t)u-65536 : (int32_t)u); }
static int8_t as_i8(uint8_t u)
    { return (int8_t)((u & 0x80u) ? (int32_t)u-256 : (int32_t)u); }

typedef enum RegisterTag { REG_EMPTY=0, REG_INT=1, REG_OBJECT=2 } RegisterTag;
typedef struct Register { int32_t value; RegisterTag tag; } Register;

static int simple_prototype(const char *p, uint32_t *n, char *ret)
    {
    size_t i, len;
    uint32_t count=0;
    if (!p || (len=strlen(p))<3 || len>256 || p[0]!='(') return 0;
    for (i=1; i<len && p[i]!=')'; ++i)
        {
        if (p[i]!='I' && p[i]!='Z') return 0;
        ++count;
        }
    if (i+2!=len || p[i]!=')' ||
        (p[i+1]!='I' && p[i+1]!='Z' && p[i+1]!='V')) return 0;
    *n=count;*ret=p[i+1];
    return 1;
    }

static uint32_t op_width(uint8_t op)
    {
    switch (op)
        {
        case 0x01:case 0x0d:case 0x0e:case 0x0f:case 0x12:
        case 0x1d:case 0x1e:case 0x27:case 0x28:return 1;
        case 0x29:case 0x38:case 0x39:case 0x55:case 0x5c:return 2;
        case 0x70:return 3;
        default:return 0;
        }
    }

static E63VmStatus validate(const E63VmObject *obj, const E63DexMethod *m,
                            uint8_t *starts)
    {
    uint32_t pc=0, i;
    if (m->registers==0 || m->registers>E63_VM_MAX_REGISTERS ||
        m->ins>m->registers || m->words_count==0 ||
        m->words_count>E63_VM_MAX_WORDS) return E63_VM_INVALID;
    memset(starts,0,m->words_count);
    while (pc<m->words_count)
        {
        uint16_t w=word_at(m,pc), b;
        uint8_t op=(uint8_t)w;
        uint32_t width=op_width(op), a=(w>>8u) & 255u;
        if (!width) return E63_VM_UNSUPPORTED; /* including unreachable code */
        if (width>m->words_count-pc) return E63_VM_INVALID;
        starts[pc]=1;
        if ((op==0x0d || op==0x0f || op==0x1d || op==0x1e || op==0x27 ||
             (op>=0x38 && op<=0x39)) && a>=m->registers)
            return E63_VM_INVALID;
        if (op==0x12 || op==0x01)
            {
            if ((a & 15u)>=m->registers || (op==0x01 && a>>4u>=m->registers))
                return E63_VM_INVALID;
            }
        if (op==0x55 || op==0x5c)
            {
            b=word_at(m,pc+1u);
            if ((a & 15u)>=m->registers || (a>>4u)>=m->registers ||
                !e63_dex_field_is(obj->dex,b,obj->class_index,"Z"))
                return E63_VM_UNSUPPORTED;
            }
        if (op==0x70)
            {
            uint32_t count=(w>>12u) & 15u, receiver=word_at(m,pc+2u) & 15u;
            b=word_at(m,pc+1u);
            if (count!=1 || receiver>=m->registers ||
                !e63_dex_method_ref_is(obj->dex,b,"Ljava/lang/Object;", "<init>","()V"))
                return E63_VM_UNSUPPORTED;
            }
        pc+=width;
        }
    for (i=0; i<m->words_count; ++i)
        {
        uint16_t w;
        uint8_t op;
        int32_t dest;
        if (!starts[i]) continue;
        w=word_at(m,i);op=(uint8_t)w;
        if (op==0x28) dest=(int32_t)i+as_i8((uint8_t)(w>>8u));
        else if (op==0x29 || op==0x38 || op==0x39)
            dest=(int32_t)i+as_i16(word_at(m,i+1u));
        else continue;
        if (dest<0 || dest>=(int32_t)m->words_count || !starts[dest])
            return E63_VM_INVALID;
        }
    return E63_VM_OK;
    }

E63VmStatus e63_vm_new(const E63DexView *view, const char *class_descriptor,
                       E63VmObject *out)
    {
    size_t length;
    int class_index;
    if (!out) return E63_VM_INVALID;
    memset(out,0,sizeof(*out));
    if (!view || !view->data || !class_descriptor ||
        view->fields_count>E63_VM_MAX_FIELDS) return E63_VM_INVALID;
    length=strlen(class_descriptor);
    if (length<3 || length>=sizeof(out->class_descriptor)) return E63_VM_INVALID;
    class_index=e63_dex_class_index(view,class_descriptor);
    if (class_index<0) return E63_VM_NO_METHOD;
    memcpy(out->class_descriptor,class_descriptor,length+1u);
    out->class_index=(uint32_t)class_index;
    out->dex=view;
    return E63_VM_OK;
    }

E63VmStatus e63_vm_call(E63VmObject *instance, const char *name,
                        const char *prototype, const int32_t *params,
                        uint32_t param_count, int32_t *result)
    {
    E63DexMethod method;
    Register regs[E63_VM_MAX_REGISTERS];
    int32_t staged_fields[E63_VM_MAX_FIELDS];
    uint8_t *starts=0;
    uint32_t formal, i, pc=0, steps=0;
    int monitor=0, exists;
    char returns;
    E63VmStatus status=E63_VM_INVALID;
    if (!instance || !instance->dex || !name ||
        !simple_prototype(prototype,&formal,&returns) || formal!=param_count ||
        (formal && !params) || (returns!='V' && !result)) return E63_VM_INVALID;
    exists=e63_dex_find_code(instance->dex,instance->class_descriptor,name,
                             prototype,&method);
    if (exists!=1) return exists<0 ? E63_VM_INVALID : E63_VM_NO_METHOD;
    if (method.class_index!=instance->class_index || method.ins!=formal+1u ||
        method.registers>E63_VM_MAX_REGISTERS || method.words_count>E63_VM_MAX_WORDS ||
        method.registers==0 || method.words_count==0) return E63_VM_INVALID;
    starts=(uint8_t *)malloc(method.words_count);
    if (!starts) return E63_VM_INVALID;
    status=validate(instance,&method,starts);
    if (status!=E63_VM_OK) goto done;
    memcpy(staged_fields,instance->fields,sizeof(staged_fields));
    memset(regs,0,sizeof(regs));
    i=method.registers-method.ins;
    regs[i].tag=REG_OBJECT;regs[i].value=1; /* one guest object */
    for (i=0; i<formal; ++i)
        {
        regs[method.registers-method.ins+1u+i].value=params[i];
        regs[method.registers-method.ins+1u+i].tag=REG_INT;
        }
    while (pc<method.words_count)
        {
        uint16_t w=word_at(&method,pc);
        uint8_t op=(uint8_t)w;
        uint32_t a=(w>>8u)&255u;
        uint32_t next=pc+op_width(op);
        Register *r;
        if (++steps>E63_VM_STEP_BUDGET) {status=E63_VM_BUDGET;goto done;}
        if (op==0x01) /* move vA,vB */
            {
            Register other=regs[a>>4u];
            if (other.tag==REG_EMPTY) {status=E63_VM_INVALID;goto done;}
            regs[a & 15u]=other;
            }
        else if (op==0x12) /* const/4 vA,#signed4 */
            {
            uint32_t value=a>>4u;
            r=&regs[a & 15u];r->value=(int32_t)value - (value>=8u ? 16 : 0);
            r->tag=REG_INT;
            }
        else if (op==0x55 || op==0x5c) /* iget-boolean / iput-boolean */
            {
            uint32_t dst=a & 15u, owner=a>>4u;
            uint16_t field=word_at(&method,pc+1u);
            if (regs[owner].tag!=REG_OBJECT || regs[owner].value!=1)
                {status=E63_VM_INVALID;goto done;}
            if (op==0x55)
                {regs[dst].value=staged_fields[field];regs[dst].tag=REG_INT;}
            else
                {
                if (regs[dst].tag!=REG_INT ||
                    (regs[dst].value!=0 && regs[dst].value!=1))
                    {status=E63_VM_INVALID;goto done;}
                staged_fields[field]=regs[dst].value;
                }
            }
        else if (op==0x38 || op==0x39) /* if-eqz / if-nez */
            {
            if (regs[a].tag==REG_EMPTY) {status=E63_VM_INVALID;goto done;}
            if ((regs[a].value==0)==(op==0x38))
                next=(uint32_t)((int32_t)pc+as_i16(word_at(&method,pc+1u)));
            }
        else if (op==0x28) /* goto/8 */
            next=(uint32_t)((int32_t)pc+as_i8((uint8_t)a));
        else if (op==0x29) /* goto/16 */
            next=(uint32_t)((int32_t)pc+as_i16(word_at(&method,pc+1u)));
        else if (op==0x1d || op==0x1e) /* monitor-enter / monitor-exit */
            {
            if (regs[a].tag!=REG_OBJECT || regs[a].value!=1)
                {status=E63_VM_INVALID;goto done;}
            monitor += (op==0x1d) ? 1 : -1;
            if (monitor<0 || monitor>1) {status=E63_VM_INVALID;goto done;}
            }
        else if (op==0x70) /* invokes only the exact native Object constructor */
            {
            uint32_t receiver=word_at(&method,pc+2u) & 15u;
            if (regs[receiver].tag!=REG_OBJECT || regs[receiver].value!=1)
                {status=E63_VM_INVALID;goto done;}
            }
        else if (op==0x0e || op==0x0f) /* return-void / return */
            {
            if (monitor!=0 || (op==0x0e)!=(returns=='V'))
                {status=E63_VM_INVALID;goto done;}
            if (op==0x0f)
                {
                if (regs[a].tag!=REG_INT) {status=E63_VM_INVALID;goto done;}
                *result=regs[a].value;
                }
            memcpy(instance->fields,staged_fields,sizeof(staged_fields));
            status=E63_VM_OK;goto done;
            }
        else /* move-exception / throw: no native guest exception VM yet */
            {status=E63_VM_UNSUPPORTED;goto done;}
        if (next>=method.words_count || !starts[next])
            {status=E63_VM_INVALID;goto done;}
        pc=next;
        }
    status=E63_VM_INVALID; /* cannot fall off a DEX method */
done:
    free(starts);
    return status;
    }

const char *e63_vm_status(E63VmStatus status)
    {
    switch (status)
        {
        case E63_VM_OK:return "ok";
        case E63_VM_INVALID:return "invalid DEX frame/method";
        case E63_VM_NO_METHOD:return "no executable method";
        case E63_VM_UNSUPPORTED:return "unsupported native DEX operation";
        case E63_VM_BUDGET:return "instruction budget exhausted";
        default:return "unknown VM status";
        }
    }
