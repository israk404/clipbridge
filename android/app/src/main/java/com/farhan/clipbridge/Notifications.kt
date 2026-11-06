package com.farhan.clipbridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Build
import android.widget.Toast
import java.io.File

object Notifications {
    private const val CH_STATUS = "status"
    private const val CH_INCOMING = "incoming"
    private const val CH_TRANSFERS = "transfers"
    const val ID_STATUS = 1
    private const val ID_PUSH_BASE = 100
    private var pushCounter = 0

    const val ACTION_COPY = "com.farhan.clipbridge.COPY"
    const val ACTION_COPY_PC = "com.farhan.clipbridge.COPY_PC_CLIP"
    const val ACTION_COPY_IMAGE = "com.farhan.clipbridge.COPY_IMAGE"
    const val ACTION_SAVE = "com.farhan.clipbridge.SAVE"
    const val ACTION_CANCEL = "com.farhan.clipbridge.CANCEL"
    const val EXTRA_TEXT = "text"
    const val EXTRA_PATH = "path"
    const val EXTRA_NAME = "name"
    const val EXTRA_MIME = "mime"
    const val EXTRA_ID = "id"
    const val EXTRA_NOTIFICATION = "nid"

    private const val FLAGS = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE

    fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)!!
        nm.createNotificationChannel(
            NotificationChannel(CH_INCOMING, "From your PC", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Text, images and files your PC sends you, with Copy / Open / Save buttons"
            }
        )
        nm.createNotificationChannel(
            NotificationChannel(CH_TRANSFERS, "File transfer progress", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Progress while photos, videos and files are being sent"
                setShowBadge(false)
            }
        )
        nm.createNotificationChannel(
            NotificationChannel(CH_STATUS, "Connection (keeps ClipBridge running)", NotificationManager.IMPORTANCE_MIN).apply {
                description = "Required by Android to stay connected in the background. Safe to minimise."
                setShowBadge(false)
            }
        )
    }

    private fun nm(ctx: Context) = ctx.getSystemService(NotificationManager::class.java)

    private fun post(ctx: Context, id: Int, n: Notification) {
        try { nm(ctx)?.notify(id, n) } catch (e: SecurityException) { /* notifications not allowed */ }
    }

    private fun openApp(ctx: Context): PendingIntent =
        PendingIntent.getActivity(ctx, 0, Intent(ctx, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP), FLAGS)

    private fun receiver(ctx: Context, code: Int, action: String, fill: Intent.() -> Unit): PendingIntent =
        PendingIntent.getBroadcast(ctx, code, Intent(ctx, CopyReceiver::class.java).setAction(action).apply(fill), FLAGS)

    private fun action(label: String, pi: PendingIntent) = Notification.Action.Builder(null, label, pi).build()

    fun status(ctx: Context): Notification {
        val sendClip = PendingIntent.getActivity(
            ctx, 1,
            Intent(ctx, ClipActivity::class.java).setAction(ClipActivity.ACTION_SEND_CLIPBOARD)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), FLAGS,
        )
        val b = Notification.Builder(ctx, CH_STATUS)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle(Hub.statusText())
            .setContentText("Swipe down → tiles, or use the buttons below")
            .setContentIntent(openApp(ctx))
            .setOngoing(true)
            .setShowWhen(false)
            .setCategory(Notification.CATEGORY_SERVICE)
        if (Hub.status == Connection.Status.CONNECTED) {
            b.addAction(action("Send clipboard to PC", sendClip))
            b.addAction(action("Copy PC clipboard", receiver(ctx, 2, ACTION_COPY_PC) {}))
        }
        if (Build.VERSION.SDK_INT >= 31) b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
        return b.build()
    }

    fun updateStatus(ctx: Context) {
        if (SyncService.running) post(ctx, ID_STATUS, status(ctx))
    }

    private fun nextPushId() = ID_PUSH_BASE + (pushCounter++ % 5)

    /** Text from the PC: Copy button (+ Open for links). */
    fun showPush(ctx: Context, item: Item, pcName: String, copied: Boolean) {
        val nid = nextPushId()
        val preview = item.text.take(1500)
        val b = Notification.Builder(ctx, CH_INCOMING)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle(if (copied) "Copied from ${pcName.ifEmpty { "PC" }} ✓" else "From ${pcName.ifEmpty { "PC" }}")
            .setContentText(preview.replace(Regex("\\s+"), " ").take(200))
            .setStyle(Notification.BigTextStyle().bigText(preview))
            .setContentIntent(openApp(ctx))
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_MESSAGE)
        if (Media.isLink(item.text)) {
            b.addAction(action("Open", PendingIntent.getActivity(ctx, nid + 50, Media.linkIntent(item.text), FLAGS)))
        }
        if (!copied) {
            b.addAction(action("Copy", receiver(ctx, nid, ACTION_COPY) {
                putExtra(EXTRA_TEXT, item.text.take(200_000)); putExtra(EXTRA_NOTIFICATION, nid)
            }))
        }
        post(ctx, nid, b.build())
    }

    /** An image the PC sent on purpose: picture preview with Copy and Save. */
    fun showImagePush(ctx: Context, file: File, pcName: String, copied: Boolean) {
        val nid = nextPushId()
        val bmp: Bitmap? = Media.decodeSampled(file.path, 720)
        val b = Notification.Builder(ctx, CH_INCOMING)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle(if (copied) "Image copied from ${pcName.ifEmpty { "PC" }} ✓" else "Image from ${pcName.ifEmpty { "PC" }}")
            .setContentText(if (copied) "Paste it anywhere" else "Tap Copy to paste it anywhere")
            .setContentIntent(openApp(ctx))
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_MESSAGE)
        if (bmp != null) b.setLargeIcon(bmp).setStyle(Notification.BigPictureStyle().bigPicture(bmp))
        if (!copied) {
            b.addAction(action("Copy", receiver(ctx, nid, ACTION_COPY_IMAGE) {
                putExtra(EXTRA_PATH, file.path); putExtra(EXTRA_NOTIFICATION, nid)
            }))
        }
        b.addAction(action("Save to gallery", receiver(ctx, nid + 20, ACTION_SAVE) {
            putExtra(EXTRA_PATH, file.path); putExtra(EXTRA_NAME, "ClipBridge ${System.currentTimeMillis()}.png")
            putExtra(EXTRA_MIME, "image/png"); putExtra(EXTRA_NOTIFICATION, nid)
        }))
        post(ctx, nid, b.build())
    }

    private fun fileNid(entry: FileEntry) = 2000 + (entry.id.hashCode() and 0x3FFF)
    private fun progressNid(entry: FileEntry) = 20000 + (entry.id.hashCode() and 0x3FFF)

    /** A file that arrived from the PC: Open / Save / Share. */
    fun showFile(ctx: Context, entry: FileEntry) {
        val file = entry.file ?: return
        val nid = fileNid(entry)
        val b = Notification.Builder(ctx, CH_INCOMING)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle("From ${entry.device.ifEmpty { "PC" }}: ${entry.name}")
            .setContentText(Media.humanSize(entry.size) + if (entry.saved) " · saved to gallery ✓" else "")
            .setContentIntent(PendingIntent.getActivity(ctx, nid, Media.viewIntent(ctx, file, entry.mime), FLAGS))
            .setAutoCancel(true)
        val bmp = if (entry.isMedia) Media.thumbFor(file, entry.mime, 720) else null
        if (bmp != null) b.setLargeIcon(bmp).setStyle(Notification.BigPictureStyle().bigPicture(bmp))
        b.addAction(action("Open", PendingIntent.getActivity(ctx, nid + 1, Media.viewIntent(ctx, file, entry.mime), FLAGS)))
        if (!entry.saved) {
            b.addAction(action(if (entry.isMedia) "Save to gallery" else "Save to Downloads",
                receiver(ctx, nid + 2, ACTION_SAVE) {
                    putExtra(EXTRA_ID, entry.id); putExtra(EXTRA_PATH, file.path); putExtra(EXTRA_NAME, entry.name)
                    putExtra(EXTRA_MIME, entry.mime); putExtra(EXTRA_NOTIFICATION, nid)
                }))
        }
        b.addAction(action("Share", PendingIntent.getActivity(ctx, nid + 3, Media.shareIntent(ctx, file, entry.mime), FLAGS)))
        post(ctx, nid, b.build())
    }

    fun progress(ctx: Context, entry: FileEntry) {
        if (!entry.active) return
        val permille = if (entry.size > 0) (entry.progress * 1000 / entry.size).toInt().coerceIn(0, 1000) else 0
        val verb = if (entry.incoming) "Receiving" else "Sending"
        val n = Notification.Builder(ctx, CH_TRANSFERS)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle("$verb ${entry.name}")
            .setContentText("${Media.humanSize(entry.progress)} of ${Media.humanSize(entry.size)}")
            .setProgress(1000, permille, entry.size <= 0)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setContentIntent(openApp(ctx))
            .addAction(action("Cancel", receiver(ctx, progressNid(entry), ACTION_CANCEL) { putExtra(EXTRA_ID, entry.id) }))
            .build()
        post(ctx, progressNid(entry), n)
    }

    fun cancelProgress(ctx: Context, entry: FileEntry) {
        nm(ctx)?.cancel(progressNid(entry))
    }
}

/** Handles notification buttons. Writing to the clipboard is allowed in the background. */
class CopyReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        Hub.init(ctx)
        val nid = intent.getIntExtra(Notifications.EXTRA_NOTIFICATION, 0)
        val appCtx = ctx.applicationContext
        fun done(ok: Boolean, okMsg: String?, failMsg: String) {
            if (ok && nid != 0) appCtx.getSystemService(android.app.NotificationManager::class.java)?.cancel(nid)
            val msg = if (ok) okMsg else failMsg
            if (!msg.isNullOrEmpty()) Toast.makeText(appCtx, msg, Toast.LENGTH_SHORT).show()
        }
        val copiedMsg = if (Build.VERSION.SDK_INT < 33) "Copied ✓" else null  // Android 13+ confirms by itself
        when (intent.action) {
            Notifications.ACTION_COPY -> {
                val text = intent.getStringExtra(Notifications.EXTRA_TEXT)
                done(!text.isNullOrEmpty() && Hub.writeClipboard(text), copiedMsg, "Nothing to copy")
            }
            Notifications.ACTION_COPY_PC -> {
                val item = Hub.pcClip
                when {
                    item == null || (!item.isImage && item.text.isEmpty()) -> done(false, null, "Nothing on the PC clipboard yet")
                    else -> { if (Hub.copyItemToPhone(item)) done(true, copiedMsg, "") }
                }
            }
            Notifications.ACTION_COPY_IMAGE -> {
                val f = intent.getStringExtra(Notifications.EXTRA_PATH)?.let { File(it) }
                done(f != null && f.exists() && Hub.writeClipboardImage(f), copiedMsg, "That image is gone")
            }
            Notifications.ACTION_SAVE -> {
                val f = intent.getStringExtra(Notifications.EXTRA_PATH)?.let { File(it) }
                val entry = intent.getStringExtra(Notifications.EXTRA_ID)?.let { Hub.findFile(it) }
                if (Media.needsStoragePermission(ctx)) {
                    Toast.makeText(ctx, "Open ClipBridge once to allow saving to the gallery", Toast.LENGTH_LONG).show()
                    return
                }
                val pending = goAsync()  // copying can take a moment; keep the receiver alive until it's done
                val finish = { ok: Boolean -> done(ok, "Saved ✓", "Couldn't save"); pending.finish() }
                when {
                    entry != null -> Hub.saveToGallery(entry, finish)
                    f != null && f.exists() -> {
                        val name = intent.getStringExtra(Notifications.EXTRA_NAME) ?: f.name
                        val mime = intent.getStringExtra(Notifications.EXTRA_MIME) ?: Media.mimeFor(f.name)
                        Thread {
                            val ok = Media.saveToGallery(ctx.applicationContext, f, name, mime)
                            android.os.Handler(android.os.Looper.getMainLooper()).post { finish(ok) }
                        }.start()
                    }
                    else -> finish(false)
                }
            }
            Notifications.ACTION_CANCEL -> {
                intent.getStringExtra(Notifications.EXTRA_ID)?.let { id -> Hub.findFile(id)?.let { Hub.cancelTransfer(it) } }
            }
        }
    }
}
