#include "binder_ipc.h"
#include <stdlib.h>
#include <string.h>

/* Android 4.2, 32-bit flat_binder_object (type,flags,handle,cookie).
 * B_PACK_CHARS('s','h','*',0x85); BINDER_TYPE_BINDER uses 'b'.
 * See AOSP frameworks/native/libs/binder/Parcel.cpp, pinned 4.2.2_r1.2. */
#define FLAT_HANDLE 0x73682a85u
#define FLAT_BINDER 0x73622a85u
#define FLAT_FLAGS 0x17fu
#define FLAT_BYTES 16u
#define MAX_DEPTH 8u

typedef struct BinderNode {
    uint32_t handle,owner_pid,owner_uid;
    E63BinderService callback;
    void *context;
    E63BinderClient *owner; /* revoke every handle if exporting session dies */
    uint8_t published;
} BinderNode;
typedef struct BinderServiceName {
    char name[E63_BINDER_MAX_NAME];
    uint32_t handle;
    uint8_t allow_isolated;
} BinderServiceName;
struct E63BinderClient {
    E63BinderDomain *domain;
    E63BinderClient *next;
    uint32_t pid,uid;
    uint16_t refs[E63_BINDER_MAX_NODES];
};
struct E63BinderDomain {
    BinderNode nodes[E63_BINDER_MAX_NODES];
    BinderServiceName services[E63_BINDER_MAX_SERVICES];
    E63BinderClient *clients;
    uint32_t next_handle;
    unsigned service_count,depth;
};
static uint32_t load32(const uint8_t *p)
    {return (uint32_t)p[0]|((uint32_t)p[1]<<8u)|
            ((uint32_t)p[2]<<16u)|((uint32_t)p[3]<<24u);}
static void store32(uint8_t *p,uint32_t v)
    {p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8u);
     p[2]=(uint8_t)(v>>16u);p[3]=(uint8_t)(v>>24u);}
static int valid_size(const E63BinderParcel *p)
    {return p && p->length<=E63_BINDER_MAX_PARCEL &&
                 p->cursor<=p->length && p->objects<=E63_BINDER_MAX_OBJECTS;}
void e63_binder_parcel_reset(E63BinderParcel *p)
    {if (p) memset(p,0,sizeof(*p));}
E63BinderResult e63_binder_write_int(E63BinderParcel *p,int32_t value)
    {
    if (!valid_size(p) || p->length%4u) return E63_BINDER_BAD_INPUT;
    if (p->length>E63_BINDER_MAX_PARCEL-4u) return E63_BINDER_BUDGET;
    store32(p->bytes+p->length,(uint32_t)value);
    p->length=(uint16_t)(p->length+4u);
    return E63_BINDER_OK;
    }
E63BinderResult e63_binder_read_int(E63BinderParcel *p,int32_t *out)
    {
    if (out) *out=0;
    if (!out || !valid_size(p)) return E63_BINDER_BAD_INPUT;
    if (p->cursor%4u || p->cursor>p->length ||
        (unsigned)(p->length-p->cursor)<4u) return E63_BINDER_MALFORMED;
    *out=(int32_t)load32(p->bytes+p->cursor);
    p->cursor=(uint16_t)(p->cursor+4u);
    return E63_BINDER_OK;
    }
E63BinderResult e63_binder_write_string(E63BinderParcel *p,const char *value)
    {
    size_t n=0u,i,pad;
    E63BinderResult rc;
    if (!valid_size(p) || !value) return E63_BINDER_BAD_INPUT;
    while (n<E63_BINDER_MAX_NAME && value[n])
        {
        if ((unsigned char)value[n]<32u ||
            (unsigned char)value[n]>126u) return E63_BINDER_UNSUPPORTED;
        ++n;
        }
    if (n>=E63_BINDER_MAX_NAME) return E63_BINDER_BAD_INPUT;
    pad=((n+1u)*2u+3u)&~3u;
    if ((size_t)p->length+4u+pad>E63_BINDER_MAX_PARCEL)
        return E63_BINDER_BUDGET;
    rc=e63_binder_write_int(p,(int32_t)n);
    if (rc!=E63_BINDER_OK) return rc;
    memset(p->bytes+p->length,0,pad);
    for (i=0u;i<n;++i) p->bytes[p->length+2u*i]=(uint8_t)value[i];
    p->length=(uint16_t)(p->length+pad);
    return E63_BINDER_OK;
    }
E63BinderResult e63_binder_read_string(E63BinderParcel *p,char *out,
                                      size_t out_bytes)
    {
    int32_t length;
    size_t n,pad,i;
    E63BinderResult rc;
    if (out && out_bytes) out[0]=0;
    if (!out || !out_bytes || !valid_size(p)) return E63_BINDER_BAD_INPUT;
    rc=e63_binder_read_int(p,&length);
    if (rc!=E63_BINDER_OK) return rc;
    if (length<0 || (uint32_t)length>=E63_BINDER_MAX_NAME)
        return E63_BINDER_UNSUPPORTED;
    n=(size_t)length;
    if (n>=out_bytes) return E63_BINDER_BUDGET;
    pad=((n+1u)*2u+3u)&~3u;
    if (pad>(size_t)(p->length-p->cursor)) return E63_BINDER_MALFORMED;
    for (i=0u;i<n;++i)
        {
        unsigned c=p->bytes[p->cursor+2u*i];
        if (c<32u || c>126u || p->bytes[p->cursor+2u*i+1u])
            return E63_BINDER_UNSUPPORTED;
        }
    /* Zero terminator AND padding are required to avoid malformed aliases. */
    for (i=n*2u;i<pad;++i)
        if (p->bytes[p->cursor+i]) return E63_BINDER_MALFORMED;
    for (i=0u;i<n;++i) out[i]=(char)p->bytes[p->cursor+2u*i];
    out[n]=0;
    p->cursor=(uint16_t)(p->cursor+pad);
    return E63_BINDER_OK;
    }
E63BinderResult e63_binder_write_token(E63BinderParcel *p,const char *name)
    {
    E63BinderResult rc;
    if (!valid_size(p) || !name) return E63_BINDER_BAD_INPUT;
    rc=e63_binder_write_int(p,(int32_t)E63_BINDER_STRICT_MODE_GATHER);
    if (rc!=E63_BINDER_OK) return rc;
    return e63_binder_write_string(p,name);
    }
E63BinderResult e63_binder_read_token(E63BinderParcel *p,const char *name)
    {
    int32_t strict_policy;
    char actual[E63_BINDER_MAX_NAME];
    E63BinderResult rc;
    if (!valid_size(p) || !name) return E63_BINDER_BAD_INPUT;
    rc=e63_binder_read_int(p,&strict_policy);
    if (rc!=E63_BINDER_OK) return rc;
    /* StrictMode policy belongs to the IPC caller, never the guest path. */
    rc=e63_binder_read_string(p,actual,sizeof(actual));
    if (rc!=E63_BINDER_OK) return rc;
    return strcmp(actual,name)==0 ? E63_BINDER_OK : E63_BINDER_DENIED;
    }
E63BinderResult e63_binder_write_handle(E63BinderParcel *p,uint32_t handle)
    {
    unsigned at;
    if (!valid_size(p) || p->length%4u) return E63_BINDER_BAD_INPUT;
    if (p->length>E63_BINDER_MAX_PARCEL-FLAT_BYTES ||
        (handle && p->objects>=E63_BINDER_MAX_OBJECTS))
        return E63_BINDER_BUDGET;
    at=p->length;
    store32(p->bytes+at,handle ? FLAT_HANDLE : FLAT_BINDER);
    store32(p->bytes+at+4u,FLAT_FLAGS);
    store32(p->bytes+at+8u,handle);
    store32(p->bytes+at+12u,0u);
    if (handle) p->object_offsets[p->objects++]=(uint16_t)at;
    p->length=(uint16_t)(at+FLAT_BYTES);
    return E63_BINDER_OK;
    }
E63BinderResult e63_binder_read_handle(E63BinderParcel *p,uint32_t *out)
    {
    unsigned i,at;
    uint32_t type,handle;
    if (out) *out=0u;
    if (!out || !valid_size(p)) return E63_BINDER_BAD_INPUT;
    at=p->cursor;
    if (at%4u || at>p->length || p->length-at<FLAT_BYTES)
        return E63_BINDER_MALFORMED;
    type=load32(p->bytes+at);
    handle=load32(p->bytes+at+8u);
    if (load32(p->bytes+at+4u)!=FLAT_FLAGS ||
        load32(p->bytes+at+12u)!=0u) return E63_BINDER_MALFORMED;
    if (type==FLAT_BINDER && handle==0u)
        {p->cursor=(uint16_t)(at+FLAT_BYTES);return E63_BINDER_OK;}
    if (type!=FLAT_HANDLE || !handle) return E63_BINDER_UNSUPPORTED;
    for (i=0u;i<p->objects;++i)
        if (p->object_offsets[i]==at)
            {p->cursor=(uint16_t)(at+FLAT_BYTES);*out=handle;
             return E63_BINDER_OK;}
    return E63_BINDER_MALFORMED; /* data bytes alone cannot forge a handle */
    }
E63BinderResult e63_binder_parcel_validate(const E63BinderParcel *p)
    {
    unsigned i,previous=0u;
    if (!valid_size(p) || p->length%4u) return E63_BINDER_MALFORMED;
    for (i=0u;i<p->objects;++i)
        {
        unsigned at=p->object_offsets[i];
        uint32_t handle;
        if (at%4u || at>p->length || p->length-at<FLAT_BYTES ||
            (i && at<previous+FLAT_BYTES)) return E63_BINDER_MALFORMED;
        if (load32(p->bytes+at)!=FLAT_HANDLE ||
            load32(p->bytes+at+4u)!=FLAT_FLAGS ||
            !(handle=load32(p->bytes+at+8u)) ||
            load32(p->bytes+at+12u)) return E63_BINDER_MALFORMED;
        previous=at;
        }
    return E63_BINDER_OK;
    }
static int find_node(E63BinderDomain *d,uint32_t handle)
    {
    unsigned i;
    if (!d || !handle) return -1;
    for (i=0u;i<E63_BINDER_MAX_NODES;++i)
        if (d->nodes[i].handle==handle) return (int)i;
    return -1;
    }
static void purge_node(E63BinderDomain *d,unsigned slot)
    {
    E63BinderClient *client;
    if (!d || d->nodes[slot].published || !d->nodes[slot].handle) return;
    for (client=d->clients;client;client=client->next)
        if (client->refs[slot]) return;
    memset(&d->nodes[slot],0,sizeof(d->nodes[slot]));
    }
E63BinderDomain *e63_binder_new(void)
    {
    E63BinderDomain *d=(E63BinderDomain*)calloc(1u,sizeof(*d));
    if (d) d->next_handle=1u;
    return d;
    }
void e63_binder_free(E63BinderDomain *d)
    {
    E63BinderClient *client;
    if (!d) return;
    for (client=d->clients;client;client=client->next)
        {client->domain=0;memset(client->refs,0,sizeof(client->refs));}
    memset(d,0,sizeof(*d));free(d);
    }
E63BinderClient *e63_binder_connect(E63BinderDomain *d,
                                    uint32_t pid,uint32_t uid)
    {
    E63BinderClient *c;
    if (!d || !pid || d->next_handle==0u) return 0;
    c=(E63BinderClient*)calloc(1u,sizeof(*c));
    if (!c) return 0;
    c->domain=d;c->pid=pid;c->uid=uid;
    c->next=d->clients;d->clients=c;
    return c;
    }
void e63_binder_disconnect(E63BinderClient *c)
    {
    E63BinderDomain *d;
    E63BinderClient **link;
    unsigned i;
    if (!c) return;
    d=c->domain;
    if (d)
        {
        link=&d->clients;
        while (*link && *link!=c) link=&(*link)->next;
        if (*link==c) *link=c->next;
        /* An owner dying invalidates its endpoints and published services.
         * Forget all other clients' references BEFORE a slot can be reused;
         * otherwise a stale ref could authorize a newly exported handle. */
        for (i=0u;i<E63_BINDER_MAX_NODES;++i)
            if (d->nodes[i].owner==c)
                {
                unsigned j=0u;
                uint32_t dead=d->nodes[i].handle;
                E63BinderClient *other;
                while (j<d->service_count)
                    {
                    if (d->services[j].handle==dead)
                        {
                        --d->service_count;
                        if (j<d->service_count)
                            memmove(&d->services[j],&d->services[j+1],
                                    (d->service_count-j)*sizeof(d->services[0]));
                        memset(&d->services[d->service_count],0,
                               sizeof(d->services[0]));
                        }
                    else ++j;
                    }
                for (other=d->clients;other;other=other->next)
                    other->refs[i]=0u;
                memset(&d->nodes[i],0,sizeof(d->nodes[i]));
                }
        for (i=0u;i<E63_BINDER_MAX_NODES;++i)
            purge_node(d,i);
        }
    memset(c,0,sizeof(*c));free(c);
    }
E63BinderResult e63_binder_export(E63BinderClient *c,
                E63BinderService service,void *context,uint32_t *out_handle)
    {
    unsigned i;
    E63BinderDomain *d;
    if (out_handle) *out_handle=0u;
    if (!c || !(d=c->domain) || !service || !out_handle)
        return E63_BINDER_BAD_INPUT;
    if (!d->next_handle) return E63_BINDER_BUDGET;
    for (i=0u;i<E63_BINDER_MAX_NODES;++i)
        if (!d->nodes[i].handle)
            {
            BinderNode *n=&d->nodes[i];
            n->handle=d->next_handle++;
            n->owner_pid=c->pid;n->owner_uid=c->uid;
            n->callback=service;n->context=context;n->owner=c;
            c->refs[i]=1u;*out_handle=n->handle;
            return E63_BINDER_OK;
            }
    return E63_BINDER_BUDGET;
    }
E63BinderResult e63_binder_release(E63BinderClient *c,uint32_t handle)
    {
    int index;
    if (!c || !c->domain || !(index=find_node(c->domain,handle)+1))
        return E63_BINDER_BAD_INPUT;
    if (!c->refs[index-1]) return E63_BINDER_DENIED;
    --c->refs[index-1];
    purge_node(c->domain,(unsigned)(index-1));
    return E63_BINDER_OK;
    }
static int service_name_ok(const char *name)
    {
    unsigned i;
    if (!name || !*name) return 0;
    for (i=0u;i<E63_BINDER_MAX_NAME && name[i];++i)
        {
        char c=name[i];
        if (!((c>='A' && c<='Z') || (c>='a' && c<='z') ||
              (c>='0' && c<='9') || c=='.' || c=='_' || c=='-')) return 0;
        }
    return i>0u && i<E63_BINDER_MAX_NAME;
    }
static E63BinderResult manager(E63BinderClient *c,uint32_t code,
                               E63BinderParcel *request,E63BinderParcel *reply)
    {
    E63BinderDomain *d=c->domain;
    char name[E63_BINDER_MAX_NAME];
    E63BinderResult rc;
    unsigned i;
    int32_t flag;
    uint32_t handle;
    rc=e63_binder_read_token(request,E63_BINDER_SERVICE_INTERFACE);
    if (rc!=E63_BINDER_OK) return rc;
    if (code==E63_BINDER_SERVICE_GET || code==E63_BINDER_SERVICE_CHECK)
        {
        rc=e63_binder_read_string(request,name,sizeof(name));
        if (rc!=E63_BINDER_OK) return rc;
        if (request->cursor!=request->length || request->objects ||
            !service_name_ok(name)) return E63_BINDER_MALFORMED;
        handle=0u;
        for (i=0u;i<d->service_count;++i)
            if (strcmp(d->services[i].name,name)==0)
                {
                unsigned user=c->uid%100000u;
                if (user<99000u || d->services[i].allow_isolated)
                    handle=d->services[i].handle;
                break;
                }
        return e63_binder_write_handle(reply,handle);
        }
    if (code==E63_BINDER_SERVICE_ADD)
        {
        if (c->uid!=0u && c->uid!=1000u) return E63_BINDER_DENIED;
        rc=e63_binder_read_string(request,name,sizeof(name));
        if (rc!=E63_BINDER_OK) return rc;
        rc=e63_binder_read_handle(request,&handle);
        if (rc!=E63_BINDER_OK) return rc;
        rc=e63_binder_read_int(request,&flag);
        if (rc!=E63_BINDER_OK) return rc;
        if (request->cursor!=request->length || request->objects!=1u ||
            !service_name_ok(name) || flag<0 || flag>1)
            return E63_BINDER_MALFORMED;
        i=(unsigned)(find_node(d,handle)+1);
        if (!handle || !i || !c->refs[i-1] ||
            d->nodes[i-1].owner_pid!=c->pid ||
            d->nodes[i-1].owner_uid!=c->uid) return E63_BINDER_DENIED;
        for (i=0u;i<d->service_count;++i)
            if (strcmp(d->services[i].name,name)==0)
                return e63_binder_write_int(reply,-17); /* EEXIST */
        if (d->service_count>=E63_BINDER_MAX_SERVICES)
            return e63_binder_write_int(reply,-12); /* ENOMEM */
        i=d->service_count;
        strcpy(d->services[i].name,name);
        d->services[i].handle=handle;
        d->services[i].allow_isolated=(uint8_t)flag;
        ++d->service_count;
        d->nodes[find_node(d,handle)].published=1u;
        return e63_binder_write_int(reply,0);
        }
    if (code==E63_BINDER_SERVICE_LIST)
        {
        rc=e63_binder_read_int(request,&flag);
        if (rc!=E63_BINDER_OK) return rc;
        if (request->cursor!=request->length || request->objects ||
            flag<0) return E63_BINDER_MALFORMED;
        if ((unsigned)flag>=d->service_count) return E63_BINDER_NOT_FOUND;
        return e63_binder_write_string(reply,d->services[flag].name);
        }
    return E63_BINDER_UNSUPPORTED;
    }
E63BinderResult e63_binder_transact(E63BinderClient *c,uint32_t handle,
                         uint32_t code,const E63BinderParcel *request,
                         E63BinderParcel *reply)
    {
    E63BinderDomain *d;
    E63BinderParcel data;
    E63BinderResult rc;
    unsigned i;
    uint16_t grants[E63_BINDER_MAX_NODES];
    int index;
    if (reply && reply==request) return E63_BINDER_BAD_INPUT;
    if (reply) e63_binder_parcel_reset(reply);
    if (!c || !(d=c->domain) || !request || !reply ||
        !code || e63_binder_parcel_validate(request)!=E63_BINDER_OK)
        return E63_BINDER_BAD_INPUT;
    if (d->depth>=MAX_DEPTH) return E63_BINDER_BUDGET;
    if (handle)
        {
        index=find_node(d,handle);
        if (index<0) return E63_BINDER_NOT_FOUND;
        if (!c->refs[index]) return E63_BINDER_DENIED;
        }
    else index=-1;
    for (i=0u;i<request->objects;++i)
        {
        uint32_t object=load32(request->bytes+request->object_offsets[i]+8u);
        int slot=find_node(d,object);
        if (slot<0 || !c->refs[slot]) return E63_BINDER_DENIED;
        }
    data=*request;
    data.cursor=0u;
    ++d->depth;
    if (index<0) rc=manager(c,code,&data,reply);
    else rc=d->nodes[index].callback(d->nodes[index].context,code,
                       c->pid,c->uid,&data,reply);
    --d->depth;
    if (rc!=E63_BINDER_OK ||
        e63_binder_parcel_validate(reply)!=E63_BINDER_OK)
        {e63_binder_parcel_reset(reply);
         return rc!=E63_BINDER_OK ? rc : E63_BINDER_MALFORMED;}
    /* Grant the caller an owned reference ONLY after authenticating every
     * returned handle. Fail the whole transaction before mutating refcounts. */
    memset(grants,0,sizeof(grants));
    for (i=0u;i<reply->objects;++i)
        {
        uint32_t object=load32(reply->bytes+reply->object_offsets[i]+8u);
        int slot=find_node(d,object);
        if (slot<0 || !d->nodes[slot].published ||
            c->refs[slot]>=0xffffu-grants[slot])
            {e63_binder_parcel_reset(reply);return E63_BINDER_DENIED;}
        ++grants[slot];
        }
    for (i=0u;i<E63_BINDER_MAX_NODES;++i)
        c->refs[i]=(uint16_t)(c->refs[i]+grants[i]);
    return E63_BINDER_OK;
    }
