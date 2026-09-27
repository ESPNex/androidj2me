#ifndef E63_VFS_MOUNT_H
#define E63_VFS_MOUNT_H

/* Portable bounded guest-path router. /system/app is backed by exact,
 * SHA-256-pinned APK files in C:\\private\\E0B63E04\\system\\app\\.
 * /system/framework is a reserved read-only namespace; its files are NOT
 * available until real runtime artifacts have been built and pinned.
 * /sdcard maps to C: private media via e63_file_services.cpp. /dev/binder
 * names an IPC ENDPOINT, never a disk, a partition or a writable C: file.
 * Other roots remain routing-only: no generic Android rootfs or native OS
 * partition.
 */
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define E63_GUEST_PATH_MAX 512

typedef enum E63MountKind {
    E63_MOUNT_RAM = 1,
    E63_MOUNT_BUNDLE_RO = 2,
    E63_MOUNT_C_PRIVATE = 3,
    E63_MOUNT_C_MEDIA = 4,
    E63_MOUNT_IPC = 5 /* virtual /dev/binder, NOT a filesystem backing */
} E63MountKind;

typedef enum E63Caller {
    E63_CALLER_OS = 1,
    E63_CALLER_FILES = 2,
    E63_CALLER_INSTALLER = 3
} E63Caller;

typedef enum E63RouteStatus {
    E63_ROUTE_OK = 0,
    E63_ROUTE_INVALID = -1,
    E63_ROUTE_DENIED = -2,
    E63_ROUTE_UNMAPPED = -3
} E63RouteStatus;

typedef struct E63MountRoute {
    E63MountKind kind;
    uint8_t read_only;
    /* Relative to mount root; never an unvalidated absolute C: path. */
    char relative[E63_GUEST_PATH_MAX + 1];
} E63MountRoute;

typedef struct E63MountEntry {
    const char *guest;
    E63MountKind kind;
    uint8_t read_only;
} E63MountEntry;
/* Statically allocated namespace descriptors; NOT physical disk partitions. */
const E63MountEntry *e63_mount_table(size_t *count);

E63RouteStatus e63_route_guest_path(const char *path, int write,
                                    E63Caller caller, E63MountRoute *out);

#ifdef __cplusplus
}
#endif
#endif
