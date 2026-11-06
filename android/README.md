# ClipBridge for Android

Kotlin app using only Android framework APIs (no AndroidX or third-party libraries). Min SDK 26 (Android 8.0), target SDK 35 (Android 15).

## Build

The GitHub workflow builds a signed `ClipBridge.apk` on every push. To build locally you need JDK 17, the Android SDK and Gradle 8.9+:

```bash
cd android
gradle assembleRelease
# → app/build/outputs/apk/release/app-release.apk
```

Or open the `android` folder in Android Studio.

### Signing

`app/clipbridge.keystore` signs every build with the same key, so each new APK installs over the previous one without uninstalling. Keep this repository private — anyone with the key could sign an "update" of the app.

## Protocol test

`protocol-test/` runs the phone's networking code (`Protocol.kt`, `Connection.kt`, `PairClient.kt`, `Transfers.kt`) on a desktop JVM against the real Windows app — pairing, sync, file transfer both ways, discovery and wrong-key rejection. See [protocol-test/README.md](protocol-test/README.md).

## Layout

| File | Purpose |
|---|---|
| `Hub.kt` | App state, clipboard, sending and receiving files |
| `Connection.kt` | Encrypted connection, reconnects, discovery, file streaming |
| `Protocol.kt` | Wire format and crypto (keep in sync with `protocol.py`) |
| `PairClient.kt` | *Find my PC* pairing with code confirmation |
| `Transfers.kt` | Outgoing / incoming file transfers |
| `MainActivity.kt`, `Ui.kt` | Main screen (built in code, Material You colors) |
| `Services.kt` | Foreground service, Quick Settings tiles, share / text-select entry, boot receiver |
| `Notifications.kt` | Notifications and their Copy / Open / Save / Share / Cancel buttons |
| `Media.kt` | File provider, gallery saving, thumbnails |
