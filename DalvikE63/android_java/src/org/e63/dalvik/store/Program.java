package org.e63.dalvik.store;

import org.e63.dalvik.runtime.Host;

/** Offline catalogue. INSTALL is offered by the separate PackageInstaller. */
public final class Program {
    private static final String INSTALLER = "org.e63.dalvik.packageinstaller";
    private Program() {}

    public static void onStart() {
        Host.title("Store - local preview");
        Host.image("store.png");
        Host.image("banner.png");
        Host.text("Catalogo locale: città · café ☕ 😀");
        Host.option(0, "File Manager details / INSTALL");
        Host.input(1, "Search local catalogue", 1);
    }

    public static void onSelect(int choice) {
        if (choice == 0) Host.open(INSTALLER);
    }

    public static void onCommand(int command, String first, String second) {
        if (command == 1) {
            if (Host.searchFile(first) != 0) Host.text("1 result found: File Manager");
            else Host.text("No results found.");
        }
    }
}
