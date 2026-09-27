"""Small MIDP/CLDC host service table for ORIGINAL converted E63Canvas DEX.

The Java ME bytecode decides which calls to make, all coordinates, screen
selection, text, assets and navigation. This module supplies only primitives
(Graphics, Font, Image, Canvas, Display, RMS, a clock), not app screens.
It is a PC-host prototype, NOT an emulation of every MIDP/Symbian API.
"""
from __future__ import annotations

import io
import json
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class NativeError(RuntimeError):
    pass


class DeviceIOException(NativeError):
    """An expected device I/O failure that guest DEX may catch."""


class YieldFrame(Exception):
    """Suspend a guest ticker at MIDP Thread.sleep; resume next host tick."""


@dataclass(eq=False)
class JObject:
    desc: str
    fields: dict = field(default_factory=dict)


def truth(value):
    return value is not None and value != 0


class MIDPHost:
    def __init__(self, apk: Path, state: Path, width=320, height=240):
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.width, self.height = width, height
        self.images: dict[str, bytes] = {}
        with zipfile.ZipFile(apk) as z:
            for name in z.namelist():
                if name.startswith("assets/j2me/") and name.count("/") == 2:
                    self.images["/" + name.rsplit("/", 1)[1]] = z.read(name)
        self.display = JObject("Ljavax/microedition/lcdui/Display;")
        self.current: JObject | None = None
        self.repaint_requested = False
        self.current_graphics: JObject | None = None
        self.now_ms = int(time.time() * 1000)
        self.quit = False
        self.yield_on_sleep = False
        self.pending_threads: list[JObject] = []
        self.draw_calls: list[tuple] = []
        self.rms_path = self.state / "c_drive/private/e63os/rms/j2me_rms.json"
        self.rms_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_rms = self.state / "j2me_rms.json"
        if legacy_rms.is_file() and not self.rms_path.exists():
            shutil.move(str(legacy_rms), str(self.rms_path))
        self.rms: dict[str, list[int]] = (json.loads(self.rms_path.read_text())
                                          if self.rms_path.is_file() else {})
        self.font_cache: dict[int, ImageFont.FreeTypeFont] = {}

    def sync_install_flag(self, installed: bool) -> None:
        """The authoritative OS package state wins over a stale J2ME RMS bit."""
        key = "J2ME_E63_demo"
        value = list(self.rms.get(key, [0, 0, 0, 0]))
        value += [0] * max(0, 4 - len(value))
        value[0] = int(installed)
        self.rms[key] = value
        tmp = self.rms_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.rms), encoding="utf-8")
        tmp.replace(self.rms_path)

    def font(self, size: int):
        point = {8: 11, 0: 13, 16: 17}.get(size, 13)
        if point not in self.font_cache:
            try: self.font_cache[point] = ImageFont.truetype("DejaVuSans.ttf", point)
            except OSError: self.font_cache[point] = ImageFont.load_default()
        return self.font_cache[point]

    def new_canvas(self) -> JObject:
        return JObject("Ljavax/microedition/lcdui/Graphics;", {
            "surface": Image.new("RGBA", (self.width, self.height), (0, 0, 0, 255)),
            "color": (255, 255, 255, 255), "font": 0, "clip": (0, 0, self.width, self.height)})

    def png(self, vm, canvas: JObject) -> bytes:
        self.draw_calls = []
        graphics = self.new_canvas()
        self.current_graphics = graphics
        try:
            vm.run("Landroid/j2me/edition/E63Canvas;->paint(Ljavax/microedition/lcdui/Graphics;)V",
                   [canvas, graphics])
            buf = io.BytesIO()
            graphics.fields["surface"].convert("RGB").save(buf, "PNG")
            self.repaint_requested = False
            return buf.getvalue()
        finally:
            self.current_graphics = None

    def _graphics(self, obj, name):
        if not isinstance(obj, JObject) or obj.desc != "Ljavax/microedition/lcdui/Graphics;":
            raise NativeError("invalid Graphics receiver: " + name)
        return obj.fields, ImageDraw.Draw(obj.fields["surface"])

    @staticmethod
    def _rgb(value):
        return ((value >> 16) & 255, (value >> 8) & 255, value & 255, 255)

    def _draw(self, name: str, args: list):
        props, draw = self._graphics(args[0], name)
        self.draw_calls.append((name, *args[1:]))
        if len(self.draw_calls) > 4000: raise NativeError("graphics call budget exceeded")
        if name == "setClip":
            props["clip"] = tuple(map(int, args[1:5]))
        elif name == "setColor":
            if len(args) == 2: props["color"] = self._rgb(int(args[1]))
            else: props["color"] = (int(args[1]), int(args[2]), int(args[3]), 255)
        elif name == "setFont":
            props["font"] = args[1].fields["size"]
        elif name == "fillRect":
            x, y, w, h = map(int, args[1:5])
            if w > 0 and h > 0: draw.rectangle((x, y, x+w-1, y+h-1), fill=props["color"])
        elif name == "drawRect":
            x, y, w, h = map(int, args[1:5])
            if w >= 0 and h >= 0: draw.rectangle((x, y, x+w, y+h), outline=props["color"])
        elif name == "drawArc":
            x, y, w, h, start, sweep = map(int, args[1:7])
            # This MIDP subset supports precisely the full circular search
            # lens requested by the guest; reject partial arcs, don't draw a
            # misleading square or silently invent different arc semantics.
            if w <= 0 or h <= 0 or start != 0 or sweep != 360:
                raise NativeError("unsupported MIDP arc geometry")
            draw.ellipse((x, y, x+w-1, y+h-1), outline=props["color"])
        elif name == "drawLine":
            draw.line(tuple(map(int, args[1:5])), fill=props["color"])
        elif name == "drawString":
            value, x, y, anchor = args[1:5]
            f = self.font(props["font"])
            x, y = int(x), int(y)
            if anchor & 1: x -= int(f.getlength(str(value))) // 2  # HCENTER
            elif anchor & 8: x -= int(f.getlength(str(value)))  # RIGHT
            if anchor & 2: y -= f.size // 2  # VCENTER
            elif anchor & 32: y -= f.size  # BOTTOM
            draw.text((x, y), str(value), font=f, fill=props["color"], anchor="lt")
        elif name == "drawImage":
            image, x, y, anchor = args[1:5]
            if not isinstance(image, JObject) or image.desc != "Ljavax/microedition/lcdui/Image;":
                raise NativeError("bad MIDP image")
            pic = image.fields["image"]
            x, y = int(x), int(y)
            if anchor & 1: x -= pic.width // 2
            elif anchor & 8: x -= pic.width
            if anchor & 2: y -= pic.height // 2
            elif anchor & 32: y -= pic.height
            props["surface"].paste(pic, (x, y), pic)
        else:
            raise NativeError("unsupported graphics operation " + name)

    def call(self, ref: str, args: list):
        # Constructors of host-class objects that have no app-specific logic.
        owner, method = ref.split("->", 1)
        name = method.split("(", 1)[0]
        if name == "<init>" and owner in ("Ljava/lang/Object;", "Ljava/lang/Thread;",
                                         "Ljavax/microedition/midlet/MIDlet;",
                                         "Ljavax/microedition/lcdui/Canvas;"):
            if owner == "Ljava/lang/Thread;": args[0].fields["runnable"] = args[1]
            return None
        if owner == "Ljava/lang/System;":
            if name == "currentTimeMillis": return self.now_ms
            if name == "getProperty": return None  # no fabricated Nokia battery / platform
        if owner == "Ljava/lang/Thread;":
            if name == "start":
                runnable = args[0].fields.get("runnable")
                if isinstance(runnable, JObject) and runnable.desc != "Landroid/j2me/edition/E63Midlet$1;":
                    self.pending_threads.append(runnable)
                return None  # original ticker is advanced explicitly by OS host
            if name == "interrupt": return None
            if name == "sleep":
                if self.yield_on_sleep: raise YieldFrame()
                return None
        if owner in ("Ljava/io/IOException;", "Ljava/lang/Exception;",
                     "Ljava/lang/IllegalArgumentException;", "Ljava/lang/Throwable;"):
            if name=="<init>":args[0].fields["message"]=args[1] if len(args)>1 else "";return None
        if owner == "Ljava/lang/Object;" and name == "getClass":
            return JObject("Ljava/lang/Class;",{"name":args[0].desc[1:-1].replace("/",".")})
        if owner == "Ljava/lang/Class;" and name == "getName":return args[0].fields["name"]
        if owner == "Ljava/lang/Character;" and name == "toLowerCase":
            return ord(chr(int(args[0])).lower())
        if owner == "Ljava/lang/Integer;":
            if name == "parseInt": return int(args[0])
            if name == "toString": return str(args[0])
        if owner == "Ljava/lang/String;":
            if name == "<init>":
                if len(args) == 4 and isinstance(args[1], list):
                    payload=bytes(int(b)&255 for b in args[1][int(args[2]):int(args[2])+int(args[3])])
                    args[0].fields["value"] = payload.decode("utf-8")
                    return None
                raise NativeError("unsupported String constructor")
            s = args[0].fields["value"] if isinstance(args[0],JObject) else args[0]
            if name == "length": return len(s)
            if name == "charAt": return ord(s[int(args[1])])
            if name == "equals":
                other=args[1].fields["value"] if isinstance(args[1],JObject) and "value" in args[1].fields else args[1]
                return int(s == other)
            if name == "equalsIgnoreCase": return int(str(s).lower() == str(args[1]).lower())
            if name == "trim": return s.strip()
            if name == "toLowerCase": return s.lower()
            if name == "toUpperCase": return s.upper()
            if name == "endsWith": return int(s.endswith(args[1]))
            if name == "startsWith": return int(s.startswith(args[1]))
            if name == "indexOf":
                sub = args[1] if isinstance(args[1], str) else chr(args[1])
                return s.find(sub)
            if name == "substring": return s[int(args[1]):int(args[2])] if len(args)>2 else s[int(args[1]):]
            if name == "getBytes": return list(s.encode("utf-8"))
            if name == "valueOf": return str(args[0])
        if owner == "Ljava/lang/StringBuffer;":
            if name == "<init>":
                args[0].fields["text"] = str(args[1]) if len(args)>1 else ""
                return None
            if name == "append":
                val = args[1]
                args[0].fields["text"] += str(val) if val is not None else "null"
                return args[0]
            if name == "toString": return args[0].fields.get("text", "")
        if owner == "Ljava/lang/StringBuilder;":
            if name == "<init>": args[0].fields["text"] = ""; return None
            if name == "append": args[0].fields["text"] += str(args[1]); return args[0]
            if name == "toString": return args[0].fields["text"]
        if owner == "Ljava/util/Calendar;":
            if name == "getInstance": return JObject(owner, {"time": datetime.fromtimestamp(self.now_ms/1000)})
            if name == "get":
                stamp = args[0].fields["time"]
                return {11: stamp.hour, 12: stamp.minute}.get(args[1], 0)
        if owner == "Ljavax/microedition/lcdui/Display;":
            if name == "getDisplay": return self.display
            if name == "setCurrent":
                self.current = args[1]
                self.repaint_requested = True
                return None
            if name == "callSerially":
                self.pending_threads.append(args[1])  # execute guest Runnable.run on UI pump
                return None
        if owner == "Ljavax/microedition/lcdui/Canvas;":
            if name == "setFullScreenMode": return None
            if name == "getWidth": return self.width
            if name == "getHeight": return self.height
            if name == "repaint": self.repaint_requested = True; return None
            if name == "getGameAction":
                actions = {-1: 1, -2: 6, -3: 2, -4: 5, -5: 8}
                return actions.get(args[1], 0)
            if name == "getKeyName":
                return {-6:"SOFT1",-7:"SOFT2",-5:"SELECT"}.get(args[1], "KEY")
        if owner == "Ljavax/microedition/lcdui/Font;":
            if name == "getFont": return JObject(owner, {"size": args[2]})
            if name == "getHeight": return self.font(args[0].fields["size"]).size + 1
            if name == "stringWidth": return int(self.font(args[0].fields["size"]).getlength(args[1]))
        if owner == "Ljavax/microedition/lcdui/Image;":
            if name == "createImage":
                data = self.images.get(args[0])
                if data is None: raise DeviceIOException("missing APK image " + str(args[0]))
                pic = Image.open(io.BytesIO(data)).convert("RGBA")
                return JObject(owner, {"image": pic})
            if name == "getWidth": return args[0].fields["image"].width
            if name == "getHeight": return args[0].fields["image"].height
        if owner == "Ljavax/microedition/lcdui/Graphics;":
            self._draw(name, args)
            return None
        if owner == "Ljavax/microedition/midlet/MIDlet;" and name == "notifyDestroyed":
            self.quit = True
            return None
        if owner == "Ljavax/microedition/io/Connector;" and name == "open":
            import socket
            if args != ["socket://127.0.0.1:27463", 3, 1]:
                raise NativeError("network access outside local SIS bridge denied")
            try:
                sock=socket.create_connection(("127.0.0.1",27463),timeout=2)
            except OSError as ex:
                raise DeviceIOException("SIS bridge unavailable on device loopback") from ex
            return JObject("Ljavax/microedition/io/SocketConnection;", {"socket":sock})
        if owner in ("Ljavax/microedition/io/OutputConnection;",
                     "Ljavax/microedition/io/InputConnection;"):
            if name == "openOutputStream":
                return JObject("Ljava/io/OutputStream;", {"socket":args[0].fields["socket"]})
            if name == "openInputStream":
                return JObject("Ljava/io/InputStream;", {"socket":args[0].fields["socket"]})
        if owner == "Ljava/io/OutputStream;":
            if name == "write":
                value=args[1]
                if not isinstance(value,list) or len(value)>512:
                    raise NativeError("invalid SIS bridge output frame")
                try: args[0].fields["socket"].sendall(bytes(int(b)&255 for b in value))
                except OSError as ex: raise DeviceIOException("SIS bridge write failed") from ex
                return None
            if name in ("flush","close"):return None
        if owner == "Ljava/io/InputStream;":
            if name == "read":
                try: byte=args[0].fields["socket"].recv(1)
                except OSError as ex: raise DeviceIOException("SIS bridge read timed out") from ex
                return byte[0] if byte else -1
            if name == "close":return None
        if owner == "Ljavax/microedition/io/Connection;" and name == "close":
            args[0].fields["socket"].close()
            return None
        if owner == "Ljavax/microedition/rms/RecordStore;": 
            if name == "openRecordStore": return JObject(owner, {"key": args[0]})
            if name == "getNumRecords": return int(args[0].fields["key"] in self.rms)
            if name == "getRecord": return list(self.rms[args[0].fields["key"]])
            if name in ("addRecord", "setRecord"):
                data, start, count = args[-3:]
                self.rms[args[0].fields["key"]] = [int(b)&255 for b in data[start:start+count]]
                self.rms_path.write_text(json.dumps(self.rms))
                return 1 if name == "addRecord" else None
            if name == "closeRecordStore": return None
        if owner == "Ljavax/microedition/lcdui/Command;":
            if name == "<init>": args[0].fields.update(label=args[1], type=args[2], priority=args[3]); return None
        if owner == "Ljavax/microedition/lcdui/Form;":
            if name == "<init>": args[0].fields.update(title=args[1], items=[], commands=[]); return None
            if name == "append": args[0].fields["items"].append(args[1]); return len(args[0].fields["items"])-1
        if owner == "Ljavax/microedition/lcdui/TextField;":
            if name == "<init>":
                args[0].fields.update(label=args[1], text=args[2], max=args[3], constraints=args[4]); return None
            if name == "setString": args[0].fields["text"] = args[1]; return None
            if name == "getString": return args[0].fields["text"]
            if name == "size": return len(args[0].fields["text"])
        if owner == "Ljavax/microedition/lcdui/StringItem;":
            if name == "<init>": args[0].fields.update(label=args[1], text=args[2]); return None
            if name == "setText": args[0].fields["text"] = args[1]; return None
        if owner == "Ljavax/microedition/lcdui/Displayable;":
            if name == "getWidth": return self.width
            if name == "getHeight": return self.height
            if name == "addCommand": args[0].fields.setdefault("commands", []).append(args[1]); return None
            if name == "setCommandListener": args[0].fields["listener"] = args[1]; return None
        raise NativeError("unsupported MIDP/native method " + ref)
