package com.farhan.clipbridge

import android.app.Activity
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.widget.Toast

/** Foreground service that keeps the connection to the PC open so pushes arrive instantly. */
class SyncService : Service() {
    companion object {
        @Volatile var running = false
            private set

        fun start(ctx: Context) {
            Hub.init(ctx)
            if (!Hub.isPaired) return
            try {
                ctx.startForegroundService(Intent(ctx, SyncService::class.java))
            } catch (e: Exception) {
                // Android refuses background starts in some states; the next app open retries.
            }
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, SyncService::class.java))
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private var netCallback: ConnectivityManager.NetworkCallback? = null
    private var lastNetwork: Network? = null
    private val idleCheck = object : Runnable {
        override fun run() {
            if (!Hub.keepAlive && Hub.visibleScreens == 0) stopSelf() else handler.postDelayed(this, 60_000)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Hub.init(this)
        running = true
        if (!goForeground()) return
        val cm = getSystemService(ConnectivityManager::class.java)!!
        netCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                val previous = lastNetwork
                lastNetwork = network
                if (previous != null && previous != network) Hub.conn.reconnect() else Hub.conn.kick()
            }
        }.also { cb -> try { cm.registerDefaultNetworkCallback(cb) } catch (e: Exception) { netCallback = null } }
        Hub.conn.start()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!Hub.isPaired) {
            stopSelf()
            return START_NOT_STICKY
        }
        goForeground()
        Hub.conn.start()
        Hub.conn.kick()
        handler.removeCallbacks(idleCheck)
        handler.postDelayed(idleCheck, 60_000)
        return START_STICKY
    }

    private fun goForeground(): Boolean = try {
        val n = Notifications.status(this)
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(Notifications.ID_STATUS, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(Notifications.ID_STATUS, n)
        }
        true
    } catch (e: Exception) {
        stopSelf()
        false
    }

    override fun onDestroy() {
        running = false
        handler.removeCallbacks(idleCheck)
        netCallback?.let { try { getSystemService(ConnectivityManager::class.java)?.unregisterNetworkCallback(it) } catch (_: Exception) {} }
        Hub.conn.stop()
        if (Hub.isPaired) Hub.onStatus(Connection.Status.OFFLINE) // so tiles don't show a stale "connected"
        super.onDestroy()
    }
}

/** Reconnects after a reboot or app update. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED || intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            Hub.init(ctx)
            if (Hub.isPaired && Hub.keepAlive) SyncService.start(ctx)
        }
    }
}

/**
 * Invisible screen behind the tiles, the share menu, "Send to PC" in the text-selection menu and the
 * notification buttons. It exists because Android only lets an app read the clipboard while it has focus.
 */
class ClipActivity : Activity() {
    companion object {
        const val ACTION_SEND_CLIPBOARD = "com.farhan.clipbridge.SEND_CLIPBOARD"
        const val ACTION_COPY_PC = "com.farhan.clipbridge.COPY_FROM_PC"
    }

    private var handled = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Hub.init(this)
        SyncService.start(this)
        when (intent?.action) {
            Intent.ACTION_SEND -> {
                val stream = streamExtra(intent)
                if (stream != null) finishWith(Hub.sendUris(this, listOf(stream)), files = 1)
                else finishWith(Hub.sendToPc(intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()))
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                val list = streamListExtra(intent)
                finishWith(Hub.sendUris(this, list), files = list.size)
            }
            Intent.ACTION_PROCESS_TEXT ->
                finishWith(Hub.sendToPc(intent.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT)?.toString()))
            ACTION_COPY_PC -> copyFromPc()
            ACTION_SEND_CLIPBOARD -> window.decorView.postDelayed({ sendClipboard() }, 800) // fallback if focus is late
            else -> finish()
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && intent?.action == ACTION_SEND_CLIPBOARD) sendClipboard()
    }

    @Suppress("DEPRECATION")
    private fun streamExtra(i: Intent): android.net.Uri? =
        if (Build.VERSION.SDK_INT >= 33) i.getParcelableExtra(Intent.EXTRA_STREAM, android.net.Uri::class.java)
        else i.getParcelableExtra(Intent.EXTRA_STREAM)

    @Suppress("DEPRECATION")
    private fun streamListExtra(i: Intent): List<android.net.Uri> =
        (if (Build.VERSION.SDK_INT >= 33) i.getParcelableArrayListExtra(Intent.EXTRA_STREAM, android.net.Uri::class.java)
        else i.getParcelableArrayListExtra<android.net.Uri>(Intent.EXTRA_STREAM)).orEmpty()

    private fun sendClipboard() {
        if (handled) return
        handled = true
        val clip = Hub.readClip(this)
        if (clip is Clip.Secret) {
            toast("That's marked as a password, so it wasn't sent")
            finish()
            return
        }
        finishWith(Hub.sendClipboard(this), image = clip is Clip.Image)
    }

    private fun copyFromPc() {
        handled = true
        val item = Hub.pcClip
        when {
            !Hub.isPaired -> toast("Open ClipBridge and pair with your PC first")
            item == null || (!item.isImage && item.text.isEmpty()) -> toast(
                if (item?.note == "hidden") "The PC's clipboard is a password — not synced" else "Nothing on the PC clipboard yet"
            )
            Hub.copyItemToPhone(item) -> if (Build.VERSION.SDK_INT < 33) toast("Copied from PC ✓")
            else -> {}  // an image is being fetched; Hub shows a toast when it's on the clipboard
        }
        finish()
    }

    private fun finishWith(result: SendResult, files: Int = 0, image: Boolean = false) {
        handled = true
        val what = when {
            files > 1 -> "$files files"
            files == 1 -> "File"
            image -> "Image"
            else -> ""
        }
        toast(
            when (result) {
                SendResult.SENT -> if (what.isEmpty()) "Sent to ${Hub.pcName.ifEmpty { "PC" }} ✓" else "$what sending to ${Hub.pcName.ifEmpty { "PC" }}…"
                SendResult.QUEUED -> "PC not connected — will send when it's back"
                SendResult.EMPTY -> if (files > 0) "Couldn't read that file" else "Clipboard is empty"
                SendResult.NOT_PAIRED -> "Open ClipBridge and pair with your PC first"
                SendResult.TOO_LONG -> "Too long to send (over 1 million characters)"
            }
        )
        finish()
    }

    private fun toast(msg: String) = Toast.makeText(applicationContext, msg, Toast.LENGTH_SHORT).show()
}

/** Quick Settings tiles. Both open the invisible ClipActivity, which does the work and closes. */
abstract class BaseTile : TileService() {
    abstract val action: String
    abstract val idleLabel: String

    override fun onStartListening() {
        super.onStartListening()
        Hub.init(this)
        val tile = qsTile ?: return
        val connected = Hub.status == Connection.Status.CONNECTED
        tile.state = if (connected) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        if (Build.VERSION.SDK_INT >= 29) {
            tile.subtitle = when {
                !Hub.isPaired -> "Not paired"
                connected -> Hub.pcName
                else -> "Offline"
            }
        }
        tile.updateTile()
    }

    override fun onClick() {
        super.onClick()
        Hub.init(this)
        val intent = Intent(this, ClipActivity::class.java).setAction(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (isLocked) unlockAndRun { launch(intent) } else launch(intent)
    }

    private fun launch(intent: Intent) {
        if (Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(
                PendingIntent.getActivity(this, action.hashCode(), intent,
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            )
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }
}

class SendTileService : BaseTile() {
    override val action = ClipActivity.ACTION_SEND_CLIPBOARD
    override val idleLabel = "Send to PC"
}

class CopyTileService : BaseTile() {
    override val action = ClipActivity.ACTION_COPY_PC
    override val idleLabel = "Copy from PC"
}
