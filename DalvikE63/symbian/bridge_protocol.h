#ifndef E63_BRIDGE_PROTOCOL_H
#define E63_BRIDGE_PROTOCOL_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Stateless V1 frame validator shared by the host tests and Symbian server.
 * Only PING is authorized; it cannot modify files, launch apps or run code.
 * req excludes the trailing TCP stream data (exactly one newline required).
 * Positive return: byte length of OK reply; negative: byte length of DENIED.
 * Zero: output buffer too small / invalid server pin.
 */
int e63_reply(const unsigned char *req, size_t n, const char pin[7],
              unsigned char *reply, size_t capacity);
#ifdef __cplusplus
}
#endif
#endif
