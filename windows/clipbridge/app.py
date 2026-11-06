"""ClipBridge for Windows — wires clipboard, server, transfers, tray, hotkey and UI together."""
from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QImage
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from . import core, media, protocol, theme, transfers, winsys
from .server import PhoneConnection, SyncServer
from .transfers import Incoming, Outgoing
from .ui import MainWindow, PairDialog, PairRequestDialog, Toast


class Controller(QObject):
    hotkey_pressed = Signal()

    def __init__(self, app: QApplication, start_hidden: bool):
        super().__init__()
        self.app = app
        self.cfg = core.Config()
        self.hist = core.History()
        self.files = core.FileList()
        self.name = core.pc_name()
        self.pc_clip: dict | None = None
        self._echo_text: str | None = None   # text we put on the clipboard ourselves
        self._echo_image_at = 0.0            # when we last put an image on the clipboard ourselves
        self._echo_item: dict | None = None
        self._last_text = ""
        self._last_text_at = 0.0
        self._last_image = ""
        self._last_image_at = 0.0
        self._incoming: dict[str, tuple[Incoming, PhoneConnection]] = {}
        self._progress_ui: dict[str, float] = {}
        self._previews: dict[str, object] = {}
        self._pair_dialog: PairDialog | None = None
        self._warned_tray = False

        self.clipboard = QGuiApplication.clipboard()
        self._clip_timer = QTimer(self, singleShot=True, interval=150)  # apps often fire several changes per copy
        self._clip_timer.timeout.connect(self._read_clipboard)
        self.clipboard.dataChanged.connect(self._clip_timer.start)

        self.server = SyncServer(self.cfg.key, self.cfg["port"], self.name, self)
        self.server.phone_ready.connect(self._on_phone_ready)
        self.server.phone_message.connect(self._on_phone_message)
        self.server.phone_chunk.connect(self._on_chunk)
        self.server.phone_gone.connect(self._on_phone_gone)
        self.server.log.connect(lambda m: print("[ClipBridge]", m, flush=True))
        self.server.pair_request.connect(self._on_pair_request)
        self.server.pair_gone.connect(self._on_pair_gone)
        self._pair_requests: dict[int, PairRequestDialog] = {}

        w = self.window = MainWindow()
        w.on_hide = self._on_window_hidden
        w.image_for = self._preview_for
        w.send_pc_clip.connect(self.send_pc_clipboard)
        w.copy_phone_clip.connect(self._copy_phone_clip)
        w.copy_item.connect(self._copy_item)
        w.send_item.connect(self._send_item)
        w.pin_item.connect(self._pin_item)
        w.delete_item.connect(self._delete_item)
        w.clear_history.connect(self._clear_history)
        w.pair_clicked.connect(self.show_pairing)
        w.setting_changed.connect(self._on_setting)
        w.send_text.connect(self._push)
        w.pick_files.connect(self.pick_files)
        w.send_paths.connect(self.send_paths)
        w.open_file.connect(self._open_file)
        w.show_file.connect(self._show_file)
        w.cancel_file.connect(self._cancel_file)
        w.remove_file.connect(self._remove_file)
        w.copy_file_image.connect(self._copy_file_image)
        w.save_item_image.connect(self._save_item_image)
        w.open_link.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        w.change_folder.connect(self._change_folder)
        w.open_folder.connect(self._open_folder)

        self.toast = Toast()

        self.hotkey = winsys.GlobalHotkey(self.hotkey_pressed.emit)
        self.hotkey_pressed.connect(self.send_pc_clipboard)

        self._build_tray()
        self.apply_theme()
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.apply_theme())
        except Exception:
            pass

        listening = self.server.start()
        self._apply_hotkey(self.cfg["hotkey"])
        self.window.set_settings(self.cfg["auto_sync"], self.cfg["auto_copy_incoming"],
                                 winsys.autostart_enabled(), self.cfg["hotkey"])
        self.window.set_folder(str(self.cfg.save_dir))
        self._read_clipboard(initial=True)
        self.window.set_phone_clip(self.hist.phone_clip)
        self.window.set_history(self.hist.ordered())
        self.window.set_files(self.files.entries)
        self._update_status()
        self.window.set_footer(self._footer_text() if listening else self.server.error)

        if not start_hidden:
            self.window.show()
            if not self.cfg["paired_once"]:
                QTimer.singleShot(400, self.show_pairing)

    # ---------------- clipboard ----------------
    def _read_clipboard(self, initial: bool = False) -> None:
        mime = self.clipboard.mimeData()
        if mime is None:
            return
        formats = mime.formats()
        if self._is_private(mime, formats):
            self._set_pc_clip({**core.make_item("", "pc", self.name), "note": "hidden"}, auto=False)
            return
        text = mime.text() if mime.hasText() else ""
        local_files = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()] if mime.hasUrls() else []
        if local_files:
            # Files copied in Explorer: offer to send them instead of syncing their paths as text.
            self._set_pc_clip({**core.make_item("", "pc", self.name), "note": "files", "files": local_files[:50]},
                              auto=False)
            return
        if not text.strip() and mime.hasImage():
            self._read_clipboard_image(initial)
            return
        if not text.strip():
            note = "nontext" if formats else "empty"
            self._set_pc_clip({**core.make_item("", "pc", self.name), "note": note}, auto=False)
            return
        echo = text == self._echo_text
        self._echo_text = None
        now = time.monotonic()
        if text == self._last_text and now - self._last_text_at < 1.5 and not initial:
            return  # same copy reported twice
        self._last_text, self._last_text_at = text, now
        if len(text) > protocol.MAX_TEXT:
            self._set_pc_clip({**core.make_item("", "pc", self.name), "note": "toolarge"}, auto=False)
            return
        item, changed = self.hist.add(text, "pc", self.name)
        self._set_pc_clip(dict(item), auto=self.cfg["auto_sync"] and not echo and not initial)
        if changed:
            self._history_changed()

    def _read_clipboard_image(self, initial: bool) -> None:
        img = self.clipboard.image()
        if img.isNull():
            self._set_pc_clip({**core.make_item("", "pc", self.name), "note": "nontext"}, auto=False)
            return
        if img.width() * img.height() > 60_000_000:
            self._set_pc_clip({**core.make_item("", "pc", self.name), "note": "toolarge"}, auto=False)
            return
        now = time.monotonic()
        echo = now - self._echo_image_at < 3
        echo_item, self._echo_item, self._echo_image_at = self._echo_item, None, 0.0
        if echo and echo_item:  # an image we just copied from history / the phone: don't add it again
            self._set_pc_clip(dict(echo_item), auto=False)
            return
        png = media.to_png(img)
        dg = media.digest(png)
        if dg == self._last_image and now - self._last_image_at < 1.5 and not initial:
            return
        self._last_image, self._last_image_at = dg, now
        if len(png) > protocol.MAX_CLIP_IMAGE:
            self._set_pc_clip({**core.make_item("", "pc", self.name), "note": "toolarge"}, auto=False)
            return
        item, changed = self.hist.add_image(png, dg, media.thumb_b64(img), img.width(), img.height(), "pc", self.name)
        self._set_pc_clip(dict(item), auto=False)
        if self.cfg["auto_sync"] and not echo and not initial:
            self._send_clip_image(item, "auto")
        if changed:
            self._history_changed()

    @staticmethod
    def _is_private(mime, formats: list[str]) -> bool:
        """Password managers mark secrets so clipboard tools skip them — respect that."""
        for f in formats:
            if "ExcludeClipboardContentFromMonitorProcessing" in f or "Clipboard Viewer Ignore" in f:
                return True
            if "CanIncludeInClipboardHistory" in f or "CanUploadToCloudClipboard" in f:
                if mime.data(f).data()[:4] == b"\x00\x00\x00\x00":
                    return True
        return False

    def _set_pc_clip(self, item: dict, auto: bool) -> None:
        self.pc_clip = item
        self.hist.protected = {item["id"]} if item.get("kind") == "image" else set()
        self.window.set_pc_clip(item)
        self.server.broadcast({"t": "pc_clip", "item": item, "auto": auto})

    def copy_to_pc(self, text: str) -> None:
        if not text:
            return
        self._echo_text = text
        self.clipboard.setText(text)

    def copy_image_to_pc(self, item: dict) -> bool:
        img = QImage(str(self.hist.image_path(item)))
        if img.isNull():
            return False
        self._echo_item = dict(item)
        self._echo_image_at = time.monotonic()
        self.clipboard.setImage(img)
        return True

    def _copy_any(self, item: dict | None) -> None:
        if not item:
            return
        if item.get("kind") == "image":
            self.copy_image_to_pc(item)
        else:
            self.copy_to_pc(item.get("text", ""))

    def _preview_for(self, item: dict):
        if item.get("kind") != "image":
            return None
        pm = self._previews.get(item["id"])
        if pm is None:
            pm = media.pixmap_from_file(str(self.hist.image_path(item)), 400, 180)
            if pm is not None:
                if len(self._previews) > 12:
                    self._previews.clear()
                self._previews[item["id"]] = pm
        return pm

    # ---------------- phone events ----------------
    def _state(self) -> dict:
        return {"t": "state", "v": protocol.VERSION, "pc_name": self.name, "pc_clip": self.pc_clip,
                "history": self.hist.ordered(), "auto_sync": self.cfg["auto_sync"]}

    def _on_phone_ready(self, phone: PhoneConnection) -> None:
        phone.send(self._state())
        first = not self.cfg["paired_once"]
        if first:
            self.cfg.set("paired_once", True)
        if self._pair_dialog and self._pair_dialog.isVisible():
            self._pair_dialog.show_success(phone.device)
        elif first:
            self.toast.show_info(f"{phone.device} is paired", "You're all set.", 3000)
        self._update_status()

    def _on_phone_gone(self, phone: PhoneConnection) -> None:
        for tid, (inc, owner) in list(self._incoming.items()):
            if owner is phone:
                inc.abort()
                del self._incoming[tid]
                self._set_file_status(tid, "failed")
        self._update_status()

    def _on_phone_message(self, phone: PhoneConnection, msg: dict) -> None:
        kind = msg.get("t")
        text = msg.get("text") if isinstance(msg.get("text"), str) else ""
        if kind == "send":
            item, _changed = self.hist.add(text, "phone", phone.device)
            if not item:
                return
            self._history_changed()
            self._announce_text(phone.device, text)
        elif kind == "phone_clip":
            if not text.strip() or len(text) > protocol.MAX_TEXT:
                return
            self.hist.set_phone_clip(core.make_item(text, "phone", phone.device))
            self.window.set_phone_clip(self.hist.phone_clip)
            _item, changed = self.hist.add(text, "phone", phone.device)
            if changed:
                self._history_changed()
        elif kind == "set" and "auto_sync" in msg:
            self._set_auto_sync(bool(msg["auto_sync"]))
        elif kind == "pin":
            if self.hist.set_pinned(str(msg.get("id")), bool(msg.get("pinned"))):
                self._history_changed()
        elif kind == "delete":
            if self.hist.delete(str(msg.get("id"))):
                self._history_changed()
        elif kind == "clear":
            self._clear_history()
        elif kind == "get_image":
            item = self.hist.find(str(msg.get("id")))
            if item is None and self.pc_clip and self.pc_clip.get("id") == msg.get("id"):
                item = self.pc_clip
            if item and item.get("kind") == "image":
                self._send_clip_image(item, "get", [phone])
        elif kind == "file_offer":
            self._on_file_offer(phone, msg)
        elif kind == "file_done":
            self._on_file_done(phone, msg)
        elif kind == "file_cancel":
            tid = str(msg.get("id"))
            if tid in self._incoming:
                self._incoming.pop(tid)[0].abort()
            else:
                phone.cancel_file(tid, tell_phone=False)
            self._set_file_status(tid, "cancelled")
        elif kind == "file_ack":
            entry = self.files.find(str(msg.get("id")))
            if entry and entry.get("dir") == "out":
                self._set_file_status(entry["id"], "done" if msg.get("ok") else "failed")

    def _announce_text(self, device: str, text: str) -> None:
        link = core.is_link(text)
        open_btn = [("Open", lambda: QDesktopServices.openUrl(QUrl(text.strip())), False, None)] if link else []
        if self.cfg["auto_copy_incoming"]:
            self.copy_to_pc(text)
            self.toast.show_message(f"Copied from {device}", core.preview(text, 300), None, open_btn,
                                    6000 if link else 3500)
        else:
            self.toast.show_message(f"From {device}", text, None,
                                    open_btn + [("Copy", lambda: self.copy_to_pc(text), True, "Copied ✓")])

    def _history_changed(self) -> None:
        items = self.hist.ordered()
        self.window.set_history(items)
        self.server.broadcast({"t": "history", "history": items})

    # ---------------- file transfer: receiving ----------------
    def _on_file_offer(self, phone: PhoneConnection, msg: dict) -> None:
        tid = str(msg.get("id") or "")[: protocol.ID_LEN]
        size = int(msg.get("size") or -1)
        kind = msg.get("kind")
        if len(tid) != protocol.ID_LEN or tid in self._incoming:
            return
        limit = protocol.MAX_CLIP_IMAGE if kind == "clip_image" else protocol.MAX_FILE
        if size > limit:
            phone.send({"t": "file_cancel", "id": tid, "reason": "too large"})
            return
        try:
            if kind == "clip_image":
                inc = Incoming(msg, self.hist.image_dir / f"incoming-{tid}")
            else:
                dest = transfers.unique_path(self.cfg.save_dir, msg.get("name") or "file")
                inc = Incoming(msg, dest)
                self.files.add({"id": tid, "name": dest.name, "size": size, "dir": "in", "device": phone.device,
                                "mime": msg.get("mime") or transfers.guess_mime(dest.name), "ts": core.now_ms(),
                                "status": "receiving", "progress": 0, "path": str(dest)})
                self.window.set_files(self.files.entries)
        except OSError as exc:
            phone.send({"t": "file_cancel", "id": tid, "reason": str(exc)})
            self.toast.show_info("Couldn't save a file from the phone", str(exc), 4000)
            return
        self._incoming[tid] = (inc, phone)

    def _on_chunk(self, phone: PhoneConnection, tid: str, data: bytes) -> None:
        pair = self._incoming.get(tid)
        if not pair:
            return
        inc = pair[0]
        try:
            inc.write(data)
        except Exception as exc:
            inc.abort()
            del self._incoming[tid]
            phone.send({"t": "file_cancel", "id": tid, "reason": str(exc)})
            self._set_file_status(tid, "failed")
            return
        entry = self.files.find(tid)
        if entry:
            entry["progress"] = inc.received
            self._progress_tick(entry)

    def _on_file_done(self, phone: PhoneConnection, msg: dict) -> None:
        tid = str(msg.get("id"))
        pair = self._incoming.pop(tid, None)
        if not pair:
            return
        inc = pair[0]
        ok = inc.finish(str(msg.get("sha256") or ""))
        phone.send({"t": "file_ack", "id": tid, "ok": ok})
        if inc.offer.get("kind") == "clip_image":
            self._on_clip_image_received(phone, inc, ok)
            return
        entry = self.files.find(tid)
        if not entry:
            return
        entry["progress"] = inc.received
        self._set_file_status(tid, "done" if ok else "failed")
        if not ok:
            self.toast.show_info("A file from the phone arrived damaged", entry["name"], 4000)
            return
        pm = media.pixmap_from_file(entry["path"], 340, 200) if entry["mime"].startswith("image/") else None
        self.toast.show_message(
            f"From {phone.device}", f"{entry['name']} · {transfers.human_size(entry['size'])}", pm,
            [("Show in folder", lambda: self._show_file(tid), False, None),
             ("Open", lambda: self._open_file(tid), True, None)])

    def _on_clip_image_received(self, phone: PhoneConnection, inc: Incoming, ok: bool) -> None:
        try:
            img = QImage(str(inc.dest)) if ok else QImage()
        finally:
            try:
                inc.dest.unlink(missing_ok=True)
            except OSError:
                pass
        if img.isNull():
            return
        png = media.to_png(img)
        item, changed = self.hist.add_image(png, media.digest(png), media.thumb_b64(img), img.width(),
                                            img.height(), "phone", phone.device)
        purpose = inc.offer.get("purpose")
        if purpose == "phone_clip":
            self.hist.set_phone_clip(dict(item))
            self.window.set_phone_clip(self.hist.phone_clip)
        if changed or purpose != "phone_clip":
            self._history_changed()
        if purpose == "phone_clip":
            return
        pm = media.pixmap_from_file(str(self.hist.image_path(item)), 340, 200)
        save = ("Save", lambda: self._save_item_image(item["id"]), False, None)
        if self.cfg["auto_copy_incoming"]:
            self.copy_image_to_pc(item)
            self.toast.show_message(f"Image copied from {phone.device}", "", pm, [save], 5000)
        else:
            self.toast.show_message(f"Image from {phone.device}", "", pm,
                                    [save, ("Copy", lambda: self.copy_image_to_pc(item), True, "Copied ✓")])

    # ---------------- file transfer: sending ----------------
    def _send_clip_image(self, item: dict, purpose: str, phones: list[PhoneConnection] | None = None) -> bool:
        path = self.hist.image_path(item)
        if not path.exists():
            return False
        data = path.read_bytes()
        for phone in phones or self.server.phones:
            offer = {"t": "file_offer", "id": transfers.new_id(), "kind": "clip_image", "purpose": purpose,
                     "name": f"ClipBridge-{item['id']}.png", "mime": "image/png", "size": len(data), "item": item}
            phone.send_file(Outgoing(offer, data))
        return True

    def pick_files(self) -> None:
        start = str(Path.home() / "Pictures") if (Path.home() / "Pictures").exists() else str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(self.window, "Send to phone", start)
        if paths:
            self.send_paths(paths)

    def send_paths(self, paths: list[str]) -> None:
        phones = self.server.phones
        if not phones:
            self.toast.show_info("No phone connected", "Open ClipBridge on your phone first.", 2500)
            return
        files = [p for p in paths if os.path.isfile(p)]
        if len(files) < len(paths):
            self.toast.show_info("Folders can't be sent", "Zip the folder first, then send the .zip.", 3500)
        for path in files:
            size = os.path.getsize(path)
            name = os.path.basename(path)
            mime = transfers.guess_mime(name)
            for phone in phones:
                tid = transfers.new_id()
                self.files.add({"id": tid, "name": name, "size": size, "dir": "out", "device": phone.device,
                                "mime": mime, "ts": core.now_ms(), "status": "sending", "progress": 0, "path": path})
                offer = {"t": "file_offer", "id": tid, "kind": "file", "name": name, "mime": mime, "size": size}
                try:
                    out = Outgoing(offer, path, on_progress=self._on_out_progress, on_done=self._on_out_done)
                except OSError as exc:
                    self._set_file_status(tid, "failed")
                    self.toast.show_info("Couldn't read a file", str(exc), 4000)
                    continue
                phone.send_file(out)
        self.window.set_files(self.files.entries)

    def _on_out_progress(self, out: Outgoing) -> None:
        entry = self.files.find(out.id)
        if entry:
            entry["progress"] = out.sent
            self._progress_tick(entry)

    def _on_out_done(self, out: Outgoing, ok: bool) -> None:
        entry = self.files.find(out.id)
        if entry and entry.get("status") == "sending":
            entry["progress"] = out.sent
            self._set_file_status(out.id, "sent" if ok else ("cancelled" if out.cancelled else "failed"))

    def _progress_tick(self, entry: dict) -> None:
        now = time.monotonic()
        if now - self._progress_ui.get(entry["id"], 0) > 0.15:
            self._progress_ui[entry["id"]] = now
            self.window.update_file(entry)

    def _set_file_status(self, tid: str, status: str) -> None:
        entry = self.files.find(tid)
        if not entry:
            return
        entry["status"] = status
        self.files.save()
        self.window.set_files(self.files.entries)

    def _cancel_file(self, tid: str) -> None:
        entry = self.files.find(tid)
        if not entry:
            return
        if tid in self._incoming:
            inc, phone = self._incoming.pop(tid)
            inc.abort()
            phone.send({"t": "file_cancel", "id": tid})
        else:
            for phone in self.server.phones:
                phone.cancel_file(tid)
        self._set_file_status(tid, "cancelled")

    def _remove_file(self, tid: str) -> None:
        if tid in self._incoming or (self.files.find(tid) or {}).get("status") == "sending":
            self._cancel_file(tid)
        self.files.remove(tid)
        self.window.set_files(self.files.entries)

    def _open_file(self, tid: str) -> None:
        entry = self.files.find(tid)
        if entry and entry.get("path") and os.path.exists(entry["path"]):
            QDesktopServices.openUrl(QUrl.fromLocalFile(entry["path"]))
        else:
            self.toast.show_info("File not found", "It may have been moved or deleted.", 2500)

    def _show_file(self, tid: str) -> None:
        entry = self.files.find(tid)
        path = entry.get("path") if entry else None
        if not path or not os.path.exists(path):
            self._open_folder()
            return
        if winsys.IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _copy_file_image(self, tid: str) -> None:
        entry = self.files.find(tid)
        img = QImage(entry["path"]) if entry and entry.get("path") else QImage()
        if not img.isNull():
            self._echo_item = None
            self._echo_image_at = time.monotonic()
            self.clipboard.setImage(img)

    def _save_item_image(self, item_id: str) -> None:
        item = self.hist.find(item_id)
        if not item or item.get("kind") != "image":
            return
        self.cfg.save_dir.mkdir(parents=True, exist_ok=True)
        default = str(self.cfg.save_dir / f"ClipBridge {time.strftime('%Y-%m-%d %H.%M.%S')}.png")
        target, _ = QFileDialog.getSaveFileName(self.window, "Save image", default, "PNG image (*.png)")
        if target:
            shutil.copyfile(self.hist.image_path(item), target)

    def _change_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self.window, "Save received files to", str(self.cfg.save_dir))
        if folder:
            self.cfg.set("save_dir", folder)
            self.window.set_folder(folder)

    def _open_folder(self) -> None:
        self.cfg.save_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.cfg.save_dir)))

    # ---------------- actions ----------------
    def send_pc_clipboard(self) -> None:
        if not self.server.phones:
            self.toast.show_info("No phone connected", "Open ClipBridge on your phone first.", 2500)
            return
        clip = self.pc_clip or {}
        if clip.get("note") == "files":
            self.send_paths(clip.get("files") or [])
            return
        if clip.get("kind") == "image" and not clip.get("note"):
            self._send_item(clip["id"])
            return
        if not clip.get("text"):
            self.toast.show_info("Nothing to send", "Copy some text or an image first.", 2200)
            return
        self._push(clip["text"])

    def _push(self, text: str) -> None:
        if not self.server.phones:
            self.toast.show_info("No phone connected", "Open ClipBridge on your phone first.", 2500)
            return
        item, changed = self.hist.add(text, "pc", self.name)
        if not item:
            return
        self.server.broadcast({"t": "push", "item": item})
        if changed:
            self._history_changed()
        names = ", ".join(p.device for p in self.server.phones)
        if not self.window.isActiveWindow():
            self.toast.show_info(f"Sent to {names} ✓", core.preview(text, 90), 1800)

    def _copy_phone_clip(self) -> None:
        self._copy_any(self.hist.phone_clip)

    def _copy_item(self, item_id: str) -> None:
        self._copy_any(self.hist.find(item_id))

    def copy_latest_from_phone(self) -> None:
        item = next((i for i in self.hist.items if i.get("src") == "phone"), None)
        if item:
            self._copy_any(item)
            what = "image" if item.get("kind") == "image" else core.preview(item["text"], 90)
            self.toast.show_info("Copied latest from phone ✓", what, 1800)
        else:
            self.toast.show_info("Nothing from the phone yet", "", 1800)

    def _send_item(self, item_id: str) -> None:
        item = self.hist.find(item_id) or (self.pc_clip if (self.pc_clip or {}).get("id") == item_id else None)
        if not item or not self.server.phones:
            return
        if item.get("kind") == "image":
            if self._send_clip_image(item, "push") and not self.window.isActiveWindow():
                self.toast.show_info("Image sent to phone ✓", "", 1800)
            if self.hist.bump(item["id"]):
                self._history_changed()
        else:
            self._push(item["text"])

    def _pin_item(self, item_id: str, pinned: bool) -> None:
        if self.hist.set_pinned(item_id, pinned):
            self._history_changed()

    def _delete_item(self, item_id: str) -> None:
        if self.hist.delete(item_id):
            self._history_changed()

    def _clear_history(self) -> None:
        self.hist.clear()
        self._history_changed()

    # ---------------- settings ----------------
    def _on_setting(self, name: str, value) -> None:
        if name == "auto_sync":
            self._set_auto_sync(bool(value))
        elif name == "auto_copy_incoming":
            self.cfg.set("auto_copy_incoming", bool(value))
        elif name == "start_with_windows":
            if not winsys.set_autostart(bool(value)):
                self.toast.show_info("Couldn't change startup setting", "", 2500)
            self.window.set_settings(self.cfg["auto_sync"], self.cfg["auto_copy_incoming"],
                                     winsys.autostart_enabled(), self.cfg["hotkey"])
        elif name == "hotkey":
            self.cfg.set("hotkey", value)
            self._apply_hotkey(value)
            self._refresh_tray_menu()

    def _set_auto_sync(self, value: bool) -> None:
        self.cfg.set("auto_sync", value)
        self.server.broadcast({"t": "settings", "auto_sync": value})
        self.window.set_settings(value, self.cfg["auto_copy_incoming"], winsys.autostart_enabled(),
                                 self.cfg["hotkey"])
        self.act_auto.blockSignals(True)
        self.act_auto.setChecked(value)
        self.act_auto.blockSignals(False)

    def _apply_hotkey(self, name: str) -> None:
        ok = self.hotkey.set(name)
        warn = "" if ok else f"{winsys.hotkey_label(name)} is already used by another app — pick a different one."
        self.window.set_hotkey_warning(warn)

    # ---------------- pairing ----------------
    def _pairing_uri(self) -> tuple[str, list[str]]:
        hosts = core.local_ipv4s()
        return protocol.pairing_uri(self.cfg.key, self.cfg["port"], hosts, self.name), hosts

    def show_pairing(self) -> None:
        if not self._pair_dialog:
            self._pair_dialog = PairDialog(self.window)
            self._pair_dialog.copy_link.connect(lambda: self.copy_to_pc(self._pairing_uri()[0]))
            self._pair_dialog.new_key.connect(self._regenerate_key)
            self._pair_dialog.fix_firewall.connect(winsys.allow_through_firewall)
            self._pair_dialog.finished.connect(lambda *_: setattr(self.server, "pairing_open", False))
        uri, hosts = self._pairing_uri()
        self._pair_dialog.set_pairing(uri, self.name, hosts, self.cfg["port"])
        self.server.pairing_open = True
        self.show_window()
        self._pair_dialog.show()
        self._pair_dialog.raise_()
        self._pair_dialog.activateWindow()

    def _on_pair_request(self, phone: PhoneConnection) -> None:
        parent = self._pair_dialog if self._pair_dialog and self._pair_dialog.isVisible() else self.window
        dlg = PairRequestDialog(parent, phone.device, phone.pair_code)
        self._pair_requests[phone.id] = dlg
        if self._pair_dialog:
            self._pair_dialog.set_status(f"{phone.device} wants to pair — check the code", ok=False)

        def done(result: int) -> None:
            self._pair_requests.pop(phone.id, None)
            if result == 1:  # QDialog.Accepted
                hosts = core.local_ipv4s()
                phone.finish_pairing({"k": protocol.b64u(self.cfg.key), "p": self.cfg["port"],
                                      "h": hosts, "n": self.name})
                if self._pair_dialog:
                    self._pair_dialog.set_status(f"Paired with {phone.device} — connecting…", ok=True)
            else:
                phone.finish_pairing(None)
                if self._pair_dialog:
                    self._pair_dialog.set_status("Pairing denied. Waiting for your phone…", ok=False)

        dlg.finished.connect(done)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_pair_gone(self, phone: PhoneConnection) -> None:
        dlg = self._pair_requests.pop(phone.id, None)
        if dlg:
            dlg.blockSignals(True)
            dlg.close()
        if self._pair_dialog and self._pair_dialog.isVisible():
            self._pair_dialog.set_status("The phone cancelled. Waiting for your phone…", ok=False)

    def _regenerate_key(self) -> None:
        self.cfg.new_key()
        self.cfg.set("paired_once", False)
        self.server.set_key(self.cfg.key)
        uri, hosts = self._pairing_uri()
        self._pair_dialog.set_pairing(uri, self.name, hosts, self.cfg["port"])
        self._update_status()

    # ---------------- tray / window ----------------
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(theme.app_icon("off"), self)
        self.tray.setToolTip("ClipBridge")
        self.menu = QMenu()
        self.act_open = QAction("Open ClipBridge", self.menu, triggered=self.show_window)
        self.act_send = QAction("", self.menu, triggered=self.send_pc_clipboard)
        self.act_latest = QAction("Copy latest from phone", self.menu, triggered=self.copy_latest_from_phone)
        self.act_files = QAction("Send files to phone…", self.menu, triggered=self.pick_files)
        self.act_auto = QAction("Auto-sync to phone", self.menu, checkable=True)
        self.act_auto.setChecked(self.cfg["auto_sync"])
        self.act_auto.toggled.connect(self._set_auto_sync)
        self.act_pair = QAction("Pair a phone…", self.menu, triggered=self.show_pairing)
        self.act_quit = QAction("Quit ClipBridge", self.menu, triggered=self.quit)
        for a in (self.act_open, None, self.act_send, self.act_files, self.act_latest, self.act_auto, None, self.act_pair,
                  None, self.act_quit):
            self.menu.addSeparator() if a is None else self.menu.addAction(a)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self._refresh_tray_menu()
        self.tray.show()

    def _refresh_tray_menu(self) -> None:
        hk = self.cfg["hotkey"]
        suffix = "" if hk == "off" else f"   ({winsys.hotkey_label(hk)})"
        self.act_send.setText("Send clipboard to phone" + suffix)

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def _on_window_hidden(self) -> None:
        if not self._warned_tray and self.tray.isVisible():
            self._warned_tray = True
            self.tray.showMessage("ClipBridge is still running",
                                  "It lives in the tray. Right-click the icon to quit.",
                                  QSystemTrayIcon.MessageIcon.Information, 3000)

    def show_window(self) -> None:
        self.window.show()
        self.window.setWindowState(self.window.windowState() & ~Qt.WindowState.WindowMinimized)
        self.window.raise_()
        self.window.activateWindow()

    def _update_status(self) -> None:
        phones = [p.device for p in self.server.phones]
        hk = self.cfg["hotkey"]
        hint = "" if hk == "off" else f"Send: {winsys.hotkey_label(hk)}"
        self.window.set_status(phones, hint)
        self.tray.setIcon(theme.app_icon("on" if phones else "off"))
        self.tray.setToolTip("ClipBridge — " + (", ".join(phones) + " connected" if phones else "no phone connected"))
        self.act_send.setEnabled(bool(phones))
        self.act_files.setEnabled(bool(phones))

    def _footer_text(self) -> str:
        hosts = core.local_ipv4s()
        where = ", ".join(hosts) if hosts else "no network"
        return f"{self.name} · {where} · port {self.cfg['port']}"

    def apply_theme(self) -> None:
        qss = theme.stylesheet(theme.palette())
        self.app.setStyleSheet(qss)
        self.window.set_status([p.device for p in self.server.phones], self.window.hint_text.text())

    def quit(self) -> None:
        self.hotkey.stop()
        self.server.stop()
        self.tray.hide()
        self.window.allow_close = True
        self.app.quit()


def _set_app_id() -> None:
    if winsys.IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClipBridge.Desktop")
        except Exception:
            pass


def main() -> int:
    _set_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("ClipBridge")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setWindowIcon(theme.app_icon())
    if winsys.IS_WINDOWS:
        f = app.font()
        f.setFamily("Segoe UI")
        f.setPointSizeF(10)
        app.setFont(f)

    # single instance: a second launch just brings the first window forward
    instance_name = f"ClipBridge-{getpass.getuser()}"
    probe = QLocalSocket()
    probe.connectToServer(instance_name)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(instance_name)
    instance = QLocalServer()
    instance.listen(instance_name)

    ctl = Controller(app, start_hidden="--tray" in sys.argv)
    instance.newConnection.connect(lambda: (instance.nextPendingConnection(), ctl.show_window()))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
