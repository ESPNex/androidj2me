#ifndef E63_BINDER_IPC_H
#define E63_BINDER_IPC_H
/* Bounded, in-memory Binder transport core for a SINGLE Symbian IPC broker.
 * This is not Linux's binder driver or the complete Android libbinder/JNI.
 * The guest name /dev/binder is a virtual IPC endpoint: these transactions
 * must be carried by a target IPC adapter, NEVER by a disk or partition.
 *
 * AOSP 4.2 wire subset: little-endian int32, UTF-16 String16, interface
 * tokens and 32-bit flat_binder_object HANDLEs with offset metadata;
 * IServiceManager transactions 1-4 on context handle 0. Service callbacks
 * are registered ONLY by an actual native service owner, never synthesized
 * on lookup. FD transfer, weak/death refs, cross-process binder objects,
 * async/oneway, JNI and Android services are NOT implemented and fail closed.
 */
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
#define E63_BINDER_MAX_PARCEL 2048u
#define E63_BINDER_MAX_OBJECTS 8u
#define E63_BINDER_MAX_NODES 16u
#define E63_BINDER_MAX_SERVICES 16u
#define E63_BINDER_MAX_NAME 64u
#define E63_BINDER_CONTEXT_HANDLE 0u
#define E63_BINDER_SERVICE_INTERFACE "android.os.IServiceManager"
#define E63_BINDER_STRICT_MODE_GATHER 0x100u
#define E63_BINDER_SERVICE_GET 1u
#define E63_BINDER_SERVICE_CHECK 2u
#define E63_BINDER_SERVICE_ADD 3u
#define E63_BINDER_SERVICE_LIST 4u

typedef enum E63BinderResult {
    E63_BINDER_OK=0, E63_BINDER_BAD_INPUT=-1, E63_BINDER_DENIED=-2,
    E63_BINDER_NOT_FOUND=-3, E63_BINDER_UNSUPPORTED=-4,
    E63_BINDER_NO_MEMORY=-5, E63_BINDER_MALFORMED=-6,
    E63_BINDER_BUDGET=-7
} E63BinderResult;

typedef struct E63BinderParcel {
    uint8_t bytes[E63_BINDER_MAX_PARCEL];
    uint16_t object_offsets[E63_BINDER_MAX_OBJECTS];
    uint16_t length, cursor;
    uint8_t objects;
} E63BinderParcel;

typedef struct E63BinderDomain E63BinderDomain;
typedef struct E63BinderClient E63BinderClient;
typedef E63BinderResult (*E63BinderService)(void *context, uint32_t code,
                       uint32_t caller_pid, uint32_t caller_uid,
                       E63BinderParcel *request,E63BinderParcel *reply);

void e63_binder_parcel_reset(E63BinderParcel *p);
E63BinderResult e63_binder_write_int(E63BinderParcel *p,int32_t value);
E63BinderResult e63_binder_read_int(E63BinderParcel *p,int32_t *out);
/* UTF-16LE length + code units + NUL + 4-byte padding, ASCII subset only.
 * Unsupported non-ASCII must fail; it MUST NOT be reinterpreted as Latin-1. */
E63BinderResult e63_binder_write_string(E63BinderParcel *p,const char *value);
E63BinderResult e63_binder_read_string(E63BinderParcel *p,char *out,
                                      size_t out_bytes);
E63BinderResult e63_binder_write_token(E63BinderParcel *p,const char *name);
E63BinderResult e63_binder_read_token(E63BinderParcel *p,const char *name);
/* Flat handle objects carry authenticated offset metadata, not C pointers. */
E63BinderResult e63_binder_write_handle(E63BinderParcel *p,uint32_t handle);
E63BinderResult e63_binder_read_handle(E63BinderParcel *p,uint32_t *handle);
E63BinderResult e63_binder_parcel_validate(const E63BinderParcel *p);

E63BinderDomain *e63_binder_new(void);
void e63_binder_free(E63BinderDomain *domain);
/* pid/uid MUST be supplied by the trusted OS/IPC adapter, not from an
 * untrusted Parcel. uid 1000 is Android's system UID; uid 0 is root. */
E63BinderClient *e63_binder_connect(E63BinderDomain *domain,
                                    uint32_t pid,uint32_t uid);
void e63_binder_disconnect(E63BinderClient *client);
/* Export an ACTUAL native service callback. This does NOT start any Android
 * service; absent ActivityManager/etc remain absent after creating a domain. */
E63BinderResult e63_binder_export(E63BinderClient *owner,
                E63BinderService service,void *context,uint32_t *out_handle);
E63BinderResult e63_binder_release(E63BinderClient *client,uint32_t handle);
/* Transaction 0 is reserved; 1..4 on context handle 0 are AOSP 4.2
 * IServiceManager's get/check/add/list. Other handles invoke their registered
 * callback with immutable caller pid/uid obtained from the client session. */
E63BinderResult e63_binder_transact(E63BinderClient *client,uint32_t handle,
                         uint32_t code,const E63BinderParcel *request,
                         E63BinderParcel *reply);
#ifdef __cplusplus
}
#endif
#endif
