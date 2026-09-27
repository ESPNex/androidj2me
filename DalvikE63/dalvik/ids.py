"""System package identifiers shared by the host and the APK builder.

No guest behavior or UI strings live here; those are assembled to DEX in
apps/specs.py, and the runtime reads that bytecode from signed APKs.
"""
BASE = "org.e63.dalvik."
LAUNCHER = BASE + "launcher"
SETTINGS = BASE + "settings"
STORE = BASE + "store"
FILES = BASE + "files"
SYSTEMUI = BASE + "systemui"
INSTALLER = BASE + "packageinstaller"
