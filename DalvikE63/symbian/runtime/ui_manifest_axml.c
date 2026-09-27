#include "ui_manifest_axml.h"
#include <string.h>

#define NO_STRING 0xffffffffu
#define MAX_STRINGS 2048u
#define MAX_NODES 4096u
#define MAX_ATTRS 64u
#define MAX_DEPTH 64u
#define MAX_NAMESPACES 16u
#define MAX_TEXT 192u
#define ANDROID_URI "http://schemas.android.com/apk/res/android"

typedef struct AxmlReader {
    E63BootReadAt read_at;
    void *context;
    uint32_t bytes;
    uint32_t strings, offsets, data_start, data_end;
    uint32_t android_uri;
    unsigned android_active;
} AxmlReader;

typedef struct Namespace {
    uint32_t prefix, uri;
} Namespace;

typedef struct Walk {
    uint32_t stack[MAX_DEPTH];
    Namespace namespaces[MAX_NAMESPACES];
    unsigned depth, namespace_count, root_seen, root_closed, app_seen;
    unsigned app_depth, component_depth, filter_depth;
    unsigned declared, matched_filter, filter_action, filter_category;
    uint32_t component_line;
    const char *package_name, *descriptor, *action, *category;
    unsigned service;
} Walk;

static uint16_t le16(const uint8_t *p)
    {return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1]<<8u));}
static uint32_t le32(const uint8_t *p)
    {return (uint32_t)p[0] | ((uint32_t)p[1]<<8u) |
            ((uint32_t)p[2]<<16u) | ((uint32_t)p[3]<<24u);}
static int within(uint32_t at,uint32_t length,uint32_t limit)
    {return at<=limit && length<=limit-at;}
static int bounded_length(const char *s)
    {
    unsigned n;
    if (!s) return -1;
    for (n=0u;n<MAX_TEXT;++n) if (!s[n]) return (int)n;
    return -1;
    }
static E63UiManifestStatus read_part(AxmlReader *r,uint32_t at,
                                     uint8_t *dst,uint32_t n)
    {
    if (!within(at,n,r->bytes)) return E63_UI_MANIFEST_INVALID;
    return r->read_at(r->context,at,dst,n) ?
           E63_UI_MANIFEST_OK : E63_UI_MANIFEST_IO;
    }

/* String pool offsets are never trusted as pointers. This reader only needs
 * ASCII XML tag/attribute names, package names, Java classes and intents;
 * an unsupported encoding is rejected rather than silently lossy-converted. */
static E63UiManifestStatus string_at(AxmlReader *r,uint32_t index,
                                     char *text)
    {
    uint8_t small[4],buffer[128];
    uint32_t at,length,base,j=0u;
    E63UiManifestStatus result;
    if (index>=r->strings || !within(r->offsets,index*4u+4u,
                                     r->data_start))
        return E63_UI_MANIFEST_INVALID;
    result=read_part(r,r->offsets+index*4u,small,4u);
    if (result!=E63_UI_MANIFEST_OK) return result;
    base=le32(small);
    if (base>=r->data_end-r->data_start)
        return E63_UI_MANIFEST_INVALID;
    at=r->data_start+base;
    result=read_part(r,at,small,2u);
    if (result!=E63_UI_MANIFEST_OK) return result;
    length=le16(small);at+=2u;
    if (length&0x8000u)
        {
        result=read_part(r,at,small,2u);
        if (result!=E63_UI_MANIFEST_OK) return result;
        length=((length&0x7fffu)<<16u)|le16(small);
        at+=2u;
        }
    if (length>=MAX_TEXT) return E63_UI_MANIFEST_UNSUPPORTED;
    if (!within(at,(length+1u)*2u,r->data_end))
        return E63_UI_MANIFEST_INVALID;
    while (j<length)
        {
        uint32_t n=length-j,k;
        if (n>64u) n=64u;
        result=read_part(r,at,buffer,n*2u);
        if (result!=E63_UI_MANIFEST_OK) return result;
        for (k=0u;k<n;++k)
            {
            if (buffer[k*2u+1u] || buffer[k*2u]<32u ||
                buffer[k*2u]>=127u)
                return E63_UI_MANIFEST_UNSUPPORTED;
            text[j+k]=(char)buffer[k*2u];
            }
        at+=n*2u;j+=n;
        }
    result=read_part(r,at,small,2u);
    if (result!=E63_UI_MANIFEST_OK) return result;
    if (le16(small)) return E63_UI_MANIFEST_INVALID;
    text[length]=0;
    return E63_UI_MANIFEST_OK;
    }
static E63UiManifestStatus equals(AxmlReader *r,uint32_t index,
                                  const char *expected,int *yes)
    {
    char text[MAX_TEXT];
    E63UiManifestStatus s=string_at(r,index,text);
    if (s==E63_UI_MANIFEST_OK) *yes=strcmp(text,expected)==0;
    return s;
    }
static E63UiManifestStatus read_value(AxmlReader *r,const uint8_t *attribute,
                                      char *out)
    {
    const uint32_t raw=le32(attribute+8u);
    const uint32_t data=le32(attribute+16u);
    if (le16(attribute+12u)!=8u || attribute[14u] ||
        attribute[15u]!=3u || data>=r->strings ||
        (raw!=NO_STRING && raw!=data))
        return E63_UI_MANIFEST_INVALID;
    return string_at(r,data,out);
    }
static int matches_class(const char *package_name,const char *relative,
                         const char *descriptor)
    {
    char full[MAX_TEXT],expect[MAX_TEXT];
    size_t pn=strlen(package_name),rn=strlen(relative),dn=strlen(descriptor);
    size_t len,i;
    if (!rn || dn<3u || descriptor[0]!='L' || descriptor[dn-1u]!=';')
        return 0;
    if (relative[0]=='.' || !strchr(relative,'.'))
        {
        const int add_dot=relative[0]!='.';
        if (pn+rn+(unsigned)add_dot>=MAX_TEXT) return 0;
        memcpy(full,package_name,pn);
        if (add_dot) full[pn++]='.';
        memcpy(full+pn,relative,rn+1u);
        }
    else
        {
        if (rn>=MAX_TEXT) return 0;
        memcpy(full,relative,rn+1u);
        }
    len=strlen(full);
    if (len+2u>=MAX_TEXT) return 0;
    expect[0]='L';
    for (i=0u;i<len;++i)
        expect[i+1u]=full[i]=='.' ? '/' : full[i];
    expect[len+1u]=';';expect[len+2u]=0;
    return strcmp(expect,descriptor)==0;
    }

static E63UiManifestStatus string_pool(AxmlReader *r,uint32_t at,
                                       uint16_t header,uint32_t size)
    {
    uint8_t data[20];
    uint32_t count,styles,flags,strings_at,styles_at;
    E63UiManifestStatus s;
    if (r->strings || header!=28u || size<28u)
        return E63_UI_MANIFEST_INVALID;
    s=read_part(r,at+8u,data,sizeof(data));
    if (s!=E63_UI_MANIFEST_OK) return s;
    count=le32(data);styles=le32(data+4u);flags=le32(data+8u);
    strings_at=le32(data+12u);styles_at=le32(data+16u);
    if (!count || count>MAX_STRINGS || styles || styles_at || flags ||
        strings_at<28u+count*4u || strings_at>=size)
        return flags ? E63_UI_MANIFEST_UNSUPPORTED : E63_UI_MANIFEST_INVALID;
    r->strings=count;
    r->offsets=at+28u;
    r->data_start=at+strings_at;
    r->data_end=at+size;
    return E63_UI_MANIFEST_OK;
    }

static E63UiManifestStatus start_namespace(AxmlReader *r,Walk *w,
                                            uint32_t at,uint32_t size)
    {
    uint8_t p[8];char uri[MAX_TEXT];
    uint32_t prefix,id;
    E63UiManifestStatus s;
    if (size!=24u || w->namespace_count>=MAX_NAMESPACES)
        return E63_UI_MANIFEST_INVALID;
    s=read_part(r,at+16u,p,8u);
    if (s!=E63_UI_MANIFEST_OK) return s;
    prefix=le32(p);id=le32(p+4u);
    if (prefix>=r->strings || id>=r->strings)
        return E63_UI_MANIFEST_INVALID;
    s=string_at(r,id,uri);
    if (s!=E63_UI_MANIFEST_OK) return s;
    if (strcmp(uri,ANDROID_URI)==0)
        {
        if (r->android_active) return E63_UI_MANIFEST_INVALID;
        r->android_uri=id;r->android_active=1u;
        }
    w->namespaces[w->namespace_count].prefix=prefix;
    w->namespaces[w->namespace_count].uri=id;
    ++w->namespace_count;
    return E63_UI_MANIFEST_OK;
    }
static E63UiManifestStatus end_namespace(AxmlReader *r,Walk *w,
                                          uint32_t at,uint32_t size)
    {
    uint8_t p[8];
    E63UiManifestStatus s;
    if (size!=24u || !w->namespace_count)
        return E63_UI_MANIFEST_INVALID;
    s=read_part(r,at+16u,p,8u);
    if (s!=E63_UI_MANIFEST_OK) return s;
    --w->namespace_count;
    if (le32(p)!=w->namespaces[w->namespace_count].prefix ||
        le32(p+4u)!=w->namespaces[w->namespace_count].uri)
        return E63_UI_MANIFEST_INVALID;
    if (r->android_active && le32(p+4u)==r->android_uri)
        r->android_active=0u;
    return E63_UI_MANIFEST_OK;
    }

/* Direct children of <application> are class declarations. Aliases and
 * children of an unrelated element MUST NOT be interpreted as the class. */
static E63UiManifestStatus start_element(AxmlReader *r,Walk *w,
                                         uint32_t at,uint32_t size)
    {
    uint8_t ext[20],attribute[20],line_bytes[4];
    uint32_t ns,name,attributes,i;
    uint16_t attr_start,attr_size;
    char tag[MAX_TEXT],name_value[MAX_TEXT]={0},package_value[MAX_TEXT]={0};
    unsigned has_name=0u,has_package=0u,enabled=1u;
    int tag_manifest=0,tag_app=0,tag_component=0,tag_filter=0;
    int tag_action=0,tag_category=0,is_activity=0,is_service=0;
    E63UiManifestStatus s;
    if (size<36u || w->depth>=MAX_DEPTH || w->root_closed)
        return E63_UI_MANIFEST_INVALID;
    s=read_part(r,at+16u,ext,sizeof(ext));
    if (s!=E63_UI_MANIFEST_OK) return s;
    ns=le32(ext);name=le32(ext+4u);
    attr_start=le16(ext+8u);attr_size=le16(ext+10u);
    attributes=le16(ext+12u);
    if (name>=r->strings || ns!=NO_STRING || attr_start!=20u ||
        attr_size!=20u || attributes>MAX_ATTRS ||
        size!=36u+attributes*20u)
        return E63_UI_MANIFEST_INVALID;
    s=string_at(r,name,tag);
    if (s!=E63_UI_MANIFEST_OK) return s;
    tag_manifest=strcmp(tag,"manifest")==0;
    tag_app=strcmp(tag,"application")==0;
    is_activity=strcmp(tag,"activity")==0;
    is_service=strcmp(tag,"service")==0;
    tag_filter=strcmp(tag,"intent-filter")==0;
    tag_action=strcmp(tag,"action")==0;
    tag_category=strcmp(tag,"category")==0;
    if (!w->depth && (!tag_manifest || w->root_seen))
        return E63_UI_MANIFEST_INVALID;
    tag_component=(w->app_depth && w->depth==w->app_depth &&
                   (is_activity || is_service));
    for (i=0u;i<attributes;++i)
        {
        uint32_t attr_ns,attr_name;
        int is_name=0,is_enabled=0,is_package=0;
        s=read_part(r,at+36u+i*20u,attribute,20u);
        if (s!=E63_UI_MANIFEST_OK) return s;
        attr_ns=le32(attribute);attr_name=le32(attribute+4u);
        if (attr_name>=r->strings ||
            (attr_ns!=NO_STRING && attr_ns>=r->strings) ||
            le16(attribute+12u)!=8u || attribute[14u])
            return E63_UI_MANIFEST_INVALID;
        if (!w->depth && tag_manifest && attr_ns==NO_STRING)
            {
            s=equals(r,attr_name,"package",&is_package);
            if (s!=E63_UI_MANIFEST_OK) return s;
            if (is_package)
                {
                if (has_package) return E63_UI_MANIFEST_INVALID;
                s=read_value(r,attribute,package_value);
                if (s!=E63_UI_MANIFEST_OK) return s;
                has_package=1u;
                }
            }
        if (attr_ns==r->android_uri && r->android_active &&
            (tag_component ||
             (w->filter_depth && w->depth==w->filter_depth &&
              (tag_action || tag_category))))
            {
            s=equals(r,attr_name,"name",&is_name);
            if (s!=E63_UI_MANIFEST_OK) return s;
            if (is_name && (tag_component ||
                (w->filter_depth && w->depth==w->filter_depth &&
                 (tag_action || tag_category))))
                {
                if (has_name) return E63_UI_MANIFEST_INVALID;
                s=read_value(r,attribute,name_value);
                if (s!=E63_UI_MANIFEST_OK) return s;
                has_name=1u;
                }
            if (tag_component)
                {
                s=equals(r,attr_name,"enabled",&is_enabled);
                if (s!=E63_UI_MANIFEST_OK) return s;
                if (is_enabled)
                    {
                    if (attribute[15u]!=0x12u)
                        return E63_UI_MANIFEST_INVALID;
                    enabled=le32(attribute+16u)!=0u;
                    }
                }
            }
        }
    if (!w->depth)
        {
        if (!has_package) return E63_UI_MANIFEST_INVALID;
        if (strcmp(package_value,w->package_name))
            return E63_UI_MANIFEST_NOT_FOUND;
        w->root_seen=1u;
        }
    if (tag_app && w->depth==1u)
        {
        if (w->app_seen) return E63_UI_MANIFEST_INVALID;
        w->app_seen=1u;w->app_depth=w->depth+1u;
        }
    if (tag_component && enabled && has_name &&
        w->service==(unsigned)is_service &&
        matches_class(w->package_name,name_value,w->descriptor))
        {
        if (w->declared) return E63_UI_MANIFEST_INVALID;
        w->declared=1u;w->component_depth=w->depth+1u;
        s=read_part(r,at+8u,line_bytes,4u);
        if (s!=E63_UI_MANIFEST_OK) return s;
        w->component_line=le32(line_bytes);
        }
    if (tag_filter && w->component_depth &&
        w->depth==w->component_depth)
        {
        if (w->filter_depth) return E63_UI_MANIFEST_INVALID;
        w->filter_depth=w->depth+1u;
        w->filter_action=0u;w->filter_category=0u;
        }
    if (has_name && w->filter_depth && w->depth==w->filter_depth)
        {
        if (tag_action && w->action && !strcmp(name_value,w->action))
            w->filter_action=1u;
        if (tag_category && w->category && !strcmp(name_value,w->category))
            w->filter_category=1u;
        }
    w->stack[w->depth++]=name;
    return E63_UI_MANIFEST_OK;
    }
static E63UiManifestStatus end_element(AxmlReader *r,Walk *w,
                                       uint32_t at,uint32_t size)
    {
    uint8_t end[8];E63UiManifestStatus s;
    if (size!=24u || !w->depth)
        return E63_UI_MANIFEST_INVALID;
    s=read_part(r,at+16u,end,8u);
    if (s!=E63_UI_MANIFEST_OK) return s;
    if (le32(end)!=NO_STRING || le32(end+4u)!=w->stack[w->depth-1u])
        return E63_UI_MANIFEST_INVALID;
    if (w->filter_depth==w->depth)
        {
        if (w->filter_action && w->filter_category)
            ++w->matched_filter;
        w->filter_depth=0u;
        }
    if (w->component_depth==w->depth) w->component_depth=0u;
    if (w->app_depth==w->depth) w->app_depth=0u;
    --w->depth;
    if (!w->depth) w->root_closed=1u;
    return E63_UI_MANIFEST_OK;
    }

E63UiManifestStatus e63_ui_manifest_find(
    E63BootReadAt read_at,void *context,size_t bytes,
    const char *package_name,const char *class_descriptor,unsigned is_service,
    const char *intent_action,const char *intent_category,
    E63UiManifestMatch *out)
    {
    AxmlReader r;
    Walk w;
    uint8_t header[8];
    uint32_t at,nodes=0u;
    E63UiManifestStatus s;
    if (out) memset(out,0,sizeof(*out));
    if (!out || !read_at || bytes<40u || bytes>E63_UI_AXML_MAX_BYTES ||
        !package_name || !class_descriptor || is_service>1u ||
        (!!intent_action != !!intent_category) ||
        bounded_length(package_name)<1 ||
        bounded_length(class_descriptor)<3 ||
        (intent_action && (bounded_length(intent_action)<1 ||
                           bounded_length(intent_category)<1)))
        return E63_UI_MANIFEST_BAD_INPUT;
    memset(&r,0,sizeof(r));memset(&w,0,sizeof(w));
    r.read_at=read_at;r.context=context;r.bytes=(uint32_t)bytes;
    r.android_uri=NO_STRING;
    w.package_name=package_name;w.descriptor=class_descriptor;
    w.action=intent_action;w.category=intent_category;w.service=is_service;
    s=read_part(&r,0u,header,8u);
    if (s!=E63_UI_MANIFEST_OK) return s;
    if (le16(header)!=3u || le16(header+2u)!=8u ||
        le32(header+4u)!=r.bytes)
        return E63_UI_MANIFEST_INVALID;
    at=8u;
    while (at<r.bytes)
        {
        uint16_t kind,size_header;
        uint32_t size;
        if (++nodes>MAX_NODES || !within(at,8u,r.bytes) || (at&3u))
            return E63_UI_MANIFEST_INVALID;
        s=read_part(&r,at,header,8u);
        if (s!=E63_UI_MANIFEST_OK) return s;
        kind=le16(header);size_header=le16(header+2u);
        size=le32(header+4u);
        if (!size || (size&3u) || size_header<8u ||
            size_header>size || !within(at,size,r.bytes))
            return E63_UI_MANIFEST_INVALID;
        if (kind==1u && at==8u)
            s=string_pool(&r,at,size_header,size);
        else if (!r.strings) return E63_UI_MANIFEST_INVALID;
        else if (kind==0x0180u && size_header==8u && !w.root_seen)
            s=E63_UI_MANIFEST_OK; /* compiled resource ID map, not UI data */
        else if (kind==0x0100u && size_header==16u)
            s=start_namespace(&r,&w,at,size);
        else if (kind==0x0101u && size_header==16u)
            s=end_namespace(&r,&w,at,size);
        else if (kind==0x0102u && size_header==16u)
            s=start_element(&r,&w,at,size);
        else if (kind==0x0103u && size_header==16u)
            s=end_element(&r,&w,at,size);
        else if (kind==0x0104u && size_header==16u)
            {
            /* Settings AOSP has one genuine text node (` />\\n`) in a
             * different Activity's intent-filter. It cannot declare a
             * component/intent and is never accepted inside OUR component. */
            uint8_t value[12];
            if (size!=28u || !w.depth || w.component_depth)
                return E63_UI_MANIFEST_INVALID;
            s=read_part(&r,at+16u,value,12u);
            if (s==E63_UI_MANIFEST_OK &&
                (le32(value)>=r.strings || le16(value+4u)!=8u || value[6u]))
                s=E63_UI_MANIFEST_INVALID;
            }
        else return E63_UI_MANIFEST_UNSUPPORTED;
        if (s!=E63_UI_MANIFEST_OK) return s;
        at+=size;
        }
    if (at!=r.bytes || !w.root_seen || !w.root_closed ||
        !w.app_seen || w.depth || w.namespace_count || r.android_active)
        return E63_UI_MANIFEST_INVALID;
    if (w.declared!=1u || (intent_action && !w.matched_filter))
        return E63_UI_MANIFEST_NOT_FOUND;
    out->line=w.component_line;
    out->matching_filters=w.matched_filter;
    out->is_service=is_service;
    return E63_UI_MANIFEST_OK;
    }
