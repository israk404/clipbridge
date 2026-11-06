"""Settings, shared history and small helpers (no Qt here)."""
from __future__ import annotations

import json
import os
import platform
import re
import socket
import sys
import time
import uuid
from pathlib import Path

from . import protocol

RECENT_LIMIT = 5   # unpinned items kept in history
PIN_LIMIT = 10     # pinned items kept on top of that


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    path = Path(base) / "ClipBridge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_ms() -> int:
    return int(time.time() * 1000)


def pc_name() -> str:
    return (os.environ.get("COMPUTERNAME") or platform.node() or "My PC")[:40]


def preview(text: str, limit: int = 160) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def time_ago(ts_ms: int | None) -> str:
    if not ts_ms:
        return ""
    sec = max(0, int(time.time() - ts_ms / 1000))
    if sec < 45:
        return "just now"
    if sec < 3600:
        return f"{max(1, sec // 60)} min ago"
    if sec < 86400:
        return f"{sec // 3600} h ago"
    return time.strftime("%d %b", time.localtime(ts_ms / 1000))


def make_item(text: str, src: str, device: str, kind: str = "text") -> dict:
    return {"id": uuid.uuid4().hex[:12], "kind": kind, "text": text, "src": src, "device": device,
            "ts": now_ms(), "pinned": False}


def is_link(text: str) -> bool:
    t = (text or "").strip()
    return bool(re.fullmatch(r"https?://\S+", t)) and len(t) < 4000


def default_save_dir() -> Path:
    return Path.home() / "Downloads" / "ClipBridge"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, path)


class Config:
    DEFAULTS = {
        "port": protocol.DEFAULT_PORT,
        "auto_sync": False,           # every PC copy goes straight into the phone's clipboard
        "auto_copy_incoming": False,  # phone sends go straight into the PC clipboard (no Copy button)
        "hotkey": "ctrl+alt+c",
        "paired_once": False,
        "save_dir": "",               # where received files go; empty = Downloads\\ClipBridge
    }

    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "config.json"
        data = _read_json(self.path, {})
        self.values = {**self.DEFAULTS, **{k: v for k, v in data.items() if k in self.DEFAULTS}}
        try:
            self.key = protocol.unb64u(data["key"])
            assert len(self.key) == 32
        except Exception:
            self.key = protocol.new_key()
            self.save()

    def __getitem__(self, name):
        return self.values[name]

    def set(self, name, value) -> None:
        self.values[name] = value
        self.save()

    def new_key(self) -> None:
        self.key = protocol.new_key()
        self.save()

    def save(self) -> None:
        _write_json(self.path, {**self.values, "key": protocol.b64u(self.key)})

    @property
    def save_dir(self) -> Path:
        return Path(self.values["save_dir"]) if self.values.get("save_dir") else default_save_dir()


class History:
    """Last RECENT_LIMIT items (text or image) from both devices plus pinned ones. The PC is the source of truth.
    Images live in %APPDATA%/ClipBridge/images/<id>.png; items carry a small JPEG thumbnail for the phone."""

    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "history.json"
        self.image_dir = self.path.parent / "images"
        self.image_dir.mkdir(parents=True, exist_ok=True)
        data = _read_json(self.path, {})
        self.items: list[dict] = [i for i in data.get("items", []) if isinstance(i, dict) and "text" in i]
        for i in self.items:
            i.setdefault("kind", "text")
        self.phone_clip: dict | None = data.get("phone_clip")
        self.protected: set[str] = set()   # ids still in use elsewhere (e.g. the current PC clipboard)
        self._trim()

    def save(self) -> None:
        _write_json(self.path, {"items": self.items, "phone_clip": self.phone_clip})

    def ordered(self) -> list[dict]:
        pinned = [i for i in self.items if i.get("pinned")]
        recent = [i for i in self.items if not i.get("pinned")]
        return pinned + recent

    def find(self, item_id: str) -> dict | None:
        found = next((i for i in self.items if i["id"] == item_id), None)
        if not found and self.phone_clip and self.phone_clip.get("id") == item_id:
            return self.phone_clip
        return found

    def image_path(self, item: dict) -> Path:
        return self.image_dir / f"{item['id']}.png"

    def _bump(self, existing: dict) -> tuple[dict, bool]:
        was_top = self.items and self.items[0] is existing
        existing["ts"] = now_ms()
        self.items.remove(existing)
        self.items.insert(0, existing)
        self.save()
        return existing, not was_top

    def bump(self, item_id: str) -> bool:
        """Move an item to the top. Returns True if the order changed."""
        item = next((i for i in self.items if i["id"] == item_id), None)
        return self._bump(item)[1] if item else False

    def add(self, text: str, src: str, device: str) -> tuple[dict | None, bool]:
        """Add or bump a text item. Returns (item, history_changed)."""
        if not text or not text.strip() or len(text) > protocol.MAX_TEXT:
            return None, False
        existing = next((i for i in self.items if i.get("kind", "text") == "text" and i["text"] == text), None)
        if existing:
            return self._bump(existing)
        item = make_item(text, src, device)
        self.items.insert(0, item)
        self._trim()
        self.save()
        return item, True

    def add_image(self, png: bytes, digest: str, thumb: str, w: int, h: int,
                  src: str, device: str) -> tuple[dict, bool]:
        """Add or bump an image item (deduplicated by content hash)."""
        existing = next((i for i in self.items if i.get("kind") == "image" and i.get("hash") == digest), None)
        if existing and self.image_path(existing).exists():
            return self._bump(existing)
        item = {**make_item("", src, device, "image"), "hash": digest, "thumb": thumb, "w": w, "h": h,
                "size": len(png)}
        self.image_path(item).write_bytes(png)
        self.items.insert(0, item)
        self._trim()
        self.save()
        return item, True

    def set_pinned(self, item_id: str, pinned: bool) -> bool:
        item = next((i for i in self.items if i["id"] == item_id), None)
        if not item or bool(item.get("pinned")) == pinned:
            return False
        item["pinned"] = pinned
        self._trim()
        self.save()
        return True

    def delete(self, item_id: str) -> bool:
        item = next((i for i in self.items if i["id"] == item_id), None)
        if not item:
            return False
        self.items.remove(item)
        self._drop_files([item])
        self.save()
        return True

    def clear(self) -> None:
        """Remove everything except pinned items."""
        gone = [i for i in self.items if not i.get("pinned")]
        self.items = [i for i in self.items if i.get("pinned")]
        self._drop_files(gone)
        self.save()

    def set_phone_clip(self, item: dict | None) -> None:
        old = self.phone_clip
        self.phone_clip = item
        if old and old.get("kind") == "image" and not (item and item.get("id") == old.get("id")):
            self._drop_files([old])
        self.save()

    def _drop_files(self, items: list[dict]) -> None:
        keep = {i["id"] for i in self.items} | self.protected
        if self.phone_clip:
            keep.add(self.phone_clip.get("id"))
        for i in items:
            if i.get("kind") == "image" and i["id"] not in keep:
                try:
                    self.image_path(i).unlink(missing_ok=True)
                except OSError:
                    pass

    def _trim(self) -> None:
        pinned = [i for i in self.items if i.get("pinned")][:PIN_LIMIT]
        recent = [i for i in self.items if not i.get("pinned")][:RECENT_LIMIT]
        keep = {id(i) for i in pinned + recent}
        gone = [i for i in self.items if id(i) not in keep]
        self.items = [i for i in self.items if id(i) in keep]
        self._drop_files(gone)


class FileList:
    """Files shared between the devices (this PC's view): what arrived and what was sent."""
    LIMIT = 40

    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "files.json"
        data = _read_json(self.path, [])
        self.entries: list[dict] = [e for e in data if isinstance(e, dict) and "id" in e] if isinstance(data, list) else []
        for e in self.entries:  # anything unfinished when the app closed is gone
            if e.get("status") in ("sending", "receiving"):
                e["status"] = "failed"

    def save(self) -> None:
        _write_json(self.path, self.entries[: self.LIMIT])

    def add(self, entry: dict) -> dict:
        self.entries.insert(0, entry)
        del self.entries[self.LIMIT:]
        self.save()
        return entry

    def find(self, entry_id: str) -> dict | None:
        return next((e for e in self.entries if e["id"] == entry_id), None)

    def remove(self, entry_id: str) -> None:
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        self.save()


_VIRTUAL_ADAPTERS = ("loopback", "vethernet", "virtualbox", "vmware", "hyper-v", "wsl", "docker", "vbox", "npcap")


def local_ipv4s(limit: int = 5) -> list[str]:
    """IPv4 addresses the phone can try, best first (Wi-Fi/LAN, then Tailscale/VPN)."""
    found: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the default route
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        import psutil
        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            if not st or not st.isup or any(v in name.lower() for v in _VIRTUAL_ADAPTERS):
                continue
            for a in addrs:
                if a.family == socket.AF_INET:
                    found.append(a.address)
    except Exception:
        pass
    out: list[str] = []
    for ip in found:
        if ip.startswith(("127.", "169.254.", "0.")) or ip in out:
            continue
        out.append(ip)
    # LAN addresses first, Tailscale (100.x) last
    ordered = sorted(enumerate(out), key=lambda p: (p[1].startswith("100."), p[0]))
    return [ip for _, ip in ordered][:limit]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
