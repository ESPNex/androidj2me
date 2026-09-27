package android.j2me.edition;

/** One source of truth for the simulated installation. No network/real store. */
public final class StoreState {
    public static final int START_INSTALL = 1;
    public static final int OPEN_APP = 2;
    public static final int WAIT = 3;

    private boolean installed;
    private boolean installing;

    public StoreState(boolean savedInstallation) {
        installed = savedInstallation;
    }

    public synchronized int activate() {
        // Important: an installed app is ALWAYS opened, never reinstalled.
        if (installed) return OPEN_APP;
        if (installing) return WAIT;
        installing = true;
        return START_INSTALL;
    }

    public synchronized void finishInstall() {
        if (installing) {
            installed = true;
            installing = false;
        }
    }

    public synchronized boolean isInstalled() {
        return installed;
    }

    public synchronized boolean isInstalling() {
        return installing;
    }
}
