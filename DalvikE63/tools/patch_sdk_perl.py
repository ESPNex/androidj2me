#!/usr/bin/env python3
"""Two necessary Perl 5.40 fixes in a PERSONAL local S60 FP1 SDK installation.

No patched Nokia file is bundled or redistributed. Check Nokia_EULA.txt in
YOUR independently obtained SDK before executing the SDK installer/patches.
"""
from __future__ import annotations

import sys
from pathlib import Path


def patch(path: Path, before: str, after: str) -> None:
    text = path.read_text()
    if before in text:
        path.write_text(text.replace(before, after))
    elif after not in text:
        raise ValueError(f"SDK not the expected S60 FP1 + GnuPoc edition: {path}")


def apply(sdk: Path) -> None:
    tools = sdk / "epoc32/tools"
    patch(tools / "e32plat.pm", "defined %{$Plat{$BSF}}", "exists $Plat{$BSF}")
    patch(tools / "e32plat.pm", "defined %{$Plat{$ASSP}}", "exists $Plat{$ASSP}")
    patch(tools / "parser.pm", "defined(@PARSER::nextNonEmptyStrippedDownLine) && ", "")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_sdk_perl.py PATH_TO/installed-s60-fp1-sdk")
    apply(Path(sys.argv[1]))
    print("Installed local SDK: modern Perl syntax fixes applied")
