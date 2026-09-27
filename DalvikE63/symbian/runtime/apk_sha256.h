#ifndef E63_APK_SHA256_H
#define E63_APK_SHA256_H
/* Portable C99 SHA-256 of an entire, bounded APK. No platform crypto needed.
 * Pinning a whole archive does NOT verify the Android signer for arbitrary
 * updates; it authenticates only the exact, preapproved built-in APK bytes.
 */
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Incremental form for pinning persistent /system files directly from RFs
 * in small chunks. Does not require loading a whole framework JAR into RAM.
 * Finalize once after zero or more updates; callers cap total input size. */
typedef struct E63Sha256Context {
    uint32_t state[8];
    uint8_t pending[64];
    size_t pending_length;
    uint64_t total_length;
} E63Sha256Context;
void e63_sha256_init(E63Sha256Context *ctx);
void e63_sha256_update(E63Sha256Context *ctx,
                       const uint8_t *bytes, size_t length);
void e63_sha256_final(E63Sha256Context *ctx, uint8_t digest[32]);
void e63_apk_sha256(const uint8_t *bytes, size_t length, uint8_t digest[32]);
#ifdef __cplusplus
}
#endif
#endif
