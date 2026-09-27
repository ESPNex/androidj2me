package org.e63.dalvik.launcher;

import org.e63.dalvik.runtime.GuestActivity;

/** API-17 Activity; E63 executes this Main/GuestActivity DEX using narrow framework shims. */
public final class Main extends GuestActivity {
    protected void showProgram() { Program.onStart(); }
    protected void selectProgram(int choice) { Program.onSelect(choice); }
    protected void commandProgram(int action, String a, String b) {
        Program.onCommand(action, a, b);
    }
}
