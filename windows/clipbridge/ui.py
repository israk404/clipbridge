"""Main window, toast popup, pairing dialog and the small custom widgets they use."""
from __future__ import annotations

import os
import re

import segno
from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                               QLabel, QMenu, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import core, media, theme, transfers, winsys


def soft_wrap(text: str, limit: int) -> str:
    """Trim for display and let very long words (URLs, hashes) wrap instead of widening the window."""
    shown = text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
    return re.sub(r"(\S{22})", "\\1\u200b", shown)


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        lbl.setProperty("role", role)
    if wrap:
        lbl.setWordWrap(True)
        lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return lbl


def button(text: str, kind: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind:
        btn.setProperty("kind", kind)
    return btn


def flash(btn: QPushButton, text: str = "Copied ✓", ms: int = 1300) -> None:
    original = btn.property("orig_text") or btn.text()
    btn.setProperty("orig_text", original)
    btn.setText(text)
    QTimer.singleShot(ms, btn, lambda: btn.setText(original))  # btn as context: skipped if btn is deleted


def clip_meta(item: dict | None) -> str:
    if not item:
        return ""
    who = "This PC" if item.get("src") == "pc" else item.get("device") or "Phone"
    return f"{who} · {core.time_ago(item.get('ts'))}"


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

    def paintEvent(self, _event) -> None:
        pal = theme.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor(pal["accent"] if self.isChecked() else pal["track"])
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(20 if self.isChecked() else 2, 2, 18, 18))
        p.end()


class Card(QFrame):
    def __init__(self, title: str | None = None):
        super().__init__()
        self.setObjectName("card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(16, 14, 16, 14)
        self.box.setSpacing(8)
        if title:
            self.box.addWidget(label(title.upper(), "section"))


class ClipCard(Card):
    """'This PC's clipboard' / 'Phone's clipboard' card with one main action. Shows text or an image."""

    def __init__(self, title: str, action: str):
        super().__init__(title)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.image.hide()
        self.box.addWidget(self.image)
        self.text = label("", "clip", wrap=True)
        self.box.addWidget(self.text)
        row = QHBoxLayout()
        self.meta = label("", "muted")
        self.button = button(action, "primary")
        row.addWidget(self.meta, 1)
        row.addWidget(self.button)
        self.box.addLayout(row)

    def set_content(self, text: str, meta: str, empty: bool, can_act: bool, pixmap: QPixmap | None = None) -> None:
        if pixmap is not None:
            self.image.setPixmap(pixmap)
            self.image.show()
            self.text.hide()
        else:
            self.image.hide()
            self.text.show()
            self.text.setProperty("role", "empty" if empty else "clip")
            self.text.style().unpolish(self.text)
            self.text.style().polish(self.text)
            self.text.setText(soft_wrap(text, 420))
            lines = 2 if empty else 4
            self.text.setMaximumHeight(self.text.fontMetrics().lineSpacing() * lines + 6)
        self.meta.setText(meta)
        self.button.setEnabled(can_act)


def item_meta(item: dict) -> str:
    pin = "📌 Pinned · " if item.get("pinned") else ""
    size = f"Image {item.get('w', '?')}×{item.get('h', '?')} · " if item.get("kind") == "image" else ""
    return pin + size + clip_meta(item)


class HistoryRow(QFrame):
    def __init__(self, window: "MainWindow", item: dict, can_send: bool):
        super().__init__()
        self.setObjectName("row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 8, 10)
        lay.setSpacing(10)
        is_pc = item.get("src") == "pc"
        is_image = item.get("kind") == "image"
        badge = label("PC" if is_pc else "PHONE")
        badge.setProperty("badge", "pc" if is_pc else "phone")
        badge.setFixedSize(50, 18)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(4)
        if is_image:
            thumb = QLabel()
            pm = media.pixmap_from_b64(item.get("thumb"), 160, 90)
            if pm:
                thumb.setPixmap(pm)
            else:
                thumb.setText("🖼  Image")
            col.addWidget(thumb)
        else:
            text = label(soft_wrap(core.preview(item["text"], 200), 200), wrap=True)
            text.setMaximumHeight(text.fontMetrics().lineSpacing() * 2 + 4)
            col.addWidget(text)
        col.addWidget(label(item_meta(item), "muted"))
        copy = button("Copy", "ghost")
        copy.clicked.connect(lambda: window.copy_item.emit(item["id"]))
        more = button("⋯", "ghost")
        more.setFixedWidth(34)
        menu = QMenu(more)
        act = menu.addAction("Send to phone")
        act.setEnabled(can_send)
        act.triggered.connect(lambda: window.send_item.emit(item["id"]))
        if not is_image and core.is_link(item["text"]):
            menu.addAction("Open link").triggered.connect(lambda: window.open_link.emit(item["text"].strip()))
        if is_image:
            menu.addAction("Save image…").triggered.connect(lambda: window.save_item_image.emit(item["id"]))
        menu.addAction("Unpin" if item.get("pinned") else "Pin to top").triggered.connect(
            lambda: window.pin_item.emit(item["id"], not item.get("pinned")))
        menu.addSeparator()
        menu.addAction("Delete").triggered.connect(lambda: window.delete_item.emit(item["id"]))
        more.clicked.connect(lambda: menu.exec(more.mapToGlobal(QPoint(0, more.height()))))
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(col, 1)
        lay.addWidget(copy, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(more, 0, Qt.AlignmentFlag.AlignVCenter)


def file_glyph(mime: str) -> str:
    if mime.startswith("image/"):
        return "🖼"
    if mime.startswith("video/"):
        return "🎬"
    if mime.startswith("audio/"):
        return "🎵"
    if mime == "application/pdf":
        return "📕"
    return "📄"


def file_status(entry: dict) -> str:
    who = entry.get("device") or "phone"
    direction = f"From {who}" if entry.get("dir") == "in" else f"To {who}"
    size = transfers.human_size(entry.get("size"))
    status = entry.get("status")
    if status in ("sending", "receiving"):
        total = entry.get("size") or 0
        done = entry.get("progress") or 0
        pct = f"{int(done * 100 / total)}%" if total > 0 else transfers.human_size(done)
        verb = "Sending" if status == "sending" else "Receiving"
        return f"{direction} · {verb} {pct} of {size}"
    tail = {"done": ("Saved" if entry.get("dir") == "in" else "Delivered ✓"),
            "sent": "Sent", "failed": "Failed", "cancelled": "Cancelled"}.get(status, "")
    return f"{direction} · {size} · {tail} · {core.time_ago(entry.get('ts'))}"


class FileRow(QFrame):
    def __init__(self, window: "MainWindow", entry: dict, pixmap: QPixmap | None):
        super().__init__()
        self.setObjectName("row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 8, 10)
        lay.setSpacing(10)
        icon = QLabel()
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pixmap:
            icon.setPixmap(pixmap)
        else:
            icon.setText(file_glyph(entry.get("mime", "")))
            icon.setStyleSheet("font-size: 20pt;")
        col = QVBoxLayout()
        col.setSpacing(3)
        name = label(soft_wrap(entry.get("name", "file"), 80), wrap=True)
        name.setMaximumHeight(name.fontMetrics().lineSpacing() + 4)
        self.meta = label(file_status(entry), "muted")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, 1000)
        active = entry.get("status") in ("sending", "receiving")
        self.bar.setVisible(active)
        col.addWidget(name)
        col.addWidget(self.meta)
        col.addWidget(self.bar)
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(col, 1)
        eid = entry["id"]
        if active:
            cancel = button("Cancel", "ghost")
            cancel.clicked.connect(lambda: window.cancel_file.emit(eid))
            lay.addWidget(cancel, 0, Qt.AlignmentFlag.AlignVCenter)
        elif entry.get("dir") == "in" and entry.get("status") == "done":
            opener = button("Open", "ghost")
            opener.clicked.connect(lambda: window.open_file.emit(eid))
            lay.addWidget(opener, 0, Qt.AlignmentFlag.AlignVCenter)
        more = button("⋯", "ghost")
        more.setFixedWidth(34)
        menu = QMenu(more)
        if entry.get("status") == "done" or entry.get("dir") == "out":
            menu.addAction("Open").triggered.connect(lambda: window.open_file.emit(eid))
            menu.addAction("Show in folder").triggered.connect(lambda: window.show_file.emit(eid))
        if entry.get("mime", "").startswith("image/") and entry.get("status") in ("done", "sent"):
            menu.addAction("Copy image").triggered.connect(lambda: window.copy_file_image.emit(eid))
        menu.addSeparator()
        menu.addAction("Remove from list").triggered.connect(lambda: window.remove_file.emit(eid))
        more.clicked.connect(lambda: menu.exec(more.mapToGlobal(QPoint(0, more.height()))))
        lay.addWidget(more, 0, Qt.AlignmentFlag.AlignVCenter)
        self.update_progress(entry)

    def update_progress(self, entry: dict) -> None:
        total = entry.get("size") or 0
        if total > 0:
            self.bar.setValue(int(1000 * (entry.get("progress") or 0) / total))
        self.meta.setText(file_status(entry))


class ComposeBox(QPlainTextEdit):
    submit = Signal()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.submit.emit()
            return
        super().keyPressEvent(e)


class SettingRow(QWidget):
    def __init__(self, title: str, subtitle: str, control: QWidget):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = label(title)
        self.subtitle = label(subtitle, "muted", wrap=True)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        lay.addLayout(col, 1)
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


class MainWindow(QWidget):
    send_pc_clip = Signal()
    copy_phone_clip = Signal()
    copy_item = Signal(str)
    send_item = Signal(str)
    pin_item = Signal(str, bool)
    delete_item = Signal(str)
    clear_history = Signal()
    pair_clicked = Signal()
    setting_changed = Signal(str, object)
    send_text = Signal(str)
    pick_files = Signal()
    send_paths = Signal(list)
    open_file = Signal(str)
    show_file = Signal(str)
    cancel_file = Signal(str)
    remove_file = Signal(str)
    copy_file_image = Signal(str)
    save_item_image = Signal(str)
    open_link = Signal(str)
    change_folder = Signal()
    open_folder = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("ClipBridge")
        self.resize(480, 820)
        self.setMinimumWidth(410)
        self.setAcceptDrops(True)
        self.allow_close = False
        self.on_hide = None
        self.image_for = None        # callback: item -> QPixmap | None (full image previews)
        self._history: list[dict] = []
        self._files: list[dict] = []
        self._file_rows: dict[str, FileRow] = {}
        self._thumbs: dict[str, QPixmap] = {}
        self._pc_clip: dict | None = None
        self._phone_clip: dict | None = None
        self._phones: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 0)
        outer.setSpacing(10)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(30))
        head.addWidget(logo)
        head.addSpacing(6)
        head.addWidget(label("ClipBridge", "title"))
        head.addStretch(1)
        self.pair_btn = button("Pair phone")
        self.pair_btn.clicked.connect(self.pair_clicked)
        head.addWidget(self.pair_btn)
        outer.addLayout(head)

        pill = QFrame()
        pill.setObjectName("card")
        pill_lay = QHBoxLayout(pill)
        pill_lay.setContentsMargins(12, 8, 12, 8)
        self.status_dot = QLabel()
        self.status_text = label("")
        self.hint_text = label("", "muted")
        pill_lay.addWidget(self.status_dot)
        pill_lay.addWidget(self.status_text, 1)
        pill_lay.addWidget(self.hint_text)
        outer.addWidget(pill)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 2, 2, 16)
        self.body.setSpacing(10)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        compose = Card("Send to phone")
        self.compose = ComposeBox()
        self.compose.setPlaceholderText("Type or paste something… (Ctrl+Enter to send)")
        self.compose.setFixedHeight(76)
        self.compose.submit.connect(self._on_send_text)
        compose.box.addWidget(self.compose)
        crow = QHBoxLayout()
        self.files_btn = button("Photos, videos && files…")
        self.files_btn.clicked.connect(self.pick_files)
        self.send_btn = button("Send  ➜", "primary")
        self.send_btn.clicked.connect(self._on_send_text)
        crow.addWidget(self.files_btn)
        crow.addStretch(1)
        crow.addWidget(self.send_btn)
        compose.box.addLayout(crow)
        compose.box.addWidget(label("Tip: drag files onto this window to send them.", "muted"))
        self.body.addWidget(compose)

        self.pc_card = ClipCard("This PC's clipboard", "Send to phone  ➜")
        self.pc_card.button.clicked.connect(self._on_send_pc)
        self.phone_card = ClipCard("Phone's clipboard", "Copy to PC")
        self.phone_card.button.clicked.connect(self._on_copy_phone)
        self.body.addWidget(self.pc_card)
        self.body.addWidget(self.phone_card)

        rec_head = QHBoxLayout()
        rec_head.setContentsMargins(4, 8, 0, 0)
        rec_head.addWidget(label("RECENT · BOTH DEVICES", "section"))
        rec_head.addStretch(1)
        self.clear_btn = button("Clear", "ghost")
        self.clear_btn.setToolTip("Remove everything except pinned items")
        self.clear_btn.clicked.connect(self.clear_history)
        rec_head.addWidget(self.clear_btn)
        self.body.addLayout(rec_head)
        self.history_box = QVBoxLayout()
        self.history_box.setSpacing(6)
        self.body.addLayout(self.history_box)

        files_head = QHBoxLayout()
        files_head.setContentsMargins(4, 8, 0, 0)
        files_head.addWidget(label("FILES", "section"))
        files_head.addStretch(1)
        open_dir = button("Open folder", "ghost")
        open_dir.clicked.connect(self.open_folder)
        files_head.addWidget(open_dir)
        self.body.addLayout(files_head)
        self.files_box = QVBoxLayout()
        self.files_box.setSpacing(6)
        self.body.addLayout(self.files_box)

        settings = Card("Settings")
        self.sw_auto_sync = ToggleSwitch()
        self.sw_auto_copy = ToggleSwitch()
        self.sw_autostart = ToggleSwitch()
        self.hotkey_box = QComboBox()
        for key, (lbl, _m, _v) in winsys.HOTKEYS.items():
            self.hotkey_box.addItem(lbl, key)
        settings.box.addWidget(SettingRow("Auto-sync to phone",
                                          "Every copy on this PC (text or image) lands in the phone's clipboard",
                                          self.sw_auto_sync))
        settings.box.addWidget(SettingRow("Auto-copy from phone",
                                          "Skip the Copy button when the phone sends text or an image",
                                          self.sw_auto_copy))
        settings.box.addWidget(SettingRow("Start with Windows", "Runs quietly in the tray", self.sw_autostart))
        settings.box.addWidget(SettingRow("Send-to-phone hotkey", "Pushes this PC's clipboard to the phone",
                                          self.hotkey_box))
        self.hotkey_warning = label("", "muted", wrap=True)
        self.hotkey_warning.hide()
        settings.box.addWidget(self.hotkey_warning)
        change = button("Change…")
        change.clicked.connect(self.change_folder)
        self.folder_row = SettingRow("Received files go to", "", change)
        settings.box.addWidget(self.folder_row)
        self.body.addWidget(settings)
        self.footer = label("", "muted", wrap=True)
        self.body.addWidget(self.footer)
        self.body.addStretch(1)

        self.sw_auto_sync.toggled.connect(lambda v: self.setting_changed.emit("auto_sync", v))
        self.sw_auto_copy.toggled.connect(lambda v: self.setting_changed.emit("auto_copy_incoming", v))
        self.sw_autostart.toggled.connect(lambda v: self.setting_changed.emit("start_with_windows", v))
        self.hotkey_box.currentIndexChanged.connect(
            lambda _i: self.setting_changed.emit("hotkey", self.hotkey_box.currentData()))

        self._ticker = QTimer(self, interval=30_000)
        self._ticker.timeout.connect(self.refresh)
        self._ticker.start()

    # ----- updates from the controller -----
    def set_settings(self, auto_sync: bool, auto_copy: bool, autostart: bool, hotkey: str) -> None:
        for sw, val in ((self.sw_auto_sync, auto_sync), (self.sw_auto_copy, auto_copy), (self.sw_autostart, autostart)):
            sw.blockSignals(True)
            sw.setChecked(val)
            sw.blockSignals(False)
            sw.update()
        self.hotkey_box.blockSignals(True)
        self.hotkey_box.setCurrentIndex(max(0, self.hotkey_box.findData(hotkey)))
        self.hotkey_box.blockSignals(False)

    def set_folder(self, path: str) -> None:
        self.folder_row.subtitle.setText(path)

    def set_hotkey_warning(self, text: str) -> None:
        self.hotkey_warning.setText(text)
        self.hotkey_warning.setVisible(bool(text))

    def set_status(self, phones: list[str], hint: str = "") -> None:
        self._phones = phones
        pal = theme.palette()
        if phones:
            names = phones[0] if len(phones) == 1 else f"{len(phones)} phones"
            self.status_text.setText(f"{names} connected")
        else:
            self.status_text.setText("Waiting for your phone…")
        self.status_dot.setPixmap(theme.dot_pixmap(pal["ok"] if phones else pal["off"]))
        self.hint_text.setText(hint)
        self.send_btn.setEnabled(bool(phones))
        self.files_btn.setEnabled(bool(phones))
        self.refresh()

    def set_footer(self, text: str) -> None:
        self.footer.setText(text)

    def set_pc_clip(self, item: dict | None) -> None:
        self._pc_clip = item
        self.refresh()

    def set_phone_clip(self, item: dict | None) -> None:
        self._phone_clip = item
        self.refresh()

    def set_history(self, items: list[dict]) -> None:
        self._history = items
        self.refresh()

    def set_files(self, entries: list[dict]) -> None:
        self._files = entries
        self._rebuild_files()

    def update_file(self, entry: dict) -> None:
        row = self._file_rows.get(entry["id"])
        if row:
            row.update_progress(entry)

    def _preview(self, item: dict) -> QPixmap | None:
        pm = self.image_for(item) if self.image_for else None
        return pm or media.pixmap_from_b64(item.get("thumb"), 400, 180)

    def refresh(self) -> None:
        connected = bool(self._phones)
        item = self._pc_clip
        note = (item or {}).get("note")
        if not item or note == "empty":
            self.pc_card.set_content("Nothing copied yet.", "", True, False)
        elif note == "hidden":
            self.pc_card.set_content("🔒 Hidden — copied from a password manager, so it isn't synced.",
                                     clip_meta(item), True, False)
        elif note == "nontext":
            self.pc_card.set_content("The clipboard holds files or something that isn't text or an image.",
                                     clip_meta(item), True, False)
        elif note == "toolarge":
            self.pc_card.set_content("Too large to sync.", clip_meta(item), True, False)
        elif note == "files":
            names = [os.path.basename(f) for f in item.get("files", [])]
            shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
            self.pc_card.set_content(f"📎 You copied {len(names)} file{'s' if len(names) != 1 else ''}: {shown}",
                                     clip_meta(item), False, connected)
        elif item.get("kind") == "image":
            self.pc_card.set_content("", item_meta(item), False, connected, self._preview(item))
        else:
            self.pc_card.set_content(item["text"], clip_meta(item), False, connected)
        self.pc_card.button.setToolTip("" if connected else "Connect your phone first")

        ph = self._phone_clip
        if ph and ph.get("kind") == "image":
            self.phone_card.set_content("", item_meta(ph), False, True, self._preview(ph))
        elif ph:
            self.phone_card.set_content(ph["text"], clip_meta(ph), False, True)
        else:
            self.phone_card.set_content("Open ClipBridge on your phone and its clipboard shows up here.",
                                        "", True, False)

        while self.history_box.count():
            w = self.history_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not self._history:
            empty = label("Copies from your PC and phone will appear here (last 5, plus anything you pin).",
                          "empty", wrap=True)
            empty.setContentsMargins(4, 0, 4, 4)
            self.history_box.addWidget(empty)
        for it in self._history:
            self.history_box.addWidget(HistoryRow(self, it, connected))
        self.clear_btn.setEnabled(any(not i.get("pinned") for i in self._history))
        self._rebuild_files()

    def _rebuild_files(self) -> None:
        while self.files_box.count():
            w = self.files_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._file_rows.clear()
        if not self._files:
            empty = label("Photos, videos and files you share show up here. Received files are saved "
                          "in the folder below.", "empty", wrap=True)
            empty.setContentsMargins(4, 0, 4, 4)
            self.files_box.addWidget(empty)
        for e in self._files[:15]:
            pm = None
            if e.get("mime", "").startswith("image/") and e.get("status") in ("done", "sent") and e.get("path"):
                pm = self._thumbs.get(e["id"])
                if pm is None:
                    pm = media.pixmap_from_file(e["path"], 44, 44)
                    if pm:
                        self._thumbs[e["id"]] = pm
            row = FileRow(self, e, pm)
            self._file_rows[e["id"]] = row
            self.files_box.addWidget(row)

    # ----- local actions -----
    def _on_send_text(self) -> None:
        text = self.compose.toPlainText()
        if text.strip() and self._phones:
            self.send_text.emit(text)
            self.compose.clear()
            flash(self.send_btn, "Sent ✓")

    def _on_send_pc(self) -> None:
        self.send_pc_clip.emit()
        flash(self.pc_card.button, "Sent ✓")

    def _on_copy_phone(self) -> None:
        self.copy_phone_clip.emit()
        flash(self.phone_card.button)

    def dragEnterEvent(self, e) -> None:
        md = e.mimeData()
        if (md.hasUrls() and any(u.isLocalFile() for u in md.urls())) or md.hasText():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        md = e.mimeData()
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []
        if paths:
            self.send_paths.emit(paths)
            e.acceptProposedAction()
        elif md.hasText():
            self.compose.setPlainText(md.text())
            self.compose.setFocus()
            e.acceptProposedAction()

    def closeEvent(self, event) -> None:
        if self.allow_close:
            event.accept()
            return
        event.ignore()
        self.hide()
        if self.on_hide:
            self.on_hide()


class Toast(QWidget):
    """Popup in the bottom-right corner with optional image and buttons. Never steals focus."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(384)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        self.frame = QFrame()
        self.frame.setObjectName("toast")
        shadow = QGraphicsDropShadowEffect(self.frame)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.frame.setGraphicsEffect(shadow)
        outer.addWidget(self.frame)
        lay = QVBoxLayout(self.frame)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(8)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(theme.logo_pixmap(20))
        self.title = label("")
        self.title.setStyleSheet("font-weight: 600;")
        close = button("✕", "ghost")
        close.setFixedWidth(30)
        close.clicked.connect(self.hide)
        top.addWidget(icon)
        top.addWidget(self.title, 1)
        top.addWidget(close)
        lay.addLayout(top)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.image)
        self.text = label("", "clip", wrap=True)
        lay.addWidget(self.text)
        self.buttons = QWidget()
        self._row = QHBoxLayout(self.buttons)
        self._row.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.buttons)
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, title: str, text: str = "", pixmap: QPixmap | None = None,
                     buttons: list[tuple] = (), timeout_ms: int = 12_000) -> None:
        """buttons: (label, callback, primary, label_after_click_or_None)."""
        self.title.setText(title)
        self.text.setText(soft_wrap(text, 300))
        self.text.setMaximumHeight(self.text.fontMetrics().lineSpacing() * 4 + 6)
        self.text.setVisible(bool(text))
        if pixmap is not None:
            self.image.setPixmap(pixmap)
        self.image.setVisible(pixmap is not None)
        while self._row.count():
            w = self._row.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._row.addStretch(1)
        for lbl, callback, primary, after in buttons:
            btn = button(lbl, "primary" if primary else None)
            if primary:
                btn.setMinimumWidth(96)
            btn.clicked.connect(lambda _=False, b=btn, cb=callback, a=after: self._clicked(b, cb, a))
            self._row.addWidget(btn)
        self.buttons.setVisible(bool(buttons))
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 8, screen.bottom() - self.height() - 8)
        self.show()
        self.raise_()
        self._timer.start(timeout_ms)

    def show_info(self, title: str, text: str = "", timeout_ms: int = 2200) -> None:
        self.show_message(title, text, None, [], timeout_ms)

    def button_named(self, text: str) -> QPushButton | None:
        for i in range(self._row.count()):
            w = self._row.itemAt(i).widget()
            if isinstance(w, QPushButton) and w.text() == text:
                return w
        return None

    def _clicked(self, btn: QPushButton, callback, after: str | None) -> None:
        callback()
        if after:
            btn.setText(after)
            btn.setEnabled(False)
            self._timer.start(1400)
        else:
            self.hide()

    def enterEvent(self, _e) -> None:
        self._timer.stop()

    def leaveEvent(self, _e) -> None:
        if self.isVisible():
            self._timer.start(4000)


def qr_pixmap(data: str, module_px: int = 6) -> QPixmap:
    matrix = segno.make(data, error="m").matrix
    n, border = len(matrix), 4
    size = (n + 2 * border) * module_px
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    black = QColor("#111111")
    for y, row in enumerate(matrix):
        for x, val in enumerate(row):
            if val & 1:
                p.fillRect((x + border) * module_px, (y + border) * module_px, module_px, module_px, black)
    p.end()
    return QPixmap.fromImage(img)


class PairDialog(QDialog):
    copy_link = Signal()
    new_key = Signal()
    fix_firewall = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pair your phone")
        self.setFixedWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Pair your phone", "title"))
        steps = Card()
        steps.box.addWidget(label("1.  Connect the phone to the same Wi-Fi as this PC.\n"
                                  "2.  Open ClipBridge on the phone and tap “Find my PC”.\n"
                                  "3.  Check the code matches, then click Allow.", wrap=True))
        lay.addWidget(steps)
        self.status = label("Waiting for your phone…  (keep this window open)", "muted", wrap=True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.status)
        self.details = label("", "muted", wrap=True)
        self.details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.details)

        other = Card("Other way")
        row = QHBoxLayout()
        self.qr = QLabel()
        self.qr.setStyleSheet("background: white; border-radius: 8px; padding: 4px;")
        row.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.addWidget(label("Scan this with Google Lens (or your camera), copy the text, then on the phone tap "
                            "“Paste pairing link”. Or send yourself the link:", "muted", wrap=True))
        copy = button("Copy pairing link")
        copy.clicked.connect(lambda: (self.copy_link.emit(), flash(copy)))
        col.addWidget(copy, 0, Qt.AlignmentFlag.AlignLeft)
        col.addStretch(1)
        row.addLayout(col, 1)
        other.box.addLayout(row)
        lay.addWidget(other)

        help_card = Card("Phone can't find the PC?")
        help_card.box.addWidget(label(
            "• Same Wi-Fi on both (guest networks often block devices from seeing each other).\n"
            "• Windows: Settings → Network & internet → Wi-Fi → your network → set it to Private.\n"
            "• Allow ClipBridge through Windows Firewall:", wrap=True))
        fw = button("Allow through firewall (asks for admin)")
        fw.clicked.connect(self.fix_firewall)
        fw.setEnabled(winsys.IS_WINDOWS)
        help_card.box.addWidget(fw, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(help_card)

        bottom = QHBoxLayout()
        reset = button("New key", "ghost")
        reset.setToolTip("Creates a new pairing key. Phones paired before will need to pair again.")
        reset.clicked.connect(self.new_key)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        done = button("Done", "primary")
        done.clicked.connect(self.accept)
        bottom.addWidget(done)
        lay.addLayout(bottom)

    def set_pairing(self, uri: str, name: str, hosts: list[str], port: int) -> None:
        self.qr.setPixmap(qr_pixmap(uri, 3))
        where = ", ".join(hosts) if hosts else "no network found"
        self.details.setText(f"{name} · {where} · port {port}")
        self.set_status("Waiting for your phone…  (keep this window open)", ok=False)

    def set_status(self, text: str, ok: bool) -> None:
        self.status.setText(text)
        self.status.setProperty("role", "" if ok else "muted")
        self.status.setStyleSheet("font-weight: 600; color: #10B981;" if ok else "")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def show_success(self, device: str) -> None:
        self.set_status(f"✓ {device} is connected — you can close this window", ok=True)


class PairRequestDialog(QDialog):
    """“Galaxy A54 wants to pair — code 482 193 — Allow?”"""

    def __init__(self, parent, device: str, code: str):
        super().__init__(parent)
        self.setWindowTitle("Pairing request")
        self.setFixedWidth(380)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label(f"Pair with {device}?", "title"))
        lay.addWidget(label("Your phone is showing a code. Allow only if it's the same:", "muted", wrap=True))
        code_lbl = label(f"{code[:3]} {code[3:]}")
        code_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code_lbl.setStyleSheet("font-size: 30pt; font-weight: 700; letter-spacing: 4px; padding: 8px;")
        lay.addWidget(code_lbl)
        row = QHBoxLayout()
        row.addStretch(1)
        deny = button("Deny")
        deny.clicked.connect(self.reject)
        allow = button("Allow", "primary")
        allow.setMinimumWidth(110)
        allow.clicked.connect(self.accept)
        row.addWidget(deny)
        row.addWidget(allow)
        lay.addLayout(row)
