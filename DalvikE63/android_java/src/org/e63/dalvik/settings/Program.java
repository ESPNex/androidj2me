package org.e63.dalvik.settings;

import org.e63.dalvik.runtime.Host;

/** Settings preview, not the Nokia radio or system clock. */
public final class Program {
    private Program() {}

    public static void onStart() {
        Host.title("Settings");
        Host.image("settings.png");
        if (Host.getFlag("wifi_demo") != 0)
            Host.text("Wi-Fi preview: ON (not device Wi-Fi)");
        else
            Host.text("Wi-Fi preview: OFF (not device Wi-Fi)");
        if (Host.getFlag("adjust_clock") != 0)
            Host.text("Adjust clock (GMT +1): ON");
        else
            Host.text("Adjust clock (GMT +1): OFF");
        Host.option(0, "Toggle Wi-Fi preview");
        Host.option(1, "Toggle clock preview");
    }

    public static void onSelect(int choice) {
        if (choice == 0) {
            if (Host.getFlag("wifi_demo") == 0) Host.setFlag("wifi_demo", 1);
            else Host.setFlag("wifi_demo", 0);
        } else if (choice == 1) {
            if (Host.getFlag("adjust_clock") == 0) Host.setFlag("adjust_clock", 1);
            else Host.setFlag("adjust_clock", 0);
        }
    }

    public static void onCommand(int command, String first, String second) {}
}
