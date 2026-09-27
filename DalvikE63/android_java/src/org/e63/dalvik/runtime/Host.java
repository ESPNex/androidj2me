package org.e63.dalvik.runtime;

import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.res.AssetFileDescriptor;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Environment;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** Android implementation of the narrow device-service API.
 * On the PC/E63 Dalvik interpreter ONLY the explicitly allowlisted signatures
 * below are brokered; arbitrary Android APIs/this Java implementation are not
 * secretly executed in Python or C. There is no native Android runtime on E63.
 */
public final class Host {
    private static GuestActivity activity;
    private static LinearLayout column;
    private static boolean opened;
    private static final int ACCENT = 0xff33b5e5;
    private static final String FILES = "org.e63.dalvik.files";
    private Host() {}

    static void begin(GuestActivity current) {
        activity = current;
        opened = false;
        ScrollView scroll = new ScrollView(current);
        scroll.setBackgroundColor(0xff101010);
        column = new LinearLayout(current);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setPadding(12, 8, 12, 12);
        scroll.addView(column);
        current.setContentView(scroll);
    }

    static boolean navigated() { return opened; }

    private static void notice(String message) {
        Toast.makeText(activity, message, Toast.LENGTH_LONG).show();
    }

    private static boolean safeAssetName(String name) {
        if (name == null || name.length() == 0 || name.length() > 80) return false;
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                  (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.'))
                return false;
        }
        return !name.equals(".") && !name.equals("..");
    }

    public static void title(String value) {
        activity.setTitle(value);
        TextView view = new TextView(activity);
        view.setText(value);
        view.setTextSize(24);
        view.setTextColor(ACCENT);
        view.setPadding(0, 5, 0, 10);
        column.addView(view);
    }

    public static void text(String value) {
        TextView view = new TextView(activity);
        view.setText(value);
        view.setTextColor(Color.WHITE);
        view.setTextSize(16);
        view.setPadding(0, 3, 0, 6);
        column.addView(view);
    }

    /** Each Activity's Program calls this only for assets in its own APK. */
    public static void image(String name) {
        if (!safeAssetName(name)) { notice("Invalid image asset"); return; }
        InputStream stream = null;
        try {
            stream = activity.getAssets().open(name);
            ImageView image = new ImageView(activity);
            image.setImageBitmap(BitmapFactory.decodeStream(stream));
            image.setAdjustViewBounds(true);
            column.addView(image);
        } catch (IOException error) {
            notice("Image unavailable: " + name);
        } finally {
            if (stream != null) try { stream.close(); } catch (IOException ignored) {}
        }
    }

    public static void option(final int index, String value) {
        Button button = new Button(activity);
        button.setText(value);
        button.setTextColor(Color.WHITE);
        final GuestActivity from = activity;
        button.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { from.choose(index); }
        });
        column.addView(button);
    }

    /** UI for Store search or File Manager commands; the Program handles it. */
    public static void input(final int code, String title, int arity) {
        if (arity < 1 || arity > 2) return;
        final EditText first = new EditText(activity);
        first.setHint(arity == 2 ? "Source" : "Path or search");
        first.setSingleLine(true);
        column.addView(first);
        final EditText second = arity == 2 ? new EditText(activity) : null;
        if (second != null) {
            second.setHint("Destination");
            second.setSingleLine(true);
            column.addView(second);
        }
        Button button = new Button(activity);
        button.setText(title);
        final GuestActivity from = activity;
        button.setOnClickListener(new View.OnClickListener() {
            public void onClick(View view) {
                from.command(code, first.getText().toString(),
                             second == null ? "" : second.getText().toString());
            }
        });
        column.addView(button);
    }

    public static void dialog(String value) {
        opened = true; // keep the current screen visible behind the dialog
        new AlertDialog.Builder(activity).setMessage(value)
            .setPositiveButton("OK", null).show();
    }

    public static void open(String packageName) {
        Intent intent = activity.getPackageManager().getLaunchIntentForPackage(packageName);
        if (intent == null) { notice("App not installed: " + packageName); return; }
        try { activity.startActivity(intent); opened = true; }
        catch (RuntimeException error) { notice("Cannot open " + packageName); }
    }

    public static int isInstalled(String packageName) {
        try {
            activity.getPackageManager().getPackageInfo(packageName, 0);
            return 1;
        } catch (android.content.pm.PackageManager.NameNotFoundException notFound) {
            return 0;
        }
    }

    public static int getFlag(String key) {
        if (!key.equals("wifi_demo") && !key.equals("adjust_clock")) return 0;
        return activity.getSharedPreferences("e63", 0).getInt(key, 0);
    }

    public static void setFlag(String key, int value) {
        if ((!key.equals("wifi_demo") && !key.equals("adjust_clock")) ||
            (value != 0 && value != 1)) return;
        SharedPreferences.Editor editor = activity.getSharedPreferences("e63", 0).edit();
        editor.putInt(key, value);
        editor.apply();
    }

    public static int searchFile(String query) {
        String q = query.trim().toLowerCase(java.util.Locale.US);
        return q.equals("file manager") || q.equals("file") || q.equals("file man") ? 1 : 0;
    }

    private static File external(String path) throws IOException {
        if (path == null || !path.startsWith("/sdcard/") || path.length() > 512)
            throw new IOException("only /sdcard paths are available");
        if (!Environment.MEDIA_MOUNTED.equals(Environment.getExternalStorageState()))
            throw new IOException("external storage not mounted");
        File root = Environment.getExternalStorageDirectory().getCanonicalFile();
        File result = new File(root, path.substring(8)).getCanonicalFile();
        if (!result.getPath().startsWith(root.getPath() + File.separator))
            throw new IOException("path escapes storage root");
        return result;
    }

    public static void list(String path) {
        try {
            File directory = path.equals("/sdcard") ?
                Environment.getExternalStorageDirectory().getCanonicalFile() : external(path);
            if (!directory.isDirectory()) throw new IOException("not a folder");
            String[] items = directory.list();
            if (items == null) throw new IOException("cannot list folder");
            StringBuilder result = new StringBuilder(path).append(": ");
            for (int i = 0; i < items.length && i < 40; i++) {
                if (i > 0) result.append(", ");
                result.append(items[i]);
            }
            text(result.toString());
        } catch (IOException error) { notice("List: " + error.getMessage()); }
    }

    public static int mkdir(String path) {
        try { return external(path).mkdir() ? 1 : 0; }
        catch (IOException error) { notice(error.getMessage()); return 0; }
    }

    public static int touch(String path) {
        try { return external(path).createNewFile() ? 1 : 0; }
        catch (IOException error) { notice(error.getMessage()); return 0; }
    }

    public static int rename(String from, String to) {
        try { File dest = external(to); return !dest.exists() && external(from).renameTo(dest) ? 1 : 0; }
        catch (IOException error) { notice(error.getMessage()); return 0; }
    }

    public static int delete(String path) {
        try { return external(path).delete() ? 1 : 0; }
        catch (IOException error) { notice(error.getMessage()); return 0; }
    }

    public static int importFile(String source, String dest) {
        // Only files intentionally placed in THIS application's private imports/
        // may be copied to external storage; not arbitrary system/Nokia files.
        if (!safeAssetName(source)) { notice("Import only a private simple filename"); return 0; }
        InputStream in = null; OutputStream out = null;
        File target = null;
        boolean created = false, complete = false;
        try {
            File origin = new File(new File(activity.getFilesDir(), "imports"), source);
            if (!origin.isFile()) throw new IOException("private import source not found");
            target = external(dest);
            if (!target.createNewFile()) throw new IOException("destination already exists");
            created = true;
            in = new java.io.FileInputStream(origin);
            out = new FileOutputStream(target);
            byte[] block = new byte[8192]; int count; long written = 0;
            while ((count = in.read(block)) != -1) {
                written += count;
                if (written > 16 * 1024 * 1024) throw new IOException("import too large");
                out.write(block, 0, count);
            }
            out.close(); out = null;
            complete = true;
            return 1;
        } catch (IOException error) { notice(error.getMessage()); return 0; }
        finally {
            if (in != null) try { in.close(); } catch (IOException ignored) {}
            if (out != null) try { out.close(); } catch (IOException ignored) {}
            if (created && !complete && target != null) target.delete();
        }
    }

    /** Requests Android's own installer with explicit user consent. Never
     * report success until PackageManager confirms FileManager is installed.
     */
    public static int install(String packageName) {
        if (!FILES.equals(packageName)) return 0;
        InputStream in = null; OutputStream out = null;
        File target = null;
        boolean requested = false;
        try {
            File cache = activity.getExternalCacheDir();
            if (cache == null || (!cache.isDirectory() && !cache.mkdirs()))
                throw new IOException("external app cache unavailable");
            target = new File(cache, "FileManager-E63.apk");
            if (target.exists() && !target.delete())
                throw new IOException("cannot replace previous app cache file");
            in = activity.getAssets().open("packages/FileManager.apk");
            out = new FileOutputStream(target);
            byte[] buffer = new byte[8192]; int count; long written = 0;
            while ((count = in.read(buffer)) != -1) {
                written += count;
                if (written > 12 * 1024 * 1024) throw new IOException("APK larger than limit");
                out.write(buffer, 0, count);
            }
            out.close(); out = null;
            PackageInfo info = activity.getPackageManager().getPackageArchiveInfo(target.getPath(), 0);
            if (info == null || !FILES.equals(info.packageName))
                throw new IOException("bundled APK has wrong package");
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(Uri.fromFile(target), "application/vnd.android.package-archive");
            activity.startActivity(intent); opened = true; requested = true;
            // A prompt has been launched, NOT a successful silent installation.
            return 0;
        } catch (IOException error) { notice("Installer: " + error.getMessage()); return 0; }
        catch (RuntimeException error) { notice("Android blocked installer request"); return 0; }
        finally {
            if (in != null) try { in.close(); } catch (IOException ignored) {}
            if (out != null) try { out.close(); } catch (IOException ignored) {}
            if (!requested && target != null && target.isFile()) target.delete();
        }
    }

    public static int wav(String path) {
        String name;
        if ("/sdcard/Music/music.wav".equals(path)) name = "music.wav";
        else if ("/system/media/audio/ui/lowbattery.wav".equals(path)) name = "lowbattery.wav";
        else { notice("Only bundled demo audio is supported"); return 0; }
        AssetFileDescriptor fd = null; MediaPlayer player = null;
        try {
            fd = activity.getAssets().openFd(name); // must be STORED, not deflated
            player = new MediaPlayer();
            player.setDataSource(fd.getFileDescriptor(), fd.getStartOffset(), fd.getLength());
            player.prepare();
            final MediaPlayer current = player;
            player.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
                public void onCompletion(MediaPlayer completed) { current.release(); }
            });
            player.start(); player = null;
            return 1;
        } catch (IOException error) { notice("Audio unavailable: " + name); return 0; }
        catch (RuntimeException error) { notice("Audio format unsupported"); return 0; }
        finally {
            if (fd != null) try { fd.close(); } catch (IOException ignored) {}
            if (player != null) player.release();
        }
    }
}
