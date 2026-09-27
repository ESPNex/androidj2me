#ifndef E63_DEX_PREFLIGHT_H
#define E63_DEX_PREFLIGHT_H

/* Portable C99 entry validation for Android DEX 035/036 images.
 * No Android SDK and no Python dependencies; usable by a future S60 loader.
 * This is NOT a DEX interpreter, a signature verifier, or a SIS application.
 */
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define E63_DEX_MAX_BYTES (32u * 1024u * 1024u)

typedef enum E63DexStatus {
    E63_DEX_OK = 0,
    E63_DEX_BAD_INPUT = 1,
    E63_DEX_BAD_HEADER = 2,
    E63_DEX_BAD_CHECKSUM = 3,
    E63_DEX_BAD_TABLE = 4,
    E63_DEX_BAD_ENCODING = 5
} E63DexStatus;

typedef struct E63DexView {
    const uint8_t *data;     /* Borrowed: caller must keep the buffer alive. */
    size_t size;
    uint32_t strings_count, strings_off;
    uint32_t types_count, types_off;
    uint32_t protos_count, protos_off;
    uint32_t fields_count, fields_off;
    uint32_t methods_count, methods_off;
    uint32_t classes_count, classes_off;
    uint32_t data_off, data_count;
} E63DexView;

typedef struct E63DexMethod {
    uint32_t method_index, class_index, code_off;
    uint16_t registers, ins, outs, tries;
    uint32_t words_count;
    const uint8_t *words_le; /* Borrowed; read unaligned LE instruction words. */
} E63DexMethod;

E63DexStatus e63_dex_open(const uint8_t *bytes, size_t count, E63DexView *out);
/* DEX string_data: validates Modified UTF-8 and declared UTF-16 unit count.
 * Output is scalar UTF-8 with a C terminator; *used counts bytes INCLUDING
 * any embedded U+0000 but EXCLUDING the terminator. Lone Java surrogates are
 * accepted in preflight but cannot be represented in Unicode scalar UTF-8:
 * this conversion returns 0 for them. Caller must reject embedded NUL before
 * passing the output to any API that takes a C string. No allocation. */
int e63_dex_string_utf8(const E63DexView *view, uint32_t string_index,
                        char *output, size_t capacity, size_t *used);
/* 1 = class defines at least one METHOD with actual code; 0 = missing;
 * -1 = invalid class_data/code. No execution occurs here. */
int e63_dex_has_code(const E63DexView *view, const char *class_descriptor,
                     const char *method_name);
/* Returns -1 for malformed class data, else number of methods with code. */
int e63_dex_count_code(const E63DexView *view);
/* 1 = unique executable method, 0 = not found, -1 = invalid/ambiguous.
 * Exact owner + name + prototype; never choose an overload by name alone. */
int e63_dex_find_code(const E63DexView *view, const char *class_descriptor,
                      const char *method_name, const char *prototype,
                      E63DexMethod *out);
/* Resolve an invoked method_id to its executable definition. As above,
 * 1 = unique, 0 = missing/native-only, -1 = invalid or ambiguous. */
int e63_dex_find_code_id(const E63DexView *view, uint32_t method_index,
                         E63DexMethod *out);
/* Resolve a field by EXACT owner, name and type; -1 = missing/ambiguous.
 * This accessor is for initializing host-provided guest object state. */
int e63_dex_field_id(const E63DexView *view, const char *class_descriptor,
                     const char *field_name, const char *type_descriptor);
/* IDs are resolved from the verified DEX, never a parallel source adapter. */
int e63_dex_class_index(const E63DexView *view, const char *class_descriptor);
/* Exact class_def superclass chain (no dynamic class loading). */
int e63_dex_super_is(const E63DexView *view, const char *child,
                     const char *parent);
int e63_dex_field_is(const E63DexView *view, uint32_t index,
                     uint32_t owning_class, const char *type_descriptor);
int e63_dex_method_ref_is(const E63DexView *view, uint32_t index,
                          const char *class_descriptor, const char *method_name,
                          const char *prototype);
const char *e63_dex_status(E63DexStatus status);

#ifdef __cplusplus
}
#endif
#endif
