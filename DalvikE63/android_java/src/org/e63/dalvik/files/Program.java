package org.e63.dalvik.files;

import org.e63.dalvik.runtime.Host;

/** Real host-brokered file operations, not an Android/data mock directory. */
public final class Program {
    private static final String SYSTEMUI = "org.e63.dalvik.systemui";
    private Program() {}

    public static void onStart() {
        Host.title("File Manager");
        Host.image("files.png");
        Host.text("/sdcard - DCIM / Download / Music / Ringtones (private C:)");
        Host.list("/sdcard");
        Host.option(0, "Android/data (simulated SystemUI error)");
        Host.option(1, "Play lowbattery.wav");
        Host.option(2, "Play music.wav");
        Host.input(6, "List folder", 1);
        Host.input(1, "Create folder", 1);
        Host.input(2, "Create empty file", 1);
        Host.input(3, "Rename", 2);
        Host.input(4, "Delete", 1);
        Host.input(5, "Import from Nokia drop folder", 2);
        Host.input(7, "Play WAV", 1);
    }

    public static void onSelect(int choice) {
        if (choice == 0) Host.open(SYSTEMUI);
        else if (choice == 1) Host.wav("/system/media/audio/ui/lowbattery.wav");
        else if (choice == 2) Host.wav("/sdcard/Music/music.wav");
    }

    public static void onCommand(int command, String first, String second) {
        if (command == 1) Host.mkdir(first);
        else if (command == 2) Host.touch(first);
        else if (command == 3) Host.rename(first, second);
        else if (command == 4) Host.delete(first);
        else if (command == 5) Host.importFile(first, second);
        else if (command == 6) Host.list(first);
        else if (command == 7) Host.wav(first);
    }
}
