#include "boot_classpath.h"
#include <string.h>

static uint32_t le32(const uint8_t *p)
    {return (uint32_t)p[0] | ((uint32_t)p[1]<<8u) |
           ((uint32_t)p[2]<<16u) | ((uint32_t)p[3]<<24u);}

E63BootStatus e63_boot_index_open(E63BootIndex *out,
                                  E63BootReadAt read_at, void *context,
                                  size_t file_bytes)
    {
    uint8_t header[E63_BOOT_HEADER_BYTES];
    uint32_t entries;
    if (!out) return E63_BOOT_BAD_INPUT;
    memset(out,0,sizeof(*out));
    if (!read_at || file_bytes<E63_BOOT_HEADER_BYTES ||
        file_bytes>E63_BOOT_MAX_BYTES) return E63_BOOT_BAD_INPUT;
    if (!read_at(context,0u,header,sizeof(header))) return E63_BOOT_IO_ERROR;
    entries=le32(header+16u);
    if (memcmp(header,"E63BOOT2",8u)!=0 ||
        le32(header+8u)!=2u || le32(header+12u)!=E63_BOOT_RECORD_BYTES ||
        entries==0u || entries>E63_BOOT_MAX_CLASSES ||
        le32(header+20u)!=0u ||
        (uint64_t)E63_BOOT_HEADER_BYTES+
            (uint64_t)entries*E63_BOOT_RECORD_BYTES!=file_bytes)
        return E63_BOOT_UNTRUSTED;
    out->context=context;
    out->read_at=read_at;
    out->class_count=entries;
    out->total_bytes=(uint32_t)file_bytes;
    return E63_BOOT_OK;
    }

E63BootStatus e63_boot_find_class(const E63BootIndex *index,
                                  const char *descriptor,
                                  E63BootClass *out)
    {
    uint8_t row[E63_BOOT_RECORD_BYTES];
    uint32_t lo,hi,i;
    size_t wanted=0;
    if (!out) return E63_BOOT_BAD_INPUT;
    memset(out,0,sizeof(*out));
    if (!index || !index->read_at || !descriptor ||
        index->class_count==0u || index->class_count>E63_BOOT_MAX_CLASSES ||
        index->total_bytes<E63_BOOT_HEADER_BYTES+E63_BOOT_RECORD_BYTES ||
        (uint64_t)E63_BOOT_HEADER_BYTES+
            (uint64_t)index->class_count*E63_BOOT_RECORD_BYTES!=
                index->total_bytes) return E63_BOOT_BAD_INPUT;
    while (wanted<E63_BOOT_DESCRIPTOR_BYTES && descriptor[wanted]) ++wanted;
    if (wanted<3u || wanted>=E63_BOOT_DESCRIPTOR_BYTES ||
        descriptor[0]!='L' || descriptor[wanted-1u]!=';')
        return E63_BOOT_BAD_INPUT;
    lo=0u;hi=index->class_count;
    while (lo<hi)
        {
        uint32_t mid=lo+(hi-lo)/2u;
        uint32_t row_at=E63_BOOT_HEADER_BYTES+mid*E63_BOOT_RECORD_BYTES;
        uint32_t length,slot,class_def;
        size_t common;
        int diff;
        if (row_at>index->total_bytes-E63_BOOT_RECORD_BYTES ||
            !index->read_at(index->context,row_at,row,sizeof(row)))
            return E63_BOOT_IO_ERROR;
        slot=le32(row+256u);class_def=le32(row+260u);
        length=le32(row+264u);
        if (length<3u || length>=E63_BOOT_DESCRIPTOR_BYTES ||
            row[0]!='L' || row[length-1u]!=';' ||
            slot>=E63_BOOT_DEX_SLOTS || class_def>=10000u)
            return E63_BOOT_UNTRUSTED;
        for (i=length;i<E63_BOOT_DESCRIPTOR_BYTES;++i)
            if (row[i]!=0u) return E63_BOOT_UNTRUSTED;
        common=wanted<length ? wanted : length;
        diff=memcmp(descriptor,row,common);
        if (diff==0) diff=wanted<length ? -1 : wanted>length ? 1 : 0;
        if (diff==0)
            {out->dex_slot=slot;out->class_def_index=class_def;
             return E63_BOOT_OK;}
        if (diff<0) hi=mid;
        else lo=mid+1u;
        }
    return E63_BOOT_NOT_FOUND;
    }

static int dex_table(uint32_t count,uint32_t at,uint32_t stride,
                     size_t dex_bytes)
    {
    return count && at>=112u && (at&3u)==0u &&
           (uint64_t)at+(uint64_t)count*stride<=dex_bytes;
    }

static int dex_u32(E63BootReadAt read_at,void *context,uint32_t offset,
                   uint32_t *value)
    {
    uint8_t bytes[4];
    if (!read_at(context,offset,bytes,sizeof(bytes))) return 0;
    *value=le32(bytes);
    return 1;
    }

E63BootStatus e63_boot_confirm_class(const E63BootClass *located,
                                     const char *descriptor,
                                     E63BootReadAt dex_read_at,
                                     void *dex_context,size_t dex_bytes)
    {
    uint8_t head[112],name[261];
    uint32_t strings,strings_at,types,types_at,classes,classes_at;
    uint32_t data_at,data_size,type_idx,string_idx,string_at;
    uint32_t utf16=0u,shift=0u;
    size_t wanted=0u,available,i,prefix=0u;
    if (!located || !descriptor || !dex_read_at ||
        located->dex_slot>=E63_BOOT_DEX_SLOTS ||
        dex_bytes<112u || dex_bytes>32u*1024u*1024u)
        return E63_BOOT_BAD_INPUT;
    while (wanted<E63_BOOT_DESCRIPTOR_BYTES && descriptor[wanted]) ++wanted;
    if (wanted<3u || wanted>=E63_BOOT_DESCRIPTOR_BYTES ||
        descriptor[0]!='L' || descriptor[wanted-1u]!=';')
        return E63_BOOT_BAD_INPUT;
    if (!dex_read_at(dex_context,0u,head,sizeof(head))) return E63_BOOT_IO_ERROR;
    if ((memcmp(head,"dex\n035\0",8u)!=0 &&
         memcmp(head,"dex\n036\0",8u)!=0) || le32(head+32u)!=dex_bytes ||
        le32(head+36u)!=112u || le32(head+40u)!=0x12345678u)
        return E63_BOOT_UNTRUSTED;
    strings=le32(head+56u);strings_at=le32(head+60u);
    types=le32(head+64u);types_at=le32(head+68u);
    classes=le32(head+96u);classes_at=le32(head+100u);
    data_size=le32(head+104u);data_at=le32(head+108u);
    if (!dex_table(strings,strings_at,4u,dex_bytes) ||
        !dex_table(types,types_at,4u,dex_bytes) ||
        !dex_table(classes,classes_at,32u,dex_bytes) ||
        classes>10000u || located->class_def_index>=classes ||
        data_at<112u || (uint64_t)data_at+data_size>dex_bytes)
        return E63_BOOT_UNTRUSTED;
    if (!dex_u32(dex_read_at,dex_context,
                 classes_at+located->class_def_index*32u,&type_idx))
        return E63_BOOT_IO_ERROR;
    if (type_idx>=types) return E63_BOOT_UNTRUSTED;
    if (!dex_u32(dex_read_at,dex_context,types_at+type_idx*4u,&string_idx))
        return E63_BOOT_IO_ERROR;
    if (string_idx>=strings) return E63_BOOT_UNTRUSTED;
    if (!dex_u32(dex_read_at,dex_context,strings_at+string_idx*4u,&string_at))
        return E63_BOOT_IO_ERROR;
    if (string_at<data_at || (uint64_t)string_at>=
            (uint64_t)data_at+data_size) return E63_BOOT_UNTRUSTED;
    available=(size_t)((uint64_t)data_at+data_size-string_at);
    if (available>sizeof(name)) available=sizeof(name);
    if (!dex_read_at(dex_context,string_at,name,available))
        return E63_BOOT_IO_ERROR;
    for (i=0u;i<5u;++i)
        {
        if (i>=available || (i==4u && (name[i]&0xf0u)!=0u))
            return E63_BOOT_UNTRUSTED;
        utf16|=(uint32_t)(name[i]&0x7fu)<<shift;
        if ((name[i]&0x80u)==0u) {prefix=i+1u;break;}
        shift+=7u;
        }
    if (!prefix || utf16!=wanted || prefix+wanted>=available ||
        name[prefix+wanted]!=0u ||
        memcmp(name+prefix,descriptor,wanted)!=0)
        return E63_BOOT_UNTRUSTED;
    return E63_BOOT_OK;
    }

const char *e63_boot_status(E63BootStatus status)
    {
    switch (status)
        {
        case E63_BOOT_OK:return "resolved class definition (not executed)";
        case E63_BOOT_BAD_INPUT:return "invalid boot index request";
        case E63_BOOT_UNTRUSTED:return "invalid/untrusted boot index format";
        case E63_BOOT_NOT_FOUND:return "class not in pinned bootclasspath";
        case E63_BOOT_IO_ERROR:return "boot index read failed";
        default:return "unknown bootclasspath status";
        }
    }
