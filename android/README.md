# ClipBridge for Android

Kotlin app using only Android framework APIs (no AndroidX or third-party libraries). Min SDK 26 (Android 8.0), target SDK 35 (Android 15).

## Build

The GitHub workflow (run it from the Actions tab) builds a signed `ClipBridge.apk`. To build locally you need JDK 17, the Android SDK and Gradle 8.9+:

```bash
cd android
gradle assembleRelease
# → app/build/outputs/apk/release/app-release.apk
```

Or open the `android` folder in Android Studio.

### Signing

Release builds are signed with a key that is **not** stored in this repository. In CI it comes from two repository secrets:

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | the release keystore, base64-encoded |
| `ANDROID_KEYSTORE_PASSWORD` | its password (store and key use the same one) |

Locally, set `CLIPBRIDGE_KEYSTORE` (path to the keystore) and `CLIPBRIDGE_KEYSTORE_PASSWORD` before `gradle assembleRelease`. Without them the release APK is built unsigned. Every published APK must be signed with the same key, otherwise Android refuses to install it as an update.

Certificate SHA-256: `0B:E8:E3:9A:2C:8F:90:07:AF:9D:D0:1A:52:4C:97:80:2E:5D:81:BE:11:8A:B3:2B:AD:CE:7D:89:33:E2:AC:E6`

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
