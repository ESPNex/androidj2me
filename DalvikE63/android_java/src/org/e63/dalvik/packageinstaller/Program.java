package org.e63.dalvik.packageinstaller;

import org.e63.dalvik.runtime.Host;

/** Android requests the system installer; the PC installs a pinned APK in its
 * VFS; E63 can only enable a pre-bundled, pinned guest after two confirmations.
 * OPEN is shown only after the host's explicit verified availability check.
 */
public final class Program {
    private static final String FILES = "org.e63.dalvik.files";
    private Program() {}

    public static void onStart() {
        Host.title("Package Installer");
        Host.image("files.png");
        if (Host.isInstalled(FILES) != 0) {
            Host.text("File Manager - available on this host");
            Host.option(0, "OPEN");
        } else {
            Host.text("File Manager - LardeXWare");
            Host.option(0, "INSTALL / ENABLE (confirmation)");
        }
    }

    public static void onSelect(int choice) {
        if (choice == 0) {
            if (Host.isInstalled(FILES) != 0) Host.open(FILES);
            else Host.install(FILES);
        }
    }

    public static void onCommand(int command, String first, String second) {}
}
