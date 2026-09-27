#ifndef E63_DEVICE_API_H
#define E63_DEVICE_API_H

/* ABI DESIGN ONLY for a future S60 host.
 * dex_vm.c executes StoreState's DEX subset; ui_event_vm.c executes selected
 * ORIGINAL Canvas/Midlet events and Canvas.paint DEX for 7 screens on PC.
 * It does NOT run startApp or every screen. rgb565_painter.c can call
 * present_frame through this interface, but there is NO Symbian implementation
 * of that callback; this is NOT a working SIS.
 * Only these host capabilities may cross from guest DEX to the device.
 */
#include <stddef.h>
#include <stdint.h>
#include "vfs_mount.h"

#ifdef __cplusplus
extern "C" {
#endif

enum { E63_SCREEN_WIDTH = 320, E63_SCREEN_HEIGHT = 240,
       E63_BRIDGE_LOOPBACK_PORT = 27463, E63_PACKAGE_FILE_MANAGER = 1 };

typedef enum E63Result {
    E63_OK = 0,
    E63_DENIED = -1,
    E63_UNAVAILABLE = -2,
    E63_INVALID = -3,
    E63_IO_ERROR = -4
} E63Result;

typedef enum E63InputKind {
    E63_INPUT_KEY = 1,      /* pass keycode to original E63Canvas.keyPressed */
    E63_INPUT_POINTER = 2,  /* x,y are screen coordinates */
    E63_INPUT_TEXT = 3,     /* return TextField content to guest commandAction */
    E63_INPUT_TICK = 4      /* resume guest tickLoop, never replace its logic */
} E63InputKind;

typedef struct E63InputEvent {
    E63InputKind kind;
    int32_t key_or_x, y;
    const uint16_t *text_utf16; /* Borrowed, length-limited, NULL if not text. */
    uint32_t text_units;
    uint32_t delta_ms;
} E63InputEvent;

typedef struct E63DeviceOps {
    void *context;
    /* Native renderer presents the RGB565 frame painted by guest Graphics. */
    E63Result (*present_frame)(void *, const uint16_t *pixels, uint16_t width,
                               uint16_t height);
    /* Pure Nokia keycode -> MIDP Canvas game-action lookup. The new C99
     * UI event interpreter accepts this through a small E63UiGameAction
     * adapter; the guest DEX still makes all navigation decisions. */
    E63Result (*canvas_game_action)(void *, int32_t key, int32_t *action);
    uint64_t (*clock_millis)(void *);
    /* MIDP assets in the signed APK. Caller asks with absolute path such as
     * /wall.png; *size is both buffer capacity and returned byte count. */
    E63Result (*asset_read)(void *, const char *path, uint8_t *buffer, size_t *size);
    E63Result (*rms_read)(void *, const char *store, uint8_t *buffer, size_t *size);
    E63Result (*rms_write)(void *, const char *store, const uint8_t *data, size_t size);
    /* Design-only VFS boundary: backend MUST route and authorize each guest
     * path with e63_route_guest_path before touching RFs or RAM. Never accept
     * an untrusted absolute C: path or infer consent from caller=OS. The
     * FILES caller is not yet wired to the guest UI; no RFs backend exists. */
    E63Result (*vfs_read)(void *, const char *guest_path, E63Caller caller,
                          uint8_t *buffer, size_t *size);
    E63Result (*vfs_write)(void *, const char *guest_path, E63Caller caller,
                           const uint8_t *data, size_t size);
    /* Exactly 127.0.0.1:E63_BRIDGE_LOOPBACK_PORT. No arbitrary host/port. */
    E63Result (*bridge_open)(void *, uint32_t *handle);
    E63Result (*bridge_write)(void *, uint32_t handle, const uint8_t *, size_t);
    E63Result (*bridge_read)(void *, uint32_t handle, uint8_t *, size_t *size);
    void (*bridge_close)(void *, uint32_t handle);
    /* Backend confirms install; it must verify a trusted APK and commit to
     * private C: storage. If install fails guest OPEN/RMS must be rolled back. */
    E63Result (*package_installed)(void *, uint32_t package_id, uint8_t *installed);
    E63Result (*package_install)(void *, uint32_t package_id);
} E63DeviceOps;

#ifdef __cplusplus
}
#endif
#endif
