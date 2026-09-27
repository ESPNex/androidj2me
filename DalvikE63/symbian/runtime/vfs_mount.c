#include "vfs_mount.h"
#include "../android_java_app/ui_apk_pins.h"
#include <stddef.h>
#include <string.h>

/* Routing alone does not prove file existence or integrity: system_image.c
 * resolves only pinned /system files and the S60 loader opens them from C:.
 */
static const E63MountEntry kMounts[] = {
    {"/",E63_MOUNT_RAM,1}, {"/system",E63_MOUNT_BUNDLE_RO,1},
    {"/data",E63_MOUNT_C_PRIVATE,0}, {"/sdcard",E63_MOUNT_C_MEDIA,0},
    {"/storage/emulated/0",E63_MOUNT_C_MEDIA,0},
    {"/storage/emulated/legacy",E63_MOUNT_C_MEDIA,1},
    {"/data/media/0",E63_MOUNT_C_MEDIA,1},
    {"/dev/binder",E63_MOUNT_IPC,0}, /* synthetic device, zero disk blocks */
    {"/tmp",E63_MOUNT_RAM,0}, {"/cache",E63_MOUNT_RAM,0}
};

const E63MountEntry *e63_mount_table(size_t *count) {
    if (count) *count = sizeof(kMounts)/sizeof(kMounts[0]);
    return kMounts;
}

static int valid(const char *path) {
    size_t i, segment;
    if (!path || path[0] != '/') return 0;
    for (i = 0; i <= E63_GUEST_PATH_MAX && path[i]; i++) {
        unsigned char c = (unsigned char)path[i];
        if (c < 32 || c == 127 || c == '\\' || c == ':') return 0;
    }
    if (i > E63_GUEST_PATH_MAX || path[i] != 0) return 0;
    if (i == 1) return 1;
    if (path[i - 1] == '/') return 0;
    for (segment = 1; segment < i; ) {
        size_t end = segment;
        while (end < i && path[end] != '/') end++;
        if (end == segment || (end == segment + 1 && path[segment] == '.') ||
            (end == segment + 2 && path[segment] == '.' && path[segment+1] == '.') ||
            path[end-1] == '.' || path[end-1] == ' ')
            return 0; /* FAT can canonicalize a trailing dot/space to an alias. */
        segment = end + 1;
    }
    return 1;
}

static int under(const char *path, const char *mount) {
    size_t len = strlen(mount);
    return strncmp(path, mount, len) == 0 &&
           (path[len] == '\0' || path[len] == '/');
}

static int bundle_asset(const char *path) {
    static const char * const apps[] = {
        "/system/app/Launcher.apk", "/system/app/Settings.apk",
        "/system/app/Store.apk", "/system/app/SystemUI.apk",
        "/system/app/PackageInstaller.apk", "/system/app/FileManager.apk"
    };
    static const char * const framework[] = {
        "/system/framework/core.jar", "/system/framework/core-junit.jar",
        "/system/framework/bouncycastle.jar", "/system/framework/ext.jar",
        "/system/framework/framework.jar",
        "/system/framework/telephony-common.jar",
        "/system/framework/mms-common.jar",
        "/system/framework/android.policy.jar", "/system/framework/services.jar",
        "/system/framework/apache-xml.jar", "/system/framework/framework-res.apk"
    };
    size_t j;
    if (strcmp(path,"/system") == 0 ||
        strcmp(path,"/system/app") == 0 ||
        strcmp(path,"/system/framework") == 0 ||
        strcmp(path,"/system/media") == 0 ||
        strcmp(path,"/system/media/audio") == 0 ||
        strcmp(path,"/system/media/audio/ui") == 0 ||
        strcmp(path,"/system/media/audio/ui/lowbattery.wav") == 0) return 1;
    for (j = 0; j < sizeof(apps)/sizeof(apps[0]); j++)
        if (strcmp(path,apps[j]) == 0) return 1;
    /* New authentic AOSP APK candidates coexist with the six old shim APKs.
     * Exact SHA pins, not an arbitrary /system/app whitelist, define paths. */
#if E63_UI_APK_PIN_COUNT > 0
    for (j = 0; j < E63_UI_APK_PIN_COUNT; j++)
        if (strcmp(path,e63_ui_apk_pins[j].guest_path) == 0) return 1;
#endif
    for (j = 0; j < sizeof(framework)/sizeof(framework[0]); j++)
        if (strcmp(path,framework[j]) == 0) return 1;
    return 0; /* reserved routes != real files: system_image checks pins */
}

E63RouteStatus e63_route_guest_path(const char *path, int write,
                                    E63Caller caller, E63MountRoute *out) {
    const char *rel = "";
    E63MountKind kind;
    int readonly = 0;
    if (!out || !valid(path)) return E63_ROUTE_INVALID;
    memset(out,0,sizeof(*out));
    if (caller != E63_CALLER_OS && caller != E63_CALLER_FILES &&
        caller != E63_CALLER_INSTALLER) return E63_ROUTE_DENIED;
    if (strcmp(path,"/") == 0) {
        kind = E63_MOUNT_RAM;
        readonly = 1;
    } else if (strcmp(path,"/dev/binder") == 0) {
        /* Android /dev/binder is a character-device IPC entry, NEVER a
         * physical or logical storage partition. Only the runtime may open
         * the virtual endpoint. No relative path exists for RFs. */
        if (caller != E63_CALLER_OS) return E63_ROUTE_DENIED;
        kind = E63_MOUNT_IPC;
    } else if (under(path,"/dev")) {
        return E63_ROUTE_UNMAPPED; /* no fake filesystem under /dev */
    } else if (under(path,"/system")) {
        if (!bundle_asset(path)) return E63_ROUTE_UNMAPPED;
        kind = E63_MOUNT_BUNDLE_RO;
        readonly = 1;
        rel = path + strlen("/system");
    } else if (under(path,"/tmp") || under(path,"/cache")) {
        const char *prefix = under(path,"/tmp") ? "/tmp" : "/cache";
        kind = E63_MOUNT_RAM;
        rel = path + 1;
        /* RAM objects have exactly one filename component; no arbitrary trees. */
        if (write && (path[strlen(prefix)] != '/' ||
                      strchr(path + strlen(prefix) + 1,'/')))
            return E63_ROUTE_DENIED;
    } else if (under(path,"/sdcard") || under(path,"/storage/emulated/0") ||
               under(path,"/storage/emulated/legacy") ||
               under(path,"/data/media/0")) {
        const char *prefix = under(path,"/sdcard") ? "/sdcard" :
                             under(path,"/storage/emulated/0") ? "/storage/emulated/0" :
                             under(path,"/storage/emulated/legacy") ?
                             "/storage/emulated/legacy" : "/data/media/0";
        kind = E63_MOUNT_C_MEDIA;
        rel = path + strlen(prefix);
        readonly = strcmp(prefix,"/data/media/0") == 0 ||
                   strcmp(prefix,"/storage/emulated/legacy") == 0;
        if (write && (caller != E63_CALLER_FILES || readonly || *rel == 0))
            return E63_ROUTE_DENIED;
    } else if (under(path,"/data")) {
        kind = E63_MOUNT_C_PRIVATE;
        rel = path + strlen("/data");
        if (caller == E63_CALLER_FILES &&
            !under(path,"/data/data/org.e63.dalvik.files")) return E63_ROUTE_DENIED;
        if (write) {
            /* Installer seeds this pinned cache as SIS payload; guest code
             * must never overwrite a verified boot DEX/index via /data. */
            if (under(path,"/data/e63-bootdex") ||
                under(path,"/data/e63-uiindex")) return E63_ROUTE_DENIED;
            if (*rel == 0) return E63_ROUTE_DENIED;
            if (caller == E63_CALLER_FILES &&
                strcmp(path,"/data/data/org.e63.dalvik.files") == 0)
                return E63_ROUTE_DENIED;
            if (under(path,"/data/app") && caller != E63_CALLER_INSTALLER)
                return E63_ROUTE_DENIED;
            if (caller == E63_CALLER_INSTALLER && !under(path,"/data/app"))
                return E63_ROUTE_DENIED;
        }
    } else {
        return E63_ROUTE_UNMAPPED;
    }
    if (write && readonly) return E63_ROUTE_DENIED;
    out->kind = kind;
    out->read_only = (uint8_t)readonly;
    if (*rel == '/') rel++;
    /* valid() has already bounded the input; rel is a suffix of path. */
    strcpy(out->relative,rel);
    return E63_ROUTE_OK;
}
