package android.j2me.edition;

import java.util.Calendar;
import javax.microedition.lcdui.Command;
import javax.microedition.lcdui.CommandListener;
import javax.microedition.lcdui.Display;
import javax.microedition.lcdui.Displayable;
import javax.microedition.lcdui.Form;
import javax.microedition.lcdui.TextField;
import javax.microedition.midlet.MIDlet;
import javax.microedition.rms.RecordStore;

/** Original Android J2ME Edition flow, genuinely ported to MIDP 2.0/CLDC 1.1. */
public final class E63Midlet extends MIDlet implements CommandListener {
    static final int BOOT = 0;
    static final int HOME = 1;
    static final int SETTINGS = 2;
    static final int NO_INTERNET = 3;
    static final int LOGIN = 4;
    static final int STORE = 5;
    static final int APP = 6;
    static final int NO_RESULTS = 7;
    static final int FILES = 8;
    static final int ANDROID_FOLDER = 9;
    static final int EMPTY_FOLDER = 10;
    static final int SYSTEM_ERROR = 11;
    static final int BATTERY_ALERT = 12;
    static final int POWER_OFF = 13;

    static final int EDIT_EMAIL = 1;
    static final int EDIT_PASSWORD = 2;
    static final int EDIT_SEARCH = 3;

    volatile int screen = BOOT;
    final int[] selected = new int[14];
    volatile boolean wifiOn;
    volatile boolean loggedIn;
    volatile boolean adjustClock;
    volatile String emailDraft = "";
    // Never keep the password itself, not even in a MIDlet field or RMS record.
    volatile int passwordLength;
    volatile String query = "";
    volatile String audioPlaying = "";
    volatile boolean oneResult;
    // -1 means that the phone has not exposed a real battery reading.
    volatile int battery = -1;
    volatile int installPercent;
    volatile long bootStarted;
    private long lastBatteryPoll;
    volatile long installStarted;
    volatile long powerStarted;
    private int folderReturnScreen = FILES;
    private int alertReturnScreen = HOME;
    StoreState store;

    private Display display;
    private E63Canvas canvas;
    private AudioDeck audio;
    private volatile boolean running;
    private volatile int tickerGeneration;
    // On some S60 builds the Home key backgrounds the MIDlet without
    // delivering keyPressed. Restore our own Home page when it resumes.
    private volatile boolean resumeAtHome;
    private boolean alertedLowBattery;
    private Thread ticker;
    volatile int editMode;
    private String previousEmail = "";
    private String previousQuery = "";
    private int previousPasswordLength;
    private boolean savedInstalled;
    private volatile Form editorForm;
    private volatile TextField editorField;
    private long lastBackPressed;
    // The fullscreen Canvas has NO CommandListener: Nokia's physical left
    // softkey must reach Canvas.keyPressed(-6) directly. Native editor Forms
    // use MIDP Commands, since Form does not expose raw keyPressed events.
    private Command editDoneCommand;
    private Command editBackCommand;

    protected void startApp() {
        if (display == null) {
            display = Display.getDisplay(this);
            // MicroEmulator's resizable skin assigns BACK to the left and OK
            // to the right; Nokia S60 assigns these command types oppositely.
            // In both, cancel (..) belongs to the PHYSICAL LEFT softkey.
            boolean reversedEmulatorKeys = false;
            try {
                reversedEmulatorKeys = "MicroEmulator".equals(
                        System.getProperty("microedition.platform"));
            } catch (SecurityException ignored) { }
            editDoneCommand = new Command("OK", reversedEmulatorKeys ?
                    Command.OK : Command.BACK, 2);
            editBackCommand = new Command("..", reversedEmulatorKeys ?
                    Command.BACK : Command.OK, 1);
            loadSettings();
            store = new StoreState(savedInstalled);
            audio = new AudioDeck(this);
            canvas = new E63Canvas(this);
            canvas.setFullScreenMode(true);
            bootStarted = System.currentTimeMillis();
            refreshBattery(true);
        }
        if (resumeAtHome) {
            resumeAtHome = false;
            home();
        }
        display.setCurrent(editorForm == null ? (Displayable) canvas : (Displayable) editorForm);
        refreshBattery(true);
        if (!running) {
            running = true;
            final int generation = ++tickerGeneration;
            ticker = new Thread(new Runnable() {
                public void run() { tickLoop(generation); }
            });
            ticker.start();
        }
    }

    protected void pauseApp() {
        resumeAtHome = true;
        stopTicker();
        if (audio != null) audio.stop();
    }

    // Some S60 firmware hides the Canvas without invoking pauseApp(). This
    // restores the in-app Home on return, not the phone's system Home itself.
    void canvasHidden() {
        if (editorForm == null) resumeAtHome = true;
    }

    void canvasShown() {
        if (resumeAtHome) {
            resumeAtHome = false;
            home();
        }
    }

    protected void destroyApp(boolean unconditional) {
        stopTicker();
        if (audio != null) audio.stop();
        if (editorField != null) editorField.setString("");
        editorField = null;
        editorForm = null;
        emailDraft = "";
        previousEmail = "";
        passwordLength = 0;
        previousPasswordLength = 0;
        editMode = 0;
        saveSettings();
    }

    private void stopTicker() {
        running = false;
        ++tickerGeneration;
        if (ticker != null) ticker.interrupt();
    }

    private void exit() {
        destroyApp(true);
        notifyDestroyed();
    }

    void navigate(int target) {
        if (editorForm != null) {
            if (editorField != null) editorField.setString("");
            editorField = null;
            editorForm = null;
            display.setCurrent(canvas);
        }
        if (screen == LOGIN && target != LOGIN) {
            emailDraft = "";
            previousEmail = "";
            passwordLength = 0;
            previousPasswordLength = 0;
        }
        editMode = 0;
        screen = target;
        selected[target] = 0;
        canvas.repaint();
    }

    int listCount() {
        switch (screen) {
            case HOME: return store.isInstalled() ? 3 : 2;
            case SETTINGS: return 2;
            case LOGIN: return 3;
            case STORE: return 2;
            case FILES: return 6;
            case ANDROID_FOLDER: return 3;
            default: return 1;
        }
    }

    void move(int delta) {
        if (editMode != 0 || screen == BOOT || screen == POWER_OFF) return;
        int count = listCount();
        if (count > 1) {
            selected[screen] = (selected[screen] + delta + count) % count;
            canvas.repaint();
        }
    }

    void activate() {
        if (editMode != 0) { commitEditing(); return; }
        int choice = selected[screen];
        switch (screen) {
            case BOOT:
                navigate(HOME);
                break;
            case HOME:
                if (store.isInstalled() && choice == 0) navigate(FILES);
                else if (choice == (store.isInstalled() ? 1 : 0)) enterStore();
                else navigate(SETTINGS);
                break;
            case SETTINGS:
                if (choice == 0) wifiOn = !wifiOn;
                else adjustClock = !adjustClock;
                saveSettings();
                break;
            case NO_INTERNET:
                // The Swing OK handler was empty. The same button now reaches
                // the setting needed to make the offline demo screen navigable.
                navigate(SETTINGS);
                break;
            case LOGIN:
                if (choice == 0) startEditing(EDIT_EMAIL);
                else if (choice == 1) startEditing(EDIT_PASSWORD);
                else {
                    // No Google login: all inputs are optional local mock data.
                    // No password or email is sent anywhere or stored in RMS.
                    emailDraft = "";
                    previousEmail = "";
                    passwordLength = 0;
                    loggedIn = true;
                    saveSettings();
                    navigate(STORE);
                }
                break;
            case STORE:
                if (choice == 0) startEditing(EDIT_SEARCH);
                else navigate(APP);
                break;
            case APP:
                int action = store.activate();
                if (action == StoreState.OPEN_APP) {
                    // The original OPEN erroneously reran INSTALL. Launch it.
                    navigate(FILES);
                } else if (action == StoreState.START_INSTALL) {
                    installStarted = System.currentTimeMillis();
                    installPercent = 0;
                }
                // WAIT must not reset the running download timer.
                break;
            case NO_RESULTS:
                navigate(STORE);
                break;
            case FILES:
                if (choice == 0) navigate(ANDROID_FOLDER);
                else if (choice < 4) {
                    folderReturnScreen = FILES;
                    navigate(EMPTY_FOLDER);
                } else if (choice == 4) {
                    audio.play("/lowbattery.wav", "lowbattery.wav playing...");
                } else {
                    audio.play("/music.wav", "Disfigure - Blank (NCS Release).wav playing...");
                }
                break;
            case ANDROID_FOLDER:
                if (choice == 0) navigate(FILES);
                else if (choice == 1) navigate(SYSTEM_ERROR);
                else {
                    folderReturnScreen = ANDROID_FOLDER;
                    navigate(EMPTY_FOLDER);
                }
                break;
            case EMPTY_FOLDER:
                navigate(folderReturnScreen);
                break;
            case SYSTEM_ERROR:
                navigate(HOME);
                break;
            case BATTERY_ALERT:
                navigate(alertReturnScreen);
                break;
            case POWER_OFF:
                exit();
                break;
            default:
                break;
        }
        canvas.repaint();
    }

    private void enterStore() {
        if (!wifiOn) navigate(NO_INTERNET);
        else if (!loggedIn) navigate(LOGIN);
        else navigate(STORE);
    }

    void back() {
        // Avoid two Back actions if a native editor Command and a key event
        // from the Canvas arrive close together during a display switch.
        long now = System.currentTimeMillis();
        if (now - lastBackPressed < 220L) return;
        lastBackPressed = now;
        if (editMode != 0) {
            if (editorForm != null) finishNativeEditing(false);
            else cancelEditing();
            return;
        }
        switch (screen) {
            case BOOT: navigate(HOME); break;
            case HOME: exit(); break;
            case SETTINGS: navigate(HOME); break;
            case NO_INTERNET: navigate(HOME); break;
            case LOGIN:
                emailDraft = "";
                previousEmail = "";
                passwordLength = 0;
                navigate(HOME);
                break;
            case STORE: navigate(HOME); break;
            case APP: navigate(STORE); break;
            case NO_RESULTS: navigate(STORE); break;
            case FILES: navigate(HOME); break;
            case ANDROID_FOLDER: navigate(FILES); break;
            case EMPTY_FOLDER: navigate(folderReturnScreen); break;
            case SYSTEM_ERROR: navigate(HOME); break;
            case BATTERY_ALERT: navigate(alertReturnScreen); break;
            case POWER_OFF: exit(); break;
            default: navigate(HOME); break;
        }
    }

    void home() {
        if (screen != BOOT && screen != POWER_OFF) navigate(HOME);
    }

    public void commandAction(Command command, Displayable source) {
        if (source == editorForm && editorForm != null) {
            if (command == editDoneCommand) finishNativeEditing(true);
            else if (command == editBackCommand) back();
        }
    }

    // Canvas keyPressed does not offer a reliable QWERTY text input method on
    // every Nokia E63 firmware. Hand text entry to MIDP's native TextField.
    void startEditing(int mode) {
        previousEmail = emailDraft;
        previousQuery = query;
        previousPasswordLength = passwordLength;
        editMode = mode;
        String label = mode == EDIT_EMAIL ? "Email" :
                mode == EDIT_PASSWORD ? "Password" : "Search";
        int max = mode == EDIT_SEARCH ? 36 : 64;
        int constraints = mode == EDIT_EMAIL ? TextField.EMAILADDR :
                mode == EDIT_PASSWORD ? TextField.ANY | TextField.PASSWORD : TextField.ANY;
        String current = mode == EDIT_EMAIL ? emailDraft :
                mode == EDIT_SEARCH ? query : "";
        try {
            Form form = new Form(mode == EDIT_SEARCH ? "Search" : "Add a Google account");
            TextField field = new TextField(label, current, max, constraints);
            form.append(field);
            form.addCommand(editDoneCommand);
            form.addCommand(editBackCommand);
            form.setCommandListener(this);
            editorField = field;
            editorForm = form;
            display.setCurrent(form);
        } catch (RuntimeException unsupported) {
            // Old LCDUI implementations may reject a constraint: keep the
            // original inline editor as a functional fallback.
            editorField = null;
            editorForm = null;
            canvas.repaint();
        }
    }

    private void finishNativeEditing(boolean accept) {
        int mode = editMode;
        TextField field = editorField;
        if (field == null) return;
        if (accept) {
            if (mode == EDIT_EMAIL) emailDraft = field.getString().trim();
            else if (mode == EDIT_PASSWORD) passwordLength = field.size();
            else if (mode == EDIT_SEARCH) query = field.getString();
        }
        // In particular, never read the password: keep only the masked count.
        field.setString("");
        editorField = null;
        editorForm = null;
        editMode = 0;
        display.setCurrent(canvas);
        if (accept && mode == EDIT_SEARCH) finishSearch();
        canvas.repaint();
    }

    void typeCharacter(char letter) {
        if (editMode == 0 || letter < 32 || letter > 126) return;
        if (editMode == EDIT_PASSWORD) {
            // Edit masked characters only: no password String is ever created.
            if (passwordLength < 64) ++passwordLength;
        } else if (editMode == EDIT_EMAIL) {
            if (letter != ' ' && emailDraft.length() < 64)
                emailDraft += Character.toLowerCase(letter);
        } else if (query.length() < 36) query += letter;
        canvas.repaint();
    }

    void deleteCharacter() {
        if (editMode == EDIT_EMAIL && emailDraft.length() > 0)
            emailDraft = emailDraft.substring(0, emailDraft.length() - 1);
        else if (editMode == EDIT_PASSWORD && passwordLength > 0) --passwordLength;
        else if (editMode == EDIT_SEARCH && query.length() > 0)
            query = query.substring(0, query.length() - 1);
        canvas.repaint();
    }

    void cancelEditing() {
        emailDraft = previousEmail;
        query = previousQuery;
        passwordLength = previousPasswordLength;
        editMode = 0;
        canvas.repaint();
    }

    void commitEditing() {
        int mode = editMode;
        editMode = 0;
        if (mode == EDIT_SEARCH) finishSearch();
        canvas.repaint();
    }

    private void finishSearch() {
        query = query.trim();
        String key = query.toLowerCase();
        oneResult = key.equals("file manager") || key.equals("file") || key.equals("file man");
        navigate(oneResult ? STORE : NO_RESULTS);
    }

    String clock() {
        Calendar c = Calendar.getInstance();
        int hour = c.get(Calendar.HOUR_OF_DAY);
        int minute = c.get(Calendar.MINUTE);
        return (hour < 10 ? "0" : "") + hour + ":" +
                (minute < 10 ? "0" : "") + minute;
    }

    void audioStatus(String text) {
        audioPlaying = text;
        if (canvas != null) canvas.repaint();
    }

    /** Nokia's optional property, if this firmware exposes it as 0..100. */
    static int parseBatteryLevel(String raw) {
        if (raw == null) return -1;
        raw = raw.trim();
        if (raw.endsWith("%")) raw = raw.substring(0, raw.length() - 1).trim();
        if (raw.length() == 0 || raw.length() > 3) return -1;
        int result = 0;
        for (int i = 0; i < raw.length(); ++i) {
            char ch = raw.charAt(i);
            if (ch < '0' || ch > '9') return -1;
            result = result * 10 + ch - '0';
        }
        return result <= 100 ? result : -1;
    }

    private void refreshBattery(boolean force) {
        long now = System.currentTimeMillis();
        if (!force && now - lastBatteryPoll < 15000L) return;
        lastBatteryPoll = now;
        int measured = -1;
        try {
            measured = parseBatteryLevel(System.getProperty("com.nokia.mid.batterylevel"));
        } catch (SecurityException unsupported) { }
        battery = measured;
        if (measured > 20) alertedLowBattery = false;
        if (measured >= 0 && measured <= 20 && !alertedLowBattery &&
                screen != BOOT && screen != POWER_OFF &&
                screen != BATTERY_ALERT && editorForm == null) {
            alertedLowBattery = true;
            alertReturnScreen = screen;
            navigate(BATTERY_ALERT);
            if (audio != null) audio.play("/lowbattery.wav", "");
        }
        if (canvas != null) canvas.repaint();
    }

    private void tickLoop(int generation) {
        while (running && generation == tickerGeneration) {
            long now = System.currentTimeMillis();
            if (screen == BOOT && now - bootStarted > 2000L) navigate(HOME);
            if (store.isInstalling()) {
                long delta = now - installStarted;
                int pct = (int) (delta * 100L / 3200L);
                if (pct > 100) pct = 100;
                installPercent = pct;
                if (delta >= 3900L) {
                    store.finishInstall();
                    saveSettings();
                }
            }
            // Never invent a battery percentage: only display a validated
            // reading provided by the E63, and show unknown otherwise.
            refreshBattery(false);
            if (screen == POWER_OFF && now - powerStarted > 7000L) {
                exit();
                return;
            }
            if (canvas != null) canvas.repaint();
            try { Thread.sleep(screen == BOOT || store.isInstalling() ? 80L : 700L); }
            catch (InterruptedException ignored) { }
        }
    }

    private void loadSettings() {
        RecordStore rs = null;
        try {
            rs = RecordStore.openRecordStore("J2ME_E63_demo", true);
            if (rs.getNumRecords() > 0) {
                byte[] data = rs.getRecord(1);
                savedInstalled = data.length > 0 && data[0] != 0;
                wifiOn = data.length > 1 && data[1] != 0;
                loggedIn = data.length > 2 && data[2] != 0;
                adjustClock = data.length > 3 && data[3] != 0;
            }
        } catch (Exception ignored) { }
        finally { if (rs != null) try { rs.closeRecordStore(); } catch (Exception ignored) { } }
    }

    private synchronized void saveSettings() {
        if (store == null) return;
        RecordStore rs = null;
        try {
            rs = RecordStore.openRecordStore("J2ME_E63_demo", true);
            byte[] data = {
                (byte) (store.isInstalled() ? 1 : 0),
                (byte) (wifiOn ? 1 : 0),
                (byte) (loggedIn ? 1 : 0),
                (byte) (adjustClock ? 1 : 0)
            };
            if (rs.getNumRecords() == 0) rs.addRecord(data, 0, data.length);
            else rs.setRecord(1, data, 0, data.length);
        } catch (Exception ignored) { }
        finally { if (rs != null) try { rs.closeRecordStore(); } catch (Exception ignored) { } }
    }
}
