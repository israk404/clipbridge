"""Runs the real PC app offscreen for the Kotlin client test. Prints the pairing URI."""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cbjvm")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from clipbridge import app as appmod, protocol as P
qapp = QApplication(sys.argv); qapp.setQuitOnLastWindowClosed(False)
ctl = appmod.Controller(qapp, start_hidden=True)
print("URI", P.pairing_uri(ctl.cfg.key, ctl.cfg["port"], ["127.0.0.1"], ctl.name), flush=True)
import hashlib
save = tempfile.mkdtemp(prefix="cbjvmsave"); ctl.cfg.set("save_dir", save)
outfile = os.path.join(save, "from-pc.bin"); blob = os.urandom(3_000_000); open(outfile, "wb").write(blob)
print("SAVE", save, flush=True)
print("PCSHA", hashlib.sha256(blob).hexdigest(), flush=True)
done = []
def on_ready(phone):
    if done: return
    done.append(1)
    QTimer.singleShot(1500, lambda: ctl.clipboard.setText("Something copied on the PC 📋"))
    QTimer.singleShot(3000, ctl.send_pc_clipboard)
    QTimer.singleShot(4500, lambda: ctl.send_paths([outfile]))
ctl.server.phone_ready.connect(on_ready)

# pairing: open from the start; "Allow" devices are approved, "Deny" devices refused, then pairing closes
ctl.server.pairing_open = True
def on_pair(phone):
    if "Deny" in phone.device:
        phone.finish_pairing(None)
        ctl.server.pairing_open = False
    else:
        phone.finish_pairing({"k": P.b64u(ctl.cfg.key), "p": ctl.cfg["port"], "h": ["127.0.0.1"],
                              "n": ctl.name, "test_code": phone.pair_code})
ctl.server.pair_request.connect(on_pair)
QTimer.singleShot(120_000, qapp.quit)
qapp.exec()
