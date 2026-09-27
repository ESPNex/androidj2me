#include "apk_sha256.h"
#include <string.h>

/* FIPS 180-4; bounded streaming input, no allocation, unaligned-safe.
 * Only checks exact, already approved build pins. Production packages need
 * platform-vetted crypto and an Android signature/updates trust policy.
 */
static const uint32_t k[64] = {
 0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
 0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
 0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
 0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
 0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
 0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
 0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
 0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u
};
static uint32_t ror(uint32_t value, unsigned count)
    { return (value>>count) | (value<<(32u-count)); }
static uint32_t read_be32(const uint8_t *p)
    { return ((uint32_t)p[0]<<24u) | ((uint32_t)p[1]<<16u) |
             ((uint32_t)p[2]<<8u) | (uint32_t)p[3]; }
static void block(uint32_t s[8], const uint8_t *p)
    {
    uint32_t w[64], a,b,c,d,e,f,g,h;
    unsigned i;
    for (i=0;i<16u;++i) w[i]=read_be32(p+4u*i);
    for (i=16u;i<64u;++i) {
        uint32_t x=w[i-15u], y=w[i-2u];
        w[i]=(ror(y,17u)^ror(y,19u)^(y>>10u)) + w[i-7u] +
             (ror(x,7u)^ror(x,18u)^(x>>3u)) + w[i-16u];
    }
    a=s[0];b=s[1];c=s[2];d=s[3];e=s[4];f=s[5];g=s[6];h=s[7];
    for (i=0;i<64u;++i) {
        uint32_t first=h+(ror(e,6u)^ror(e,11u)^ror(e,25u))+
                       ((e&f)^(~e&g))+k[i]+w[i];
        uint32_t second=(ror(a,2u)^ror(a,13u)^ror(a,22u))+
                        ((a&b)^(a&c)^(b&c));
        h=g;g=f;f=e;e=d+first;d=c;c=b;b=a;a=first+second;
    }
    s[0]+=a;s[1]+=b;s[2]+=c;s[3]+=d;
    s[4]+=e;s[5]+=f;s[6]+=g;s[7]+=h;
    }
void e63_sha256_init(E63Sha256Context *ctx)
    {
    static const uint32_t initial[8]={
         0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
         0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u};
    if (!ctx) return;
    memcpy(ctx->state,initial,sizeof(initial));
    ctx->pending_length=0u;
    ctx->total_length=0u;
    }

void e63_sha256_update(E63Sha256Context *ctx,
                       const uint8_t *bytes, size_t length)
    {
    size_t taken;
    if (!ctx || !length) return;
    if (!bytes) return;
    ctx->total_length+=(uint64_t)length;
    if (ctx->pending_length) {
        taken=64u-ctx->pending_length;
        if (taken>length) taken=length;
        if (taken) memcpy(ctx->pending+ctx->pending_length,bytes,taken);
        ctx->pending_length+=taken;
        bytes+=taken;length-=taken;
        if (ctx->pending_length==64u) {
            block(ctx->state,ctx->pending);
            ctx->pending_length=0u;
        }
    }
    while (length>=64u) {
        block(ctx->state,bytes);bytes+=64u;length-=64u;
    }
    if (length) {
        memcpy(ctx->pending,bytes,length);
        ctx->pending_length=length;
    }
    }

void e63_sha256_final(E63Sha256Context *ctx, uint8_t out[32])
    {
    uint8_t tail[128];
    size_t remaining, i;
    uint64_t bits;
    if (!ctx || !out) return;
    remaining=ctx->pending_length;
    bits=ctx->total_length*8u;
    memset(tail,0,sizeof(tail));
    if (remaining) memcpy(tail,ctx->pending,remaining);
    tail[remaining]=0x80u;
    for (i=0;i<8u;++i) tail[(remaining>=56u ? 120u : 56u)+i]=
                         (uint8_t)(bits>>(56u-8u*i));
    block(ctx->state,tail);
    if (remaining>=56u) block(ctx->state,tail+64u);
    for (i=0;i<8u;++i) {
        out[i*4u]=(uint8_t)(ctx->state[i]>>24u);
        out[i*4u+1u]=(uint8_t)(ctx->state[i]>>16u);
        out[i*4u+2u]=(uint8_t)(ctx->state[i]>>8u);
        out[i*4u+3u]=(uint8_t)ctx->state[i];
    }
    memset(ctx,0,sizeof(*ctx));
    }

void e63_apk_sha256(const uint8_t *bytes, size_t length, uint8_t out[32])
    {
    E63Sha256Context ctx;
    if (!out || (!bytes && length)) return;
    e63_sha256_init(&ctx);
    e63_sha256_update(&ctx,bytes,length);
    e63_sha256_final(&ctx,out);
    }
