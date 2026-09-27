#include "vfs_ram.h"
#include <stdlib.h>
#include <string.h>

typedef struct RamEntry {
    char path[E63_GUEST_PATH_MAX + 1];
    uint8_t *data;
    size_t size;
    uint8_t used;
} RamEntry;
struct E63RamFs {
    RamEntry entries[E63_RAM_MAX_FILES];
    size_t total_bytes;
};

static E63RamStatus route_file(const char *path, E63Caller caller, int write,
                               E63MountRoute *out) {
    E63RouteStatus status=e63_route_guest_path(path,write,caller,out);
    if (status == E63_ROUTE_INVALID) return E63_RAM_INVALID;
    if (status != E63_ROUTE_OK) return E63_RAM_DENIED;
    if (out->kind != E63_MOUNT_RAM ||
        !(strncmp(out->relative,"tmp/",4)==0 ||
          strncmp(out->relative,"cache/",6)==0)) return E63_RAM_DENIED;
    return E63_RAM_OK;
}

E63RamFs *e63_ram_new(void) { return (E63RamFs *)calloc(1,sizeof(E63RamFs)); }

void e63_ram_free(E63RamFs *fs) {
    size_t i;
    if (!fs) return;
    for (i=0;i<E63_RAM_MAX_FILES;i++) free(fs->entries[i].data);
    free(fs);
}

static int find(const E63RamFs *fs, const char *path) {
    size_t i;
    for (i=0;i<E63_RAM_MAX_FILES;i++)
        if (fs->entries[i].used && strcmp(fs->entries[i].path,path)==0)
            return (int)i;
    return -1;
}

E63RamStatus e63_ram_write(E63RamFs *fs, const char *path, E63Caller caller,
                           const uint8_t *data, size_t size) {
    E63MountRoute route;
    RamEntry *entry;
    uint8_t *replacement;
    size_t existing=0, i;
    int slot;
    E63RamStatus status=route_file(path,caller,1,&route);
    if (!fs || !path || (size && !data)) return E63_RAM_INVALID;
    if (status!=E63_RAM_OK) return status;
    if (size>E63_RAM_FILE_MAX) return E63_RAM_LIMIT;
    slot=find(fs,path);
    if (slot>=0) existing=fs->entries[slot].size;
    if (size > E63_RAM_TOTAL_MAX - (fs->total_bytes - existing))
        return E63_RAM_LIMIT;
    if (slot<0) {
        for (i=0;i<E63_RAM_MAX_FILES && fs->entries[i].used;i++);
        if (i==E63_RAM_MAX_FILES) return E63_RAM_LIMIT;
        slot=(int)i;
    }
    replacement=(uint8_t *)malloc(size ? size : 1u);
    if (!replacement) return E63_RAM_NO_MEMORY;
    if (size) memcpy(replacement,data,size);
    entry=&fs->entries[slot];
    free(entry->data);
    entry->data=replacement;
    entry->size=size;
    strcpy(entry->path,path);
    entry->used=1;
    fs->total_bytes=fs->total_bytes-existing+size;
    return E63_RAM_OK;
}

E63RamStatus e63_ram_read(const E63RamFs *fs, const char *path, E63Caller caller,
                          uint8_t *buffer, size_t *size) {
    E63MountRoute route;
    int slot;
    E63RamStatus status=route_file(path,caller,0,&route);
    if (!fs || !path || !size) return E63_RAM_INVALID;
    if (status!=E63_RAM_OK) return status;
    slot=find(fs,path);
    if (slot<0) return E63_RAM_NOT_FOUND;
    if (*size<fs->entries[slot].size || (!buffer && fs->entries[slot].size)) {
        *size=fs->entries[slot].size;
        return E63_RAM_BUFFER_TOO_SMALL;
    }
    *size=fs->entries[slot].size;
    if (*size) memcpy(buffer,fs->entries[slot].data,*size);
    return E63_RAM_OK;
}

E63RamStatus e63_ram_delete(E63RamFs *fs, const char *path, E63Caller caller) {
    E63MountRoute route;
    int slot;
    E63RamStatus status=route_file(path,caller,1,&route);
    if (!fs || !path) return E63_RAM_INVALID;
    if (status!=E63_RAM_OK) return status;
    slot=find(fs,path);
    if (slot<0) return E63_RAM_NOT_FOUND;
    fs->total_bytes-=fs->entries[slot].size;
    free(fs->entries[slot].data);
    memset(&fs->entries[slot],0,sizeof(fs->entries[slot]));
    return E63_RAM_OK;
}

size_t e63_ram_bytes_used(const E63RamFs *fs) {
    return fs ? fs->total_bytes : 0;
}
