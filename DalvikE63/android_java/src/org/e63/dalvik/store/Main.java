package org.e63.dalvik.store;
import org.e63.dalvik.runtime.GuestActivity;

public final class Main extends GuestActivity {
    protected void showProgram() { Program.onStart(); }
    protected void selectProgram(int choice) { Program.onSelect(choice); }
    protected void commandProgram(int code, String a, String b) {
        Program.onCommand(code, a, b);
    }
}
