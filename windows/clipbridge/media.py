"""Image helpers (Qt): PNG encoding, thumbnails for the phone, previews for the UI."""
from __future__ import annotations

import base64
import hashlib

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

THUMB_SIDE = 220


def to_png(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba.data())


def digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def thumb_b64(img: QImage, side: int = THUMB_SIDE) -> str:
    """Small JPEG (a few KB) sent along with history items so the phone can show a preview."""
    scaled = img.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    flat = QImage(scaled.size(), QImage.Format.Format_RGB32)
    flat.fill(QColor("white"))
    p = QPainter(flat)
    p.drawImage(0, 0, scaled)
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    flat.save(buf, "JPEG", 72)
    buf.close()
    return base64.b64encode(bytes(ba.data())).decode("ascii")


def pixmap_from_b64(data: str | None, max_w: int, max_h: int) -> QPixmap | None:
    if not data:
        return None
    img = QImage.fromData(base64.b64decode(data))
    if img.isNull():
        return None
    return QPixmap.fromImage(img.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))


def pixmap_from_file(path: str, max_w: int, max_h: int) -> QPixmap | None:
    img = QImage(path)
    if img.isNull():
        return None
    return QPixmap.fromImage(img.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
