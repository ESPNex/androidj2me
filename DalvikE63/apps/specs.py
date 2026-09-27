"""Per-app bridge adapters assembled into classes2.dex inside each APK.

The actual Java ME source (the port plus a new SIS client) is compiled to
classfiles, then D8 converts those classfiles into classes.dex. These tiny adapters expose existing screen flows
to the PC shell; they are not passed off as a translation of the full MIDlet.
The host never executes this Python module when running an APK.
"""
from __future__ import annotations

from dalvik.assembler import Asm, GuestApp, GuestMethod, HOST
from dalvik.ids import LAUNCHER, SETTINGS, STORE, FILES, SYSTEMUI, INSTALLER


def host(name: str, proto: str) -> str:
    return HOST + "->" + name + proto

TITLE = host("title", "(Ljava/lang/String;)V")
TEXT = host("text", "(Ljava/lang/String;)V")
OPTION = host("option", "(ILjava/lang/String;)V")
DIALOG = host("dialog", "(Ljava/lang/String;)V")
OPEN = host("open", "(Ljava/lang/String;)V")
GET = host("getFlag", "(Ljava/lang/String;)I")
SET = host("setFlag", "(Ljava/lang/String;I)V")
INSTALLED = host("isInstalled", "(Ljava/lang/String;)I")
STORE_ACTION = host("storeAction", "()I")
INSTALL = host("install", "(Ljava/lang/String;)I")
LIST = host("list", "(Ljava/lang/String;)V")
SEARCH = host("searchFile", "(Ljava/lang/String;)I")
MKDIR = host("mkdir", "(Ljava/lang/String;)I")
TOUCH = host("touch", "(Ljava/lang/String;)I")
RENAME = host("rename", "(Ljava/lang/String;Ljava/lang/String;)I")
DELETE = host("delete", "(Ljava/lang/String;)I")
IMPORT = host("importFile", "(Ljava/lang/String;Ljava/lang/String;)I")
WAV = host("wav", "(Ljava/lang/String;)I")


def line(a: Asm, text: str):
    a.string(0, text).invoke(TEXT, 0)


def title(a: Asm, text: str):
    a.string(0, text).invoke(TITLE, 0)


def option(a: Asm, index: int, text: str):
    a.const(0, index).string(1, text).invoke(OPTION, 0, 1)


def open_app(a: Asm, package: str):
    a.string(0, package).invoke(OPEN, 0)


def select(a: Asm, choices: list[tuple[int, str, str]]):
    """Compile branching/dispatch to real Dalvik if-eq/goto instructions."""
    for idx, _, _ in choices:
        a.const(0, idx).if_eq(7, 0, "case_%d" % idx)
    a.ret()
    for idx, _, package in choices:
        a.label("case_%d" % idx)
        open_app(a, package)
        a.ret()


def guest(name: str, package: str, label: str, start: Asm, on_select: Asm,
          command: Asm | None = None, *, system: bool = True,
          assets: dict[str, str] | None = None) -> GuestApp:
    methods = [GuestMethod("onStart", "()V", start),
               GuestMethod("onSelect", "(I)V", on_select)]
    if command:
        methods.append(GuestMethod("onCommand", "(ILjava/lang/String;Ljava/lang/String;)V", command))
    return GuestApp(name, package, label, methods, system, assets)


def programs() -> list[GuestApp]:
    all_apps = []

    # Launcher: the old HomeScreen shows File Manager only after installation.
    start = Asm(8)
    title(start, "Launcher")
    line(start, "Android J2ME Edition - Dalvik")
    option(start, 0, "Store (offline)")
    option(start, 1, "Settings")
    start.string(0, FILES).invoke(INSTALLED, 0).result(2).if_eqz(2, "no_files")
    option(start, 2, "File Manager")
    start.label("no_files")
    option(start, 3, "SystemUI (error test)")
    start.ret()
    pick = Asm(8, 1)
    select(pick, [(0, "Store", STORE), (1, "Settings", SETTINGS),
                  (2, "File Manager", FILES), (3, "SystemUI", SYSTEMUI)])
    all_apps.append(guest("Launcher.apk", LAUNCHER, "Launcher", start, pick,
                          assets={"assets/wall.png": "assets/wall.png",
                                  "assets/boot.png": "assets/boot.png"}))

    # Settings: the old Wi-Fi switch is a local demo flag, not device Wi-Fi.
    start = Asm(8)
    title(start, "Settings")
    start.string(0, "wifi_demo").invoke(GET, 0).result(2).if_eqz(2, "wifi_off")
    line(start, "Wi-Fi preview: ON (not device Wi-Fi)")
    start.goto("wifi_done").label("wifi_off")
    line(start, "Wi-Fi preview: OFF (not device Wi-Fi)")
    start.label("wifi_done")
    start.string(0, "adjust_clock").invoke(GET, 0).result(2).if_eqz(2, "clock_off")
    line(start, "Adjust clock (GMT +1): ON")
    start.goto("clock_done").label("clock_off")
    line(start, "Adjust clock (GMT +1): OFF")
    start.label("clock_done")
    option(start, 0, "Toggle Wi-Fi preview")
    option(start, 1, "Toggle clock preview")
    start.ret()
    pick = Asm(8, 1)
    pick.const(0, 0).if_eq(7, 0, "wifi")
    pick.const(0, 1).if_eq(7, 0, "clock")
    pick.ret()
    for key, label in (("wifi_demo", "wifi"), ("adjust_clock", "clock")):
        pick.label(label).string(0, key).invoke(GET, 0).result(2).if_eqz(2, label + "_enable")
        pick.const(2, 0).goto(label + "_save")
        pick.label(label + "_enable").const(2, 1)
        pick.label(label + "_save").string(0, key).invoke(SET, 0, 2).ret()
    all_apps.append(guest("Settings.apk", SETTINGS, "Settings", start, pick,
                          assets={"assets/settings.png": "assets/settings.png"}))

    # Original store has a File Manager card, search and INSTALL -> OPEN.
    start = Asm(8)
    title(start, "Store")
    line(start, "Apps - File Manager - LardeXWare")
    option(start, 0, "File Manager details")
    option(start, 1, "Search: use 'search file manager'")
    start.ret()
    pick = Asm(8, 1)
    pick.const(0, 0).if_eq(7, 0, "store_activate").ret()
    pick.label("store_activate")
    pick.invoke(STORE_ACTION).result(2)
    for value in (1, 2, 3):  # genuine J2ME START_INSTALL / OPEN_APP / WAIT
        pick.const(0, value).if_eq(2, 0, "installer")
    pick.ret()  # unknown outcome is not interpreted as success
    pick.label("installer")
    open_app(pick, INSTALLER)
    pick.ret()
    command = Asm(8, 3)  # v5=command, v6=query, v7=other
    command.const(0, 1).if_ne(5, 0, "end")
    command.invoke(SEARCH, 6).result(2).if_eqz(2, "no_results")
    line(command, "1 result found: File Manager")
    command.goto("end").label("no_results")
    line(command, "No results found.")
    command.label("end").ret()
    all_apps.append(guest("Store.apk", STORE, "Dalvik Store", start, pick, command,
                          assets={"assets/store.png": "assets/store.png",
                                  "assets/banner.png": "assets/banner.png"}))

    # An app in its own right: status/dialog behavior sourced from Canvas's
    # paintSystemError and paintBatteryDialog. It NEVER kills the real UI.
    start = Asm(8)
    title(start, "SystemUI - simulated error")
    start.string(0, "Unfortunately, the process com.android.systemui has stopped.").invoke(DIALOG, 0)
    option(start, 0, "OK - Home")
    option(start, 1, "Low battery dialog (test only)")
    start.ret()
    pick = Asm(8, 1)
    pick.const(0, 0).if_eq(7, 0, "home")
    pick.const(0, 1).if_eq(7, 0, "battery")
    pick.ret()
    pick.label("home")
    open_app(pick, LAUNCHER)
    pick.ret()
    pick.label("battery")
    pick.string(0, "Low battery - example only; no battery level is fabricated.").invoke(DIALOG, 0)
    pick.string(0, "/system/media/audio/ui/lowbattery.wav").invoke(WAV, 0).result(2).ret()
    all_apps.append(guest("SystemUI.apk", SYSTEMUI, "SystemUI", start, pick,
                          assets={"assets/lowbattery.wav": "assets/lowbattery.wav",
                                  "assets/warning.png": "assets/warning.png"}))

    # First-stage package installer installs only a prebuilt, local APK into
    # the host PC VFS. It does NOT install anything onto Symbian.
    start = Asm(8)
    title(start, "Package Installer")
    start.string(0, FILES).invoke(INSTALLED, 0).result(2).if_eqz(2, "not_yet")
    line(start, "File Manager - installed")
    option(start, 0, "OPEN")
    start.goto("done").label("not_yet")
    line(start, "File Manager - LardeXWare")
    option(start, 0, "INSTALL")
    start.label("done").ret()
    pick = Asm(8, 1)
    pick.const(0, 0).if_eq(7, 0, "activate").ret()
    pick.label("activate").string(0, FILES).invoke(INSTALLED, 0).result(2)
    pick.if_eqz(2, "install")
    open_app(pick, FILES)
    pick.ret()
    pick.label("install").string(0, FILES).invoke(INSTALL, 0).result(2).ret()
    all_apps.append(guest("PackageInstaller.apk", INSTALLER, "Package Installer", start, pick,
                          assets={"assets/file.png": "assets/files.png"}))

    # FileManager: existing Android/data -> simulated SystemUI error path, real
    # operations go through host-broker calls emitted as invoke-static in DEX.
    start = Asm(8)
    title(start, "File Manager")
    line(start, "/sdcard - Android / DCIM / Download / Ringtones")
    start.string(0, "/sdcard").invoke(LIST, 0)
    option(start, 0, "Android/data (simulated SystemUI error)")
    option(start, 1, "Play lowbattery.wav")
    option(start, 2, "Play music.wav")
    line(start, "Commands: ls, mkdir, touch, rename, delete, import")
    start.ret()
    pick = Asm(8, 1)
    pick.const(0, 0).if_eq(7, 0, "systemui")
    pick.const(0, 1).if_eq(7, 0, "low")
    pick.const(0, 2).if_eq(7, 0, "music")
    pick.ret()
    pick.label("systemui")
    open_app(pick, SYSTEMUI)
    pick.ret()
    pick.label("low").string(0, "/system/media/audio/ui/lowbattery.wav")
    pick.invoke(WAV, 0).result(2).ret()
    pick.label("music").string(0, "/sdcard/Music/music.wav")
    pick.invoke(WAV, 0).result(2).ret()
    command = Asm(8, 3)  # v5 command; v6 source/path; v7 second path
    for code, label in ((1, "mkdir"), (2, "touch"), (3, "rename"),
                        (4, "delete"), (5, "import"), (6, "list"), (7, "wav")):
        command.const(0, code).if_eq(5, 0, label)
    command.ret()
    for label, ref, args in (("mkdir", MKDIR, (6,)), ("touch", TOUCH, (6,)),
                             ("rename", RENAME, (6, 7)), ("delete", DELETE, (6,)),
                             ("import", IMPORT, (6, 7)), ("list", LIST, (6,)),
                             ("wav", WAV, (6,))):
        command.label(label).invoke(ref, *args)
        if label not in ("list",): command.result(2)
        command.ret()
    all_apps.append(guest("FileManager.apk", FILES, "File Manager", start, pick, command,
                          system=False,
                          assets={"assets/music.wav": "assets/music.wav",
                                  "assets/file.png": "assets/files.png",
                                  "assets/folder.png": "assets/folder.png"}))
    return all_apps
