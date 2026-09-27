#!/usr/bin/env python3
"""Python 3 port of the Android 4.2 build/tools/java-event-log-tags.py output.

Uses only the AOSP .logtags inputs. The original generator needs Python 2;
this produces the same constants and EventLog.writeEvent wrappers without
pretending to implement Android's EventLog native service. Used for compiling
framework/services bytecode, not executing or replacing those services.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

KEYWORDS = frozenset("""abstract continue for new switch assert default goto package synchronized
boolean do if private this break double implements protected throw byte else
import public throws case enum instanceof return transient catch extends int
short try char final interface static void class finally long strictfp volatile
const float native super while""".split())
TYPES = ("ERROR", "int", "long", "String", "Object[]")


def java_name(value: str) -> str:
    name = value[0].lower() + re.sub(r"[^A-Za-z0-9]", "", value.title())[1:]
    return name + "_" if name in KEYWORDS else name


def generate(source: Path, target: Path) -> int:
    package = None
    tags: list[tuple[int, str, str]] = []
    for no, original in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("option java_package "):
            if package is not None:
                raise ValueError("duplicate java_package")
            package = line.removeprefix("option java_package ").strip().rstrip(";")
            if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", package):
                raise ValueError(f"invalid AOSP package {source}:{no}")
            continue
        if line.startswith("option "):
            continue
        match = re.fullmatch(r"([0-9]+)\s+([A-Za-z_]\w*)(?:\s+(.*))?", line)
        if not match:
            raise ValueError(f"invalid AOSP logtags {source}:{no}: {line}")
        ident, name, desc = match.groups()
        if desc and not re.fullmatch(r"\(.*\)", desc):
            raise ValueError(f"invalid AOSP log description {source}:{no}")
        tags.append((int(ident), name, desc or ""))
    if not package or not tags:
        raise ValueError(f"missing AOSP log package or tags: {source}")
    out = [f"/* Generated only from AOSP {source.name}; no host log shim. */",
           f"package {package};", "", "/** @hide */",
           "public class EventLogTags {",
           "  private EventLogTags() { }"]
    for number, name, description in tags:
        out.append(f"  public static final int {name.upper()} = {number};")
        args = [field.strip("() ").split("|") for field in description.split(",")] if description else []
        if any(len(field) < 2 or not field[1].isdigit() or
               int(field[1]) >= len(TYPES) for field in args):
            raise ValueError(f"unsupported tag field {source}:{name}")
        params = ", ".join(TYPES[int(field[1])] + " " + java_name(field[0]) for field in args)
        names = "".join(", " + java_name(field[0]) for field in args)
        out += [f"  public static void {java_name('write_' + name)}({params}) {{",
                f"    android.util.EventLog.writeEvent({name.upper()}{names});",
                "  }"]
    out.append("}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(tags)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    print(generate(args.source, args.target), "AOSP log tags generated")
