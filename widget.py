import sys, json, asyncio, threading, time
from pathlib import Path

CFG_PATH = Path(__file__).with_name("config.json")
THEMES = {
    "midnight": dict(bg1="#1b1d3d", bg2="#0b0c1e", accent="#6d7cff"),
    "neon":     dict(bg1="#1a0a2e", bg2="#07030f", accent="#ff4fd8"),
    "sunset":   dict(bg1="#3a1c2e", bg2="#120a14", accent="#ff8a4c"),
    "mono":     dict(bg1="#222222", bg2="#0a0a0a", accent="#ffffff"),
}

def load_cfg():
    try: return json.loads(CFG_PATH.read_text())
    except Exception: return {}

def cli():
    a = sys.argv[1:]
    if not a: return False
    cfg = load_cfg()
    if a[0] == "theme" and len(a) > 1 and a[1] in THEMES: cfg.update(THEMES[a[1]])
    elif a[0] == "set":
        for kv in a[1:]:
            k, v = kv.split("=", 1)
            try: v = json.loads(v)
            except Exception: pass
            cfg[k] = v
    else:
        print("usage: widget.py theme <name> | set key=value ..."); return True
    CFG_PATH.write_text(json.dumps(cfg, indent=2)); print("Saved."); return True

if cli(): sys.exit()

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRectF, QPointF
from PySide6.QtGui import (QPainter, QColor, QLinearGradient, QPainterPath, QPixmap,
                           QFont, QPen, QFontMetrics, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget, QMenu
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as Mgr,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PS)
from winsdk.windows.storage.streams import Buffer, InputStreamOptions


class Media(QObject):
    updated = Signal(dict)
    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop(); self.session = None
        self.key = None; self.art = None
        threading.Thread(target=self._run, daemon=True).start()
    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._poll()); self.loop.run_forever()
    async def _thumb(self, props):
        try:
            s = await props.thumbnail.open_read_async()
            b = Buffer(s.size)
            await s.read_async(b, s.size, InputStreamOptions.READ_AHEAD)
            return bytes(memoryview(b))
        except Exception: return None
    async def _poll(self):
        mgr = await Mgr.request_async()
        while True:
            try:
                s = mgr.get_current_session(); self.session = s
                if not s: self.updated.emit({"none": True})
                else:
                    p = await s.try_get_media_properties_async()
                    tl = s.get_timeline_properties()
                    k = (p.title, p.artist)
                    if k != self.key: self.key = k; self.art = await self._thumb(p)
                    self.updated.emit(dict(
                        title=p.title, artist=p.artist, album=p.album_title, art=self.art,
                        pos=tl.position.total_seconds(), dur=tl.end_time.total_seconds(),
                        playing=s.get_playback_info().playback_status == PS.PLAYING,
                        src=s.source_app_user_model_id.replace(".exe", "").split("!")[0]))
            except Exception as e: print(e)
            await asyncio.sleep(0.5)
    def do(self, name, *a):
        if self.session:
            asyncio.run_coroutine_threadsafe(getattr(self.session, name)(*a), self.loop)


def fmt(t):
    t = max(0, int(t)); return f"{t // 60}:{t % 60:02d}"


class Widget(QWidget):
    def __init__(self):
        super().__init__()
        self.media = Media(); self.media.updated.connect(self.on_media)
        self.st = {"none": True}; self.t0 = time.monotonic(); self.pix = None
        self.hover = None; self.hv = {}; self.mtime = 0
        self.setMouseTracking(True)
        self.reload(); self.show()
        t = QTimer(self); t.timeout.connect(self.tick); t.start(16)

    def reload(self):
        c = dict(width=440, height=200, radius=34, opacity=235, bg1="#1b1d3d", bg2="#0b0c1e",
                 accent="#6d7cff", text="#ffffff", subtext="#a9adc9", glow=1.0,
                 always_on_top=True, hide_from_taskbar=True, x=None, y=None)
        c.update(load_cfg()); self.c = c
        f = Qt.FramelessWindowHint
        if c["always_on_top"]: f |= Qt.WindowStaysOnTopHint
        if c["hide_from_taskbar"]: f |= Qt.Tool
        vis = self.isVisible()
        self.setWindowFlags(f); self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(c["width"], c["height"])
        g = QApplication.primaryScreen().availableGeometry()
        self.move(c["x"] if c["x"] is not None else g.center().x() - c["width"] // 2,
                  c["y"] if c["y"] is not None else g.bottom() - c["height"] - 12)
        if vis: self.show()
        try: self.mtime = CFG_PATH.stat().st_mtime
        except Exception: pass

    def on_media(self, d):
        if not d.get("none") and d["art"] != self.st.get("art"):
            self.pix = QPixmap(); self.pix.loadFromData(d["art"]) if d["art"] else None
        self.st = d; self.t0 = time.monotonic(); self.base = d.get("pos", 0)

    def pos_now(self):
        s = self.st
        if s.get("none"): return 0
        p = self.base + (time.monotonic() - self.t0 if s["playing"] else 0)
        return min(p, s["dur"]) if s["dur"] else 0

    def tick(self):
        for k in ("prev", "play", "next", "bar"):
            tgt = 1.0 if self.hover == k else 0.0
            self.hv[k] = self.hv.get(k, 0) + (tgt - self.hv.get(k, 0)) * 0.2
        if int(time.monotonic() * 2) % 2 == 0:
            try:
                m = CFG_PATH.stat().st_mtime
                if m != self.mtime: self.reload()
            except Exception: pass
        self.update()

    def rects(self):
        w, h = self.width(), self.height()
        return {"art": QRectF(22, 22, 92, 92),
                "bar": QRectF(74, h - 70, w - 148, 14),
                "prev": QRectF(w / 2 - 92, h - 52, 40, 40),
                "play": QRectF(w / 2 - 28, h - 60, 56, 56),
                "next": QRectF(w / 2 + 52, h - 52, 40, 40)}

    def paintEvent(self, _):
        c = self.c; p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        acc = QColor(c["accent"]); R = self.rects(); s = self.st
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath(); path.addRoundedRect(r, c["radius"], c["radius"])
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        b1, b2 = QColor(c["bg1"]), QColor(c["bg2"]); b1.setAlpha(c["opacity"]); b2.setAlpha(c["opacity"])
        g.setColorAt(0, b1); g.setColorAt(1, b2); p.fillPath(path, g)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1.2)); p.drawPath(path)

        # art
        ar = R["art"]; ap = QPainterPath(); ap.addRoundedRect(ar, 16, 16)
        p.save(); p.setClipPath(ap)
        if self.pix and not self.pix.isNull():
            p.drawPixmap(ar.toRect(), self.pix.scaled(ar.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            ag = QLinearGradient(ar.topLeft(), ar.bottomRight()); ag.setColorAt(0, acc); ag.setColorAt(1, QColor(c["bg2"])); p.fillPath(ap, ag)
        p.restore()

        # text
        tx = 134; tw = self.width() - tx - 24
        def txt(y, size, col, s_, bold=False):
            f = QFont("Segoe UI", size); f.setBold(bold); p.setFont(f); p.setPen(QColor(col))
            p.drawText(tx, y, QFontMetrics(f).elidedText(s_, Qt.ElideRight, tw))
        if s.get("none"):
            txt(62, 13, c["text"], "Nothing playing", True); txt(86, 10, c["subtext"], "Start some music")
        else:
            txt(50, 14, c["text"], s["title"], True); txt(72, 10, c["subtext"], s["artist"])
            txt(92, 9, c["subtext"], s["album"]); txt(112, 9, c["subtext"], "Playing from " + s["src"].title())

        # progress bar
        bar = R["bar"]; hv = self.hv.get("bar", 0); dur = s.get("dur", 0) or 1
        frac = min(1, self.pos_now() / dur); cy = bar.center().y(); th = 5 + 2 * hv
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 28))
        p.drawRoundedRect(QRectF(bar.left(), cy - th / 2, bar.width(), th), th / 2, th / 2)
        fw = bar.width() * frac; fg = QLinearGradient(bar.left(), 0, bar.left() + max(fw, 1), 0)
        fg.setColorAt(0, acc.darker(130)); fg.setColorAt(1, acc.lighter(130)); p.setBrush(fg)
        p.drawRoundedRect(QRectF(bar.left(), cy - th / 2, fw, th), th / 2, th / 2)
        kx = bar.left() + fw; rad = (14 + 8 * hv) * c["glow"]
        rg = QRadialGradient(QPointF(kx, cy), rad); gc = QColor(acc); gc.setAlpha(120); rg.setColorAt(0, gc); gc.setAlpha(0); rg.setColorAt(1, gc)
        p.setBrush(rg); p.drawEllipse(QPointF(kx, cy), rad, rad)
        p.setBrush(QColor("white")); p.drawEllipse(QPointF(kx, cy), 5 + hv, 5 + hv)
        f = QFont("Segoe UI", 8); p.setFont(f); p.setPen(QColor(c["subtext"]))
        p.drawText(QRectF(18, cy - 10, 52, 20), Qt.AlignLeft | Qt.AlignVCenter, fmt(self.pos_now()))
        p.drawText(QRectF(self.width() - 70, cy - 10, 52, 20), Qt.AlignRight | Qt.AlignVCenter, "-" + fmt(dur - self.pos_now()))

        # buttons
        for k in ("prev", "play", "next"):
            rc = R[k]; h = self.hv.get(k, 0); ctr = rc.center()
            big = k == "play"
            if h > 0.01:
                rg = QRadialGradient(ctr, rc.width() * 0.95); gc = QColor(acc); gc.setAlpha(int(110 * h * c["glow"]))
                rg.setColorAt(0.5, gc); gc.setAlpha(0); rg.setColorAt(1, gc); p.setPen(Qt.NoPen); p.setBrush(rg); p.drawEllipse(ctr, rc.width() * 0.95, rc.width() * 0.95)
            bg = QColor(acc); bg.setAlpha(int((60 if big else 40) + 70 * h)); p.setPen(Qt.NoPen); p.setBrush(bg)
            rr = rc.width() / 2 * (1 + 0.05 * h); p.drawEllipse(ctr, rr, rr)
            p.setBrush(acc.lighter(140)); p.setPen(Qt.NoPen); x, y = ctr.x(), ctr.y()
            if k == "play":
                if s.get("playing"):
                    p.drawRoundedRect(QRectF(x - 8, y - 9, 5.5, 18), 2, 2); p.drawRoundedRect(QRectF(x + 2.5, y - 9, 5.5, 18), 2, 2)
                else:
                    t = QPainterPath(); t.moveTo(x - 6, y - 10); t.lineTo(x + 10, y); t.lineTo(x - 6, y + 10); t.closeSubpath(); p.drawPath(t)
            else:
                d = 1 if k == "next" else -1; t = QPainterPath()
                for o in (-7, 3):
                    t.moveTo(x + d * (o - 3), y - 7); t.lineTo(x + d * (o + 7), y); t.lineTo(x + d * (o - 3), y + 7); t.closeSubpath()
                p.drawPath(t)

    def hit(self, pt):
        for k in ("play", "prev", "next", "bar"):
            rc = self.rects()[k]
            if (rc.adjusted(-6, -10, 6, 10) if k == "bar" else rc).contains(pt): return k

    def mouseMoveEvent(self, e):
        self.hover = self.hit(e.position()); self.setCursor(Qt.PointingHandCursor if self.hover else Qt.ArrowCursor)
    def leaveEvent(self, _): self.hover = None
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton: return
        k = self.hit(e.position())
        if k == "play": self.media.do("try_toggle_play_pause_async")
        elif k == "next": self.media.do("try_skip_next_async")
        elif k == "prev": self.media.do("try_skip_previous_async")
        elif k == "bar" and self.st.get("dur"):
            bar = self.rects()["bar"]; f = min(1, max(0, (e.position().x() - bar.left()) / bar.width()))
            self.media.do("try_change_playback_position_async", int(f * self.st["dur"] * 1e7))
            self.base = f * self.st["dur"]; self.t0 = time.monotonic()
        else: self.windowHandle().startSystemMove()
    def contextMenuEvent(self, e):
        m = QMenu(self); m.addAction("Reload config", self.reload); m.addAction("Quit", QApplication.quit); m.exec(e.globalPos())


if __name__ == "__main__":
    app = QApplication(sys.argv); w = Widget(); sys.exit(app.exec())
