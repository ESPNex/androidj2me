#!/usr/bin/env python3
"""Live OS-host UI: ORIGINAL J2ME E63Canvas/E63Midlet interpreted from APK DEX.

The browser is a thin input/display terminal. Its 320x240 PNG pixels come from
executing the converted classes.dex guest paint(Graphics), never from the old
classes2.dex adapter preview or hardcoded HTML replicas of the screens.
"""
from __future__ import annotations

import argparse
import html
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from dalvik.midp_host import JObject, NativeError
from dalvik.ui_vm import JavaMEUI, UIVMError

HERE = Path(__file__).resolve().parent
E = html.escape

CSS = """
*{box-sizing:border-box}body{background:#12171e;color:#dfe6ef;margin:0;
font:14px Arial,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
main{max-width:360px;margin:18px auto;text-align:center}.eyebrow{color:#75bee9;
font-size:10px;letter-spacing:1.3px;font-weight:bold;text-transform:uppercase;margin:0 0 8px}
.phone{width:328px;padding:3px;margin:auto;border:1px solid #8799a8;border-radius:8px;
background:#252b32;box-shadow:0 14px 35px #05070a}
.screen{display:block;width:320px;height:240px;background:#090c0f;image-rendering:auto;cursor:pointer}
.controls{display:flex;justify-content:center;gap:7px;margin-top:12px;flex-wrap:wrap}
.controls form{display:inline;margin:0}.controls button,.editor button{border:1px solid #327da7;
background:#1d4260;color:#f4fbff;border-radius:4px;font:12px Arial;min-width:53px;height:30px;cursor:pointer}
.controls button:hover,.editor button:hover{background:#216e98}.help,.disclaimer{font-size:11px;
line-height:1.4;color:#9faebc;margin:9px 6px 0}.editor{border:1px solid #465668;
background:#222c36;padding:9px;margin:12px auto 0;text-align:left;width:328px;border-radius:4px}
.editor label{display:block;color:#badcf0;font-size:12px}.editor input{display:block;
width:100%;background:#101a23;color:white;border:1px solid #378bbe;padding:7px;margin:5px 0 8px;font:14px Arial}
.editor button{margin-right:7px}.error{font-size:11px;color:#ffb4af;overflow-wrap:anywhere}
"""


class OSPreview:
    def __init__(self, state: Path):
        self.ui = JavaMEUI(HERE / "apks/Launcher.apk", state)
        self.lock = threading.RLock()
        self.error = ""
        self.last_tick = time.monotonic()

    def advance(self):
        now = time.monotonic()
        elapsed = min(10000, int((now - self.last_tick) * 1000))
        if elapsed > 80:
            self.ui.tick(elapsed)  # invokes actual E63Midlet.tickLoop DEX once
            self.last_tick = now

    def form_html(self) -> str:
        form = self.ui.host.current
        if not isinstance(form, JObject) or form.desc != "Ljavax/microedition/lcdui/Form;":
            return ""
        fields = [item for item in form.fields.get("items", [])
                  if isinstance(item, JObject) and item.desc == "Ljavax/microedition/lcdui/TextField;"]
        if not fields: return ""
        field = fields[0]
        label = E(str(field.fields.get("label", "Testo")))
        maxlen = min(64, int(field.fields.get("max", 64)))
        secret = "password" if field.fields.get("constraints", 0) & 0x10000 else "text"
        return (f'<form class="editor" method="post" action="/action">'
                f'<input type="hidden" name="type" value="form">'
                f'<label>{label}<input autofocus type="{secret}" name="text" '
                f'maxlength="{maxlen}" autocomplete="off"></label>'
                f'<button type="submit" name="accept" value="1">Conferma</button>'
                f'<button type="submit" name="accept" value="0">Indietro</button></form>')

    def html(self) -> bytes:
        buttons = ''.join(
            '<form action="/action" method="post"><input type="hidden" name="type" value="key">'
            f'<button name="code" value="{code}">{E(label)}</button></form>'
            for code, label in ((-6, "◁ Indietro"), (-1, "↑"), (-2, "↓"),
                                (-7, "Seleziona"), (35, "⌂ Home"),
                                (49, "▦ App"), (51, "Notifiche"),
                                (55, "Impost. rapide")))
        page = f'''<!doctype html><html lang="it"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Android J2ME Edition — OS host DEX</title><style>{CSS}</style>
<main><p class="eyebrow">E63 OS host · UI J2ME eseguita dal DEX</p>
<div class="phone"><img class="screen" id="display" src="/screen.png" width="320" height="240"
alt="Interfaccia E63 resa da E63Canvas nel classes.dex"></div>
<div class="controls">{buttons}</div>
{self.form_html()}
<p class="help">Frecce su/giù · Invio/OK · Escape/Indietro · H/Home<br>
1/App · 3/Notifiche · 7/Impostazioni rapide · 9/Widgets nella pagina App.<br>
Tocca la barra in alto (sinistra/destra) o i tre tasti in basso: i click
raggiungono E63Canvas.pointerPressed nel DEX guest.</p>
<p class="disclaimer">Aspetto ispirato ad Android 4.2, non framework Android:
Wi-Fi e Store sono simulati, Recenti mostra solo schermate guest, nessuna notifica del Nokia.
Il bridge DEX può inviare PING via TCP locale; SIS non compilato, niente prova su E63.</p>
{('<p class="error">'+E(self.error)+'</p>') if self.error else ''}
</main><script>
function update() {{ document.getElementById('display').src='/screen.png?t='+Date.now(); }}
setInterval(update, 450);
const keys={{ArrowUp:-1,ArrowDown:-2,Enter:-7,Escape:-6,Backspace:-6,
h:35,H:35,'1':49,'3':51,'7':55,'9':57}};
window.addEventListener('keydown', async ev=>{{
 if (ev.target.tagName==='INPUT') return;
 const k=keys[ev.key];if(k===undefined)return;
 ev.preventDefault();
 await fetch('/action',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
 body:new URLSearchParams({{type:'key',code:k}})}});
 location.reload();
}});
document.getElementById('display').addEventListener('click',async ev=>{{
 const r=ev.currentTarget.getBoundingClientRect();
 const x=Math.max(0,Math.min(319,Math.floor((ev.clientX-r.left)*320/r.width)));
 const y=Math.max(0,Math.min(239,Math.floor((ev.clientY-r.top)*240/r.height)));
 await fetch('/action',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
 body:new URLSearchParams({{type:'pointer',x:x,y:y}})}});
 location.reload();
}});
</script></html>'''
        return page.encode("utf-8")

    def action(self, data: dict[str,list[str]]):
        self.error = ""
        try:
            kind = data.get("type", [""])[0]
            if kind == "key":
                code = int(data.get("code", [""])[0])
                if code not in (-1, -2, -7, -6, 35, 49, 51, 55, 57):
                    raise UIVMError("key not in OS preview whitelist")
                self.ui.key(code)
            elif kind == "pointer":
                x, y = int(data.get("x", [""])[0]), int(data.get("y", [""])[0])
                if not 0 <= x < 320 or not 0 <= y < 240:
                    raise UIVMError("pointer outside E63 screen")
                self.ui.pointer(x, y)
            elif kind == "form":
                self.ui.form_action(data.get("text", [""])[0],
                                    data.get("accept", ["0"])[0] == "1")
            else: raise UIVMError("unrecognized OS input")
        except (UIVMError, NativeError, ValueError, IndexError) as exc:
            self.error = str(exc)


def serve(port: int, state: Path):
    app = OSPreview(state)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?", 1)[0] not in ("/", "/screen.png"):
                self.send_error(404); return
            with app.lock:
                try:
                    app.advance()
                    if self.path.startswith("/screen.png"):
                        data, mime = app.ui.png(), "image/png"
                    else:
                        data, mime = app.html(), "text/html; charset=utf-8"
                except (UIVMError, NativeError) as ex:
                    app.error = str(ex)
                    self.send_error(500, "guest UI failed"); return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/action": self.send_error(404); return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096: raise ValueError("invalid input length")
                data = parse_qs(self.rfile.read(size).decode("utf-8"),
                                keep_blank_values=True)
                with app.lock: app.action(data)
            except (ValueError, UnicodeError) as ex:
                self.send_error(400, str(ex)); return
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
