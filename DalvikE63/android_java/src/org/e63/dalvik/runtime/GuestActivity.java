package org.e63.dalvik.runtime;

import android.app.Activity;
import android.os.Bundle;

/** An ordinary Android Activity, not a MIDlet or a host-rendered mock screen.
 * Each APK's own Program chooses its strings, assets, options and actions.
 * The E63 interpreter separately maps Host's small API to device primitives.
 */
public abstract class GuestActivity extends Activity {
    private boolean resumedOnce;
    protected abstract void showProgram();
    protected abstract void selectProgram(int choice);
    protected void commandProgram(int command, String first, String second) {}

    @Override public void onCreate(Bundle state) {
        setTheme(android.R.style.Theme_Holo_NoActionBar);
        super.onCreate(state);
        redraw();
    }

    @Override public void onStart() {
        super.onStart();
    }

    @Override public void onResume() {
        super.onResume();
        if (resumedOnce) redraw(); // returned from Android's installer/dialog
        resumedOnce = true;
    }

    @Override public void onPause() {
        super.onPause();
    }

    @Override public void onStop() {
        super.onStop();
    }

    @Override public void onDestroy() {
        super.onDestroy();
    }

    public final void redraw() {
        Host.begin(this);
        showProgram();
    }

    final void choose(int choice) {
        selectProgram(choice);
        if (!isFinishing() && !Host.navigated()) redraw();
    }

    final void command(int code, String first, String second) {
        // Search/list commands append their Java-generated results to the
        // current Activity. Clearing the view here would erase the result.
        commandProgram(code, first, second);
    }
}
