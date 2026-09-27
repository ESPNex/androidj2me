#!/usr/bin/env python3
"""Minimal GPL GnuPoc 1.22 compatibility edits for GCC 14, glibc, OpenSSL 3.

Applies only to the user's locally downloaded GnuPoc tree, never to Nokia
SDK binaries. Re-running this file on an already patched tree is harmless.
"""
from __future__ import annotations

import sys
from pathlib import Path


def replace(path: Path, old: str, new: str) -> None:
    original = path.read_bytes()
    a, b = old.encode(), new.encode()
    if a not in original:
        if b not in original:
            raise ValueError(f"GnuPoc 1.22 source unexpected at {path}: {old[:48]!r}")
        return
    path.write_bytes(original.replace(a, b))


def apply(root: Path) -> None:
    tools = root / "tools"
    for rel in ("petran-1.1.0/deflate/farray.h",
                "elf2e32/deflate/deflate/farray.h"):
        replace(tools / rel, "verify(InRange(aIndex))", "assert(InRange(aIndex))")
    replace(tools / "bmconv-1.1.0-2/src/pbmcomp.cpp",
            "(foundPath > 0)", "(foundPath != 0)")

    sign = tools / "makesis-4/src/signutils.cpp"
    changes = (
        ("if (key->type == EVP_PKEY_DSA || key->type == EVP_PKEY_DSA1 || key->type == EVP_PKEY_DSA2 || key->type == EVP_PKEY_DSA3 || key->type == EVP_PKEY_DSA4)",
         "if (EVP_PKEY_base_id(key) == EVP_PKEY_DSA)"),
        ("EVP_MD_CTX ctx, verify;\n\tEVP_MD_CTX_init(&ctx);\n\tEVP_MD_CTX_init(&verify);",
         "EVP_MD_CTX* ctx = EVP_MD_CTX_new();\n\tEVP_MD_CTX* verify = EVP_MD_CTX_new();\n\tif (!ctx || !verify) throw SignOpenSSLErr;"),
        ("md = EVP_dss1();", "md = EVP_sha1();"),
        ("EVP_SignInit_ex(&ctx, md, NULL)", "EVP_SignInit_ex(ctx, md, NULL)"),
        ("EVP_VerifyInit(&verify, md)", "EVP_VerifyInit(verify, md)"),
        ("EVP_SignUpdate(&ctx, buffer, controller->Length())",
         "EVP_SignUpdate(ctx, buffer, controller->Length())"),
        ("EVP_VerifyUpdate(&verify, buffer, controller->Length())",
         "EVP_VerifyUpdate(verify, buffer, controller->Length())"),
        ("EVP_SignFinal(&ctx, signature, &siglen, key)",
         "EVP_SignFinal(ctx, signature, &siglen, key)"),
        ("EVP_MD_CTX_cleanup(&ctx);", "EVP_MD_CTX_free(ctx);"),
        ("EVP_VerifyFinal(&verify, signature, siglen, publicKey)",
         "EVP_VerifyFinal(verify, signature, siglen, publicKey)"),
        ("EVP_MD_CTX_cleanup(&verify);", "EVP_MD_CTX_free(verify);"),
        ("\t\t\tint func = ERR_GET_FUNC(err);\n",
         "\t\t\t/* OpenSSL 3 removed the obsolete error function number. */\n"),
        ("lib == ERR_LIB_PEM && func == PEM_F_PEM_READ_BIO && reason == PEM_R_NO_START_LINE",
         "lib == ERR_LIB_PEM && reason == PEM_R_NO_START_LINE"),
        ("lib == ERR_LIB_ASN1 && func == ASN1_F_ASN1_GET_OBJECT && reason == ASN1_R_HEADER_TOO_LONG",
         "lib == ERR_LIB_ASN1 && reason == ASN1_R_HEADER_TOO_LONG"),
        ("\t\tX509_OBJECT obj;\n\t\tobj.type = X509_LU_X509;\n\t\tobj.data.x509 = cert;\n\t\tX509_OBJECT_free_contents(&obj);",
         "\t\tX509_free(cert);"),
    )
    # Replace the comparisons BEFORE deleting the `int func` declaration.
    for a, b in changes[:11]:
        replace(sign, a, b)
    for a, b in changes[12:14]:
        replace(sign, a, b)
    replace(sign, *changes[11])
    replace(sign, *changes[14])
    replace(tools / "makesis-4/src/signsis.cpp",
            "\t\t\t\tX509_OBJECT obj;\n\t\t\t\tobj.type = X509_LU_X509;\n\t\t\t\tobj.data.x509 = cert;\n\t\t\t\tX509_OBJECT_free_contents(&obj);",
            "\t\t\t\tX509_free(cert);")
    replace(tools / "make-3.81/glob/glob.c",
            "#if !defined __alloca && !defined __GNU_LIBRARY__",
            "#if defined(__GNU_LIBRARY__) && !defined(_LIBC)\n"
            "/* Modern glibc no longer exports the internal __alloca and __stat names. */\n"
            "# define __alloca __builtin_alloca\n# define __stat stat\n#endif\n\n"
            "#if !defined __alloca && !defined __GNU_LIBRARY__")
    replace(tools / "make-3.81/main.c", "bsd_signal (", "signal (")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_gnupoc_122.py PATH_TO/gnupoc-package-1.22")
    apply(Path(sys.argv[1]))
    print("GnuPoc 1.22 source: compatibility edits applied")
