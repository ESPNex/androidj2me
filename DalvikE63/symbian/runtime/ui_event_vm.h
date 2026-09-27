#ifndef E63_UI_EVENT_VM_H
#define E63_UI_EVENT_VM_H

/* Portable C99 DEX interpreter for selected ORIGINAL E63Midlet/E63Canvas
 * paths. Executes guest event dispatch and guest Canvas.paint on SEVEN
 * pixel-tested screens (Home, empty folder, power-off overlay, app drawer,
 * notifications, Quick Settings and Recents) including status/nav. Handles
 * original static battery glyph data and guest clock string construction.
 * rgb565_painter.c rasterizes these complete frames on PC. Other screen
 * paths and startApp/MIDP Forms/exceptions/Unicode/RFs/SIS are NOT supported.
 * Unsupported reached bytecode fails closed, never substitutes UI logic.
 * A zero key-action callback result is a valid game action (UNKNOWN).
 */
#include "dex_preflight.h"
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define E63_UI_MAX_OBJECTS 32u
#define E63_UI_MAX_ARRAYS 16u
#define E63_UI_MAX_STRINGS 64u
#define E63_UI_MAX_ARRAY_ITEMS 32u
#define E63_UI_MAX_FIELDS 256u
#define E63_UI_MAX_REGISTERS 256u
#define E63_UI_MAX_WORDS 8192u
#define E63_UI_MAX_DEPTH 12u
#define E63_UI_STEP_BUDGET 8192u
#define E63_UI_MAX_DRAW_OPS 256u
#define E63_UI_MAX_TEXT_BYTES 160u

typedef enum E63UiStatus {
    E63_UI_OK = 0,
    E63_UI_INVALID = -1,
    E63_UI_NO_METHOD = -2,
    E63_UI_UNSUPPORTED = -3,
    E63_UI_BUDGET = -4,
    E63_UI_LIMIT = -5
} E63UiStatus;

typedef struct E63UiVm E63UiVm;

/* The C interpreter buffers guest Graphics commands until the method returns
 * successfully. A host draws the complete batch atomically, never chooses a
 * screen. Font/image metric callbacks must be pure: they can precede a fault.
 * Text remains ASCII-only in this bounded subset; unsupported guest strings
 * return UNSUPPORTED rather than being corrupted. No Symbian backend yet. */
typedef enum E63UiPaintCode {
    E63_UI_SET_COLOR = 1,
    E63_UI_FILL_RECT = 2,
    E63_UI_SET_FONT = 3,
    E63_UI_DRAW_STRING = 4,
    E63_UI_DRAW_IMAGE = 5, /* a = resource id; b,c = x,y; d = MIDP anchor */
    E63_UI_DRAW_RECT = 6,  /* a,b = x,y; c,d = width,height */
    E63_UI_DRAW_LINE = 7,  /* a,b,c,d = x1,y1,x2,y2 */
    E63_UI_SET_CLIP = 8,   /* bounded subset: whole logical viewport */
    E63_UI_DRAW_ELLIPSE = 9 /* guest drawArc(x,y,w,h,0,360) outline */
} E63UiPaintCode;
typedef struct E63UiPaintOp {
    int32_t code, a, b, c, d;
    char text[E63_UI_MAX_TEXT_BYTES + 1u];
} E63UiPaintOp;
typedef struct E63UiPaintHost {
    void *context;
    int (*font_height)(void *context, int32_t midp_size, int32_t *result);
    int (*font_width)(void *context, int32_t midp_size,
                      const char *ascii, int32_t *result);
    /* Pure asset metadata callback; the resource ID is an opaque handle
     * seeded into a typed Image guest field, never chosen by C layout code. */
    int (*image_bounds)(void *context, int32_t resource_id,
                        int32_t *width, int32_t *height);
    /* MUST apply the batch atomically (e.g. to an offscreen framebuffer).
     * A nonzero return must leave the previous visible frame untouched. */
    int (*commit)(void *context, const E63UiPaintOp *ops, uint32_t count);
    /* Pure local time service for the ORIGINAL guest Calendar/clock method.
     * No screen text, time adjustment or battery value is chosen by host. */
    int (*local_clock)(void *context, int32_t *hour, int32_t *minute);
} E63UiPaintHost;

/* Pure platform primitive, not a screen decision: map a physical keycode to
 * a MIDP Canvas game action (UP/DOWN/LEFT/RIGHT/FIRE/UNKNOWN). Return 0 on
 * successful lookup and write the action to out; nonzero = unavailable.
 * VM calls this only for the DEX Canvas.getGameAction(I) invocation. */
typedef int (*E63UiGameAction)(void *context, int32_t key, int32_t *out);
/* Milliseconds since Unix epoch: host service used ONLY when the ORIGINAL
 * MIDlet.back() bytecode invokes System.currentTimeMillis()J for debounce.
 * No host-supplied navigation or screen contents. Nonzero means unavailable. */
typedef int (*E63UiTimeMillis)(void *context, int64_t *out);
E63UiStatus e63_ui_set_time_host(E63UiVm *vm, E63UiTimeMillis clock,
                                void *context);

/* Borrowed DEX must outlive VM. e63_ui_object(Canvas) executes the ORIGINAL
 * <clinit> bytecode to populate tiny battery digit arrays. Other guest
 * constructors/startApp do not run: host must seed typed instance fields from
 * a trusted boot path. Not a complete MIDP lifecycle. */
E63UiVm *e63_ui_new(const E63DexView *dex, E63UiGameAction action, void *context);
void e63_ui_free(E63UiVm *vm);
/* Host-reported logical Canvas size; only consulted when DEX invokes
 * Displayable.getWidth/getHeight. Zero/unset fails closed on those calls. */
E63UiStatus e63_ui_set_viewport(E63UiVm *vm, uint16_t width, uint16_t height);
E63UiStatus e63_ui_object(E63UiVm *vm, const char *descriptor, uint32_t *handle);
/* Typed external MIDP instances: Graphics (native_id=0), Font (8 small,
 * 0 medium, 16 large), Image (opaque resource id 1..32), NOT arbitrary
 * platform objects. Host maps verified APK image resources to these IDs.
 * Guest DEX fields and instructions choose which image/font to use. */
E63UiStatus e63_ui_host_object(E63UiVm *vm, const char *descriptor,
                               int32_t native_id, uint32_t *handle);
E63UiStatus e63_ui_set_paint_host(E63UiVm *vm, const E63UiPaintHost *host);
E63UiStatus e63_ui_int_array(E63UiVm *vm, uint32_t count, uint32_t *handle);
E63UiStatus e63_ui_set_int(E63UiVm *vm, uint32_t object, uint32_t field, int32_t value);
E63UiStatus e63_ui_get_int(const E63UiVm *vm, uint32_t object, uint32_t field, int32_t *value);
E63UiStatus e63_ui_set_ref(E63UiVm *vm, uint32_t object, uint32_t field, uint32_t reference);
E63UiStatus e63_ui_set_array(E63UiVm *vm, uint32_t object, uint32_t field, uint32_t array);
E63UiStatus e63_ui_array_set(E63UiVm *vm, uint32_t array, uint32_t index, int32_t value);
E63UiStatus e63_ui_array_get(const E63UiVm *vm, uint32_t array, uint32_t index, int32_t *value);

/* Top-level entry point accepts only I/Z primitive parameters and I/Z/V
 * result; guest object graph is supplied via typed fields above. State and
 * repaint requests are rolled back if an interpreter error is returned.
 * This is NOT full guest Java exception or transactional OS I/O semantics. */
E63UiStatus e63_ui_call(E63UiVm *vm, uint32_t receiver, const char *method,
                        const char *prototype, const int32_t *parameters,
                        uint32_t param_count, int32_t *result);
/* Invoke an ORIGINAL guest method that takes exactly one Graphics reference.
 * e63_ui_call_ref("paint", ...) pixel-tested for 7 complete 320x240/220x180
 * scenes; unsupported screen paths fail atomically, not painted by the host. */
E63UiStatus e63_ui_call_ref(E63UiVm *vm, uint32_t receiver,
                            const char *method, const char *prototype,
                            uint32_t graphics);
int e63_ui_repaint_pending(const E63UiVm *vm);
void e63_ui_clear_repaint(E63UiVm *vm);
const char *e63_ui_status(E63UiStatus status);

#ifdef __cplusplus
}
#endif
#endif
