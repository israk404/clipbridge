"""Renders the screenshots in docs/screenshots with realistic demo data (runs offscreen, no display needed).

    python windows/tests/make_screenshots.py
"""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cbshots")
OUT = os.path.join(os.path.dirname(ROOT), "docs", "screenshots")
os.makedirs(OUT, exist_ok=True)

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QApplication

from clipbridge import app as appmod, media, theme
from fake_phone import FakePhone


def landscape(w=1280, h=800) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    sky = QLinearGradient(0, 0, 0, h)
    sky.setColorAt(0, QColor("#1E3A8A"))
    sky.setColorAt(0.55, QColor("#F97316"))
    sky.setColorAt(1, QColor("#FDE68A"))
    p.fillRect(0, 0, w, h, sky)
    sun = QRadialGradient(QPointF(w * 0.68, h * 0.55), h * 0.18)
    sun.setColorAt(0, QColor("#FFF7D6"))
    sun.setColorAt(1, QColor(255, 247, 214, 0))
    p.setBrush(sun)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(w * 0.68, h * 0.55), h * 0.18, h * 0.18)
    for color, base, peaks in (("#7C2D12", 0.72, [(0, .62), (.18, .45), (.35, .6), (.52, .40), (.7, .58), (.88, .47), (1, .6)]),
                               ("#431407", 0.85, [(0, .78), (.2, .64), (.42, .76), (.6, .62), (.8, .74), (1, .66)])):
        path = QPainterPath(QPointF(0, h))
        for x, y in peaks:
            path.lineTo(QPointF(x * w, y * h))
        path.lineTo(QPointF(w, h))
        path.closeSubpath()
        p.setBrush(QColor(color))
        p.drawPath(path)
    p.end()
    return img


def product_card(w=900, h=900) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg = QLinearGradient(0, 0, w, h)
    bg.setColorAt(0, QColor("#ECFDF5"))
    bg.setColorAt(1, QColor("#A7F3D0"))
    p.fillRect(0, 0, w, h, bg)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#065F46"))
    p.drawRoundedRect(QRectF(w * .38, h * .18, w * .24, h * .62), 40, 40)
    p.setBrush(QColor("#10B981"))
    p.drawRoundedRect(QRectF(w * .42, h * .10, w * .16, h * .1), 14, 14)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(QRectF(w * .40, h * .42, w * .20, h * .16), 10, 10)
    leaf = QPainterPath(QPointF(w * .5, h * .44))
    leaf.cubicTo(QPointF(w * .56, h * .45), QPointF(w * .56, h * .53), QPointF(w * .5, h * .56))
    leaf.cubicTo(QPointF(w * .44, h * .53), QPointF(w * .44, h * .45), QPointF(w * .5, h * .44))
    p.setBrush(QColor("#10B981"))
    p.drawPath(leaf)
    p.end()
    return img


class Invoker(QObject):
    call = Signal(object)


qapp = QApplication(sys.argv)
qapp.setStyle("Fusion")
qapp.setQuitOnLastWindowClosed(False)
inv = Invoker()
inv.call.connect(lambda f: f(), Qt.ConnectionType.QueuedConnection)


def on_main(fn):
    done, box = threading.Event(), {}

    def run():
        box["v"] = fn()
        done.set()

    inv.call.emit(run)
    done.wait(10)
    return box.get("v")


ctl = appmod.Controller(qapp, start_hidden=False)


def shot(widget, name):
    on_main(lambda: widget.grab().save(os.path.join(OUT, name)))
    print("saved", name)


def scenario():
    try:
        time.sleep(1)
        save_dir = tempfile.mkdtemp(prefix="cbsave")
        on_main(lambda: ctl.cfg.set("save_dir", save_dir))
        shot(ctl._pair_dialog, "pc-pair-dialog.png")
        on_main(lambda: ctl._pair_dialog.hide())
        ph = FakePhone(ctl.cfg.key, ctl.cfg["port"], "Galaxy A54")
        ph.start()
        ph.expect("state")
        time.sleep(0.3)
        on_main(lambda: ctl.clipboard.setText("Order #4471 — 2× Neem face wash, ship to Mirpur 10, Dhaka"))
        time.sleep(0.4)
        on_main(lambda: ctl.clipboard.setImage(product_card()))
        time.sleep(0.6)
        ph.send({"t": "send", "text": "https://leafas.example/products/neem-face-wash"})
        time.sleep(0.3)
        land = on_main(lambda: media.to_png(landscape()))
        ph.send_file(land, "clip.png", "image/png", kind="clip_image", purpose="send")
        time.sleep(0.8)
        shot(ctl.toast, "pc-image-popup.png")
        ph.send({"t": "phone_clip", "text": "bKash TrxID 9XK2A77Q · ৳1,250 received"})
        photo = os.path.join(tempfile.mkdtemp(), "IMG_20261106_0912.jpg")
        on_main(lambda: landscape(1600, 1000).save(photo, "JPEG", 85))
        ph.send_file(open(photo, "rb").read(), "IMG_20261106_0912.jpg", "image/jpeg")
        ph.expect("file_ack", 10)
        pdf = os.path.join(save_dir, "Invoice-4471.pdf")
        open(pdf, "wb").write(os.urandom(480_000))
        on_main(lambda: ctl.send_paths([pdf]))
        offer, _data, _done = ph.receive_file()
        ph.send({"t": "file_ack", "id": offer["id"], "ok": True})
        time.sleep(0.6)
        ph.send({"t": "send", "text": "Meeting moved to 4:30 PM — bring the sample box."})
        time.sleep(0.5)
        shot(ctl.toast, "pc-text-popup.png")
        on_main(lambda: ctl.toast.hide())
        on_main(lambda: ctl.window.resize(480, 1180))
        time.sleep(0.4)
        shot(ctl.window, "pc-window-light.png")
        theme.is_dark = lambda: True
        on_main(ctl.apply_theme)
        on_main(ctl.window.refresh)
        time.sleep(0.4)
        shot(ctl.window, "pc-window-dark.png")
        # pairing request dialog
        from clipbridge.ui import PairRequestDialog
        dlg = on_main(lambda: PairRequestDialog(None, "Galaxy A54", "482193"))
        on_main(dlg.show)
        time.sleep(0.3)
        shot(dlg, "pc-pair-request.png")
    finally:
        on_main(ctl.quit)


threading.Thread(target=scenario, daemon=True).start()
qapp.exec()
