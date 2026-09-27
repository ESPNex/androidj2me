package android.j2me.edition;

import java.io.InputStream;
import javax.microedition.media.Manager;
import javax.microedition.media.Player;

/** Optional local WAV playback (JSR-135); never touches the network. */
final class AudioDeck {
    private final E63Midlet app;
    private Player current;
    private InputStream stream;
    private int generation;

    AudioDeck(E63Midlet app) {
        this.app = app;
    }

    void play(final String resource, final String originalPlayingText) {
        final int request;
        synchronized (this) {
            ++generation;
            request = generation;
            closeCurrent();
            app.audioStatus("");
        }
        // Several-megabyte WAVs must not freeze the keypad/UI thread.
        new Thread(new Runnable() {
            public void run() {
                Player p = null;
                InputStream input = null;
                boolean handedOff = false;
                try {
                    input = AudioDeck.class.getResourceAsStream(resource);
                    if (input == null) return;
                    p = Manager.createPlayer(input, "audio/x-wav");
                    p.realize();
                    p.prefetch();
                    synchronized (AudioDeck.this) {
                        if (generation == request) {
                            current = p;
                            stream = input;
                            handedOff = true;
                        }
                    }
                    if (handedOff) {
                        p.start();
                        if (originalPlayingText.length() > 0 && app.screen == E63Midlet.FILES)
                            app.audioStatus(originalPlayingText);
                    }
                } catch (Throwable unsupported) {
                    // The original UI has no extra "audio unavailable" caption.
                    synchronized (AudioDeck.this) {
                        if (generation == request) {
                            closeCurrent();
                            app.audioStatus("");
                        }
                    }
                } finally {
                    if (!handedOff) {
                        if (p != null) try { p.close(); } catch (Throwable ignored) { }
                        if (input != null) try { input.close(); } catch (Exception ignored) { }
                    }
                }
            }
        }).start();
    }

    synchronized void stop() {
        ++generation;
        closeCurrent();
        app.audioStatus("");
    }

    private void closeCurrent() {
        if (current != null) {
            try { current.stop(); } catch (Throwable ignored) { }
            try { current.close(); } catch (Throwable ignored) { }
            current = null;
        }
        if (stream != null) {
            try { stream.close(); } catch (Exception ignored) { }
            stream = null;
        }
    }
}
