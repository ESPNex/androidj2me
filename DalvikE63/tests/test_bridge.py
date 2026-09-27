"""Host tests run the ACTUAL preverified Java ME BridgeClient.class.

A tiny test-only MIDP Connector shim forwards to localhost. The server uses
exactly the portable C parser linked by the (uncompiled) Symbian adapter.
This does NOT prove S60 socket permissions, UI, SIS packaging or E63 behavior.
"""
import ctypes
import os
import shutil
import socketserver
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from dalvik.tools import jdk_tool

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "j2me/Android_J2ME_E63_Bridge.jar"
CORE = ROOT / "symbian/bridge_protocol.c"


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gcc, javac, java = shutil.which("gcc"), jdk_tool("javac"), jdk_tool("java")
        if not gcc or not javac or not java:
            raise unittest.SkipTest("host gcc and JDK needed for portable bridge test")
        cls.java = java
        (ROOT / "build").mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.path = Path(cls.tmp.name)
        dll = cls.path / "libe63bridge.so"
        subprocess.run([gcc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-fPIC",
                        "-shared", str(CORE), "-o", str(dll)], check=True,
                       capture_output=True, text=True)
        cls.core = ctypes.CDLL(str(dll)).e63_reply
        cls.core.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p,
                             ctypes.c_void_p, ctypes.c_size_t]
        cls.core.restype = ctypes.c_int
        cls.classes = cls.path / "classes"
        cls.classes.mkdir()
        java_files = sorted((ROOT / "tests/java_stubs").rglob("*.java"))
        result = subprocess.run([javac, "-cp", str(JAR), "-d", str(cls.classes),
                                 *map(str, java_files)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Java ME test shim failed: " + result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"): cls.tmp.cleanup()

    @classmethod
    def reply(cls, data: bytes, code: bytes = b"123456") -> tuple[int, bytes]:
        inp = ctypes.create_string_buffer(data)
        out = ctypes.create_string_buffer(96)
        result = cls.core(inp, len(data), code, out, len(out))
        return result, out.raw[:abs(result)]

    def test_c_protocol_accepts_only_correct_pin_version_and_ping(self):
        frame = b"E63BRIDGE/1\tAUTH\t123456\tPING\n"
        success = b"E63BRIDGE/1\tOK\tPONG\n"
        self.assertEqual(self.reply(frame), (len(success), success))
        for bad in (b"E63BRIDGE/2\tAUTH\t123456\tPING\n",
                    b"E63BRIDGE/1\tAUTH\t000000\tPING\n",
                    b"E63BRIDGE/1\tAUTH\t123456\tDELETE\n",
                    frame + b"garbage", frame[:-1], frame + b"!" * 200):
            with self.subTest(frame=bad):
                n, reply = self.reply(bad)
                self.assertLess(n, 0)
                self.assertEqual(reply, b"E63BRIDGE/1\tERR\tDENIED\n")

    def test_real_midp_classfile_client_to_compiled_c_core(self):
        outer = self

        class BridgeServer(socketserver.TCPServer):
            allow_reuse_address = True

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                received = bytearray()
                try:
                    while len(received) < 97:
                        b = self.request.recv(1)
                        if not b: break
                        received += b
                        if b == b"\n": break
                    n, response = outer.reply(bytes(received))
                    self.request.sendall(response)
                    self.server.received.append((bytes(received), n))
                except OSError:
                    pass

        server = BridgeServer(("127.0.0.1", 0), Handler)
        server.received = []
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        env = os.environ.copy()
        env["E63_TEST_PORT"] = str(server.server_address[1])
        classpath = os.pathsep.join((str(self.classes), str(JAR)))
        try:
            def call(code):
                return subprocess.run([self.java, "-cp", classpath,
                                       "android.j2me.edition.BridgeHarness", code],
                                      env=env, capture_output=True, text=True, timeout=10)
            ok = call("123456")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("SIS bridge: PONG", ok.stdout)
            wrong = call("987654")
            self.assertEqual(wrong.returncode, 2)
            self.assertIn("rejected pairing", wrong.stderr)
            invalid = call("letters")
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(len(server.received), 2)  # invalid code never opens a socket
            self.assertEqual(server.received[0][0], b"E63BRIDGE/1\tAUTH\t123456\tPING\n")
            self.assertGreater(server.received[0][1], 0)
            self.assertLess(server.received[1][1], 0)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
