#include "apk_dex_loader.h"
#include <string.h>

static unsigned short le16(const uint8_t *p)
    { return (unsigned short)(p[0] | ((unsigned short)p[1]<<8)); }
static uint32_t le32(const uint8_t *p)
    { return (uint32_t)p[0] | ((uint32_t)p[1]<<8) |
             ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24); }
static int inside(size_t length, size_t off, size_t count)
    { return off<=length && count<=length-off; }
static uint32_t crc32_stored(const uint8_t *data, size_t size)
    {
    uint32_t value=0xffffffffu;
    size_t i;
    for (i=0;i<size;++i)
        {
        unsigned bit;
        value^=data[i];
        for (bit=0;bit<8;++bit)
            value=(value>>1) ^ ((value&1u) ? 0xedb88320u : 0u);
        }
    return value ^ 0xffffffffu;
    }

E63ApkStatus e63_apk_dex_open(const uint8_t *apk, size_t bytes, E63DexView *out)
    {
    size_t pos, earliest, directory, end, chosen=(size_t)-1;
    unsigned count, n, hits=0;
    if (!out) return E63_APK_INVALID;
    memset(out,0,sizeof(*out));
    if (!apk || bytes<22u || bytes>E63_APK_MAX_BYTES) return E63_APK_INVALID;
    earliest=bytes>22u+65535u ? bytes-(22u+65535u) : 0u;
    pos=bytes-22u;
    for (;;) {
        if (inside(bytes,pos,22u) && le32(apk+pos)==0x06054b50u &&
            le16(apk+pos+20u)==bytes-pos-22u) break;
        if (pos==earliest) return E63_APK_INVALID;
        --pos;
    }
    if (le16(apk+pos+4u) || le16(apk+pos+6u) ||
        le16(apk+pos+8u)!=le16(apk+pos+10u) ||
        le16(apk+pos+10u)>128u) return E63_APK_UNSUPPORTED;
    count=le16(apk+pos+10u);
    directory=le32(apk+pos+16u);
    if (directory>(size_t)pos || le32(apk+pos+12u)!=(uint32_t)((size_t)pos-directory))
        return E63_APK_INVALID;
    end=pos;
    pos=directory;
    for (n=0;n<count;++n)
        {
        size_t next, name_length, extra_length, comment_length;
        if (!inside(end,pos,46u) || le32(apk+pos)!=0x02014b50u)
            return E63_APK_INVALID;
        name_length=le16(apk+pos+28u);
        extra_length=le16(apk+pos+30u);
        comment_length=le16(apk+pos+32u);
        next=pos+46u;
        if (!inside(end,next,name_length) ||
            !inside(end,next+name_length,extra_length) ||
            !inside(end,next+name_length+extra_length,comment_length))
            return E63_APK_INVALID;
        if (name_length==11u && memcmp(apk+next,"classes.dex",11u)==0)
            {
            if (++hits>1u) return E63_APK_INVALID;
            chosen=pos;
            }
        pos=next+name_length+extra_length+comment_length;
        }
    if (pos!=end) return E63_APK_INVALID;
    if (hits!=1u || chosen==(size_t)-1) return E63_APK_MISSING_DEX;
    {
    size_t local=le32(apk+chosen+42u), data_offset;
    unsigned method=le16(apk+chosen+10u),flags=le16(apk+chosen+8u);
    uint32_t crc=le32(apk+chosen+16u);
    size_t compressed=le32(apk+chosen+20u), expanded=le32(apk+chosen+24u);
    if ((flags & ~0x0800u) || method!=0u || compressed!=expanded ||
        compressed<112u || compressed>4u*1024u*1024u ||
        le16(apk+chosen+34u) || !inside(directory,local,30u) ||
        le32(apk+local)!=0x04034b50u ||
        le16(apk+local+6u)!=flags || le16(apk+local+8u)!=method ||
        le32(apk+local+14u)!=crc ||
        le32(apk+local+18u)!=compressed || le32(apk+local+22u)!=expanded ||
        le16(apk+local+26u)!=11u ||
        !inside(directory,local+30u,11u) ||
        memcmp(apk+local+30u,"classes.dex",11u)!=0)
        return E63_APK_UNSUPPORTED;
    data_offset=local+30u+11u+le16(apk+local+28u);
    if (!inside(directory,data_offset,expanded) ||
        crc32_stored(apk+data_offset,expanded)!=crc)
        return E63_APK_INVALID;
    if (e63_dex_open(apk+data_offset,expanded,out)!=E63_DEX_OK)
        { memset(out,0,sizeof(*out)); return E63_APK_BAD_DEX; }
    }
    return E63_APK_OK;
    }

const char *e63_apk_status(E63ApkStatus status)
    {
    switch(status)
        {
        case E63_APK_OK: return "OK (CRC and DEX, NOT cryptographic signature)";
        case E63_APK_INVALID: return "Malformed/CRC-invalid APK ZIP";
        case E63_APK_UNSUPPORTED: return "Unsupported APK ZIP (stored primary DEX only)";
        case E63_APK_MISSING_DEX: return "Primary classes.dex missing";
        case E63_APK_BAD_DEX: return "Invalid DEX preflight";
        default: return "unknown APK status";
        }
    }
