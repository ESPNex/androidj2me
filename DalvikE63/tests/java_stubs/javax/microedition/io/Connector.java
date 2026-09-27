package javax.microedition.io;
import java.io.*;
import java.net.Socket;

/** JVM-only test shim: NOT shipped in the MIDlet or APK. */
public final class Connector {
    public static final int READ_WRITE = 3;
    public static Connection open(String uri, int mode, boolean timeouts) throws IOException {
        if (!"socket://127.0.0.1:27463".equals(uri) || mode != READ_WRITE)
            throw new IOException("unexpected MIDP socket endpoint");
        int port = Integer.parseInt(System.getenv("E63_TEST_PORT"));
        final Socket socket = new Socket("127.0.0.1", port);
        socket.setSoTimeout(2000);
        return new SocketConnection() {
            public InputStream openInputStream() throws IOException { return socket.getInputStream(); }
            public OutputStream openOutputStream() throws IOException { return socket.getOutputStream(); }
            public void close() throws IOException { socket.close(); }
        };
    }
}
