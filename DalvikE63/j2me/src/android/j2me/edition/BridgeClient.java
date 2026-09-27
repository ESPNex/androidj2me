package android.j2me.edition;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import javax.microedition.io.Connector;
import javax.microedition.io.SocketConnection;

/** MIDP 2.0 client for the companion Symbian console EXE packaged in a SIS.
 *  Loopback, one request per connection, bounded ASCII frame, PIN entered by
 *  the user from the native console. Never sends login credentials or files.
 */
final class BridgeClient {
    static final String ENDPOINT = "socket://127.0.0.1:27463";
    private static final String VERSION = "E63BRIDGE/1";

    private BridgeClient() { }

    static String ping(String pin) throws IOException {
        if (pin == null || pin.length() != 6) throw new IOException("Code: six digits required");
        for (int i = 0; i < pin.length(); ++i) {
            char c = pin.charAt(i);
            if (c < '0' || c > '9') throw new IOException("Code: digits only");
        }
        SocketConnection socket = null;
        InputStream input = null;
        OutputStream output = null;
        try {
            socket = (SocketConnection) Connector.open(ENDPOINT, Connector.READ_WRITE, true);
            output = socket.openOutputStream();
            input = socket.openInputStream();
            byte[] request = (VERSION + "\tAUTH\t" + pin + "\tPING\n").getBytes();
            output.write(request);
            output.flush();
            byte[] reply = new byte[96];
            int count = 0;
            while (count < reply.length) {
                int b = input.read();
                if (b == -1) throw new IOException("SIS closed the bridge connection");
                if (b == '\n') {
                    String response = new String(reply, 0, count);
                    if ((VERSION + "\tOK\tPONG").equals(response)) return "SIS bridge: PONG";
                    throw new IOException("SIS rejected pairing or version");
                }
                if (b < 32 && b != '\t' || b > 126) throw new IOException("Invalid SIS reply");
                reply[count++] = (byte) b;
            }
            throw new IOException("SIS reply too long");
        } finally {
            if (input != null) try { input.close(); } catch (IOException ignored) { }
            if (output != null) try { output.close(); } catch (IOException ignored) { }
            if (socket != null) try { socket.close(); } catch (IOException ignored) { }
        }
    }
}
