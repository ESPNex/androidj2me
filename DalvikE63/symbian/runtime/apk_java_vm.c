#include "apk_java_vm.h"
#include <string.h>

#define E63_JAVA_PROGRAM_WORDS 2048u
#define E63_JAVA_PROGRAM_REGS 32u
#define E63_JAVA_PROGRAM_STEPS 10000u
#define HOST_DESC "Lorg/e63/dalvik/runtime/Host;"

typedef struct HostSignature {
    E63JavaService service;
    const char *name, *proto, *input;
    char output; /* V = void; I = int */
} HostSignature;
static const HostSignature methods[] = {
    { E63_SERVICE_TITLE,"title","(Ljava/lang/String;)V","S",'V' },
    { E63_SERVICE_TEXT,"text","(Ljava/lang/String;)V","S",'V' },
    { E63_SERVICE_OPTION,"option","(ILjava/lang/String;)V","IS",'V' },
    { E63_SERVICE_IMAGE,"image","(Ljava/lang/String;)V","S",'V' },
    { E63_SERVICE_INPUT,"input","(ILjava/lang/String;I)V","ISI",'V' },
    { E63_SERVICE_DIALOG,"dialog","(Ljava/lang/String;)V","S",'V' },
    { E63_SERVICE_OPEN,"open","(Ljava/lang/String;)V","S",'V' },
    { E63_SERVICE_GET_FLAG,"getFlag","(Ljava/lang/String;)I","S",'I' },
    { E63_SERVICE_SET_FLAG,"setFlag","(Ljava/lang/String;I)V","SI",'V' },
    { E63_SERVICE_IS_INSTALLED,"isInstalled","(Ljava/lang/String;)I","S",'I' },
    { E63_SERVICE_SEARCH_FILE,"searchFile","(Ljava/lang/String;)I","S",'I' },
    { E63_SERVICE_INSTALL,"install","(Ljava/lang/String;)I","S",'I' },
    { E63_SERVICE_LIST,"list","(Ljava/lang/String;)V","S",'V' },
    { E63_SERVICE_MKDIR,"mkdir","(Ljava/lang/String;)I","S",'I' },
    { E63_SERVICE_TOUCH,"touch","(Ljava/lang/String;)I","S",'I' },
    { E63_SERVICE_RENAME,"rename","(Ljava/lang/String;Ljava/lang/String;)I","SS",'I' },
    { E63_SERVICE_DELETE,"delete","(Ljava/lang/String;)I","S",'I' },
    { E63_SERVICE_IMPORT_FILE,"importFile","(Ljava/lang/String;Ljava/lang/String;)I","SS",'I' },
    { E63_SERVICE_WAV,"wav","(Ljava/lang/String;)I","S",'I' }
};

static uint16_t u16(const uint8_t *p)
    { return (uint16_t)(p[0] | ((uint16_t)p[1]<<8)); }
static int32_t s16(uint16_t v)
    { return (v&0x8000u) ? (int32_t)v-65536 : (int32_t)v; }
static int32_t s8(uint8_t v)
    { return (v&128u) ? (int32_t)v-256 : (int32_t)v; }
static uint16_t word(const E63DexMethod *m, uint32_t pc)
    { return u16(m->words_le+(size_t)pc*2u); }
/* Bounded scalar UTF-8 for UI labels and user input. MUTF-8 literals are
 * decoded by dex_preflight first. Embedded NUL and lone surrogates are never
 * silently passed to a C-string host service or a filesystem path.
 */
static int utf8_512(const char *str)
    {
    size_t i=0;
    if (!str) return 0;
    while (i<=512u)
        {
        uint8_t a=(uint8_t)str[i], b, c, d;
        uint32_t cp;
        unsigned n;
        if (!a) return 1;
        if (a<0x80u) {cp=a;n=1u;}
        else if (a>=0xc2u && a<=0xdfu) {cp=a & 31u;n=2u;}
        else if (a>=0xe0u && a<=0xefu) {cp=a & 15u;n=3u;}
        else if (a>=0xf0u && a<=0xf4u) {cp=a & 7u;n=4u;}
        else return 0;
        if (n>513u-i) return 0;
        if (n>=2u) {
            b=(uint8_t)str[i+1u];
            if ((b & 0xc0u)!=0x80u ||
                (a==0xe0u && b<0xa0u) || (a==0xedu && b>=0xa0u) ||
                (a==0xf0u && b<0x90u) || (a==0xf4u && b>0x8fu)) return 0;
            cp=(cp<<6)|(b & 63u);
        }
        if (n>=3u) {
            c=(uint8_t)str[i+2u];
            if ((c & 0xc0u)!=0x80u) return 0;
            cp=(cp<<6)|(c & 63u);
        }
        if (n==4u) {
            d=(uint8_t)str[i+3u];
            if ((d & 0xc0u)!=0x80u) return 0;
            cp=(cp<<6)|(d & 63u);
        }
        if (cp<32u || cp==127u || cp>0x10ffffu) return 0;
        i+=n;
        }
    return 0;
    }
static int literal(const E63DexView *d, uint32_t index, char *output)
    {
    size_t used;
    return e63_dex_string_utf8(d,index,output,513u,&used) &&
           !memchr(output,0,used) && utf8_512(output);
    }
static const HostSignature *service(const E63DexView *d, uint32_t method_id)
    {
    size_t i;
    if (method_id>=d->methods_count) return 0;
    for (i=0;i<sizeof(methods)/sizeof(methods[0]);++i)
        if (e63_dex_method_ref_is(d,method_id,HOST_DESC,
                                  methods[i].name,methods[i].proto))
            return &methods[i];
    return 0;
    }
static unsigned width(unsigned opcode)
    {
    switch (opcode) {
        case 0x12: case 0x01: case 0x0a: case 0x28: case 0x0e:return 1u;
        case 0x13: case 0x1a: case 0x29:
        case 0x32: case 0x33: case 0x38: case 0x39:return 2u;
        case 0x71:return 3u;
        default:return 0u;
    }
    }
static int preflight(const E63DexView *d, const E63DexMethod *m)
    {
    uint8_t starts[E63_JAVA_PROGRAM_WORDS];
    uint32_t pc=0;
    unsigned last=0;
    if (m->tries || !m->registers || m->registers>E63_JAVA_PROGRAM_REGS ||
        m->ins>m->registers || m->outs>5u ||
        !m->words_count || m->words_count>E63_JAVA_PROGRAM_WORDS) return 0;
    memset(starts,0,sizeof(starts));
    while (pc<m->words_count) {
        uint16_t w=word(m,pc);
        unsigned op=w&255u, a=w>>8u, step=width(op);
        if (!step || step>m->words_count-pc) return 0;
        starts[pc]=1u;
        if ((op==0x0a || op==0x13 || op==0x1a || op==0x38 || op==0x39) &&
            a>=m->registers) return 0;
        if (op==0x12 && (a&15u)>=m->registers) return 0;
        if ((op==0x01 || op==0x32 || op==0x33) &&
            (((a&15u)>=m->registers) || ((a>>4u)>=m->registers))) return 0;
        if (op==0x0a && last!=0x71u) return 0;
        if (op==0x1a && word(m,pc+1u)>=d->strings_count) return 0;
        if (op==0x71) {
            unsigned count=(w>>12u)&15u, rword=word(m,pc+2u), i;
            const HostSignature *s=service(d,word(m,pc+1u));
            if (!s || count>5u || count>m->outs || strlen(s->input)!=count)
                return 0;
            for (i=0;i<count;++i) {
                unsigned reg=i==4u ? ((w>>8u)&15u) : ((rword>>(i*4u))&15u);
                if (reg>=m->registers) return 0;
            }
        }
        last=op;
        pc+=step;
    }
    if (last!=0x0eu) return 0;
    pc=0;
    while (pc<m->words_count) {
        uint16_t w=word(m,pc);
        unsigned op=w&255u, step=width(op);
        if (op==0x28 || op==0x29 || op==0x32 || op==0x33 ||
            op==0x38 || op==0x39) {
            int32_t delta=op==0x28 ? s8((uint8_t)(w>>8u)) : s16(word(m,pc+1u));
            int32_t target=(int32_t)pc+delta;
            if (target<0 || target>=(int32_t)m->words_count ||
                !starts[target]) return 0;
        }
        pc+=step;
    }
    return 1;
    }

E63JavaStatus e63_java_run(const E63DexView *dex, const char *program,
                           const char *method_name, const char *prototype,
                           const E63JavaValue *arguments, unsigned arg_count,
                           const E63JavaHost *host)
    {
    E63DexMethod method;
    E63JavaValue regs[E63_JAVA_PROGRAM_REGS], pending;
    char literals[E63_JAVA_PROGRAM_REGS][513];
    uint32_t literal_ids[E63_JAVA_PROGRAM_REGS];
    unsigned literal_count=0;
    E63JavaStatus status;
    unsigned i, pending_ok=0, last_invoke=0, steps=0;
    uint32_t pc=0;
    if (!dex || !dex->data || !program || !method_name || !prototype ||
        !host || !host->invoke || (arg_count && !arguments) || arg_count>3u)
        return E63_JAVA_BAD_INPUT;
    if (strcmp(method_name,"onStart")==0 && strcmp(prototype,"()V")==0) {
        if (arg_count) return E63_JAVA_BAD_INPUT;
    } else if (strcmp(method_name,"onSelect")==0 && strcmp(prototype,"(I)V")==0) {
        if (arg_count!=1u || arguments[0].type!=E63_JAVA_INT)
            return E63_JAVA_BAD_INPUT;
    } else if (strcmp(method_name,"onCommand")==0 &&
               strcmp(prototype,"(ILjava/lang/String;Ljava/lang/String;)V")==0) {
        if (arg_count!=3u || arguments[0].type!=E63_JAVA_INT ||
            arguments[1].type!=E63_JAVA_STRING ||
            arguments[2].type!=E63_JAVA_STRING ||
            !utf8_512(arguments[1].string) || !utf8_512(arguments[2].string))
            return E63_JAVA_BAD_INPUT;
    } else return E63_JAVA_UNSUPPORTED;
    i=(unsigned)e63_dex_find_code(dex,program,method_name,prototype,&method);
    if (i!=1u) return E63_JAVA_NO_CODE;
    if (!preflight(dex,&method) || method.ins!=arg_count)
        return E63_JAVA_UNSUPPORTED;
    memset(regs,0,sizeof(regs));
    memset(&pending,0,sizeof(pending));
    for (i=0;i<arg_count;++i)
        regs[method.registers-method.ins+i]=arguments[i];
    status=E63_JAVA_OK;
    while (pc<method.words_count && steps++<E63_JAVA_PROGRAM_STEPS) {
        uint16_t w=word(&method,pc);
        unsigned op=w&255u, a=w>>8u, r=a&15u;
        uint32_t next=pc+width(op);
        if (op==0x12) { /* const/4 */
            int32_t val=(int32_t)(a>>4u);
            if (val&8) val-=16;
            regs[r].type=E63_JAVA_INT;regs[r].number=val;regs[r].string=0;
        } else if (op==0x13) {
            regs[a].type=E63_JAVA_INT;
            regs[a].number=s16(word(&method,pc+1u));regs[a].string=0;
        } else if (op==0x1a) {
            uint32_t id=word(&method,pc+1u);
            unsigned slot;
            for (slot=0;slot<literal_count;++slot)
                if (literal_ids[slot]==id) break;
            if (slot==literal_count) {
                if (literal_count==E63_JAVA_PROGRAM_REGS ||
                    !literal(dex,id,literals[slot]))
                    {status=E63_JAVA_UNSUPPORTED;break;}
                literal_ids[slot]=id;++literal_count;
            }
            regs[a].type=E63_JAVA_STRING;
            regs[a].string=literals[slot];regs[a].number=0;
        } else if (op==0x01) {
            if (regs[a>>4u].type==E63_JAVA_EMPTY)
                {status=E63_JAVA_UNSUPPORTED;break;}
            regs[r]=regs[a>>4u];
        } else if (op==0x0a) {
            if (!last_invoke || !pending_ok)
                {status=E63_JAVA_UNSUPPORTED;break;}
            regs[a]=pending;pending_ok=0;
        } else if (op==0x28 || op==0x29) {
            int32_t delta=op==0x28 ? s8((uint8_t)a) : s16(word(&method,pc+1u));
            next=(uint32_t)((int32_t)pc+delta);
        } else if (op==0x32 || op==0x33) {
            unsigned other=a>>4u;
            int equal;
            if (regs[r].type!=E63_JAVA_INT || regs[other].type!=E63_JAVA_INT)
                {status=E63_JAVA_UNSUPPORTED;break;}
            equal=regs[r].number==regs[other].number;
            if (equal==(op==0x32))
                next=(uint32_t)((int32_t)pc+s16(word(&method,pc+1u)));
        } else if (op==0x38 || op==0x39) {
            int zero;
            if (regs[a].type!=E63_JAVA_INT)
                {status=E63_JAVA_UNSUPPORTED;break;}
            zero=regs[a].number==0;
            if (zero==(op==0x38))
                next=(uint32_t)((int32_t)pc+s16(word(&method,pc+1u)));
        } else if (op==0x71) {
            const HostSignature *sig=service(dex,word(&method,pc+1u));
            uint16_t bits=word(&method,pc+2u);
            unsigned count=(w>>12u)&15u;
            E63JavaValue args[5], result;
            memset(&result,0,sizeof(result));
            for (i=0;i<count;++i) {
                unsigned number=i==4u ? ((w>>8u)&15u) :
                                        ((bits>>(i*4u))&15u);
                args[i]=regs[number];
                if ((sig->input[i]=='I' && args[i].type!=E63_JAVA_INT) ||
                    (sig->input[i]=='S' && (args[i].type!=E63_JAVA_STRING ||
                                           !utf8_512(args[i].string))))
                    {status=E63_JAVA_UNSUPPORTED;break;}
            }
            if (status!=E63_JAVA_OK) break;
            if (host->invoke(host->context,sig->service,args,count,&result)!=0)
                {status=E63_JAVA_HOST_FAILURE;break;}
            pending_ok=(sig->output=='I');
            if (pending_ok && result.type!=E63_JAVA_INT)
                {status=E63_JAVA_HOST_FAILURE;break;}
            pending=result;
        } else if (op==0x0e) {
            return E63_JAVA_OK;
        } else {status=E63_JAVA_UNSUPPORTED;break;}
        last_invoke=op==0x71;
        pc=next;
    }
    if (status==E63_JAVA_OK) status=E63_JAVA_BUDGET;
    return status;
    }

const char *e63_java_status(E63JavaStatus status)
    {
    switch(status) {
        case E63_JAVA_OK: return "OK: Java Program DEX executed";
        case E63_JAVA_BAD_INPUT: return "invalid Java Program input";
        case E63_JAVA_NO_CODE: return "Java Program method missing";
        case E63_JAVA_UNSUPPORTED: return "unsupported/invalid DEX subset";
        case E63_JAVA_HOST_FAILURE: return "platform Host service failed";
        case E63_JAVA_BUDGET: return "Java Program instruction budget exhausted";
        default: return "unknown Java Program status";
    }
    }
