/* GCCE 3.4.3 / S60 3.1 ships no <stdint.h>. Compile-only portability shim.
 * This directory is used as a USERINCLUDE by the S60 build; the desktop
 * compiler keeps using its normal system header. No Nokia header is copied.
 */
#ifndef E63_SYMBIAN_STDINT_H
#define E63_SYMBIAN_STDINT_H
#ifdef __symbian__
#include <stddef.h>
#include <limits.h>
typedef signed char int8_t;
typedef unsigned char uint8_t;
typedef signed short int16_t;
typedef unsigned short uint16_t;
typedef signed int int32_t;
typedef unsigned int uint32_t;
typedef signed long long int64_t;
typedef unsigned long long uint64_t;
#define UINT32_MAX 4294967295U
#define SIZE_MAX ((size_t)-1)
#else
#include_next <stdint.h>
#endif
#endif
