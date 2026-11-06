# ClipBridge for Windows

Tray app written in Python with PySide6 (Qt). It is the hub: it watches the PC clipboard, keeps the shared history, and accepts the phone's encrypted connection.

## Run from source

Requires **Python 3.10+** (python.org, tick *Add python.exe to PATH*).

```bat
windows\run.bat
```

The first run creates a virtual environment in `windows\.venv` and installs `requirements.txt`. Or manually:

```bat
cd windows
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw ClipBridge.pyw
```

## Build the portable package (any OS)

```bash
pip install ziglang
python windows/build_portable.py
```

Output: `windows/dist/ClipBridge-Windows.zip` — `ClipBridge.exe` (a small launcher compiled from `launcher/launcher.c`), the app, and a pruned Python 3.12 + PySide6 runtime for 64-bit Windows. Works on Linux, macOS or Windows; nothing needs to be installed on the target PC.

## Build a single-file exe (on Windows)

```bat
windows\build_exe.bat
```

Output: `windows\dist\ClipBridge.exe` via PyInstaller.

## Tests

The tests run the real app offscreen with a simulated phone speaking the wire protocol — pairing, text, images, files, cancel, discovery and wrong-key rejection.

```bash
cd windows
pip install -r requirements.txt
python tests/test_headless.py        # end-to-end checks
python tests/make_screenshots.py     # regenerates docs/screenshots
```

## Layout

| File | Purpose |
|---|---|
| `ClipBridge.pyw` | Entry point (used by PyInstaller and *Start with Windows*) |
| `clipbridge/app.py` | Controller: clipboard, phone events, transfers, tray |
| `clipbridge/server.py` | TCP server, UDP discovery, pairing, file streaming with flow control |
| `clipbridge/protocol.py` | Wire format and crypto (keep in sync with `Protocol.kt`) |
| `clipbridge/transfers.py` | Outgoing / incoming file transfers |
| `clipbridge/core.py` | Settings, shared history, file list |
| `clipbridge/ui.py` | Main window, popups, pairing dialogs |
| `clipbridge/theme.py`, `media.py` | Colors, painted icons, image helpers |
| `clipbridge/winsys.py` | Global hotkey, start with Windows, firewall rule |
| `assets/clipbridge.ico` | App icon |
| `launcher/` | Source of the portable package's `ClipBridge.exe` |
| `build_portable.py` | Builds `ClipBridge-Windows.zip` |

Settings and history live in `%APPDATA%\ClipBridge`; received files go to `Downloads\ClipBridge` by default.
