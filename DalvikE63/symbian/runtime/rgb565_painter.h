#ifndef E63_RGB565_PAINTER_H
#define E63_RGB565_PAINTER_H

/* Bounded portable C99 raster for ORIGINAL guest-Dex Graphics command batches.
 * CPU compositing/full-circle arc is C99; the platform provides ONLY decoded
 * RGBA images and glyph masks (no screen/layout decisions). On PC these
 * resources come from the signed APK and Pillow. Seven guest Canvas.paint
 * paths produce complete RGB565 frames; other UI paths may fail closed. This
 * is not a Symbian Window Server backend or a buildable SIS.
 *
 * API returns 0 on success; any failure MUST leave the last frame unchanged.
 * References returned by resource callbacks must remain valid until commit
 * returns; callbacks must be pure and cannot touch the displayed frame.
 */
#include "ui_event_vm.h"
#include "device_api.h"
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define E63_RGB565_MAX_WIDTH 320u
#define E63_RGB565_MAX_HEIGHT 240u
#define E63_RGB565_MAX_ASSET_SIDE 512u
#define E63_RGB565_MAX_GLYPH_WIDTH 4096u
#define E63_RGB565_MAX_GLYPH_HEIGHT 512u

/* Pixel data is RGBA, row-major, top-down, one 8-bit channel per byte.
 * size includes all usable bytes, including optional row padding. */
typedef struct E63RgbaResource {
    const uint8_t *pixels;
    size_t size;
    uint32_t stride;
    int32_t width, height;
} E63RgbaResource;

/* Coverage of an ASCII string for one MIDP font, no foreground color.
 * left/top are offsets from the guest drawString(x,y,TOP|LEFT) anchor. */
typedef struct E63GlyphResource {
    const uint8_t *alpha;
    size_t size;
    uint32_t stride;
    int32_t width, height, left, top;
} E63GlyphResource;

typedef struct E63Rgb565Resources {
    void *context;
    int (*image_rgba)(void *context, int32_t opaque_id, E63RgbaResource *out);
    int (*text_mask)(void *context, int32_t midp_font, const char *ascii,
                     E63GlyphResource *out);
} E63Rgb565Resources;

typedef struct E63Rgb565Painter E63Rgb565Painter;

/* Logical pixels are RGB565: 5 red, 6 green, 5 blue, uint16_t row-major.
 * Width/height are limited to the target E63 landscape viewport; ownership
 * of returned pointer stays with painter and lasts until the next commit.
 * Memory on 320x240: two RGB888 working buffers plus one RGB565 frame. */
E63Rgb565Painter *e63_rgb565_new(uint16_t width, uint16_t height,
                                  const E63Rgb565Resources *resources);
void e63_rgb565_free(E63Rgb565Painter *painter);
const uint16_t *e63_rgb565_pixels(const E63Rgb565Painter *painter);
uint32_t e63_rgb565_frames(const E63Rgb565Painter *painter);
uint16_t e63_rgb565_width(const E63Rgb565Painter *painter);
uint16_t e63_rgb565_height(const E63Rgb565Painter *painter);

/* Can be used as E63UiPaintHost.commit with context=painter. A failed batch
 * changes neither visible RGB565 pixels nor the next frame's RGB888 source.
 * Only Graphics.TOP|LEFT=20 is supported for image/string anchors here. */
int e63_rgb565_commit(void *painter, const E63UiPaintOp *ops, uint32_t count);

/* Optional bridge to the design-only E63DeviceOps.present_frame callback.
 * Only a committed frame may be presented. Failure keeps the RGB565 buffer
 * for retry; an S60 implementation of the callback does not exist yet. */
E63Result e63_rgb565_present(const E63Rgb565Painter *painter,
                             const E63DeviceOps *device);

#ifdef __cplusplus
}
#endif
#endif
