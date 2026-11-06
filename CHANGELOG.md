# Changelog

## 2.0.1 — 2026-11-06

### Changed
- New release signing key, kept in GitHub secrets instead of the repository (the repository is now public). **Uninstall the old app once before installing 2.0.1**, then pair again — later updates install over it as usual.
- Automatic builds publish to the Releases page; an APK is also kept in `downloads/`.

## 2.0.0 — 2026-11-06

### Added
- **Images** both ways: copy a picture or screenshot on one device and get it on the other, with Copy and Save buttons; image thumbnails in the shared history.
- **Text box** in both apps to type and send.
- **Photos, videos and any file** in both directions — buttons in both apps, Android share sheet (*Send to PC*), drag & drop onto the PC window, and Explorer-copied files via the hotkey.
- **Files** list on both sides with progress bars and Cancel; SHA-256 check on every file.
- Phone: *Save to gallery*, *Share*, and an option to auto-save received photos and videos.
- PC: received files saved to `Downloads\ClipBridge` (changeable), *Open* and *Show in folder*.
- **Open** button for links on both devices.

### Changed
- Pairing is now **Find my PC** + a 6-digit code confirmed on both screens (no camera needed).

## 1.0.0 — 2026-11-06

- First release: text clipboard sync between Windows and Android, Quick Settings tiles, notifications with a Copy button, shared history of the last 5 items, auto-sync, global hotkey, tray app, encrypted connection with UDP discovery.
