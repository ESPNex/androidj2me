#include "ui_apk_archive.h"
#include <string.h>

static uint16_t le16(const uint8_t *p)
    {return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1]<<8u));}
static uint32_t le32(const uint8_t *p)
    {return (uint32_t)p[0] | ((uint32_t)p[1]<<8u) |
            ((uint32_t)p[2]<<16u) | ((uint32_t)p[3]<<24u);}
static int within(uint64_t offset,uint64_t count,uint64_t end)
    {return offset<=end && count<=end-offset;}
static int read_part(E63BootReadAt read_at,void *ctx,uint32_t at,
                     uint8_t *out,size_t size)
    {
    size_t have=0u;
    if (!read_at || !out || size==0u) return 0;
    while (have<size)
        {
        size_t part=size-have;
        if (part>256u) part=256u;
        if (!read_at(ctx,at+(uint32_t)have,out+have,part)) return 0;
        have+=part;
        }
    return 1;
    }
static uint32_t crc_part(uint32_t crc,const uint8_t *src,size_t size)
    {
    size_t i;
    for (i=0u;i<size;++i)
        {
        unsigned j;
        crc^=src[i];
        for (j=0u;j<8u;++j)
            crc=(crc>>1u)^((crc&1u)?0xedb88320u:0u);
        }
    return crc;
    }

E63UiArchiveStatus e63_ui_apk_open(E63UiDexSlice *out,
                                   E63BootReadAt read_at,void *ctx,
                                   size_t bytes)
    {
    uint8_t end[22],central[46],name[256],local[30],local_name[256];
    uint8_t buffer[256];
    uint32_t dir_at,dir_bytes,dir_end,position,dex_crc=0u;
    uint32_t dex_at=0u,dex_bytes=0u,manifest_at=0u,manifest_bytes=0u;
    uint32_t resources_at=0u,resources_bytes=0u;
    uint16_t manifest_method=0u,resources_method=0u,entries,n;
    unsigned have_dex=0u,have_manifest=0u,have_resources=0u;
    E63UiArchiveStatus status=E63_UI_ARCHIVE_INVALID;
    if (!out) return E63_UI_ARCHIVE_BAD_INPUT;
    memset(out,0,sizeof(*out));
    if (!read_at || bytes<22u || bytes>E63_UI_APK_MAX_BYTES)
        return E63_UI_ARCHIVE_BAD_INPUT;
    if (!read_part(read_at,ctx,(uint32_t)(bytes-22u),end,sizeof(end)))
        return E63_UI_ARCHIVE_IO;
    /* This local build has no ZIP comment, multi-disk layout, or ZIP64. */
    if (le32(end)!=0x06054b50u || le16(end+4u)!=0u ||
        le16(end+6u)!=0u || le16(end+20u)!=0u ||
        le16(end+8u)!=le16(end+10u)) return E63_UI_ARCHIVE_UNSUPPORTED;
    entries=le16(end+10u);
    dir_at=le32(end+16u);dir_bytes=le32(end+12u);
    if (entries<3u || entries>E63_UI_APK_MAX_ENTRIES ||
        !within(dir_at,dir_bytes,bytes-22u) ||
        (uint64_t)dir_at+dir_bytes!=bytes-22u)
        return E63_UI_ARCHIVE_INVALID;
    dir_end=dir_at+dir_bytes;
    position=dir_at;
    for (n=0u;n<entries;++n)
        {
        uint16_t file_name,extra,comment,flags,method;
        uint32_t compressed,expanded,local_at,crc,body_at;
        uint64_t next;
        int wanted;
        const char *expected;
        size_t wanted_len;
        if (!within(position,sizeof(central),dir_end)) goto fail;
        if (!read_part(read_at,ctx,position,central,sizeof(central)))
            {status=E63_UI_ARCHIVE_IO;goto fail;}
        if (le32(central)!=0x02014b50u) goto fail;
        flags=le16(central+8u);method=le16(central+10u);
        crc=le32(central+16u);compressed=le32(central+20u);
        expanded=le32(central+24u);
        file_name=le16(central+28u);extra=le16(central+30u);
        comment=le16(central+32u);local_at=le32(central+42u);
        next=(uint64_t)position+sizeof(central)+file_name+extra+comment;
        if ((flags & ~(uint16_t)(2u|8u|0x0800u)) ||
            le16(central+34u)!=0u ||
            file_name==0u || file_name>=sizeof(name) ||
            !within(position,next-position,dir_end)) goto fail;
        if (!read_part(read_at,ctx,position+(uint32_t)sizeof(central),
                       name,file_name))
            {status=E63_UI_ARCHIVE_IO;goto fail;}
        position=(uint32_t)next;
        wanted=0;expected=0;wanted_len=0u;
        if (file_name==11u && memcmp(name,"classes.dex",11u)==0)
            {wanted=1;expected="classes.dex";wanted_len=11u;
             if (++have_dex>1u) goto fail;}
        else if (file_name==19u && memcmp(name,"AndroidManifest.xml",19u)==0)
            {wanted=2;expected="AndroidManifest.xml";wanted_len=19u;
             if (++have_manifest>1u) goto fail;}
        else if (file_name==14u && memcmp(name,"resources.arsc",14u)==0)
            {wanted=3;expected="resources.arsc";wanted_len=14u;
             if (++have_resources>1u) goto fail;}
        if (!wanted) continue;
        if ((flags & 8u) && wanted==1) {
            status=E63_UI_ARCHIVE_UNSUPPORTED;
            goto fail; /* primary classes.dex must remain stored/direct */
            }
        if (!within(local_at,sizeof(local),dir_at)) goto fail;
        if (!read_part(read_at,ctx,local_at,local,sizeof(local)))
            {status=E63_UI_ARCHIVE_IO;goto fail;}
        if (le32(local)!=0x04034b50u || le16(local+6u)!=flags ||
            le16(local+8u)!=method ||
            (!(flags&8u) && (le32(local+14u)!=crc ||
                le32(local+18u)!=compressed || le32(local+22u)!=expanded)) ||
            ((flags&8u) && (le32(local+14u)!=0u ||
                le32(local+18u)!=0u || le32(local+22u)!=0u)) ||
            le16(local+26u)!=wanted_len ||
            !within((uint64_t)local_at+sizeof(local),wanted_len,dir_at))
            goto fail;
        if (!read_part(read_at,ctx,local_at+(uint32_t)sizeof(local),
                       local_name,wanted_len))
            {status=E63_UI_ARCHIVE_IO;goto fail;}
        if (memcmp(local_name,expected,wanted_len)!=0) goto fail;
        next=(uint64_t)local_at+sizeof(local)+wanted_len+le16(local+28u);
        if (!within(next,compressed,dir_at) || !compressed || !expanded)
            goto fail;
        body_at=(uint32_t)next;
        if (wanted==1)
            {
            if (method!=0u || compressed!=expanded ||
                expanded<112u || expanded>32u*1024u*1024u)
                {status=E63_UI_ARCHIVE_UNSUPPORTED;goto fail;}
            dex_at=body_at;dex_bytes=expanded;dex_crc=crc;
            }
        else if (wanted==2)
            {if (expanded>512u*1024u) goto fail;
             manifest_at=body_at;manifest_bytes=compressed;
             manifest_method=method;}
        else
            {if (expanded>16u*1024u*1024u) goto fail;
             resources_at=body_at;resources_bytes=compressed;
             resources_method=method;}
        if (method!=0u && method!=8u)
            {status=E63_UI_ARCHIVE_UNSUPPORTED;goto fail;}
        }
    if (position!=dir_end || !have_dex || !have_manifest || !have_resources)
        goto fail;
    {
    uint32_t crc=0xffffffffu,at=0u;
    while (at<dex_bytes)
        {
        size_t portion=dex_bytes-at;
        if (portion>sizeof(buffer)) portion=sizeof(buffer);
        if (!read_part(read_at,ctx,dex_at+at,buffer,portion))
            {status=E63_UI_ARCHIVE_IO;goto fail;}
        crc=crc_part(crc,buffer,portion);
        at+=(uint32_t)portion;
        }
    if ((crc^0xffffffffu)!=dex_crc)
        {status=E63_UI_ARCHIVE_BAD_CRC;goto fail;}
    }
    out->archive_read_at=read_at;out->archive_context=ctx;
    out->archive_bytes=(uint32_t)bytes;
    out->dex_offset=dex_at;out->dex_bytes=dex_bytes;
    out->manifest_offset=manifest_at;
    out->manifest_compressed_bytes=manifest_bytes;
    out->manifest_compression=manifest_method;
    out->resources_offset=resources_at;
    out->resources_compressed_bytes=resources_bytes;
    out->resources_compression=resources_method;
    return E63_UI_ARCHIVE_OK;
fail:
    memset(out,0,sizeof(*out));
    return status;
    }

int e63_ui_dex_read_at(void *context,uint32_t offset,
                       uint8_t *dst,size_t length)
    {
    const E63UiDexSlice *slice=(const E63UiDexSlice *)context;
    if (!slice || !slice->archive_read_at || !dst || length==0u ||
        length>E63_BOOT_RECORD_BYTES ||
        !within(offset,length,slice->dex_bytes) ||
        !within((uint64_t)slice->dex_offset+offset,length,
                slice->archive_bytes)) return 0;
    return slice->archive_read_at(slice->archive_context,
                                  slice->dex_offset+offset,dst,length);
    }

const char *e63_ui_archive_status(E63UiArchiveStatus status)
    {
    switch (status)
        {
        case E63_UI_ARCHIVE_OK:return "stored real APK DEX located (not executed)";
        case E63_UI_ARCHIVE_BAD_INPUT:return "invalid APK read request";
        case E63_UI_ARCHIVE_INVALID:return "malformed APK ZIP metadata";
        case E63_UI_ARCHIVE_UNSUPPORTED:return "unsupported APK ZIP feature";
        case E63_UI_ARCHIVE_IO:return "APK disk read failed";
        case E63_UI_ARCHIVE_BAD_CRC:return "APK DEX CRC mismatch";
        default:return "unknown APK archive status";
        }
    }
