package org.e63.dalvik.launcher;

import org.e63.dalvik.runtime.Host;

/** Launcher Home is decided by this APK's Java/Dalvik bytecode, not Python. */
public final class Program {
    private static final String STORE = "org.e63.dalvik.store";
    private static final String SETTINGS = "org.e63.dalvik.settings";
    private static final String FILES = "org.e63.dalvik.files";
    private static final String SYSTEMUI = "org.e63.dalvik.systemui";
    private Program() {}

    public static void onStart() {
        Host.title("Android J2ME Edition");
        Host.image("wall.png");
        Host.text("Jelly Bean inspired Home - local applications");
        Host.option(0, "Store (offline)");
        Host.option(1, "Settings");
        if (Host.isInstalled(FILES) != 0) Host.option(2, "File Manager");
        Host.option(3, "SystemUI (simulated error)");
    }

    public static void onSelect(int choice) {
        if (choice == 0) Host.open(STORE);
        else if (choice == 1) Host.open(SETTINGS);
        else if (choice == 2) Host.open(FILES);
        else if (choice == 3) Host.open(SYSTEMUI);
    }

    public static void onCommand(int command, String first, String second) {}
}
