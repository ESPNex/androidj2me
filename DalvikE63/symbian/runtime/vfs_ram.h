#ifndef E63_VFS_RAM_H
#define E63_VFS_RAM_H

/* Bounded volatile file backing for guest /tmp and /cache on a future S60
 * process. One E63RamFs per process; destroying it erases the data. The root
 * namespace is the static mount table in vfs_mount.c, not a disk directory.
 */
#include "vfs_mount.h"
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define E63_RAM_MAX_FILES 32u
#define E63_RAM_FILE_MAX (64u * 1024u)
#define E63_RAM_TOTAL_MAX (256u * 1024u)

typedef struct E63RamFs E63RamFs;
typedef enum E63RamStatus {
    E63_RAM_OK = 0,
    E63_RAM_INVALID = -1,
    E63_RAM_DENIED = -2,
    E63_RAM_NOT_FOUND = -3,
    E63_RAM_LIMIT = -4,
    E63_RAM_NO_MEMORY = -5,
    E63_RAM_BUFFER_TOO_SMALL = -6
} E63RamStatus;

E63RamFs *e63_ram_new(void);
void e63_ram_free(E63RamFs *fs);
E63RamStatus e63_ram_write(E63RamFs *fs, const char *path, E63Caller caller,
                           const uint8_t *data, size_t size);
/* *size is capacity on entry and required/actual bytes on return. */
E63RamStatus e63_ram_read(const E63RamFs *fs, const char *path, E63Caller caller,
                          uint8_t *buffer, size_t *size);
E63RamStatus e63_ram_delete(E63RamFs *fs, const char *path, E63Caller caller);
size_t e63_ram_bytes_used(const E63RamFs *fs);

#ifdef __cplusplus
}
#endif
#endif
