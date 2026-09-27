#!/usr/bin/env python3
"""Optional 320x240 browser preview powered by the real APK DEX interpreter.

Rendered options/text come from adapter classes2.dex; Store decisions run from
actual D8-translated MIDP StoreState in classes.dex.
No JavaScript, external assets, proxy, Android emulator or Nokia installation.
"""
from __future__ import annotations

import argparse
import base64
import html
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from dalvik.ids import FILES, LAUNCHER, STORE, SYSTEMUI
from dalvik.host import HostError
from dalvik.dex_j2me import J2MEDexError
from dalvik.vm import VMError
from shell import DesktopShell

HERE = Path(__file__).resolve().parent
E = html.escape

CSS = """
*{box-sizing:border-box}body{background:#17191e;color:#d1d8e1;font:14px Arial,sans-serif;
margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center}
.stage{max-width:340px;margin:16px}.caption{text-align:center;color:#9ca7b9;font-size:11px;
margin:0 0 8px}.phone{width:320px;height:240px;position:relative;overflow:hidden;
border:2px solid #767f8b;background:#333;box-shadow:0 16px 40px #080a0c;border-radius:3px}
.wall{position:absolute;inset:0;background-position:center;background-size:cover;opacity:.88}
.status{height:19px;position:relative;z-index:2;background:#08090b;color:#e7e9ec;
font-size:10px;line-height:19px;padding:0 7px;display:flex;justify-content:space-between}
.header{height:30px;position:relative;z-index:2;background:#3c3f41;color:#e4e8ef;
border-bottom:1px solid #39f;font-size:15px;font-weight:bold;padding:6px 8px}
.header.files{background:#09f;color:white;border:0}.body{position:relative;z-index:2;
height:157px;padding:7px 8px;overflow:auto;font-size:11px;line-height:1.3}
.body.launcher{padding-top:72px}.body.systemui{background:#050505}
.row{padding:2px 0;color:#dce6f1;overflow-wrap:anywhere}
.options{display:grid;gap:3px;margin-top:5px}.options form{margin:0}
.opt{width:100%;min-height:19px;border:1px solid #4f718b;background:#2f3842;
color:#f3f7fd;text-align:left;font:11px Arial;padding:3px 6px;cursor:pointer;border-radius:2px}
.opt:hover,.opt:focus{border-color:#39f;background:#18547a}.launcher .opt{background:#2d3038ee}
.nav{height:30px;position:absolute;bottom:0;left:0;right:0;background:#08090b;
display:flex;align-items:center;justify-content:space-around;z-index:4}
.nav form{width:50%;margin:0;text-align:center}.nav button{width:92%;height:25px;
border:1px solid #424b54;background:#161b21;color:#dfe6ee;font-size:11px;cursor:pointer}
.dialog{margin:14px 5px 7px;background:#3c3f41;border-top:3px solid #39f;
border-bottom:1px solid #39f;padding:10px 9px;color:#e7e8eb;font-size:13px}
.meta{font-size:10px;color:#9cacc0;margin:6px 0 3px}
.toolbox{margin-top:9px;padding:9px;background:#222831;border:1px solid #4f5661;
font-size:11px}.toolbox select,.toolbox input{background:#10151b;color:white;
border:1px solid #596676;font:12px Arial;padding:4px;margin:3px 0;width:100%}
.toolbox button{border:1px solid #1b7ab1;background:#146196;color:white;padding:5px 10px}
.error{color:#ffc0c0;font-size:12px;max-width:320px;overflow-wrap:anywhere}
"""


class WebState:
    def __init__(self, state: Path):
        self.shell = DesktopShell(state=state, import_root=HERE / "imports")
        self.lock = threading.RLock()
        self.error = ""
        wall = (HERE / "assets/wall.png").read_bytes()
        self.wall = "data:image/png;base64," + base64.b64encode(wall).decode("ascii")

    def html(self) -> str:
        shell = self.shell
        events = shell.events[:]
        title = next((e[1] for e in events if e[0] == "title"), "Dalvik E63")
        lines = [e[1] for e in events if e[0] in ("text", "message")]
        dialogs = [e[1] for e in events if e[0] == "dialog"]
        options = [(e[1], e[2]) for e in events if e[0] == "option"]
        kind = "launcher" if shell.active == LAUNCHER else "systemui" if shell.active == SYSTEMUI else ""
        header = "files" if shell.active == FILES else ""
        bg = f'<div class="wall" style="background-image:url({self.wall})"></div>' \
            if shell.active == LAUNCHER else ""
        buttons = "".join(
            '<form action="/action" method="post"><input type="hidden" name="type" value="select">'
            f'<input type="hidden" name="index" value="{n}">'
            f'<button class="opt" type="submit">{n} &nbsp; {E(label)}</button></form>'
            for n, label in options)
        rows = "".join('<div class="row">' + E(line) + '</div>' for line in lines)
        warning = "".join('<div class="dialog">' + E(msg) + '</div>' for msg in dialogs)
        tools = ""
        if shell.active == STORE:
            tools = '<form class="toolbox" method="post" action="/action">' \
                    '<input type="hidden" name="type" value="search">' \
                    '<label>Cerca in Store (offline)<input name="arg1" placeholder="file manager"></label>' \
                    '<button>Cerca</button></form>'
        elif shell.active == FILES:
            choices = "".join(f'<option value="{name}">{name}</option>'
                              for name in ("ls", "mkdir", "touch", "rename", "delete", "import", "wav"))
            tools = '<form class="toolbox" method="post" action="/action">' \
                    '<input type="hidden" name="type" value="file">' \
                    '<label>Operazione<select name="command">' + choices + '</select></label>' \
                    '<input name="arg1" placeholder="/sdcard/Download o file sorgente da imports/">' \
                    '<input name="arg2" placeholder="secondo percorso (rename/import)">' \
                    '<button>Esegui</button></form>'
        now = datetime.now().strftime("%H:%M")
        page = f'''<!doctype html><html lang="it"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} | Dalvik E63</title><style>{CSS}</style>
<main class="stage"><p class="caption">ANTEPRIMA PC · DEX adattatori + StoreState J2ME originale · NON NOKIA</p>
<div class="phone">{bg}
<div class="status"><span>No service</span><span>Battery: ? &nbsp; {now}</span></div>
<div class="header {header}">{E(title)}</div>
<div class="body {kind}">{warning}{rows}<div class="options">{buttons}</div></div>
<div class="nav">
<form action="/action" method="post"><input type="hidden" name="type" value="back"><button>◁ &nbsp; Indietro</button></form>
<form action="/action" method="post"><input type="hidden" name="type" value="home"><button>⌂ &nbsp; Home</button></form>
</div></div>{tools}
<p class="meta">Solo VM host: APK Android reali ma incompatibili con Android 4.2; nessun SISX su E63.</p>
{('<p class="error">'+E(self.error)+'</p>') if self.error else ''}
</main></html>'''
        return page

    def action(self, fields: dict[str, list[str]]):
        shell = self.shell
        action = fields.get("type", [""])[0]
        self.error = ""
        try:
            if action == "back": shell.back()
            elif action == "home": shell.home()
            elif action == "select": shell.select(int(fields.get("index", ["-1"])[0]))
            elif action == "search": shell.command("search", fields.get("arg1", [""])[0])
            elif action == "file":
                cmd = fields.get("command", [""])[0]
                a, b = fields.get("arg1", [""])[0], fields.get("arg2", [""])[0]
                shell.command(cmd, a, b) if cmd in ("rename", "import") else shell.command(cmd, a)
            else: raise HostError("invalid action")
        except (ValueError, HostError, VMError, J2MEDexError, OSError) as exc:
            self.error = str(exc)


def serve(port: int, state: Path):
    app = WebState(state)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            with app.lock:
                content = app.html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            if self.path != "/action":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > 2048: raise ValueError("request too large")
                fields = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True)
                with app.lock:
                    app.action(fields)
            except (UnicodeError, ValueError) as exc:
                self.send_error(400, str(exc))
                return
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state", type=Path, default=HERE / "state")
    args = parser.parse_args()
    serve(args.port, args.state)
