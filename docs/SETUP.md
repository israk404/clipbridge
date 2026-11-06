# Setup guide

[← Back to README](../README.md)

## 1. Get the apps

Download **ClipBridge.apk** and **ClipBridge.exe** from the repository's [Releases page](https://github.com/israk404/clipbridge/releases/latest).

Prefer to build the PC app yourself? Install Python 3.10+ from python.org (tick **Add python.exe to PATH**), then double-click `windows\build_exe.bat` — or `windows\run.bat` to run it without making an exe. See [windows/README.md](../windows/README.md).

## 2. Install

**Phone** — open `ClipBridge.apk`, allow *Install unknown apps* for your browser or Files app when asked, then tap **Install**. Play Protect may warn because the app isn't from the Play Store — choose **Install anyway**.

**PC** — put `ClipBridge.exe` somewhere permanent (for example `Documents\ClipBridge`) and run it. If SmartScreen says *Windows protected your PC*, click **More info → Run anyway**.

## 3. Connect them (one time)

1. **Same Wi-Fi.** The PC may be on a cable to the same router — that's fine.
2. **Firewall.** The first time ClipBridge runs, Windows asks to allow it — tick **Private networks** and click **Allow**.
3. **Mark your network as Private.** Windows Settings → *Network & internet* → *Wi-Fi* (or *Ethernet*) → your network → *Network profile type* → **Private**. This is the most common reason a phone can't connect.
4. **Pair.** On the PC click **Pair phone**. On the phone open ClipBridge → **Find my PC**. Both screens show the same 6-digit code — if it matches, click **Allow** on the PC.
5. **On the phone**, allow notifications when asked, then in Settings tap:
   - **Add Quick Settings tiles** — adds *Send to PC* and *Copy from PC*
   - **Allow running in background** — so the PC's messages arrive instantly

Optional on the PC: turn on **Start with Windows**.

## 4. Phones that stop background apps

Xiaomi / Redmi / POCO, Samsung, realme / OPPO, vivo and Infinix / Tecno often stop apps to save battery. If messages from the PC stop arriving:

| Brand | Setting |
|---|---|
| Xiaomi / Redmi / POCO | Settings → Apps → ClipBridge → **Autostart** on, **Battery saver → No restrictions**. In Recents, pull the ClipBridge card down to lock it. |
| Samsung | Settings → Apps → ClipBridge → Battery → **Unrestricted**. Check it isn't listed under Battery → Background usage limits → *Sleeping apps*. |
| realme / OPPO / vivo | Settings → Apps → ClipBridge → Battery → **Allow background activity** and **Allow auto launch**. |

The small *Connection* notification is required by Android to stay connected. Long-press it and set that category to *Silent* or *Minimised* to keep it out of the way.

## 5. Use it away from home (optional)

Install **Tailscale** (free) on the PC and the phone and sign in with the same account. Then, on your home Wi-Fi, pair once more (**Pair phone** on the PC → **Find my PC**). The PC also hands over its Tailscale address, so ClipBridge keeps working over mobile data.

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| Phone says *Looking for your PC…* or *offline* | Same Wi-Fi? Network set to **Private** on the PC? In the PC's *Pair phone* window press **Allow through firewall**. Guest networks often block devices from seeing each other — use the main network. |
| *No PC found* when pairing | Keep **Pair phone** open on the PC. Still nothing? In that window click **Copy pairing link**, send it to yourself (WhatsApp, Telegram…), copy it on the phone and tap **Paste pairing link**. |
| *PC didn't accept this phone* | Someone pressed **New key** on the PC. Pair again. |
| The hotkey does nothing | Another app owns it — pick a different one in the PC's Settings. |
| A big video stopped half-way | Keep both devices on the same Wi-Fi and the phone awake, then send again. |
| *Save to gallery* does nothing on Android 8 / 9 | Open ClipBridge and allow storage access when asked. |
| The PC clipboard shows 🔒 | It came from a password manager, so it's deliberately not synced. |
| A note says *ClipBridge pasted from your clipboard* | Normal on Android 12+ — that's the app reading the clipboard when you tap the tile or open it. |
