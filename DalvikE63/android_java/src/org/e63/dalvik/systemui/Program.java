package org.e63.dalvik.systemui;

import org.e63.dalvik.runtime.Host;

/** Deliberately SIMULATED crash dialog, not Android's privileged SystemUI. */
public final class Program {
    private static final String LAUNCHER = "org.e63.dalvik.launcher";
    private Program() {}

    public static void onStart() {
        Host.title("SystemUI - simulated error");
        Host.image("warning.png");
        Host.dialog("Unfortunately, the process com.android.systemui has stopped.");
        Host.option(0, "OK - Home");
        Host.option(1, "Low battery dialog (test only)");
    }

    public static void onSelect(int choice) {
        if (choice == 0) Host.open(LAUNCHER);
        else if (choice == 1) {
            Host.dialog("Low battery - example only; no battery level is fabricated.");
            Host.wav("/system/media/audio/ui/lowbattery.wav");
        }
    }

    public static void onCommand(int command, String first, String second) {}
}
