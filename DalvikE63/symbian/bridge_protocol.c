#include "bridge_protocol.h"

static const unsigned char prefix[] = "E63BRIDGE/1\tAUTH\t";
static const unsigned char suffix[] = "\tPING\n";
static const unsigned char ok[] = "E63BRIDGE/1\tOK\tPONG\n";
static const unsigned char denied[] = "E63BRIDGE/1\tERR\tDENIED\n";

int e63_reply(const unsigned char *req, size_t n, const char pin[7],
              unsigned char *reply, size_t capacity)
{
    size_t i;
    unsigned char diff = 0;
    int valid = 1;
    const size_t pre = sizeof(prefix) - 1;
    const size_t post = sizeof(suffix) - 1;
    const size_t expected = pre + 6 + post;
    const unsigned char *response;
    size_t answer;
    if (!req || !pin || !reply) return 0;
    for (i = 0; i < 6; ++i) {
        if (pin[i] < '0' || pin[i] > '9') return 0;
    }
    if (pin[6] != '\0') return 0;
    if (n != expected || n > 96) valid = 0;
    if (valid) {
        for (i = 0; i < pre; ++i) diff |= (unsigned char)(req[i] ^ prefix[i]);
        for (i = 0; i < 6; ++i) diff |= (unsigned char)(req[pre + i] ^ (unsigned char)pin[i]);
        for (i = 0; i < post; ++i)
            diff |= (unsigned char)(req[pre + 6 + i] ^ suffix[i]);
        if (diff) valid = 0;
    }
    response = valid ? ok : denied;
    answer = valid ? sizeof(ok) - 1 : sizeof(denied) - 1;
    if (capacity < answer) return 0;
    for (i = 0; i < answer; ++i) reply[i] = response[i];
    return valid ? (int)answer : -(int)answer;
}
