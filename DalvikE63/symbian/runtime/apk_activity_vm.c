#include "apk_activity_vm.h"
#include <string.h>

#define GUEST "Lorg/e63/dalvik/runtime/GuestActivity;"
#define HOST  "Lorg/e63/dalvik/runtime/Host;"
#define ANDROID "Landroid/app/Activity;"
#define BUNDLE "(Landroid/os/Bundle;)V"
#define COMMAND "(ILjava/lang/String;Ljava/lang/String;)V"
#define ACTIVITY_MAX_WORDS 128u
#define ACTIVITY_MAX_REGS 8u
#define ACTIVITY_MAX_DEPTH 12u
#define ACTIVITY_MAX_STEPS 1500u

/* Activity object is a SINGLE opaque instance. NULL Bundle has object id 0.
 * Strings are immutable values borrowed from the event caller; Program's
 * interpreter validates them and never writes into them. No Java heap exists.
 */
#define ACTIVITY_OBJECT E63_JAVA_OBJECT

typedef struct ActivityVM {
    const E63JavaSession *session;
    E63ActivityState *state;
    const E63ActivityHost *host;
    /* NULL is the separately preserved 0.2 compatibility interpreter. */
    const E63FrameworkDispatch *framework;
    unsigned steps;
} ActivityVM;

static uint16_t read16(const uint8_t *p)
    { return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1]<<8)); }
static uint32_t read32(const uint8_t *p)
    { return (uint32_t)p[0] | ((uint32_t)p[1]<<8) |
             ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24); }
static uint16_t inst(const E63DexMethod *code, uint32_t pc)
    { return read16(code->words_le+pc*2u); }
static int32_t signed16(uint16_t v)
    { return (v&0x8000u) ? (int32_t)v-65536 : (int32_t)v; }
static unsigned width(unsigned op)
    {
    switch (op) {
        case 0x01: case 0x07: case 0x0a: case 0x0e: case 0x12:return 1u;
        case 0x13: case 0x32: case 0x33: case 0x38: case 0x39:
        case 0x55: case 0x5c:return 2u;
        case 0x14: case 0x6e: case 0x6f: case 0x70: case 0x71:return 3u;
        default:return 0u;
    }
    }
static int preflight(const E63DexView *dex, const E63DexMethod *m)
    {
    uint8_t starts[ACTIVITY_MAX_WORDS];
    uint32_t pc=0;
    unsigned last=0;
    if (!m->registers || m->registers>ACTIVITY_MAX_REGS ||
        m->ins>m->registers || m->outs>5u || m->tries ||
        !m->words_count || m->words_count>ACTIVITY_MAX_WORDS) return 0;
    memset(starts,0,sizeof(starts));
    while (pc<m->words_count) {
        uint16_t w=inst(m,pc);
        unsigned op=w & 255u, a=w>>8u, len=width(op);
        if (!len || len>m->words_count-pc) return 0;
        starts[pc]=1u;
        if ((op==0x0a || op==0x13 || op==0x14 || op==0x38 || op==0x39) &&
            a>=m->registers) return 0;
        if ((op==0x01 || op==0x07 || op==0x32 || op==0x33 ||
             op==0x55 || op==0x5c) &&
            ((a&15u)>=m->registers || (a>>4u)>=m->registers)) return 0;
        if (op==0x12 && (a&15u)>=m->registers) return 0;
        if (op==0x0a && last<0x6eu) return 0;
        if ((op==0x55 || op==0x5c) &&
            inst(m,pc+1u)>=(uint16_t)dex->fields_count) return 0;
        if (op>=0x6eu && op<=0x71u) {
            unsigned n=(w>>12u)&15u, packed=inst(m,pc+2u), i;
            if (n>5u || n>m->outs || inst(m,pc+1u)>=dex->methods_count)
                return 0;
            for (i=0;i<n;++i) {
                unsigned r=i==4u ? ((w>>8u)&15u) : ((packed>>(i*4u))&15u);
                if (r>=m->registers) return 0;
            }
        }
        last=op;pc+=len;
    }
    if (last!=0x0eu) return 0;
    for (pc=0;pc<m->words_count;) {
        unsigned op=inst(m,pc)&255u;
        if (op==0x32 || op==0x33 || op==0x38 || op==0x39) {
            int32_t target=(int32_t)pc+signed16(inst(m,pc+1u));
            if (target<0 || target>=(int32_t)m->words_count ||
                !starts[target]) return 0;
        }
        pc+=width(op);
    }
    return 1;
    }

static E63JavaStatus run(ActivityVM *vm, const char *owner,
                          const char *name, const char *proto,
                          const E63JavaValue *inputs, unsigned input_count,
                          unsigned depth);

static int this_object(const E63JavaValue *v)
    {return v->type==ACTIVITY_OBJECT && v->number==1;}

static E63JavaStatus framework_call(ActivityVM *vm, const char *name,
                            const char *proto, const E63JavaValue *args,
                            unsigned count, E63JavaValue *result)
    {
    if (!vm->framework || !vm->framework->invoke)
        return E63_JAVA_UNSUPPORTED;
    return vm->framework->invoke(vm->framework->context,ANDROID,name,proto,
                                 args,count,result);
    }

static E63JavaStatus invoke(ActivityVM *vm, unsigned opcode, uint32_t method_id,
                             const E63JavaValue *args, unsigned count,
                             E63JavaValue *result, unsigned depth)
    {
    const E63DexView *dex=&vm->session->dex;
    const char *main_class=vm->session->activity;
    if (opcode==0x6fu && count>=1u && this_object(args)) {
        static const char * const lifecycle[]={"onCreate","onStart",
                                "onResume","onPause","onStop","onDestroy"};
        unsigned j;
        for (j=0;j<sizeof(lifecycle)/sizeof(lifecycle[0]);++j) {
            const char *proto=j==0u ? BUNDLE : "()V";
            if (e63_dex_method_ref_is(dex,method_id,ANDROID,
                                      lifecycle[j],proto)) {
                if (count!=(j==0u ? 2u : 1u)) return E63_JAVA_UNSUPPORTED;
                return vm->framework ?
                    framework_call(vm,lifecycle[j],proto,args,count,result) :
                    E63_JAVA_OK; /* legacy 0.2 no-op only */
            }
        }
    }
    if (opcode==0x70u && count==1u && this_object(args)) {
        if (e63_dex_method_ref_is(dex,method_id,ANDROID,"<init>","()V"))
            return vm->framework ?
                framework_call(vm,"<init>","()V",args,count,result) :
                E63_JAVA_OK; /* legacy 0.2 no-op only */
        if (e63_dex_method_ref_is(dex,method_id,GUEST,"<init>","()V"))
            return run(vm,GUEST,"<init>","()V",args,count,depth+1u);
    }
    if (opcode==0x6eu && count>=1u && this_object(args)) {
        if (count==2u && args[1].type==E63_JAVA_INT &&
            e63_dex_method_ref_is(dex,method_id,GUEST,"setTheme","(I)V"))
            return vm->framework ?
                framework_call(vm,"setTheme","(I)V",args,count,result) :
                E63_JAVA_OK; /* Avkon shim only in legacy 0.2 */
        if (count==1u &&
            e63_dex_method_ref_is(dex,method_id,GUEST,"isFinishing","()Z")) {
            if (vm->framework)
                return framework_call(vm,"isFinishing","()Z",
                                      args,count,result);
            result->type=E63_JAVA_INT;result->number=0;return E63_JAVA_OK;
        }
        if (count==1u &&
            e63_dex_method_ref_is(dex,method_id,GUEST,"redraw","()V"))
            return run(vm,GUEST,"redraw","()V",args,count,depth+1u);
        if (count==1u &&
            e63_dex_method_ref_is(dex,method_id,GUEST,"showProgram","()V"))
            return run(vm,main_class,"showProgram","()V",args,count,depth+1u);
        if (count==2u && args[1].type==E63_JAVA_INT &&
            e63_dex_method_ref_is(dex,method_id,GUEST,"selectProgram","(I)V"))
            return run(vm,main_class,"selectProgram","(I)V",args,count,depth+1u);
        if (count==4u && args[1].type==E63_JAVA_INT &&
            args[2].type==E63_JAVA_STRING && args[3].type==E63_JAVA_STRING &&
            e63_dex_method_ref_is(dex,method_id,GUEST,"commandProgram",COMMAND))
            return run(vm,main_class,"commandProgram",COMMAND,args,count,depth+1u);
    }
    if (opcode==0x71u) {
        if (count==1u && this_object(args) &&
            e63_dex_method_ref_is(dex,method_id,HOST,"begin",
                                   "(Lorg/e63/dalvik/runtime/GuestActivity;)V")) {
            if (vm->framework) return E63_JAVA_UNSUPPORTED;
            return vm->host->begin(vm->host->context)==0 ?
                E63_JAVA_OK : E63_JAVA_HOST_FAILURE;
        }
        if (count==0u &&
            e63_dex_method_ref_is(dex,method_id,HOST,"navigated","()Z")) {
            int status;
            if (vm->framework) return E63_JAVA_UNSUPPORTED;
            status=vm->host->navigated(vm->host->context);
            if (status<0 || status>1) return E63_JAVA_HOST_FAILURE;
            result->type=E63_JAVA_INT;result->number=status;
            return E63_JAVA_OK;
        }
        if ((count==0u && e63_dex_method_ref_is(dex,method_id,
                                    vm->session->program,"onStart","()V")) ||
            (count==1u && e63_dex_method_ref_is(dex,method_id,
                                    vm->session->program,"onSelect","(I)V")) ||
            (count==3u && e63_dex_method_ref_is(dex,method_id,
                                    vm->session->program,"onCommand",COMMAND))) {
            const char *method=count==0u ? "onStart" :
                               count==1u ? "onSelect" : "onCommand";
            const char *proto=count==0u ? "()V" :
                              count==1u ? "(I)V" : COMMAND;
            /* Legacy 0.2 Program/Host services are NOT Android services. */
            if (vm->framework) return E63_JAVA_UNSUPPORTED;
            return e63_session_run(vm->session,method,proto,args,count,
                                   vm->host->program_host);
        }
    }
    return E63_JAVA_UNSUPPORTED; /* no arbitrary Android method dispatch */
    }

static E63JavaStatus run(ActivityVM *vm, const char *owner,
                          const char *name, const char *proto,
                          const E63JavaValue *inputs, unsigned input_count,
                          unsigned depth)
    {
    const E63DexView *dex=&vm->session->dex;
    E63DexMethod code;
    E63JavaValue regs[ACTIVITY_MAX_REGS], pending;
    E63JavaStatus status;
    unsigned i, last_invoke=0, pending_ok=0;
    uint32_t pc=0;
    if (depth>ACTIVITY_MAX_DEPTH) return E63_JAVA_BUDGET;
    if (e63_dex_find_code(dex,owner,name,proto,&code)!=1)
        return E63_JAVA_NO_CODE;
    if (!preflight(dex,&code) || code.ins!=input_count)
        return E63_JAVA_UNSUPPORTED;
    memset(regs,0,sizeof(regs));memset(&pending,0,sizeof(pending));
    for (i=0;i<input_count;++i)
        regs[code.registers-code.ins+i]=inputs[i];
    while (pc<code.words_count && vm->steps++<ACTIVITY_MAX_STEPS) {
        uint16_t w=inst(&code,pc);
        unsigned op=w&255u, a=w>>8u, r=a&15u;
        uint32_t next=pc+width(op);
        if (op==0x12) {
            int32_t v=(int32_t)(a>>4u);
            if (v&8) v-=16;
            regs[r].type=E63_JAVA_INT;regs[r].number=v;regs[r].string=0;
        } else if (op==0x13 || op==0x14) {
            regs[a].type=E63_JAVA_INT;regs[a].string=0;
            regs[a].number=op==0x13 ? signed16(inst(&code,pc+1u)) :
                (int32_t)read32(code.words_le+(pc+1u)*2u);
        } else if (op==0x01 || op==0x07) {
            E63JavaValue source=regs[a>>4u];
            if ((op==0x01 && source.type!=E63_JAVA_INT) ||
                (op==0x07 && source.type!=ACTIVITY_OBJECT)) return E63_JAVA_UNSUPPORTED;
            regs[r]=source;
        } else if (op==0x0a) {
            if (!last_invoke || !pending_ok || pending.type!=E63_JAVA_INT)
                return E63_JAVA_UNSUPPORTED;
            regs[a]=pending;pending_ok=0;
        } else if (op==0x55 || op==0x5c) {
            int field=e63_dex_field_id(dex,GUEST,"resumedOnce","Z");
            if (field<0 || inst(&code,pc+1u)!=(unsigned)field ||
                !this_object(&regs[a>>4u])) return E63_JAVA_UNSUPPORTED;
            if (op==0x55) {
                regs[r].type=E63_JAVA_INT;
                regs[r].number=vm->state->resumed_once ? 1 : 0;
                regs[r].string=0;
            } else {
                if (regs[r].type!=E63_JAVA_INT ||
                    (regs[r].number!=0 && regs[r].number!=1))
                    return E63_JAVA_UNSUPPORTED;
                vm->state->resumed_once=(unsigned char)regs[r].number;
            }
        } else if (op==0x32 || op==0x33 || op==0x38 || op==0x39) {
            int32_t left=regs[r].number;
            int eq;
            if (regs[r].type!=E63_JAVA_INT) return E63_JAVA_UNSUPPORTED;
            if (op==0x32 || op==0x33) {
                if (regs[a>>4u].type!=E63_JAVA_INT) return E63_JAVA_UNSUPPORTED;
                eq=left==regs[a>>4u].number;
            } else eq=left==0;
            if (eq==(op==0x32 || op==0x38))
                next=(uint32_t)((int32_t)pc+signed16(inst(&code,pc+1u)));
        } else if (op>=0x6e && op<=0x71) {
            E63JavaValue actual[5], result;
            unsigned count=(w>>12u)&15u, packed=inst(&code,pc+2u);
            memset(&result,0,sizeof(result));
            for (i=0;i<count;++i) {
                unsigned number=i==4u ? ((w>>8u)&15u) :
                                        ((packed>>(i*4u))&15u);
                actual[i]=regs[number];
                if (actual[i].type==E63_JAVA_EMPTY)
                    return E63_JAVA_UNSUPPORTED;
            }
            status=invoke(vm,op,inst(&code,pc+1u),actual,count,&result,depth);
            if (status!=E63_JAVA_OK) return status;
            pending_ok=result.type==E63_JAVA_INT;pending=result;
        } else if (op==0x0e) return E63_JAVA_OK;
        else return E63_JAVA_UNSUPPORTED;
        last_invoke=(op>=0x6e && op<=0x71);
        pc=next;
    }
    return E63_JAVA_BUDGET;
    }

static E63JavaStatus activity_event_inner(const E63JavaSession *session,
                                  E63ActivityState *state,
                                  const E63ActivityHost *host,
                                  const E63FrameworkDispatch *framework,
                                  const char *event,
                                  const E63JavaValue *args, unsigned count)
    {
    ActivityVM vm;
    E63ActivityState next;
    E63JavaValue input[4];
    E63JavaStatus status;
    const char *owner=GUEST, *name=event, *proto="()V";
    unsigned n=1u;
    if (!session || !session->apk || !session->dex.data ||
        !session->activity[0] || !state || !host || !host->begin ||
        !host->navigated || !host->program_host || !event ||
        (count && !args)) return E63_JAVA_BAD_INPUT;
    next=*state;
    input[0].type=ACTIVITY_OBJECT;input[0].number=1;input[0].string=0;
    if (strcmp(event,"onCreate")==0 && !count && !state->constructed) {
        vm.session=session;vm.state=&next;vm.host=host;
        vm.framework=framework;vm.steps=0;
        status=run(&vm,session->activity,"<init>","()V",input,1u,0u);
        if (status!=E63_JAVA_OK) return status;
        next.constructed=1u;
        input[1].type=ACTIVITY_OBJECT;input[1].number=0;input[1].string=0;
        proto=BUNDLE;n=2u;
    } else if (strcmp(event,"onStart")==0 && !count &&
               state->created && !state->started) {
    } else if (strcmp(event,"onResume")==0 && !count &&
               state->started && !state->resumed) {
        /* First resume sets resumedOnce; subsequent resumes execute the
         * DEX's own conditional redraw in GuestActivity.onResume. */
    } else if (strcmp(event,"onPause")==0 && !count && state->resumed) {
    } else if (strcmp(event,"onStop")==0 && !count &&
               state->started && !state->resumed) {
    } else if (strcmp(event,"onDestroy")==0 && !count &&
               state->created && !state->started && !state->resumed) {
    } else if (strcmp(event,"choose")==0 && count==1u &&
               state->resumed && args[0].type==E63_JAVA_INT) {
        proto="(I)V";n=2u;input[1]=args[0];
    } else if (strcmp(event,"command")==0 && count==3u &&
               state->resumed && args[0].type==E63_JAVA_INT &&
               args[1].type==E63_JAVA_STRING &&
               args[2].type==E63_JAVA_STRING) {
        proto=COMMAND;n=4u;
        input[1]=args[0];input[2]=args[1];input[3]=args[2];
    } else return E63_JAVA_BAD_INPUT;
    vm.session=session;vm.state=&next;vm.host=host;
    vm.framework=framework;vm.steps=0;
    status=run(&vm,owner,name,proto,input,n,0u);
    if (status!=E63_JAVA_OK) return status;
    if (strcmp(event,"onCreate")==0) next.created=1u;
    if (strcmp(event,"onStart")==0) next.started=1u;
    if (strcmp(event,"onResume")==0) next.resumed=1u;
    if (strcmp(event,"onPause")==0) next.resumed=0u;
    if (strcmp(event,"onStop")==0) next.started=0u;
    if (strcmp(event,"onDestroy")==0) {
        next.created=0u;next.constructed=0u;next.resumed_once=0u;
    }
    *state=next;
    return E63_JAVA_OK;
    }

E63JavaStatus e63_activity_event(const E63JavaSession *session,
                                  E63ActivityState *state,
                                  const E63ActivityHost *host,
                                  const char *event,
                                  const E63JavaValue *args, unsigned count)
    {
    /* Existing 0.2 preview ABI and no-op superclass behavior unchanged. */
    return activity_event_inner(session,state,host,0,event,args,count);
    }

E63JavaStatus e63_activity_event_framework(const E63JavaSession *session,
                                  E63ActivityState *state,
                                  const E63ActivityHost *host,
                                  const E63FrameworkDispatch *framework,
                                  const char *event,
                                  const E63JavaValue *args, unsigned count)
    {
    if (!framework || !framework->invoke) return E63_JAVA_UNSUPPORTED;
    return activity_event_inner(session,state,host,framework,event,args,count);
    }
