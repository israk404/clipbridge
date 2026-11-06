# How it works

[← Back to README](../README.md)

## Architecture

```
┌──────────────────────────┐        Wi-Fi / Tailscale         ┌──────────────────────────┐
│ Windows app (the hub)    │  TCP 47821  ◄──── encrypted ────► │ Android app              │
│ • clipboard watcher      │  UDP 47822  ◄── discovery/pair ──  │ • foreground service     │
│ • shared history         │                                   │ • Quick Settings tiles   │
│ • received files         │                                   │ • share / text-select    │
└──────────────────────────┘                                   └──────────────────────────┘
```

- The **PC is the hub**: it runs a TCP server on port **47821** and a UDP responder on **47822**, and keeps the shared history in `%APPDATA%\ClipBridge`.
- The **phone** keeps one connection open from a foreground service, tries its last good address first, then every address it was given at pairing, then UDP broadcast discovery — so it finds the PC again when the PC's IP changes.
- Android only allows reading the clipboard while an app has focus. The tiles, the share entry and the text-selection entry open an invisible screen for a split second to read it.

## Pairing

1. While **Pair phone** is open, the PC answers pairing broadcasts.
2. Phone and PC do an **ECDH P-256** key exchange over TCP.
3. Both derive a 6-digit code from the shared secret and show it. A device in the middle would produce different codes on the two screens.
4. When you click **Allow**, the PC sends its random 256-bit pairing key (and its addresses) encrypted with the exchanged secret.

## Sessions

- Each connection starts with both sides sending 16 random bytes; the session key is `HMAC-SHA256(pairing key, nonces)`.
- Every frame is **AES-256-GCM** encrypted. The nonce is (direction, frame counter) and is never sent, so a wrong key, tampering, replay or reordering simply drops the connection.
- Messages are small JSON objects (`push`, `pc_clip`, `history`, `send`, …). The phone pings every 20 seconds.

## File transfer

- A transfer is a `file_offer`, then encrypted binary chunks of **256 KB**, then `file_done` with a **SHA-256** of the whole file. The receiver answers `file_ack`; either side can send `file_cancel`.
- Control messages always go ahead of file data, so text still arrives instantly during a big upload.
- Clipboard images use the same mechanism (`kind: "clip_image"`). History items carry a small JPEG thumbnail; the full image is fetched only when you copy it.

## Source map

| Concern | Windows (`windows/clipbridge/`) | Android (`android/app/src/main/java/com/farhan/clipbridge/`) |
|---|---|---|
| Wire protocol & crypto | `protocol.py` | `Protocol.kt` |
| Connection | `server.py` | `Connection.kt` |
| Pairing | `server.py`, `ui.py` (`PairRequestDialog`) | `PairClient.kt` |
| File transfer | `transfers.py` | `Transfers.kt`, `Hub.kt` |
| App state & logic | `app.py`, `core.py` | `Hub.kt` |
| UI | `ui.py`, `theme.py`, `media.py` | `MainActivity.kt`, `Ui.kt`, `Notifications.kt`, `Services.kt` (tiles, share), `Media.kt` |

Change `protocol.py` and `Protocol.kt` together — the two must stay byte-compatible.
