"""End-to-end test: real PC app (offscreen) + simulated phone over TCP/UDP. Saves screenshots."""
import os, sys, tempfile, threading, time, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cbtest")
SHOTS = os.environ.get("SHOTS", "/tmp/shots"); os.makedirs(SHOTS, exist_ok=True)

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QApplication
from clipbridge import app as appmod, theme, protocol as P
from fake_phone import FakePhone, discover

class Invoker(QObject):
    call = Signal(object)
inv = Invoker()
inv.call.connect(lambda f: f(), Qt.ConnectionType.QueuedConnection)

def on_main(fn, wait=True):
    done = threading.Event(); box = {}
    def run():
        try: box["v"] = fn()
        except Exception as e: box["e"] = e
        done.set()
    inv.call.emit(run)
    if wait:
        done.wait(5)
        if "e" in box: raise box["e"]
        return box.get("v")

qapp = QApplication(sys.argv); qapp.setStyle("Fusion"); qapp.setQuitOnLastWindowClosed(False)
ctl = appmod.Controller(qapp, start_hidden=False)
results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond), detail)); print(("PASS " if cond else "FAIL ") + name, detail, flush=True)

def shot(widget, name):
    on_main(lambda: widget.grab().save(os.path.join(SHOTS, name)))

PH = []
def ph_drain():
    for p in PH: p.drain()

def scenario():
    try:
        time.sleep(1.0)
        key, port = ctl.cfg.key, ctl.cfg["port"]
        ph_drain(); on_main(lambda: ctl.clipboard.setText("Order #4471 — ship to Mirpur 10, Dhaka"))
        time.sleep(0.4)
        shot(ctl._pair_dialog, "pair_dialog.png")
        ph = FakePhone(key, port, "Galaxy A54"); PH.append(ph); ph.start()
        st = ph.expect("state")
        check("state received", st.get("pc_name") == ctl.name and st["pc_clip"]["text"].startswith("Order"), st["pc_clip"])
        time.sleep(0.3)
        check("pair dialog shows success", "connected" in on_main(lambda: ctl._pair_dialog.status.text()))
        # code pairing: a real ECDH exchange with an auto-clicked Allow
        import socket, struct
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        priv = ec.generate_private_key(ec.SECP256R1())
        pub = priv.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(P.PAIR_MAGIC + struct.pack(">H", len(pub)) + pub + bytes([5]) + b"Pixel")
        hdr = s.recv(6); n = struct.unpack(">H", hdr[4:6])[0]; pc_pub = b""
        while len(pc_pub) < n: pc_pub += s.recv(n - len(pc_pub))
        shared = priv.exchange(ec.ECDH(), serialization.load_der_public_key(pc_pub))
        kenc, code = P.pair_derive(shared, pub, pc_pub)
        time.sleep(0.4)
        dlg = on_main(lambda: next(iter(ctl._pair_requests.values())))
        shot(dlg, "pair_request.png")
        on_main(dlg.accept)
        body = b""
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            body += chunk
        ans = P.pair_open(kenc, body[4:])
        check("Allow sends the pairing key", ans["ok"] and P.unb64u(ans["k"]) == key, list(ans))
        on_main(lambda: ctl._pair_dialog.hide())

        ph_drain(); on_main(lambda: ctl.clipboard.setText("https://leafas.example/products/neem-face-wash-100ml?ref=whatsapp"))
        m = ph.expect("pc_clip")
        check("pc copy reaches phone (auto off)", m["item"]["text"].startswith("https://leafas") and m["auto"] is False)

        ph.send({"t": "set", "auto_sync": True})
        m = ph.expect("settings"); check("phone can turn auto-sync on", m["auto_sync"] is True and ctl.cfg["auto_sync"])
        ph_drain(); on_main(lambda: ctl.clipboard.setText("Second PC copy"))
        m = ph.expect("pc_clip"); check("auto-sync flag set", m["auto"] is True and m["item"]["text"] == "Second PC copy")

        ph.send({"t": "send", "text": "OTP is 482193 — sent from my phone"})
        h = ph.expect("history")
        check("phone send lands in history", h["history"][0]["text"].startswith("OTP") and h["history"][0]["src"] == "phone")
        time.sleep(0.3)
        check("toast shown with Copy", on_main(lambda: ctl.toast.isVisible() and ctl.toast.button_named("Copy") is not None),
              on_main(lambda: ctl.toast.title.text()))
        shot(ctl.toast, "toast_incoming.png")

        ph_drain(); on_main(lambda: ctl.toast.button_named("Copy").click())
        m = ph.expect("pc_clip")
        check("toast Copy puts text on PC clipboard",
              on_main(lambda: ctl.clipboard.text()).startswith("OTP"), "")
        check("echo is not auto-synced back", m["auto"] is False, m)

        ph.send({"t": "phone_clip", "text": "Phone clipboard: bKash ref 9XK2-77Q"})
        h = ph.expect("history")
        check("phone clipboard shows on PC", on_main(lambda: ctl.hist.phone_clip["text"]).startswith("Phone clipboard"))

        ph_drain(); on_main(lambda: ctl.clipboard.setText("Push me to the phone"))
        ph.expect("pc_clip")
        ph_drain(); on_main(ctl.send_pc_clipboard)
        m = ph.expect("push"); check("Send to phone pushes", m["item"]["text"] == "Push me to the phone")

        hid = on_main(lambda: ctl.hist.ordered()[-1]["id"])
        ph.send({"t": "pin", "id": hid, "pinned": True})
        h = ph.expect("history"); check("pin from phone", h["history"][0]["id"] == hid and h["history"][0]["pinned"])
        for i in range(7):
            ph.send({"t": "send", "text": f"bulk item {i}"}); ph.expect("history")
        h = ctl.hist.ordered()
        check("history = pinned + last 5", len(h) == 6 and h[0]["pinned"] and h[1]["text"] == "bulk item 6", [i["text"] for i in h])

        bad = FakePhone(os.urandom(32), port, "Intruder"); bad.start()
        msg = bad.inbox.get(timeout=5)
        check("wrong key is rejected", msg.get("t") == "__closed__", msg)

        addr, resp = discover(key, host="127.0.0.1")
        check("UDP discovery answers paired phone", resp and resp[0] == port and resp[1] == ctl.name, resp)
        try:
            discover(os.urandom(32), host="127.0.0.1"); check("discovery ignores strangers", False)
        except Exception:
            check("discovery ignores strangers", True)

        ph.send({"t": "ping"}); check("ping/pong", ph.expect("pong")["t"] == "pong")

        # ---------- v2: files, images, compose, links ----------
        import hashlib
        from PySide6.QtGui import QImage, QColor, QPainter
        save_dir = tempfile.mkdtemp(prefix="cbsave")
        on_main(lambda: ctl.cfg.set("save_dir", save_dir))
        blob = os.urandom(1_600_000)
        ph.send_file(blob, "IMG_2048 receipt.jpg", "image/jpeg")
        ack = ph.expect("file_ack", 15)
        saved = os.path.join(save_dir, "IMG_2048 receipt.jpg")
        check("phone → PC file saved intact", ack["ok"] and open(saved, "rb").read() == blob, ack)
        time.sleep(0.3)
        check("received file listed on PC", on_main(lambda: ctl.files.entries[0]["status"]) == "done")

        out_path = os.path.join(save_dir, "price-list.pdf")
        big = os.urandom(3_300_000)
        open(out_path, "wb").write(big)
        ph_drain(); on_main(lambda: ctl.send_paths([out_path]))
        offer, data, done = ph.receive_file()
        check("PC → phone file arrives intact", offer["kind"] == "file" and data == big
              and done["sha256"] == hashlib.sha256(big).hexdigest(), (offer["name"], len(data)))
        ph.send({"t": "file_ack", "id": offer["id"], "ok": True}); time.sleep(0.3)
        check("PC marks it delivered", on_main(lambda: ctl.files.find(offer["id"])["status"]) == "done")

        huge = os.path.join(save_dir, "video.mp4"); open(huge, "wb").write(os.urandom(12_000_000))
        ph_drain(); on_main(lambda: ctl.send_paths([huge]))
        o = ph.expect("file_offer", 10)
        ph.send_quiet({"t": "file_cancel", "id": o["id"]}); time.sleep(0.8)
        check("phone can cancel a transfer", on_main(lambda: ctl.files.find(o["id"])["status"]) == "cancelled")

        img = QImage(640, 360, QImage.Format.Format_ARGB32); img.fill(QColor("#4F46E5"))
        ph_drain(); on_main(lambda: ctl.clipboard.setImage(img))
        m = ph.expect("pc_clip", 8)
        check("PC image copy reaches phone card (with thumbnail)", m["item"].get("kind") == "image" and len(m["item"].get("thumb", "")) > 100,
              {k: m["item"].get(k) for k in ("kind", "w", "h")})
        iid = m["item"]["id"]
        ph.send({"t": "get_image", "id": iid})
        offer, data, done = ph.receive_file()
        check("phone can fetch the full image", offer["kind"] == "clip_image" and offer["purpose"] == "get"
              and QImage.fromData(data).width() == 640)

        pimg = QImage(300, 200, QImage.Format.Format_RGB32); pimg.fill(QColor("#10B981"))
        from clipbridge import media
        png = on_main(lambda: media.to_png(pimg))
        ph.send_file(png, "clip.png", "image/png", kind="clip_image", purpose="send")
        h = ph.expect("history", 8)
        first = next(i for i in h["history"] if not i["pinned"])
        check("phone image lands in history", first["kind"] == "image" and first["src"] == "phone", [(i["kind"], i["src"], i.get("pinned")) for i in h["history"]])
        time.sleep(0.4)
        check("image toast has Copy + Save", on_main(lambda: ctl.toast.button_named("Copy") is not None and ctl.toast.button_named("Save") is not None))
        shot(ctl.toast, "toast_image.png")
        hist_len = on_main(lambda: len(ctl.hist.items))
        on_main(lambda: ctl.toast.button_named("Copy").click()); time.sleep(0.8)
        check("Copy puts the image on the PC clipboard", on_main(lambda: ctl.clipboard.image().width()) == 300)
        check("…without duplicating it in history", on_main(lambda: len(ctl.hist.items)) == hist_len)

        ph_drain(); on_main(lambda: ctl.window.compose.setPlainText("typed on the PC")); on_main(ctl.window._on_send_text)
        check("text box sends to phone", ph.expect("push")["item"]["text"] == "typed on the PC")
        ph.send({"t": "send", "text": "https://leafas.example/order/4471"}); ph.expect("history"); time.sleep(0.3)
        check("links get an Open button", on_main(lambda: ctl.toast.button_named("Open") is not None))

        on_main(lambda: ctl.window.resize(480, 1500)); time.sleep(0.3)
        shot(ctl.window, "window_light.png")
        theme.is_dark = lambda: True
        on_main(ctl.apply_theme); on_main(ctl.window.refresh); time.sleep(0.3)
        shot(ctl.window, "window_dark.png")
        on_main(ctl.show_pairing); time.sleep(0.3); shot(ctl._pair_dialog, "pair_dark.png")
    except Exception:
        traceback.print_exc(); check("scenario crashed", False)
    finally:
        on_main(ctl.quit, wait=False)

threading.Thread(target=scenario, daemon=True).start()
qapp.exec()
failed = [r for r in results if not r[1]]
print(f"\n{len(results)-len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
