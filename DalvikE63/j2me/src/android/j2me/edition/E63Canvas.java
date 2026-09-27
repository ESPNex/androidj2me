package android.j2me.edition;

import javax.microedition.lcdui.Canvas;
import javax.microedition.lcdui.Font;
import javax.microedition.lcdui.Graphics;
import javax.microedition.lcdui.Image;

/**
 * Guest-owned MIDP Canvas: original E63 app flows reflowed to 320x240 with
 * Jelly Bean 4.2/Holo-inspired chrome. No host-rendered app screens, AWT or
 * pretence that the MIDlet is Android's real framework or radio hardware.
 */
final class E63Canvas extends Canvas {
    private static final int BLACK = 0x000000;
    private static final int BG = 0x303030;
    private static final int DIALOG = 0x424242;
    private static final int LIGHT = 0xEEEEEE;
    private static final int MUTED = 0x999999;
    private static final int BLUE = 0x33B5E5;
    private static final int FILE_BLUE = 0x0099CC;
    private static final int GREEN = 0x80C342;
    private static final int RED = 0xFF4444;
    private static final int STATUS_H = 18;
    private static final int NAV_H = 32;
    private static final int QUICK_BG = 0x101010;
    private static final int FILE_HEADER_H = STATUS_H + 41;
    private static final int STORE_HEADER_H = STATUS_H + 40;
    private static final byte[][] TINY_DIGITS = {
        {7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}, {7, 1, 7, 4, 7},
        {7, 1, 7, 1, 7}, {5, 5, 7, 1, 1}, {7, 4, 7, 1, 7},
        {7, 4, 7, 5, 7}, {7, 1, 2, 2, 2}, {7, 5, 7, 5, 7},
        {7, 5, 7, 1, 7}, {5, 1, 2, 4, 5}, // percent sign
        {7, 1, 3, 0, 2} // unknown battery level
    };

    private final E63Midlet app;
    private final Font small;
    private final Font medium;
    private final Font large;
    private final Image wall;
    private final Image boot;
    private final Image storeIcon;
    private final Image drawerIcon;
    private final Image fileIcon;
    private final Image storeAppIcon;
    private final Image settingsIcon;
    private final Image settingsMini;
    private final Image folderIcon;
    private final Image audioIcon;
    private final Image wifiIcon;
    private final Image wifiStatus;
    private final Image warningIcon;
    private final Image accountIcon;
    private final Image logo;
    private final Image nextIcon;
    private final Image banner;
    private final Image shortBanner;
    private final Image narrowBanner;
    private final Image navBack;
    private final Image navHome;
    private final Image navRecent;
    private int w;
    private int h;

    E63Canvas(E63Midlet midlet) {
        app = midlet;
        small = Font.getFont(Font.FACE_SYSTEM, Font.STYLE_PLAIN, Font.SIZE_SMALL);
        medium = Font.getFont(Font.FACE_SYSTEM, Font.STYLE_PLAIN, Font.SIZE_MEDIUM);
        large = Font.getFont(Font.FACE_SYSTEM, Font.STYLE_PLAIN, Font.SIZE_LARGE);
        wall = image("/wall.png");
        boot = image("/boot.png");
        storeIcon = image("/store.png");
        drawerIcon = image("/drawer.png");
        fileIcon = image("/files.png");
        storeAppIcon = image("/store_app.png");
        settingsIcon = image("/settings.png");
        settingsMini = image("/settings_mini.png");
        folderIcon = image("/folder.png");
        audioIcon = image("/music.png");
        wifiIcon = image("/wifi.png");
        wifiStatus = image("/wifi_status.png");
        warningIcon = image("/warning.png");
        accountIcon = image("/account.png");
        logo = image("/logo.png");
        nextIcon = image("/next.png");
        banner = image("/banner.png");
        shortBanner = image("/banner_short.png");
        narrowBanner = image("/banner_narrow.png");
        navBack = image("/nav_back.png");
        navHome = image("/nav_home.png");
        navRecent = image("/nav_recent.png");
    }

    private Image image(String name) {
        try { return Image.createImage(name); }
        catch (Exception unavailable) { return null; }
    }

    protected void paint(Graphics g) {
        w = getWidth();
        h = getHeight();
        if (w < 90 || h < 115) return;
        g.setClip(0, 0, w, h);
        g.setColor(BG);
        g.fillRect(0, 0, w, h);
        switch (app.screen) {
            case E63Midlet.BOOT: paintBoot(g); break;
            case E63Midlet.HOME: paintHome(g); break;
            case E63Midlet.SETTINGS: paintSettings(g); break;
            case E63Midlet.NO_INTERNET: paintNoInternet(g); break;
            case E63Midlet.LOGIN: paintLogin(g); break;
            case E63Midlet.STORE: paintStore(g); break;
            case E63Midlet.APP: paintApp(g); break;
            case E63Midlet.NO_RESULTS: paintNoResults(g); break;
            case E63Midlet.FILES: paintFiles(g); break;
            case E63Midlet.ANDROID_FOLDER: paintAndroidFolder(g); break;
            case E63Midlet.EMPTY_FOLDER: paintEmpty(g); break;
            case E63Midlet.SYSTEM_ERROR: paintSystemError(g); break;
            case E63Midlet.BATTERY_ALERT:
                paintHome(g);
                paintBatteryDialog(g);
                break;
            case E63Midlet.POWER_OFF:
                paintHome(g);
                paintShutdownDialog(g);
                break;
            case E63Midlet.APP_DRAWER: paintAppDrawer(g); break;
            case E63Midlet.NOTIFICATIONS: paintNotifications(g); break;
            case E63Midlet.QUICK_SETTINGS: paintQuickSettings(g); break;
            case E63Midlet.RECENTS: paintRecents(g); break;
            default: break;
        }
        if (app.screen != E63Midlet.BOOT) {
            // In 4.2 both bars frame the app, including Store, Files and Login.
            // These pixels are painted by this guest DEX, not by the host.
            paintStatus(g);
            paintNav(g);
        }
    }

    private void paintBoot(Graphics g) {
        g.setColor(BLACK);
        g.fillRect(0, 0, w, h);
        if (boot != null)
            g.drawImage(boot, (w - boot.getWidth()) / 2,
                    (h - boot.getHeight()) / 2, Graphics.TOP | Graphics.LEFT);
        long elapsed = System.currentTimeMillis() - app.bootStarted;
        int percent = (int) (elapsed * 100L / 2000L);
        if (percent > 100) percent = 100;
        if (percent < 0) percent = 0;
        g.setColor(BLACK);
        g.fillRect(0, h - 9, w, 9);
        g.setColor(FILE_BLUE);
        g.fillRect(0, h - 9, w * percent / 100, 9);
    }

    private void paintStatus(Graphics g) {
        g.setColor(BLACK);
        g.fillRect(0, 0, w, STATUS_H);
        // Align both labels with the battery outline, not its top edge.
        // MIDP Font heights vary between the PC shim and S60; keep text inside
        // the 18px bar even when the device reports a taller small font.
        int labelY = (STATUS_H - small.getHeight()) / 2 + 2;
        if (labelY + small.getHeight() > STATUS_H)
            labelY = STATUS_H - small.getHeight();
        if (labelY < 0) labelY = 0;
        text(g, "No service", 6, labelY, small, LIGHT);
        String clock = app.clock();
        String percent = app.battery >= 0 ? app.battery + "%" : "?";
        int clockX = w - small.stringWidth(clock) - 6;
        int digitWidth = percent.length() * 7 - 1;
        int barW = digitWidth + 8;
        int barX = clockX - barW - 7;
        if (barX <= small.stringWidth("No service") + 12) {
            text(g, clock, clockX, labelY, small, BLUE);
            return;
        }
        if (app.wifiOn && wifiStatus != null) {
            int wifiX = barX - wifiStatus.getWidth() - 8;
            if (wifiX > small.stringWidth("No service") + 10)
                g.drawImage(wifiStatus, wifiX, 3, Graphics.TOP | Graphics.LEFT);
        }
        g.setColor(0x292929);
        g.fillRect(barX, 4, barW, 11);
        if (app.battery >= 0) {
            g.setColor(app.battery <= 20 ? RED : BLUE);
            g.fillRect(barX + 1, 5, (barW - 2) * app.battery / 100, 9);
        }
        // Unknown means '?' in the outline: never fabricate a battery reading.
        g.setColor(MUTED);
        g.drawRect(barX, 4, barW - 1, 10);
        g.fillRect(barX + barW, 7, 2, 5);
        batteryPercent(g, percent, barX + (barW - digitWidth) / 2, 4);
        text(g, clock, clockX, labelY, small, BLUE);
    }

    private void batteryPercent(Graphics g, String content, int x, int y) {
        g.setColor(0xFFFFFF);
        for (int i = 0; i < content.length(); ++i) {
            char c = content.charAt(i);
            int glyph = c == '%' ? 10 : c == '?' ? 11 : c - '0';
            if (glyph < 0 || glyph >= TINY_DIGITS.length) continue;
            for (int row = 0; row < 5; ++row) {
                int dots = TINY_DIGITS[glyph][row];
                for (int col = 0; col < 3; ++col)
                    if ((dots & (4 >> col)) != 0)
                        g.fillRect(x + i * 7 + col * 2, y + row * 2, 2, 2);
            }
        }
    }

    private void paintHome(Graphics g) {
        if (wall != null)
            g.drawImage(wall, (w - wall.getWidth()) / 2,
                    (h - wall.getHeight()) / 2, Graphics.TOP | Graphics.LEFT);
        int searchY = STATUS_H + 8;
        g.setColor(0xD9DDE0);
        g.fillRect(12, searchY, w - 24, 25);
        g.setColor(0x555E63);
        // A real round magnifying lens, not the previous square outline.
        g.drawArc(22, searchY + 5, 11, 11, 0, 360);
        g.drawLine(30, searchY + 14, 35, searchY + 19);
        text(g, "Search apps", 44, searchY + 5, small, 0x43474A);
        int dockY = h - NAV_H - 55;
        int labelY = dockY + 37;
        g.setColor(0xA4A9AC);
        g.drawLine(12, dockY - 9, w - 13, dockY - 9);
        for (int i = -1; i <= 1; ++i) {
            g.setColor(i == 0 ? BLUE : 0xD0D0D0);
            g.fillRect(w / 2 + i * 11 - 1, dockY - 15, 3, 3);
        }
        if (app.store.isInstalled()) {
            homeIcon(g, fileIcon, "File Manager", w / 4,
                    dockY - 70, dockY - 32,
                    app.selected[E63Midlet.HOME] == 0 && app.screen == E63Midlet.HOME);
        }
        homeIcon(g, storeIcon, "Play Store", w / 4,
                dockY, labelY,
                app.selected[E63Midlet.HOME] == (app.store.isInstalled() ? 1 : 0) &&
                app.screen == E63Midlet.HOME);
        homeIcon(g, settingsIcon, "Settings", w * 3 / 4,
                dockY, labelY,
                app.selected[E63Midlet.HOME] == (app.store.isInstalled() ? 2 : 1) &&
                app.screen == E63Midlet.HOME);
        if (drawerIcon != null)
            g.drawImage(drawerIcon, (w - drawerIcon.getWidth()) / 2,
                    dockY, Graphics.TOP | Graphics.LEFT);
        else {
            // Still accessible with key 1 if an optional icon is unavailable.
            g.setColor(LIGHT);
            for (int row = 0; row < 3; ++row)
                for (int col = 0; col < 3; ++col)
                    g.fillRect(w / 2 - 8 + col * 6, dockY + 9 + row * 6, 3, 3);
        }
        center(g, "Apps", w / 2, labelY, small, LIGHT);
    }

    private void homeIcon(Graphics g, Image icon, String caption,
                          int centerX, int iconY, int labelY, boolean selected) {
        if (icon != null) {
            int x = centerX - icon.getWidth() / 2;
            g.drawImage(icon, x, iconY, Graphics.TOP | Graphics.LEFT);
            if (selected) {
                g.setColor(BLUE);
                g.drawRect(x - 3, iconY - 3, icon.getWidth() + 5,
                        icon.getHeight() + 5);
            }
        }
        if (w < 230) {
            if (caption.equals("File Manager")) {
                center(g, "File", centerX, labelY - 3, small, LIGHT);
                center(g, "Manager", centerX, labelY + small.getHeight() - 3, small, LIGHT);
            } else if (caption.equals("Play Store")) {
                center(g, "Play", centerX, labelY - 3, small, LIGHT);
                center(g, "Store", centerX, labelY + small.getHeight() - 3, small, LIGHT);
            } else center(g, caption, centerX, labelY + small.getHeight() - 3, small, LIGHT);
        } else center(g, caption, centerX, labelY, small, LIGHT);
        if (selected) {
            int underlineW = small.stringWidth(caption);
            if (underlineW > w / 3 - 4) underlineW = w / 3 - 4;
            g.setColor(BLUE);
            int underlineY = labelY + small.getHeight() + (w < 230 ? small.getHeight() + 1 : 0);
            if (underlineY < h)
                g.drawLine(centerX - underlineW / 2, underlineY,
                        centerX + underlineW / 2, underlineY);
        }
    }

    private void paintAppDrawer(Graphics g) {
        g.setColor(0x202020);
        g.fillRect(0, STATUS_H, w, h - STATUS_H - NAV_H);
        text(g, "APPS", 16, STATUS_H + 10, medium,
                app.widgetsTab ? MUTED : LIGHT);
        text(g, "WIDGETS", w / 2 + 16, STATUS_H + 10, medium,
                app.widgetsTab ? LIGHT : MUTED);
        g.setColor(BLUE);
        g.fillRect(app.widgetsTab ? w / 2 : 0, STATUS_H + 37, w / 2, 2);
        if (app.widgetsTab) {
            center(g, "No widgets installed", w / 2,
                    (STATUS_H + h - NAV_H - small.getHeight()) / 2, small, LIGHT);
            return;
        }
        int iconY = STATUS_H + 76;
        int labelY = iconY + 39;
        int count = app.store.isInstalled() ? 3 : 2;
        for (int i = 0; i < count; ++i) {
            Image icon = app.store.isInstalled() && i == 0 ? fileIcon :
                    i == count - 1 ? settingsIcon : storeIcon;
            String name = app.store.isInstalled() && i == 0 ? "File Manager" :
                    i == count - 1 ? "Settings" : "Play Store";
            homeIcon(g, icon, name, w * (i * 2 + 1) / (count * 2),
                    iconY, labelY, app.selected[E63Midlet.APP_DRAWER] == i);
        }
    }

    private void paintNotifications(Graphics g) {
        g.setColor(0x151515);
        g.fillRect(0, STATUS_H, w, h - STATUS_H - NAV_H);
        text(g, app.clock(), 12, STATUS_H + 6, large, BLUE);
        text(g, "NOTIFICATIONS", 12, STATUS_H + 36, small, LIGHT);
        g.setColor(0x484848);
        g.drawLine(0, STATUS_H + 57, w - 1, STATUS_H + 57);
        center(g, "No notifications", w / 2, STATUS_H + 84, small, LIGHT);
        g.setColor(0x292929);
        g.fillRect(18, h - NAV_H - 39, w - 36, 29);
        g.setColor(BLUE);
        g.drawRect(18, h - NAV_H - 39, w - 37, 28);
        center(g, "QUICK SETTINGS", w / 2,
                h - NAV_H - 32, small, LIGHT);
    }

    private void paintQuickSettings(Graphics g) {
        g.setColor(QUICK_BG);
        g.fillRect(0, STATUS_H, w, h - STATUS_H - NAV_H);
        text(g, "QUICK SETTINGS", 11, STATUS_H + 11, small, LIGHT);
        String time = app.clock();
        text(g, time, w - medium.stringWidth(time) - 13,
                STATUS_H + 7, medium, BLUE);
        g.setColor(0x555555);
        g.drawLine(0, STATUS_H + 41, w - 1, STATUS_H + 41);
        int tileW = (w - 28) / 2;
        int tileY = STATUS_H + 44;
        quickTile(g, 10, tileY, tileW, "Wi-Fi",
                app.wifiOn ? "demo ON" : "demo OFF", wifiIcon,
                app.selected[E63Midlet.QUICK_SETTINGS] == 0);
        quickTile(g, w - tileW - 10, tileY, tileW, "Settings",
                "Open", settingsMini,
                app.selected[E63Midlet.QUICK_SETTINGS] == 1);
        quickTile(g, 10, tileY + 70, tileW, "Battery",
                app.battery < 0 ? "Unknown" : app.battery + "%", null, false);
        quickTile(g, w - tileW - 10, tileY + 70, tileW, "Clock",
                app.adjustClock ? "+1h display" : "Local", null, false);
    }

    private void quickTile(Graphics g, int x, int y, int width,
                           String name, String info, Image icon, boolean chosen) {
        // All four tiles share the actual panel backdrop; selection is a
        // border/accent only, never a different surface tint.
        g.setColor(QUICK_BG);
        g.fillRect(x, y, width, 68);
        g.setColor(chosen ? BLUE : 0x414141);
        g.drawRect(x, y, width - 1, 67);
        if (icon != null) {
            g.drawImage(icon, x + (width - icon.getWidth()) / 2,
                    y + 4, Graphics.TOP | Graphics.LEFT);
        } else {
            center(g, name.equals("Battery") ?
                    (app.battery < 0 ? "?" : app.battery + "%") : app.clock(),
                    x + width / 2, y + 6, medium, BLUE);
        }
        center(g, name, x + width / 2, y + 36, small, LIGHT);
        center(g, info, x + width / 2, y + 51, small,
                chosen ? BLUE : MUTED);
    }

    private void paintRecents(Graphics g) {
        g.setColor(0x151515);
        g.fillRect(0, STATUS_H, w, h - STATUS_H - NAV_H);
        text(g, "Recent screens", 12, STATUS_H + 8, medium, LIGHT);
        text(g, "Local guest history", 12, STATUS_H + 30, small, MUTED);
        recentCard(g, STATUS_H + 54, app.recentsOrigin, "Current",
                app.selected[E63Midlet.RECENTS] == 0);
        if (app.recentScreen != app.recentsOrigin)
            recentCard(g, STATUS_H + 117, app.recentScreen, "Previous",
                    app.selected[E63Midlet.RECENTS] == 1);
    }

    private void recentCard(Graphics g, int y, int page,
                            String heading, boolean chosen) {
        g.setColor(0x303030);
        g.fillRect(12, y, w - 24, 55);
        g.setColor(chosen ? BLUE : 0x545454);
        g.drawRect(12, y, w - 25, 54);
        Image icon = page == E63Midlet.SETTINGS ? settingsIcon :
                page == E63Midlet.FILES || page == E63Midlet.ANDROID_FOLDER ||
                page == E63Midlet.EMPTY_FOLDER ? fileIcon :
                page == E63Midlet.LOGIN || page == E63Midlet.STORE ||
                page == E63Midlet.APP ? storeIcon : drawerIcon;
        if (icon != null)
            g.drawImage(icon, 21, y + 11, Graphics.TOP | Graphics.LEFT);
        text(g, heading, 66, y + 5, small, MUTED);
        fit(g, app.screenTitle(page), 66, y + 25,
                w - 83, small, LIGHT);
    }

    private void paintSettings(Graphics g) {
        int headerBottom = STATUS_H + 35;
        if (settingsMini != null)
            g.drawImage(settingsMini, 5, STATUS_H + 3, Graphics.TOP | Graphics.LEFT);
        text(g, "Settings", 45, STATUS_H + 11, medium, LIGHT);
        g.setColor(BLUE);
        g.fillRect(0, headerBottom - 1, w, 1);
        int navY = h - NAV_H;
        int wifiY = headerBottom;
        int wifiH = navY - headerBottom >= 132 ? 52 : 43;
        if (wifiH > navY - wifiY - 43) wifiH = navY - wifiY - 43;
        int clockY = wifiY + wifiH;
        if (wifiIcon != null)
            g.drawImage(wifiIcon, 8, wifiY + (wifiH - wifiIcon.getHeight()) / 2,
                    Graphics.TOP | Graphics.LEFT);
        text(g, "Wi-Fi", 56, wifiY + 7, medium, LIGHT);
        fit(g, app.wifiOn ? "Store switch ON (demo)" : "Store switch OFF (demo)",
                56, wifiY + wifiH - small.getHeight() - 5,
                w - 112, small, BLUE);
        int toggleW = 38, toggleH = 17, toggleX = w - toggleW - 12;
        int toggleY = wifiY + (wifiH - toggleH) / 2;
        g.setColor(app.wifiOn ? BLUE : 0xDDDDDD);
        g.fillRect(toggleX, toggleY, toggleW, toggleH);
        center(g, app.wifiOn ? "ON" : "OFF", toggleX + toggleW / 2,
                toggleY + (toggleH - small.getHeight()) / 2,
                small, app.wifiOn ? 0xFFFFFF : 0xAAAAAA);
        g.setColor(0x7D8790);
        g.fillRect(0, clockY - 1, w, 1);
        int clockH = navY - clockY >= 85 ? 43 : 39;
        Font clockFont = w < 230 ? small : medium;
        int clockTextY = w < 230 ? clockY + 3 :
                clockY + (clockH - clockFont.getHeight()) / 2;
        wrapped(g, "Display clock +1 hour", 13, clockTextY,
                w - 60, clockFont, LIGHT, clockY + clockH - 2);
        int checkX = w - 31, checkY = clockY + (clockH - 14) / 2;
        g.setColor(0xE5E5E5);
        g.fillRect(checkX, checkY, 13, 13);
        if (app.adjustClock) {
            g.setColor(GREEN);
            g.drawLine(checkX + 2, checkY + 6, checkX + 5, checkY + 9);
            g.drawLine(checkX + 5, checkY + 9, checkX + 11, checkY + 2);
        }
        g.setColor(0x7D8790);
        g.fillRect(0, clockY + clockH - 1, w, 1);
        int bridgeY = clockY + clockH;
        int bridgeH = navY - bridgeY;
        if (bridgeH > 16) {
            text(g, "SIS Bridge (loopback)", 13, bridgeY + 5, small, LIGHT);
            text(g, "Pairing / PING only", 13,
                    bridgeY + 5 + small.getHeight(), small, BLUE);
        }
        int focus = app.selected[E63Midlet.SETTINGS];
        int focusY = focus == 0 ? wifiY : focus == 1 ? clockY : bridgeY;
        int focusH = focus == 0 ? wifiH : focus == 1 ? clockH : bridgeH;
        g.setColor(BLUE);
        if (focusH > 5) g.drawRect(1, focusY + 1, w - 3, focusH - 3);
    }

    private void paintNoInternet(Graphics g) {
        int navY = h - NAV_H;
        int y = navY / 2 - 24;
        if (y < 25) y = 25;
        y = wrapped(g, "No internet connection. Please enable Wi-Fi or mobile data and retry.",
                12, y, w - 24, small, LIGHT, navY - 39);
        int buttonY = y + 9;
        if (buttonY + 23 > navY - 5) buttonY = navY - 28;
        button(g, "OK", (w - 60) / 2, buttonY, 60, 23, true);
    }

    private void paintLogin(Graphics g) {
        // Keep the original fields visible on this Canvas. Selection opens
        // a native MIDP TextField so QWERTY typing works on the real E63.
        // This is a local offline demo: nothing is sent or saved as a login.
        int titleY = h >= 220 ? 26 : 15;
        text(g, "Add a Google account", 9, titleY, large, BLUE);
        int lineY = titleY + large.getHeight() + 11;
        g.setColor(LIGHT);
        g.fillRect(0, lineY, w, 1);
        int field1Y = lineY + 22;
        int field2Y = field1Y + 36;
        int left = 18, right = w - 19;
        String email = app.emailDraft.length() == 0 && app.editMode != E63Midlet.EDIT_EMAIL ?
                "Email" : app.emailDraft;
        if (app.editMode == E63Midlet.EDIT_EMAIL) email += "|";
        tailFit(g, email, left + 5, field1Y, right - left - 12,
                small, app.emailDraft.length() == 0 && app.editMode != E63Midlet.EDIT_EMAIL ? MUTED : LIGHT);
        String password = "Password";
        if (app.passwordLength > 0 || app.editMode == E63Midlet.EDIT_PASSWORD) {
            StringBuffer stars = new StringBuffer();
            for (int i = 0; i < app.passwordLength; ++i) stars.append('*');
            if (app.editMode == E63Midlet.EDIT_PASSWORD) stars.append('|');
            password = stars.toString();
        }
        tailFit(g, password, left + 5, field2Y, right - left - 12,
                small, app.passwordLength == 0 && app.editMode != E63Midlet.EDIT_PASSWORD ? MUTED : LIGHT);
        g.setColor(app.selected[E63Midlet.LOGIN] == 0 ? BLUE : LIGHT);
        g.fillRect(left, field1Y + small.getHeight() + 4, right - left, 1);
        g.setColor(app.selected[E63Midlet.LOGIN] == 1 ? BLUE : LIGHT);
        g.fillRect(left, field2Y + small.getHeight() + 4, right - left, 1);
        if (app.selected[E63Midlet.LOGIN] == 0 || app.selected[E63Midlet.LOGIN] == 1) {
            int focusY = app.selected[E63Midlet.LOGIN] == 0 ? field1Y : field2Y;
            g.setColor(BLUE);
            g.drawRect(left - 2, focusY - 3, right - left + 4, small.getHeight() + 8);
        }
        int arrowX = w - 57;
        int arrowY = h - 67;
        if (nextIcon != null)
            g.drawImage(nextIcon, arrowX, arrowY, Graphics.TOP | Graphics.LEFT);
        if (app.selected[E63Midlet.LOGIN] == 2) {
            g.setColor(BLUE);
            g.drawRect(arrowX - 5, arrowY - 5, 39, 42);
        }
    }

    private void storeHeader(Graphics g) {
        g.setColor(BG);
        g.fillRect(0, STATUS_H, w, STORE_HEADER_H - STATUS_H);
        if (w < 230) {
            if (logo != null)
                g.drawImage(logo, 5, STATUS_H + 1, Graphics.TOP | Graphics.LEFT);
            int fieldW = w - 69;
            g.setColor(0xFFFFFF);
            g.fillRect(5, STATUS_H + 23, fieldW, 15);
            tailFit(g, app.query + (app.editMode == E63Midlet.EDIT_SEARCH ? "|" : ""),
                    8, STATUS_H + 24, fieldW - 6, small, BG);
            g.setColor(0xDEE5EB);
            g.fillRect(w - 60, STATUS_H + 23, 55, 15);
            center(g, "Search", w - 33, STATUS_H + 24, small, BG);
            if (app.screen == E63Midlet.STORE && app.selected[E63Midlet.STORE] == 0) {
                g.setColor(BLUE);
                g.drawRect(4, STATUS_H + 22, w - 9, 17);
            }
            return;
        }
        if (logo != null)
            g.drawImage(logo, 5, STATUS_H + 7, Graphics.TOP | Graphics.LEFT);
        int accountX = w - 26;
        int buttonW = 48;
        int buttonX = accountX - buttonW - 5;
        int fieldX = 114;
        int fieldW = buttonX - fieldX - 4;
        if (fieldW < 18) fieldW = 18;
        g.setColor(0xFFFFFF);
        g.fillRect(fieldX, STATUS_H + 7, fieldW, 19);
        tailFit(g, app.query + (app.editMode == E63Midlet.EDIT_SEARCH ? "|" : ""),
                fieldX + 3, STATUS_H + 9, fieldW - 6, small, BG);
        g.setColor(0xDEE5EB);
        g.fillRect(buttonX, STATUS_H + 7, buttonW, 19);
        center(g, "Search", buttonX + buttonW / 2, STATUS_H + 9, small, BG);
        if (accountIcon != null)
            g.drawImage(accountIcon, accountX, STATUS_H + 7,
                    Graphics.TOP | Graphics.LEFT);
        center(g, "a", accountX + 11, STATUS_H + 8, small, 0xFFFFFF);
        if (app.screen == E63Midlet.STORE && app.selected[E63Midlet.STORE] == 0) {
            g.setColor(BLUE);
            g.drawRect(fieldX - 1, STATUS_H + 6, fieldW + buttonW + 5, 21);
        }
    }

    private void paintStore(Graphics g) {
        storeHeader(g);
        int bodyHeight = h - NAV_H - STORE_HEADER_H;
        boolean compact = bodyHeight < 150;
        int appY = STORE_HEADER_H + (compact ? 33 : 51);
        int nameY = appY + (storeAppIcon == null ? 51 : storeAppIcon.getHeight()) + 2;
        int developerY = nameY + small.getHeight() + 3;
        text(g, app.oneResult ? "1 result found." : "Apps", 9,
                STORE_HEADER_H + (compact ? 8 : 17), medium, LIGHT);
        if (storeAppIcon != null)
            g.drawImage(storeAppIcon, 20, appY, Graphics.TOP | Graphics.LEFT);
        text(g, "File Manager", 20, nameY, small, LIGHT);
        text(g, "LardeXWare", 20, developerY, small, GREEN);
        if (app.selected[E63Midlet.STORE] == 1) {
            g.setColor(BLUE);
            int focusBottom = developerY + small.getHeight() + 3;
            if (focusBottom > h - NAV_H - 2) focusBottom = h - NAV_H - 2;
            g.drawRect(16, appY - 3, 83, focusBottom - appY + 3);
        }
    }

    private void paintApp(Graphics g) {
        storeHeader(g);
        int bodyHeight = h - NAV_H - STORE_HEADER_H;
        Image image = w < 230 ? narrowBanner :
                bodyHeight < 145 ? shortBanner : banner;
        int imageH = image == null ? 0 : image.getHeight();
        if (image != null)
            g.drawImage(image, (w - image.getWidth()) / 2,
                    STORE_HEADER_H, Graphics.TOP | Graphics.LEFT);
        int nameY = STORE_HEADER_H + imageH + 7;
        text(g, "File Manager", 20, nameY, medium, LIGHT);
        int developerY = nameY + medium.getHeight() + 2;
        text(g, "LardeXWare", 20, developerY, small, GREEN);
        int buttonY = h - NAV_H - 29;
        if (!app.store.isInstalling()) {
            storeButton(g, app.store.isInstalled() ? "OPEN" : "INSTALL",
                    20, buttonY);
        } else {
            g.setColor(0x666666);
            g.fillRect(20, buttonY + 3, w - 56, 4);
            g.setColor(GREEN);
            g.fillRect(20, buttonY + 3, (w - 56) * app.installPercent / 100, 4);
            if (app.installPercent < 100) {
                text(g, "Downloading...", 20, buttonY + 10, small, LIGHT);
                text(g, app.installPercent + "%", w - 42, buttonY + 10, small, LIGHT);
            } else text(g, "Installing...", 20, buttonY + 10, small, LIGHT);
        }
    }

    private void paintNoResults(Graphics g) {
        storeHeader(g);
        int bodyCenter = (STORE_HEADER_H + h - NAV_H) / 2;
        center(g, "No results found.", w / 2,
                bodyCenter - small.getHeight() / 2, small, LIGHT);
    }

    private void fileHeader(Graphics g) {
        g.setColor(FILE_BLUE);
        g.fillRect(0, STATUS_H, w, FILE_HEADER_H - STATUS_H);
        if (fileIcon != null)
            g.drawImage(fileIcon, 5, STATUS_H +
                    (FILE_HEADER_H - STATUS_H - fileIcon.getHeight()) / 2,
                    Graphics.TOP | Graphics.LEFT);
        text(g, "File Manager", 46, STATUS_H +
                (FILE_HEADER_H - STATUS_H - small.getHeight()) / 2,
                small, LIGHT);
    }

    private void paintFiles(Graphics g) {
        fileHeader(g);
        int bodyTop = FILE_HEADER_H;
        int navY = h - NAV_H;
        if (w < 240) {
            String[] names = {"Android", "DCIM", "Download", "Ringtones",
                    "lowbattery.wav", "Disfigure - Blank (NCS Release).wav"};
            int rowH = 34;
            int visible = (navY - bodyTop - 5) / rowH;
            if (visible < 1) visible = 1;
            int first = app.selected[E63Midlet.FILES] - visible + 1;
            if (first < 0) first = 0;
            if (first > names.length - visible) first = names.length - visible;
            if (first < 0) first = 0;
            for (int i = first; i < names.length && i < first + visible; ++i) {
                int rowY = bodyTop + 4 + (i - first) * rowH;
                if (rowY + rowH > navY) break;
                Image icon = i < 4 ? folderIcon : audioIcon;
                if (icon != null)
                    g.drawImage(icon, 6, rowY + (rowH - icon.getHeight()) / 2,
                            Graphics.TOP | Graphics.LEFT);
                fit(g, names[i], 46, rowY + (rowH - small.getHeight()) / 2,
                        w - 54, small, LIGHT);
                if (i == app.selected[E63Midlet.FILES]) focus(g, 2, rowY, w - 4, rowH - 1);
            }
            scrollbar(g, bodyTop + 3, navY - bodyTop - 6, 6,
                    visible, first);
            return;
        }
        int leftW = w * 54 / 100;
        int rightX = leftW + 5;
        int rightW = w - rightX - 4;
        String[] folders = {"Android", "DCIM", "Download", "Ringtones"};
        int rowH = (navY - bodyTop - 10) / 4;
        if (rowH > 39) rowH = 39;
        if (rowH < 27) rowH = 27;
        for (int i = 0; i < folders.length; ++i) {
            int y = bodyTop + 5 + i * rowH;
            if (y + rowH > navY) break;
            if (folderIcon != null)
                g.drawImage(folderIcon, 6, y + (rowH - folderIcon.getHeight()) / 2,
                        Graphics.TOP | Graphics.LEFT);
            fit(g, folders[i], 40, y + (rowH - small.getHeight()) / 2,
                    leftW - 44, small, LIGHT);
            if (app.selected[E63Midlet.FILES] == i) focus(g, 2, y, leftW - 5, rowH - 1);
        }
        int firstAudioY = bodyTop + 8;
        int secondAudioY = bodyTop + (navY - bodyTop >= 150 ? 75 : 59);
        audioItem(g, rightX, firstAudioY, rightW, "lowbattery.wav",
                "located in /system/media/ui",
                app.selected[E63Midlet.FILES] == 4, secondAudioY - 4);
        audioItem(g, rightX, secondAudioY, rightW, "Disfigure - Blank",
                "(NCS Release).wav",
                app.selected[E63Midlet.FILES] == 5, navY - 25);
        if (app.audioPlaying.length() > 0) {
            int statusY = navY - 29;
            wrapped(g, app.audioPlaying, rightX + 2, statusY,
                    rightW - 5, small, 0xFFFFFF, navY - 2);
        }
    }

    private void audioItem(Graphics g, int x, int y, int width,
                           String name, String detail,
                           boolean selected, int bottom) {
        if (audioIcon != null)
            g.drawImage(audioIcon, x, y + 2, Graphics.TOP | Graphics.LEFT);
        int textX = x + (audioIcon == null ? 4 : audioIcon.getWidth() + 3);
        int maxWidth = width - (textX - x);
        int nextY = wrapped(g, name, textX, y + 3, maxWidth,
                small, LIGHT, bottom);
        wrapped(g, detail, textX, nextY, maxWidth, small,
                name.equals("lowbattery.wav") ? MUTED : LIGHT, bottom);
        if (selected) {
            int boxH = bottom - y + 2;
            if (boxH > 58) boxH = 58;
            focus(g, x - 3, y, width + 2, boxH);
        }
    }

    private void paintAndroidFolder(Graphics g) {
        fileHeader(g);
        int navY = h - NAV_H;
        int rowH = (navY - FILE_HEADER_H - 8) / 3;
        if (rowH > 42) rowH = 42;
        if (rowH < 29) rowH = 29;
        String[] names = {"..", "data", "obb"};
        for (int i = 0; i < names.length; ++i) {
            int y = FILE_HEADER_H + 5 + i * rowH;
            if (y + rowH > navY) break;
            if (folderIcon != null)
                g.drawImage(folderIcon, 7, y + (rowH - folderIcon.getHeight()) / 2,
                        Graphics.TOP | Graphics.LEFT);
            text(g, names[i], 40, y + (rowH - small.getHeight()) / 2,
                    small, LIGHT);
            if (app.selected[E63Midlet.ANDROID_FOLDER] == i)
                focus(g, 2, y, w - 4, rowH - 1);
        }
    }

    private void paintEmpty(Graphics g) {
        fileHeader(g);
        int navY = h - NAV_H;
        center(g, "This folder is empty.", w / 2,
                (FILE_HEADER_H + navY - small.getHeight()) / 2,
                small, LIGHT);
    }

    private void paintSystemError(Graphics g) {
        g.setColor(BLACK);
        g.fillRect(0, 0, w, h);
        int navY = h - NAV_H;
        int dialogW = w - 18;
        int dialogH = navY >= 180 ? 109 : 103;
        int x = (w - dialogW) / 2;
        int y = (navY - dialogH) / 2;
        g.setColor(DIALOG);
        g.fillRect(x, y, dialogW, dialogH);
        g.setColor(BLUE);
        g.fillRect(x, y + 17, dialogW, 2);
        int lineY = y + 24;
        lineY = wrapped(g, "Unfortunately, the process com.android.systemui",
                x + 9, lineY, dialogW - 18, small, LIGHT, y + dialogH - 42);
        text(g, "has stopped.", x + 9, lineY + 2, small, LIGHT);
        button(g, "OK", x, y + dialogH - 24, dialogW, 23, true);
    }

    private void paintBatteryDialog(Graphics g) {
        int boxW = w - 22, boxH = 82, x = (w - boxW) / 2;
        int y = (h - boxH) / 2 - 8;
        g.setColor(DIALOG);
        g.fillRect(x, y, boxW, boxH);
        g.setColor(BLUE);
        g.fillRect(x, y + 13, boxW, 2);
        int iconRoom = warningIcon == null ? 0 : warningIcon.getWidth() + 7;
        wrapped(g, "Low battery. " + app.battery + "% remaining.", x + 8, y + 25,
                boxW - 16 - iconRoom, small, LIGHT, y + boxH - 25);
        if (warningIcon != null)
            g.drawImage(warningIcon, x + boxW - warningIcon.getWidth() - 5,
                    y + 19, Graphics.TOP | Graphics.LEFT);
        button(g, "OK", x, y + boxH - 24, boxW, 23, true);
    }

    private void paintShutdownDialog(Graphics g) {
        int boxW = w - 44, boxH = 52;
        int x = (w - boxW) / 2, y = (h - boxH) / 2 - 8;
        g.setColor(DIALOG);
        g.fillRect(x, y, boxW, boxH);
        g.setColor(BLUE);
        g.fillRect(x, y + 17, boxW, 2);
        text(g, "Shutting down...", x + 9, y + 25, medium, LIGHT);
    }

    private void paintNav(Graphics g) {
        int top = h - NAV_H;
        g.setColor(BLACK);
        g.fillRect(0, top, w, NAV_H);
        if (navBack != null)
            g.drawImage(navBack, w * 21 / 100 - navBack.getWidth() / 2,
                    top + (NAV_H - navBack.getHeight()) / 2,
                    Graphics.TOP | Graphics.LEFT);
        if (navHome != null)
            g.drawImage(navHome, w * 49 / 100 - navHome.getWidth() / 2,
                    top + (NAV_H - navHome.getHeight()) / 2,
                    Graphics.TOP | Graphics.LEFT);
        if (navRecent != null)
            g.drawImage(navRecent, w * 77 / 100 - navRecent.getWidth() / 2,
                    top + (NAV_H - navRecent.getHeight()) / 2,
                    Graphics.TOP | Graphics.LEFT);
    }

    private void focus(Graphics g, int x, int y, int width, int height) {
        if (x < 0 || y < 0 || width < 4 || height < 4 ||
                x + width > w || y + height > h) return;
        g.setColor(BLUE);
        g.drawRect(x, y, width - 1, height - 1);
    }

    private void button(Graphics g, String label, int x, int y,
                        int width, int height, boolean selected) {
        if (y < 0 || y + height > h || width < 1) return;
        g.setColor(DIALOG);
        g.fillRect(x, y, width, height);
        g.setColor(selected ? BLUE : 0x68727A);
        g.drawRect(x, y, width - 1, height - 1);
        center(g, label, x + width / 2,
                y + (height - small.getHeight()) / 2, small, LIGHT);
    }

    private void storeButton(Graphics g, String label, int x, int y) {
        // The original Swing action was a small pale-blue rectangular button.
        g.setColor(0xE8EDF1);
        g.fillRect(x, y, 77, 11);
        g.setColor(0xAEC9DF);
        g.fillRect(x, y + 11, 77, 11);
        g.setColor(BLUE);
        g.drawRect(x, y, 76, 21);
        center(g, label, x + 38, y + (22 - small.getHeight()) / 2,
                small, 0x505457);
    }

    private void text(Graphics g, String content, int x, int y, Font f, int colour) {
        if (content == null || y < 0 || y + f.getHeight() > h) return;
        g.setFont(f);
        g.setColor(colour);
        g.drawString(content, x, y, Graphics.TOP | Graphics.LEFT);
    }

    private void center(Graphics g, String content, int x, int y,
                        Font f, int colour) {
        text(g, content, x - f.stringWidth(content) / 2, y, f, colour);
    }

    private void fit(Graphics g, String content, int x, int y,
                     int maxWidth, Font f, int colour) {
        if (content == null || maxWidth <= 4) return;
        if (f.stringWidth(content) <= maxWidth) {
            text(g, content, x, y, f, colour);
            return;
        }
        if (f.stringWidth("...") > maxWidth) return;
        int end = content.length();
        while (end > 0 && f.stringWidth(content.substring(0, end) + "...") > maxWidth)
            --end;
        text(g, content.substring(0, end) + "...", x, y, f, colour);
    }

    /** Like Swing's scrolling text fields: keep the caret visible at the end. */
    private void tailFit(Graphics g, String content, int x, int y,
                         int maxWidth, Font f, int colour) {
        if (content == null || maxWidth <= 4) return;
        int first = 0;
        while (first < content.length() &&
                f.stringWidth(content.substring(first)) > maxWidth) ++first;
        text(g, content.substring(first), x, y, f, colour);
    }

    /** Wrap complete original copy rather than clipping the Swing label. */
    private int wrapped(Graphics g, String content, int x, int y,
                        int width, Font f, int colour, int stopY) {
        if (width < 8) return y;
        String rest = content;
        while (rest.length() > 0 && y + f.getHeight() <= stopY) {
            int end = 0;
            int lastSpace = -1;
            while (end < rest.length() &&
                    f.stringWidth(rest.substring(0, end + 1)) <= width) {
                if (rest.charAt(end) == ' ') lastSpace = end;
                ++end;
            }
            if (end < rest.length() && lastSpace > 0) end = lastSpace;
            if (end == 0) end = 1;
            text(g, rest.substring(0, end).trim(), x, y, f, colour);
            rest = rest.substring(end).trim();
            y += f.getHeight() + 2;
        }
        return y;
    }

    private void scrollbar(Graphics g, int start, int height,
                           int total, int visible, int first) {
        if (visible >= total || height < 8) return;
        int thumbH = height * visible / total;
        if (thumbH < 8) thumbH = 8;
        int thumbY = start + (height - thumbH) * first / (total - visible);
        g.setColor(0x676767);
        g.fillRect(w - 4, start, 2, height);
        g.setColor(BLUE);
        g.fillRect(w - 4, thumbY, 2, thumbH);
    }

    protected void hideNotify() {
        app.canvasHidden();
    }

    protected void showNotify() {
        app.canvasShown();
    }

    protected void keyPressed(int code) {
        if (homeKeyName(code)) { app.home(); return; }
        if (app.editMode != 0) {
            editKey(code);
            return;
        }
        // Nokia's numeric keys provide non-touch access to 4.2-style panels.
        if (code == KEY_NUM1 && app.screen == E63Midlet.HOME) {
            app.openDrawer(); return;
        }
        if (code == KEY_NUM1 && app.screen == E63Midlet.APP_DRAWER) {
            app.drawerTab(false); return;
        }
        if (code == KEY_NUM9 && app.screen == E63Midlet.APP_DRAWER) {
            app.drawerTab(true); return;
        }
        if (code == KEY_NUM3) { app.openNotifications(); return; }
        if (code == KEY_NUM7) { app.openQuickSettings(); return; }
        if (code == KEY_POUND) { app.home(); return; }
        // S60 selection keys: -6 is the physical LEFT softkey, not D-pad LEFT.
        // D-pad LEFT/RIGHT remain navigation, never Back or Home.
        if (code == -6 || code == KEY_NUM0 || code == KEY_STAR ||
                leftSoftkeyName(code)) { app.back(); return; }
        if (code == -7 || code == -22 || code == -5 || code == KEY_NUM5 ||
                rightSoftkeyName(code)) { app.activate(); return; }
        int action = 0;
        try { action = getGameAction(code); }
        catch (IllegalArgumentException ignored) { }
        if (action == FIRE) app.activate();
        else if (action == UP || action == LEFT || code == KEY_NUM2 || code == KEY_NUM4)
            app.move(-1);
        else if (action == DOWN || action == RIGHT || code == KEY_NUM8 || code == KEY_NUM6)
            app.move(1);
    }

    private boolean leftSoftkeyName(int code) {
        if (code >= 0) return false;
        try {
            String name = getKeyName(code).toUpperCase();
            return name.indexOf("SOFT1") >= 0 ||
                   name.indexOf("SOFTKEY 1") >= 0 ||
                   name.indexOf("SOFTKEY1") >= 0 ||
                   name.indexOf("SOFT LEFT") >= 0 ||
                   name.indexOf("LEFT SOFT") >= 0 ||
                   name.indexOf("LEFT SELECTION") >= 0;
        } catch (Exception unknownKey) { return false; }
    }

    private boolean rightSoftkeyName(int code) {
        if (code >= 0) return false;
        try {
            String name = getKeyName(code).toUpperCase();
            return name.indexOf("SOFT2") >= 0 ||
                   name.indexOf("SOFTKEY 2") >= 0 ||
                   name.indexOf("SOFTKEY2") >= 0 ||
                   name.indexOf("SOFT RIGHT") >= 0 ||
                   name.indexOf("RIGHT SOFT") >= 0 ||
                   name.indexOf("RIGHT SELECTION") >= 0;
        } catch (Exception unknownKey) { return false; }
    }

    private boolean homeKeyName(int code) {
        if (code >= 0) return false;
        try {
            String name = getKeyName(code).toUpperCase();
            return "HOME".equals(name) || "HOME KEY".equals(name) ||
                   "MENU".equals(name) || "MENU KEY".equals(name);
        } catch (Exception unknownKey) { return false; }
    }

    /** Tap targets mirror the drawn guest widgets; no host-side UI routing. */
    protected void pointerPressed(int x, int y) {
        int width = getWidth(), height = getHeight();
        int navY = height - NAV_H;
        if (y >= navY && y < height) {
            if (x < width / 3) app.back();
            else if (x >= width * 2 / 3) app.openRecents();
            else app.home();
            return;
        }
        if (app.editMode != 0) return;
        if (y >= 0 && y < STATUS_H) {
            if (x >= width * 2 / 3) app.openQuickSettings();
            else app.openNotifications();
            return;
        }
        pointerBody(x, y);
    }

    // Keep the bar/key dispatch small enough for the bounded native event VM;
    // the richer tap targets are interpreted by the full PC guest DEX VM.
    private void pointerBody(int x, int y) {
        int width = getWidth(), height = getHeight();
        int navY = height - NAV_H;
        if (app.screen == E63Midlet.HOME) {
            int dockY = height - NAV_H - 55;
            if (y >= STATUS_H + 5 && y <= STATUS_H + 37) {
                app.openDrawer();
            } else if (app.store.isInstalled() && x < width / 2 &&
                    y >= dockY - 72 && y < dockY - 22) {
                app.selected[E63Midlet.HOME] = 0;
                app.activate();
            } else if (y >= dockY - 8 && y < navY) {
                if (x < width / 3) {
                    app.selected[E63Midlet.HOME] = app.store.isInstalled() ? 1 : 0;
                    app.activate();
                } else if (x >= width * 2 / 3) {
                    app.selected[E63Midlet.HOME] = app.store.isInstalled() ? 2 : 1;
                    app.activate();
                } else app.openDrawer();
            }
        } else if (app.screen == E63Midlet.APP_DRAWER) {
            if (y < STATUS_H + 43) app.drawerTab(x >= width / 2);
            else if (!app.widgetsTab && y >= STATUS_H + 56) {
                int count = app.store.isInstalled() ? 3 : 2;
                int index = x * count / width;
                if (index >= count) index = count - 1;
                app.selected[E63Midlet.APP_DRAWER] = index;
                app.activate();
            }
        } else if (app.screen == E63Midlet.NOTIFICATIONS) {
            if (y >= navY - 51) app.openQuickSettings();
        } else if (app.screen == E63Midlet.QUICK_SETTINGS) {
            if (y >= STATUS_H + 44 && y < STATUS_H + 112) {
                app.selected[E63Midlet.QUICK_SETTINGS] = x < width / 2 ? 0 : 1;
                app.activate();
            }
        } else if (app.screen == E63Midlet.RECENTS) {
            if (y >= STATUS_H + 54 && y < STATUS_H + 109) {
                app.selected[E63Midlet.RECENTS] = 0;
                app.activate();
            } else if (y >= STATUS_H + 117 && y < STATUS_H + 172 &&
                    app.recentScreen != app.recentsOrigin) {
                app.selected[E63Midlet.RECENTS] = 1;
                app.activate();
            }
        } else if (app.screen == E63Midlet.SETTINGS) {
            int headerBottom = STATUS_H + 35;
            if (y < headerBottom) return;
            int wifiH = navY - headerBottom >= 132 ? 52 : 43;
            if (wifiH > navY - headerBottom - 43)
                wifiH = navY - headerBottom - 43;
            int clockY = headerBottom + wifiH;
            int clockH = navY - clockY >= 85 ? 43 : 39;
            app.selected[E63Midlet.SETTINGS] = y < clockY ? 0 :
                    y < clockY + clockH ? 1 : 2;
            app.activate();
        } else if (app.screen == E63Midlet.LOGIN) {
            int titleY = height >= 220 ? 26 : 15;
            int firstY = titleY + large.getHeight() + 33;
            if (x >= 16 && x < width - 16 && y >= firstY - 6 &&
                    y <= firstY + small.getHeight() + 9) {
                app.selected[E63Midlet.LOGIN] = 0;
                app.activate();
            } else if (x >= 16 && x < width - 16 && y >= firstY + 30 &&
                    y <= firstY + 36 + small.getHeight() + 9) {
                app.selected[E63Midlet.LOGIN] = 1;
                app.activate();
            } else if (x >= width - 65 && y >= height - 75 && y < navY) {
                app.selected[E63Midlet.LOGIN] = 2;
                app.activate();
            }
        } else if (app.screen == E63Midlet.STORE) {
            if (y < STORE_HEADER_H && (width < 230 ? y >= STATUS_H + 22 :
                    x >= 110 && x <= width - 19)) {
                app.selected[E63Midlet.STORE] = 0;
                app.activate();
            } else if (y >= STORE_HEADER_H + 22) {
                app.selected[E63Midlet.STORE] = 1;
                app.activate();
            }
        } else if (app.screen == E63Midlet.APP) {
            if (x >= 18 && x < 100 && y >= navY - 32) app.activate();
        } else if (app.screen == E63Midlet.FILES && y >= FILE_HEADER_H) {
            if (width >= 240 && x >= width * 54 / 100) {
                app.selected[E63Midlet.FILES] =
                        y < FILE_HEADER_H + (navY - FILE_HEADER_H) / 2 ? 4 : 5;
            } else if (width >= 240) {
                int rowH = (navY - FILE_HEADER_H - 10) / 4;
                if (rowH > 39) rowH = 39;
                if (rowH < 27) rowH = 27;
                int row = (y - FILE_HEADER_H - 5) / rowH;
                if (row < 0 || row > 3) return;
                app.selected[E63Midlet.FILES] = row;
            } else return; // Narrow layout remains keyboard-navigable.
            app.activate();
        } else if (app.screen == E63Midlet.ANDROID_FOLDER &&
                y >= FILE_HEADER_H) {
            int rowH = (navY - FILE_HEADER_H - 8) / 3;
            if (rowH > 42) rowH = 42;
            if (rowH < 29) rowH = 29;
            int row = (y - FILE_HEADER_H - 5) / rowH;
            if (row >= 0 && row < 3) {
                app.selected[E63Midlet.ANDROID_FOLDER] = row;
                app.activate();
            }
        } else if (app.screen == E63Midlet.NO_INTERNET ||
                app.screen == E63Midlet.SYSTEM_ERROR ||
                app.screen == E63Midlet.BATTERY_ALERT) {
            app.activate();
        }
    }

    private void editKey(int code) {
        if (code == -6 || code == 27 || leftSoftkeyName(code)) {
            app.back(); return;
        }
        if (code == -7 || code == -22 || code == -5 || code == 10 ||
                code == 13 || rightSoftkeyName(code)) {
            app.commitEditing(); return;
        }
        if (code == 8 || code == 127 || code == -8) {
            app.deleteCharacter(); return;
        }
        if (code == KEY_POUND && app.editMode == E63Midlet.EDIT_EMAIL) {
            // QWERTY alternate input: the E63's # key can supply an @ sign.
            app.typeCharacter('@'); return;
        }
        // Handle printable QWERTY keys before getGameAction: otherwise the
        // digits 2/4/5/6/8 would accidentally navigate/confirm the form.
        if (code >= 32 && code <= 126) {
            app.typeCharacter((char) code); return;
        }
        int action = 0;
        try { action = getGameAction(code); }
        catch (IllegalArgumentException ignored) { }
        if (action == FIRE) app.commitEditing();
    }

    protected void keyRepeated(int code) {
        if (app.editMode != 0) return;
        int action = 0;
        try { action = getGameAction(code); }
        catch (IllegalArgumentException ignored) { }
        if (action == UP || action == LEFT) app.move(-1);
        else if (action == DOWN || action == RIGHT) app.move(1);
    }
}
