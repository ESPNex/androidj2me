#include "rgb565_painter.h"
#include <limits.h>
#include <stdlib.h>
#include <string.h>

struct E63Rgb565Painter {
    uint16_t width,height;
    E63Rgb565Resources resources;
    uint8_t *front_rgb,*work_rgb; /* full 8-bit channels before quantization */
    uint16_t *front565;
    size_t pixel_count;
    uint32_t frames;
};

E63Rgb565Painter *e63_rgb565_new(uint16_t width, uint16_t height,
                                  const E63Rgb565Resources *resources) {
    E63Rgb565Painter *p;
    size_t pixels;
    if (!resources || !resources->image_rgba || !resources->text_mask ||
        width<64u || width>E63_RGB565_MAX_WIDTH ||
        height<64u || height>E63_RGB565_MAX_HEIGHT) return 0;
    pixels=(size_t)width*height;
    p=(E63Rgb565Painter *)calloc(1,sizeof(*p));
    if (!p) return 0;
    p->front_rgb=(uint8_t *)calloc(pixels,3u);
    p->work_rgb=(uint8_t *)calloc(pixels,3u);
    p->front565=(uint16_t *)calloc(pixels,sizeof(uint16_t));
    if (!p->front_rgb || !p->work_rgb || !p->front565) {
        e63_rgb565_free(p);return 0;
    }
    p->width=width;p->height=height;
    p->pixel_count=pixels;
    p->resources=*resources;
    return p;
}
void e63_rgb565_free(E63Rgb565Painter *p) {
    if (!p) return;
    free(p->front_rgb);free(p->work_rgb);free(p->front565);free(p);
}
const uint16_t *e63_rgb565_pixels(const E63Rgb565Painter *p) {
    return p ? p->front565 : 0;
}
uint32_t e63_rgb565_frames(const E63Rgb565Painter *p) {
    return p ? p->frames : 0u;
}
uint16_t e63_rgb565_width(const E63Rgb565Painter *p) {
    return p ? p->width : 0u;
}
uint16_t e63_rgb565_height(const E63Rgb565Painter *p) {
    return p ? p->height : 0u;
}

E63Result e63_rgb565_present(const E63Rgb565Painter *p,
                             const E63DeviceOps *device) {
    if (!p || !device || !device->present_frame || !p->frames)
        return E63_UNAVAILABLE;
    return device->present_frame(device->context,p->front565,p->width,p->height);
}

static void dot(E63Rgb565Painter *p, int64_t x, int64_t y, uint32_t color) {
    uint8_t *dst;
    if (x<0 || y<0 || x>=p->width || y>=p->height) return;
    dst=p->work_rgb+((size_t)y*p->width+(size_t)x)*3u;
    dst[0]=(uint8_t)(color>>16u);
    dst[1]=(uint8_t)(color>>8u);
    dst[2]=(uint8_t)color;
}
static void blend(E63Rgb565Painter *p, int64_t x, int64_t y,
                  const uint8_t *source, uint8_t coverage) {
    uint8_t *dst;
    size_t i;
    if (!coverage || x<0 || y<0 || x>=p->width || y>=p->height) return;
    dst=p->work_rgb+((size_t)y*p->width+(size_t)x)*3u;
    for (i=0;i<3u;i++)
        dst[i]=(uint8_t)(((uint32_t)dst[i]*(255u-coverage)+
                          (uint32_t)source[i]*coverage+127u)/255u);
}
static int valid_span(size_t bytes, uint32_t stride, int32_t width,
                      int32_t height, uint32_t channels) {
    size_t end;
    if (width<1 || height<1 || (uint64_t)(uint32_t)width*channels>stride ||
        (size_t)(height-1)>SIZE_MAX/stride) return 0;
    end=(size_t)(height-1)*stride;
    return end<=bytes && (size_t)(uint32_t)width*channels<=bytes-end;
}
static void horizontal(E63Rgb565Painter *p, int64_t left,int64_t right,
                       int64_t y,uint32_t color) {
    int64_t x;
    if (y<0 || y>=p->height) return;
    if (left<0) left=0;
    if (right>=p->width) right=(int64_t)p->width-1;
    for (x=left;x<=right;x++) dot(p,x,y,color);
}
static void vertical(E63Rgb565Painter *p, int64_t x,int64_t top,
                     int64_t bottom,uint32_t color) {
    int64_t y;
    if (x<0 || x>=p->width) return;
    if (top<0) top=0;
    if (bottom>=p->height) bottom=(int64_t)p->height-1;
    for (y=top;y<=bottom;y++) dot(p,x,y,color);
}
static void rectangle(E63Rgb565Painter *p,const E63UiPaintOp *op,
                      uint32_t color,int fill) {
    int64_t x=op->a,y=op->b,w=op->c,h=op->d;
    int64_t right=x+w-(fill ? 1 : 0),bottom=y+h-(fill ? 1 : 0);
    int64_t row;
    if (fill) {
        if (w<=0 || h<=0 || x>=p->width || right<0 ||
            y>=p->height || bottom<0) return;
        if (y<0) y=0;
        if (bottom>=p->height) bottom=(int64_t)p->height-1;
        for (row=y;row<=bottom;row++) horizontal(p,x,right,row,color);
    } else if (w>=0 && h>=0) {
        /* Pillow's drawRect includes x+w,y+h; MIDP guest supplies w/h. */
        horizontal(p,x,right,y,color);
        horizontal(p,x,right,bottom,color);
        vertical(p,x,y,bottom,color);
        vertical(p,right,y,bottom,color);
    }
}
static int draw_line(E63Rgb565Painter *p,const E63UiPaintOp *op,
                     uint32_t color) {
    int64_t x=op->a,y=op->b,tx=op->c,ty=op->d;
    int64_t dx,dy,sx,sy,err;
    /* Bound work even when a guest asks for absurd offscreen coordinates.
     * Cropping lines that cross farther away needs a separate clipped path. */
    if (x < -4096 || x > 4096 || y < -4096 || y > 4096 ||
        tx < -4096 || tx > 4096 || ty < -4096 || ty > 4096) return 1;
    /* Differences are now within [-8192, 8192]; Symbian libc lacks llabs. */
    dx=tx-x; if (dx<0) dx=-dx;
    dy=ty-y; if (dy<0) dy=-dy;
    dy=-dy;
    sx=x<tx ? 1 : -1;sy=y<ty ? 1 : -1;
    err=dx+dy;
    for (;;) {
        int64_t twice;
        dot(p,x,y,color);
        if (x==tx && y==ty) break;
        twice=2*err;
        if (twice>=dy) {err+=dy;x+=sx;}
        if (twice<=dx) {err+=dx;y+=sy;}
    }
    return 0;
}
static int ellipse(E63Rgb565Painter *p,const E63UiPaintOp *op,
                   uint32_t color) {
    /* Full MIDP arc only. Scan a bounded ellipse and keep the outline:
     * center and radii are half-pixel aware, unlike a square approximation. */
    int32_t left[E63_RGB565_MAX_ASSET_SIDE];
    int32_t right[E63_RGB565_MAX_ASSET_SIDE];
    int32_t w=op->c,h=op->d,iy,ix;
    int64_t wx,hy,limit;
    if (w<1 || h<1 || w>(int32_t)E63_RGB565_MAX_ASSET_SIDE ||
        h>(int32_t)E63_RGB565_MAX_ASSET_SIDE) return 1;
    wx=(int64_t)w*w;hy=(int64_t)h*h;limit=wx*hy;
    for (iy=0;iy<h;iy++) {
        int64_t dy=(int64_t)iy*2-(h-1);
        left[iy]=w;right[iy]=-1;
        for (ix=0;ix<w;ix++) {
            int64_t dx=(int64_t)ix*2-(w-1);
            if (dx*dx*hy+dy*dy*wx<=limit) {
                if (left[iy]==w) left[iy]=ix;
                right[iy]=ix;
            }
        }
    }
    for (iy=0;iy<h;iy++) {
        if (right[iy]<left[iy]) continue;
        for (ix=left[iy];ix<=right[iy];ix++) {
            if (iy==0 || iy==h-1 || ix==left[iy] || ix==right[iy] ||
                ix<left[iy-1] || ix>right[iy-1] ||
                ix<left[iy+1] || ix>right[iy+1])
                dot(p,(int64_t)op->a+ix,(int64_t)op->b+iy,color);
        }
    }
    return 0;
}
static int image(E63Rgb565Painter *p,const E63UiPaintOp *op) {
    E63RgbaResource resource;
    int64_t x=op->b,y=op->c;
    int64_t ix,iy;
    if (op->d!=20) return 1; /* Graphics.TOP | Graphics.LEFT */
    memset(&resource,0,sizeof(resource));
    if (p->resources.image_rgba(p->resources.context,op->a,&resource)!=0 ||
        !resource.pixels || resource.width>(int32_t)E63_RGB565_MAX_ASSET_SIDE ||
        resource.height>(int32_t)E63_RGB565_MAX_ASSET_SIDE ||
        !valid_span(resource.size,resource.stride,
                    resource.width,resource.height,4u)) return 1;
    for (iy=0;iy<resource.height;iy++) {
        const uint8_t *row;
        if (y+iy<0 || y+iy>=p->height) continue;
        row=resource.pixels+(size_t)iy*resource.stride;
        for (ix=0;ix<resource.width;ix++) {
            const uint8_t *rgba;
            if (x+ix<0 || x+ix>=p->width) continue;
            rgba=row+(size_t)ix*4u;
            blend(p,x+ix,y+iy,rgba,rgba[3]);
        }
    }
    return 0;
}
static int text(E63Rgb565Painter *p,const E63UiPaintOp *op,
                int32_t font,uint32_t color) {
    E63GlyphResource glyph;
    const uint8_t *rgb=(const uint8_t[3]){
        (uint8_t)(color>>16u),(uint8_t)(color>>8u),(uint8_t)color};
    int64_t x,y,ix,iy;
    if (op->c!=20 || !memchr(op->text,0,sizeof(op->text)) ||
        (font!=0 && font!=8 && font!=16)) return 1;
    memset(&glyph,0,sizeof(glyph));
    if (p->resources.text_mask(p->resources.context,font,op->text,&glyph)!=0 ||
        glyph.width<0 || glyph.height<0 ||
        glyph.width>(int32_t)E63_RGB565_MAX_GLYPH_WIDTH ||
        glyph.height>(int32_t)E63_RGB565_MAX_GLYPH_HEIGHT) return 1;
    if (!glyph.width || !glyph.height) return 0;
    if (!glyph.alpha || !valid_span(glyph.size,glyph.stride,
                                   glyph.width,glyph.height,1u)) return 1;
    x=(int64_t)op->a+glyph.left;
    y=(int64_t)op->b+glyph.top;
    for (iy=0;iy<glyph.height;iy++) {
        const uint8_t *row;
        if (y+iy<0 || y+iy>=p->height) continue;
        row=glyph.alpha+(size_t)iy*glyph.stride;
        for (ix=0;ix<glyph.width;ix++) {
            if (x+ix<0 || x+ix>=p->width) continue;
            blend(p,x+ix,y+iy,rgb,row[ix]);
        }
    }
    return 0;
}
int e63_rgb565_commit(void *context, const E63UiPaintOp *ops, uint32_t count) {
    E63Rgb565Painter *p=(E63Rgb565Painter *)context;
    uint32_t color=0xFFFFFFu,i;
    int32_t font=0;
    uint8_t *old;
    if (!p || !ops || !count || count>E63_UI_MAX_DRAW_OPS) return 1;
    memcpy(p->work_rgb,p->front_rgb,p->pixel_count*3u);
    for (i=0;i<count;i++) {
        const E63UiPaintOp *op=&ops[i];
        switch (op->code) {
        case E63_UI_SET_CLIP:
            /* The guest's Canvas.paint installs precisely the full viewport.
             * Anything narrower must fail, never silently lose clipping. */
            if (op->a!=0 || op->b!=0 || op->c!=p->width ||
                op->d!=p->height) return 1;
            break;
        case E63_UI_SET_COLOR:color=(uint32_t)op->a&0xFFFFFFu;break;
        case E63_UI_SET_FONT:
            if (op->a!=0 && op->a!=8 && op->a!=16) return 1;
            font=op->a;break;
        case E63_UI_FILL_RECT:rectangle(p,op,color,1);break;
        case E63_UI_DRAW_RECT:rectangle(p,op,color,0);break;
        case E63_UI_DRAW_LINE:
            if (draw_line(p,op,color)) return 1;
            break;
        case E63_UI_DRAW_ELLIPSE:
            if (ellipse(p,op,color)) return 1;
            break;
        case E63_UI_DRAW_IMAGE:
            if (image(p,op)) return 1;
            break;
        case E63_UI_DRAW_STRING:
            if (text(p,op,font,color)) return 1;
            break;
        default:return 1;
        }
    }
    old=p->front_rgb;p->front_rgb=p->work_rgb;p->work_rgb=old;
    for (i=0;i<p->pixel_count;i++) {
        const uint8_t *rgb=p->front_rgb+(size_t)i*3u;
        p->front565[i]=(uint16_t)(((uint16_t)(rgb[0]>>3u)<<11u)|
                                  ((uint16_t)(rgb[1]>>2u)<<5u)|
                                   ((uint16_t)(rgb[2]>>3u)));
    }
    p->frames++;
    return 0;
}
