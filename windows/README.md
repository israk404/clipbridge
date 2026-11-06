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

## Build ClipBridge.exe

```bat
windows\build_exe.bat
```

Output: `windows\dist\ClipBridge.exe` (single file, no Python needed). The GitHub workflow builds the same file on every push and attaches it to the latest release.

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

Settings and history live in `%APPDATA%\ClipBridge`; received files go to `Downloads\ClipBridge` by default.
