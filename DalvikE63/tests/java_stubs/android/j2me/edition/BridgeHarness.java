package android.j2me.edition;
public final class BridgeHarness {
    public static void main(String[] args) {
        try { System.out.println(BridgeClient.ping(args[0])); }
        catch (Exception e) { System.err.println(e.toString()); System.exit(2); }
    }
}
