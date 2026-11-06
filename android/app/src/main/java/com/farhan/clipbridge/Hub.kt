package com.farhan.clipbridge

import android.app.Application
import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.service.quicksettings.TileService
import android.util.Log
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArraySet

/** One clipboard/history entry (text or image), same shape as on the PC. */
data class Item(
    val id: String, val kind: String, val text: String, val src: String, val device: String,
    val ts: Long, val pinned: Boolean, val note: String?, val thumb: String?, val w: Int, val h: Int,
) {
    val fromPc: Boolean get() = src == "pc"
    val isImage: Boolean get() = kind == "image"

    fun toJson(): JSONObject = JSONObject()
        .put("id", id).put("kind", kind).put("text", text).put("src", src).put("device", device)
        .put("ts", ts).put("pinned", pinned).put("w", w).put("h", h)
        .apply { if (note != null) put("note", note); if (thumb != null) put("thumb", thumb) }

    companion object {
        fun from(o: JSONObject?): Item? {
            if (o == null) return null
            return Item(
                o.optString("id"), o.optString("kind", "text").ifEmpty { "text" }, o.optString("text"),
                o.optString("src", "pc"), o.optString("device"), o.optLong("ts"), o.optBoolean("pinned"),
                o.optString("note").takeIf { it.isNotEmpty() }, o.optString("thumb").takeIf { it.isNotEmpty() },
                o.optInt("w"), o.optInt("h"),
            )
        }

        fun list(a: JSONArray?): List<Item> =
            if (a == null) emptyList() else (0 until a.length()).mapNotNull { from(a.optJSONObject(it)) }
    }
}

/** A shared file as this phone sees it: received from the PC ("in") or sent to it ("out"). */
class FileEntry(
    val id: String, val name: String, val mime: String, val size: Long, val dir: String, val device: String,
    val ts: Long, @Volatile var status: String, @Volatile var progress: Long, val path: String?, var saved: Boolean,
) {
    val active: Boolean get() = status == "sending" || status == "receiving"
    val incoming: Boolean get() = dir == "in"
    val isMedia: Boolean get() = mime.startsWith("image/") || mime.startsWith("video/")
    val file: File? get() = path?.let { File(it) }?.takeIf { it.exists() }

    fun toJson(): JSONObject = JSONObject().put("id", id).put("name", name).put("mime", mime).put("size", size)
        .put("dir", dir).put("device", device).put("ts", ts).put("status", status).put("progress", progress)
        .put("path", path ?: "").put("saved", saved)

    companion object {
        fun from(o: JSONObject): FileEntry = FileEntry(
            o.optString("id"), o.optString("name"), o.optString("mime"), o.optLong("size", -1), o.optString("dir"),
            o.optString("device"), o.optLong("ts"),
            o.optString("status").let { if (it == "sending" || it == "receiving") "failed" else it },
            o.optLong("progress"), o.optString("path").ifEmpty { null }, o.optBoolean("saved"),
        )
    }
}

enum class SendResult { SENT, QUEUED, EMPTY, NOT_PAIRED, TOO_LONG }

/** What the phone's clipboard holds right now (only readable while one of our screens has focus). */
sealed class Clip {
    data class Text(val text: String) : Clip()
    data class Image(val uri: Uri, val mime: String) : Clip()
    object Secret : Clip()
    object Empty : Clip()
}

/**
 * App-wide state: pairing, what the PC told us, settings, shared files and the live connection.
 * UI state changes happen on the main thread; file transfers are handled on the connection thread.
 */
object Hub : Connection.Listener {
    private const val TAG = "ClipBridge"
    private const val FILES_LIMIT = 40
    lateinit var app: Context
        private set
    private lateinit var prefs: SharedPreferences
    private val main = Handler(Looper.getMainLooper())
    private val listeners = CopyOnWriteArraySet<() -> Unit>()
    private val progressListeners = CopyOnWriteArraySet<(FileEntry) -> Unit>()
    private val pending = ArrayDeque<String>()
    private val pendingFiles = ArrayList<Outgoing>()
    private val outgoing = ConcurrentHashMap<String, Outgoing>()
    private val incoming = ConcurrentHashMap<String, InTransfer>()
    private val lastProgressPost = ConcurrentHashMap<String, Long>()

    private class InTransfer(val inc: Incoming, val offer: JSONObject, val entry: FileEntry?)

    val conn = Connection(this)

    @Volatile private var cachedPairing: Pairing? = null
    @Volatile var status = Connection.Status.NOT_PAIRED
        private set
    var pcName = ""
        private set
    var pcClip: Item? = null
        private set
    var history: List<Item> = emptyList()
        private set
    var autoSync = false
        private set
    /** What this phone's clipboard held the last time ClipBridge could look at it. */
    var phoneClip: String? = null
        private set
    var phoneClipImage: Uri? = null
        private set
    var phoneClipSensitive = false
        private set
    val files = ArrayList<FileEntry>()
    var visibleScreens = 0

    val isPaired: Boolean get() = cachedPairing != null
    val isConnected: Boolean get() = status == Connection.Status.CONNECTED
    var autoCopyPush: Boolean
        get() = prefs.getBoolean("autoCopyPush", false)
        set(v) { prefs.edit().putBoolean("autoCopyPush", v).apply() }
    var keepAlive: Boolean
        get() = prefs.getBoolean("keepAlive", true)
        set(v) { prefs.edit().putBoolean("keepAlive", v).apply() }
    var autoSaveMedia: Boolean
        get() = prefs.getBoolean("autoSaveMedia", false)
        set(v) { prefs.edit().putBoolean("autoSaveMedia", v).apply() }

    @Synchronized
    fun init(context: Context) {
        if (::app.isInitialized) return
        app = context.applicationContext
        prefs = app.getSharedPreferences("clipbridge", Context.MODE_PRIVATE)
        cachedPairing = Pairing.fromStored(
            prefs.getString("key", null), prefs.getInt("port", Proto.DEFAULT_PORT),
            prefs.getString("hosts", null), prefs.getString("pcName", null),
        )
        pcName = cachedPairing?.pcName ?: ""
        autoSync = prefs.getBoolean("autoSync", false)
        try {
            history = Item.list(JSONArray(prefs.getString("history", "[]")))
            pcClip = prefs.getString("pcClip", null)?.let { Item.from(JSONObject(it)) }
            val arr = JSONArray(prefs.getString("files", "[]"))
            for (i in 0 until arr.length()) files.add(FileEntry.from(arr.getJSONObject(i)))
        } catch (e: Exception) {
            history = emptyList()
        }
        status = if (isPaired) Connection.Status.CONNECTING else Connection.Status.NOT_PAIRED
        Notifications.createChannels(app)
    }

    // ---------------- listeners (UI) ----------------
    fun addListener(l: () -> Unit) { listeners.add(l) }
    fun removeListener(l: () -> Unit) { listeners.remove(l) }
    fun addProgressListener(l: (FileEntry) -> Unit) { progressListeners.add(l) }
    fun removeProgressListener(l: (FileEntry) -> Unit) { progressListeners.remove(l) }

    private fun changed() {
        listeners.forEach { it() }
        try {
            TileService.requestListeningState(app, ComponentName(app, SendTileService::class.java))
            TileService.requestListeningState(app, ComponentName(app, CopyTileService::class.java))
        } catch (e: Exception) {
            // tiles not added yet
        }
    }

    private fun toast(msg: String) = main.post { Toast.makeText(app, msg, Toast.LENGTH_SHORT).show() }

    // ---------------- Connection.Listener (called on the connection thread) ----------------
    override fun pairing(): Pairing? = cachedPairing

    override fun deviceName(): String {
        val name = try { Settings.Global.getString(app.contentResolver, Settings.Global.DEVICE_NAME) } catch (e: Exception) { null }
        return (name?.takeIf { it.isNotBlank() } ?: "${Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${Build.MODEL}").take(40)
    }

    override fun lastGoodAddress(): Pair<String, Int>? {
        val host = prefs.getString("lastHost", null) ?: return null
        return host to prefs.getInt("lastPort", Proto.DEFAULT_PORT)
    }

    override fun onGoodAddress(host: String, port: Int) {
        prefs.edit().putString("lastHost", host).putInt("lastPort", port).apply()
    }

    override fun onStatus(status: Connection.Status) {
        if (status != Connection.Status.CONNECTED) failIncoming()
        main.post {
            if (this.status == status) return@post
            this.status = status
            Notifications.updateStatus(app)
            changed()
        }
    }

    override fun onMessage(json: String) {
        if (json.startsWith("{\"t\":\"file_")) {
            try {
                handleTransfer(JSONObject(json))  // stays on this thread so chunks and offers keep their order
            } catch (e: Exception) {
                Log.w(TAG, "transfer message failed", e)
            }
            return
        }
        main.post {
            try {
                handle(JSONObject(json))
            } catch (e: Exception) {
                Log.w(TAG, "bad message", e)
            }
        }
    }

    override fun onBinary(frame: ByteArray) {
        if (frame.size < 1 + Proto.ID_LEN) return
        val id = String(frame, 1, Proto.ID_LEN, Charsets.US_ASCII)
        val t = incoming[id] ?: return
        try {
            t.inc.write(frame, 1 + Proto.ID_LEN, frame.size - 1 - Proto.ID_LEN)
        } catch (e: Exception) {
            incoming.remove(id)
            t.inc.abort()
            conn.send(JSONObject().put("t", "file_cancel").put("id", id).toString())
            t.entry?.let { finishEntry(it, "failed") }
            return
        }
        t.entry?.let { progressTick(it, t.inc.received) }
    }

    override fun log(msg: String) { Log.d(TAG, msg) }

    private fun handle(o: JSONObject) {
        when (o.optString("t")) {
            "state" -> {
                pcName = o.optString("pc_name", pcName)
                pcClip = Item.from(o.optJSONObject("pc_clip"))
                history = Item.list(o.optJSONArray("history"))
                autoSync = o.optBoolean("auto_sync")
                prefs.edit().putString("pcName", pcName).putBoolean("autoSync", autoSync).apply()
                saveCaches()
                flushPending()
                Notifications.updateStatus(app)
                if (visibleScreens > 0) reportPhoneClipboard(app)
            }
            "pc_clip" -> {
                pcClip = Item.from(o.optJSONObject("item")) ?: return
                val item = pcClip!!
                if (o.optBoolean("auto") && !item.isImage && item.text.isNotEmpty()) writeClipboard(item.text)
                saveCaches()
            }
            "push" -> {
                val item = Item.from(o.optJSONObject("item")) ?: return
                if (item.text.isEmpty()) return
                if (autoCopyPush) writeClipboard(item.text)
                Notifications.showPush(app, item, pcName, copied = autoCopyPush)
            }
            "history" -> {
                history = Item.list(o.optJSONArray("history"))
                saveCaches()
            }
            "settings" -> {
                autoSync = o.optBoolean("auto_sync", autoSync)
                prefs.edit().putBoolean("autoSync", autoSync).apply()
            }
            else -> return  // pong etc.
        }
        changed()
    }

    private fun saveCaches() {
        val arr = JSONArray()
        history.forEach { arr.put(it.toJson()) }
        prefs.edit().putString("history", arr.toString()).putString("pcClip", pcClip?.toJson()?.toString()).apply()
    }

    // ---------------- file transfers: receiving (connection thread) ----------------
    private fun handleTransfer(o: JSONObject) {
        val id = o.optString("id")
        when (o.optString("t")) {
            "file_offer" -> {
                if (id.length != Proto.ID_LEN || incoming.containsKey(id)) return
                val size = o.optLong("size", -1)
                val clipImage = o.optString("kind") == "clip_image"
                val dir = if (clipImage) Media.clipDir(app) else Media.receivedDir(app)
                val limit = if (clipImage) Proto.MAX_CLIP_IMAGE else Proto.MAX_FILE
                if (size > limit || (size > 0 && dir.usableSpace < size + 50L * 1024 * 1024)) {
                    conn.send(JSONObject().put("t", "file_cancel").put("id", id).put("reason", "no space").toString())
                    toast("Not enough space on the phone for ${o.optString("name")}")
                    return
                }
                if (clipImage) {
                    val itemId = Item.from(o.optJSONObject("item"))?.id?.takeIf { it.matches(Regex("[0-9a-f]{6,32}")) } ?: id
                    trimClipCache()
                    incoming[id] = InTransfer(Incoming(id, File(dir, "$itemId.png"), size, o), o, null)
                } else {
                    val name = Media.safeName(o.optString("name"))
                    val file = File(dir, "${id}_$name")
                    val entry = FileEntry(id, name, o.optString("mime").ifEmpty { Media.mimeFor(name) }, size, "in",
                        pcName, System.currentTimeMillis(), "receiving", 0, file.path, false)
                    incoming[id] = InTransfer(Incoming(id, file, size, o), o, entry)
                    main.post {
                        files.add(0, entry)
                        trimFiles()
                        changed()
                        Notifications.progress(app, entry)
                    }
                }
            }
            "file_done" -> {
                val t = incoming.remove(id) ?: return
                val ok = t.inc.finish(o.optString("sha256"))
                conn.send(JSONObject().put("t", "file_ack").put("id", id).put("ok", ok).toString())
                main.post {
                    if (t.entry == null) onClipImage(t, ok) else onFileReceived(t.entry, ok)
                }
            }
            "file_cancel" -> {
                incoming.remove(id)?.let { t -> t.inc.abort(); t.entry?.let { finishEntry(it, "cancelled") } }
                outgoing[id]?.cancelled = true
            }
            "file_ack" -> main.post {
                files.firstOrNull { it.id == id && !it.incoming }?.let {
                    it.status = if (o.optBoolean("ok")) "done" else "failed"
                    saveFiles()
                    changed()
                }
            }
        }
    }

    private fun failIncoming() {
        for ((id, t) in incoming) {
            incoming.remove(id)
            t.inc.abort()
            t.entry?.let { finishEntry(it, "failed") }
        }
    }

    private fun progressTick(entry: FileEntry, bytes: Long) {
        entry.progress = bytes
        val now = System.currentTimeMillis()
        if (now - (lastProgressPost[entry.id] ?: 0L) < 250) return
        lastProgressPost[entry.id] = now
        main.post {
            progressListeners.forEach { it(entry) }
            Notifications.progress(app, entry)
        }
    }

    private fun finishEntry(entry: FileEntry, status: String) = main.post {
        if (!entry.active) return@post
        entry.status = status
        Notifications.cancelProgress(app, entry)
        saveFiles()
        changed()
    }

    private fun onClipImage(t: InTransfer, ok: Boolean) {
        if (!ok) return
        val file = t.inc.file
        when (t.offer.optString("purpose")) {
            "auto" -> writeClipboardImage(file)
            "get" -> if (writeClipboardImage(file) && Build.VERSION.SDK_INT < 33) toast("Image copied ✓")
            else -> {  // "push": the PC sent it on purpose
                if (autoCopyPush) writeClipboardImage(file)
                Notifications.showImagePush(app, file, pcName, copied = autoCopyPush)
            }
        }
        changed()
    }

    private fun onFileReceived(entry: FileEntry, ok: Boolean) {
        Notifications.cancelProgress(app, entry)
        entry.status = if (ok) "done" else "failed"
        if (ok) {
            entry.progress = entry.file?.length() ?: entry.progress
            if (autoSaveMedia && entry.isMedia && !Media.needsStoragePermission(app)) {
                saveToGallery(entry) { Notifications.showFile(app, entry) }
            } else {
                Notifications.showFile(app, entry)
            }
        } else {
            toast("${entry.name} arrived damaged — ask the PC to send it again")
        }
        saveFiles()
        changed()
    }

    private fun trimClipCache() {
        val files = Media.clipDir(app).listFiles()?.sortedByDescending { it.lastModified() } ?: return
        files.drop(20).forEach { it.delete() }
    }

    private fun trimFiles() {
        while (files.size > FILES_LIMIT) {
            val old = files.removeAt(files.size - 1)
            if (old.incoming && !old.active) old.file?.delete()
        }
        saveFiles()
    }

    private fun saveFiles() {
        val arr = JSONArray()
        files.take(FILES_LIMIT).forEach { arr.put(it.toJson()) }
        prefs.edit().putString("files", arr.toString()).apply()
    }

    // ---------------- file transfers: sending ----------------
    private fun queueFile(out: Outgoing): SendResult {
        if (conn.sendFile(out)) return SendResult.SENT
        pendingFiles.add(out)
        SyncService.start(app)
        conn.kick()
        return SendResult.QUEUED
    }

    /** Send photos, videos or any files the user picked or shared. Streams are opened right away. */
    fun sendUris(context: Context, uris: List<Uri>): SendResult {
        if (!isPaired) return SendResult.NOT_PAIRED
        var result = SendResult.EMPTY
        for (uri in uris) {
            val info = Media.info(context, uri)
            val stream: InputStream = try {
                context.contentResolver.openInputStream(uri) ?: continue
            } catch (e: Exception) {
                continue
            }
            val id = Proto.newId()
            val offer = JSONObject().put("t", "file_offer").put("id", id).put("kind", "file")
                .put("name", info.name).put("mime", info.mime).put("size", info.size).toString()
            val entry = FileEntry(id, info.name, info.mime, info.size, "out", pcName.ifEmpty { "PC" },
                System.currentTimeMillis(), "sending", 0, null, false)
            val out = Outgoing(id, offer, stream, info.size)
            out.onProgress = { progressTick(entry, it.sent) }
            out.onFinished = { o, ok ->
                outgoing.remove(id)
                main.post {
                    if (entry.status == "sending") {
                        entry.progress = o.sent
                        entry.status = if (ok) "sent" else if (o.cancelled) "cancelled" else "failed"
                        Notifications.cancelProgress(app, entry)
                        saveFiles()
                        changed()
                    }
                }
            }
            outgoing[id] = out
            files.add(0, entry)
            result = queueFile(out)
        }
        trimFiles()
        changed()
        return result
    }

    /** Send the phone's clipboard image (purpose "send" shows a popup on the PC; "phone_clip" just updates it). */
    fun sendClipImage(context: Context, uri: Uri, mime: String, purpose: String): SendResult {
        if (!isPaired) return SendResult.NOT_PAIRED
        if (purpose == "phone_clip" && !conn.isConnected) return SendResult.EMPTY
        val bytes = try {
            context.contentResolver.openInputStream(uri)?.use { readBounded(it, Proto.MAX_CLIP_IMAGE) }
        } catch (e: Exception) {
            null
        } ?: return SendResult.EMPTY
        if (bytes.isEmpty()) return SendResult.EMPTY
        if (bytes.size >= Proto.MAX_CLIP_IMAGE) return SendResult.TOO_LONG
        val id = Proto.newId()
        val ext = android.webkit.MimeTypeMap.getSingleton().getExtensionFromMimeType(mime) ?: "png"
        val offer = JSONObject().put("t", "file_offer").put("id", id).put("kind", "clip_image").put("purpose", purpose)
            .put("name", "clip.$ext").put("mime", mime).put("size", bytes.size).toString()
        prefs.edit().putString("lastReported", "img:$uri:${bytes.size}").apply()
        return queueFile(Outgoing(id, offer, ByteArrayInputStream(bytes), bytes.size.toLong()))
    }

    private fun readBounded(input: InputStream, limit: Long): ByteArray {
        val out = ByteArrayOutputStream()
        val buf = ByteArray(64 * 1024)
        while (out.size() < limit) {
            val n = input.read(buf)
            if (n < 0) break
            out.write(buf, 0, n)
        }
        return out.toByteArray()
    }

    private fun flushPending() {
        while (pending.isNotEmpty()) {
            if (!conn.send(pending.first())) return
            pending.removeFirst()
        }
        val waiting = ArrayList(pendingFiles)
        pendingFiles.clear()
        for (f in waiting) if (!f.cancelled && !conn.sendFile(f)) pendingFiles.add(f)
    }

    fun cancelTransfer(entry: FileEntry) {
        if (!entry.active) return
        if (entry.incoming) {
            incoming.remove(entry.id)?.inc?.abort()
        } else {
            outgoing[entry.id]?.cancelled = true
            pendingFiles.removeAll { it.id == entry.id }
        }
        conn.send(JSONObject().put("t", "file_cancel").put("id", entry.id).toString())
        entry.status = "cancelled"
        Notifications.cancelProgress(app, entry)
        saveFiles()
        changed()
    }

    fun deleteFile(entry: FileEntry) {
        cancelTransfer(entry)
        if (entry.incoming) entry.file?.delete()
        files.remove(entry)
        saveFiles()
        changed()
    }

    /** Copies into the gallery/Downloads on a background thread (videos can be big); [done] runs on main. */
    fun saveToGallery(entry: FileEntry, done: (Boolean) -> Unit = {}) {
        val f = entry.file ?: return done(false)
        Thread {
            val ok = Media.saveToGallery(app, f, entry.name, entry.mime)
            main.post {
                if (ok) {
                    entry.saved = true
                    saveFiles()
                    changed()
                }
                done(ok)
            }
        }.start()
    }

    fun findFile(id: String): FileEntry? = files.firstOrNull { it.id == id }

    // ---------------- clipboard ----------------
    private fun fingerprint(text: String) = "${text.length}:${text.hashCode()}"

    /** Writing is allowed from the background; Android 13+ shows its own "Copied" confirmation. */
    fun writeClipboard(text: String): Boolean = try {
        val cm = app.getSystemService(ClipboardManager::class.java)!!
        cm.setPrimaryClip(ClipData.newPlainText("ClipBridge", text))
        prefs.edit().putString("lastSet", fingerprint(text)).apply()
        phoneClip = text
        phoneClipImage = null
        phoneClipSensitive = false
        true
    } catch (e: Exception) {
        Log.w(TAG, "clipboard write failed", e)
        false
    }

    /** Puts an image on the phone's clipboard (served to the pasting app by FilesProvider). */
    fun writeClipboardImage(file: File): Boolean = try {
        file.setLastModified(System.currentTimeMillis())
        val uri = FilesProvider.uriFor(app, file)
        val cm = app.getSystemService(ClipboardManager::class.java)!!
        cm.setPrimaryClip(ClipData.newUri(app.contentResolver, "ClipBridge image", uri))
        prefs.edit().putString("lastSet", "img:$uri").apply()
        phoneClipImage = uri
        phoneClip = null
        true
    } catch (e: Exception) {
        Log.w(TAG, "clipboard image write failed", e)
        false
    }

    /** Copy a history item (text or image) onto this phone. Returns false if an image is still being fetched. */
    fun copyItemToPhone(item: Item): Boolean {
        if (!item.isImage) return writeClipboard(item.text)
        val cached = File(Media.clipDir(app), "${item.id}.png")
        if (cached.exists() && cached.length() > 0) return writeClipboardImage(cached)
        if (conn.send(JSONObject().put("t", "get_image").put("id", item.id).toString())) {
            toast("Getting the image from ${pcName.ifEmpty { "PC" }}…")
        } else {
            toast("PC not connected")
        }
        return false
    }

    /** Read the clipboard. Only works while one of our screens has focus (Android 10+ rule). */
    fun readClip(context: Context): Clip {
        return try {
            val cm = context.getSystemService(ClipboardManager::class.java)!!
            val clip = cm.primaryClip
            val desc = cm.primaryClipDescription
            val item = if (clip != null && clip.itemCount > 0) clip.getItemAt(0) else null
            val sensitive = Build.VERSION.SDK_INT >= 33 &&
                desc?.extras?.getBoolean(ClipDescription.EXTRA_IS_SENSITIVE) == true
            phoneClipSensitive = sensitive
            if (sensitive) return Clip.Secret.also { phoneClip = null; phoneClipImage = null }
            val uri = item?.uri
            if (uri != null) {
                val mime = context.contentResolver.getType(uri) ?: desc?.takeIf { it.mimeTypeCount > 0 }?.getMimeType(0) ?: ""
                if (mime.startsWith("image/")) {
                    phoneClipImage = uri
                    phoneClip = null
                    return Clip.Image(uri, mime)
                }
            }
            val text = item?.text?.toString() ?: item?.htmlText?.let { android.text.Html.fromHtml(it, 0).toString() }
            phoneClipImage = null
            phoneClip = text?.takeIf { it.isNotEmpty() }
            if (phoneClip != null) Clip.Text(phoneClip!!) else Clip.Empty
        } catch (e: Exception) {
            Clip.Empty
        }
    }

    /** Called when a ClipBridge screen gains focus: share the phone's clipboard so the PC can see it. */
    fun reportPhoneClipboard(context: Context) {
        when (val c = readClip(context)) {
            is Clip.Text -> {
                val fp = fingerprint(c.text)
                if (c.text.length <= Proto.MAX_TEXT && fp != prefs.getString("lastSet", null) &&
                    fp != prefs.getString("lastReported", null)) {
                    val json = JSONObject().put("t", "phone_clip").put("text", c.text).toString()
                    if (conn.send(json)) prefs.edit().putString("lastReported", fp).apply()
                }
            }
            is Clip.Image -> {
                val set = prefs.getString("lastSet", null)
                val reported = prefs.getString("lastReported", null)
                if (set != "img:${c.uri}" && reported?.startsWith("img:${c.uri}:") != true) {
                    sendClipImage(context, c.uri, c.mime, "phone_clip")
                }
            }
            else -> {}
        }
        changed()
    }

    fun wasShared(text: String?): Boolean {
        if (text == null) return false
        val fp = fingerprint(text)
        return fp == prefs.getString("lastReported", null) || fp == prefs.getString("lastSet", null)
    }

    fun imageShared(uri: Uri?): Boolean {
        if (uri == null) return false
        return prefs.getString("lastSet", null) == "img:$uri" ||
            prefs.getString("lastReported", null)?.startsWith("img:$uri:") == true
    }

    // ---------------- actions ----------------
    fun sendToPc(text: String?): SendResult {
        if (!isPaired) return SendResult.NOT_PAIRED
        if (text.isNullOrBlank()) return SendResult.EMPTY
        if (text.length > Proto.MAX_TEXT) return SendResult.TOO_LONG
        prefs.edit().putString("lastReported", fingerprint(text)).apply()
        val json = JSONObject().put("t", "send").put("text", text).toString()
        if (conn.send(json)) return SendResult.SENT
        pending.addLast(json)
        while (pending.size > 10) pending.removeFirst()
        SyncService.start(app)
        conn.kick()
        return SendResult.QUEUED
    }

    /** Send whatever is on the phone's clipboard right now (text or image). Needs focus. */
    fun sendClipboard(context: Context): SendResult = when (val c = readClip(context)) {
        is Clip.Text -> sendToPc(c.text)
        is Clip.Image -> sendClipImage(context, c.uri, c.mime, "send")
        else -> SendResult.EMPTY
    }

    fun setAutoSync(value: Boolean) {
        autoSync = value
        prefs.edit().putBoolean("autoSync", value).apply()
        conn.send(JSONObject().put("t", "set").put("auto_sync", value).toString())
        changed()
    }

    fun pin(item: Item, pinned: Boolean) {
        conn.send(JSONObject().put("t", "pin").put("id", item.id).put("pinned", pinned).toString())
    }

    fun delete(item: Item) {
        conn.send(JSONObject().put("t", "delete").put("id", item.id).toString())
    }

    fun clearHistory() {
        conn.send(JSONObject().put("t", "clear").toString())
    }

    // ---------------- pairing ----------------
    fun pair(p: Pairing) {
        prefs.edit()
            .putString("key", p.keyText()).putInt("port", p.port)
            .putString("hosts", p.hosts.joinToString(",")).putString("pcName", p.pcName)
            .remove("lastHost").remove("lastPort").remove("history").remove("pcClip")
            .apply()
        cachedPairing = p
        pcName = p.pcName
        history = emptyList()
        pcClip = null
        status = Connection.Status.CONNECTING
        SyncService.start(app)
        conn.reconnect()
        changed()
    }

    fun unpair() {
        prefs.edit().remove("key").remove("hosts").remove("pcName").remove("lastHost").remove("lastPort")
            .remove("history").remove("pcClip").apply()
        cachedPairing = null
        pcName = ""
        history = emptyList()
        pcClip = null
        status = Connection.Status.NOT_PAIRED
        conn.reconnect()
        SyncService.stop(app)
        changed()
    }

    fun statusText(): String = when (status) {
        Connection.Status.NOT_PAIRED -> "Not paired yet"
        Connection.Status.CONNECTING -> "Connecting to ${pcName.ifEmpty { "your PC" }}…"
        Connection.Status.SEARCHING -> "Looking for ${pcName.ifEmpty { "your PC" }} on this network…"
        Connection.Status.CONNECTED -> "Connected to $pcName"
        Connection.Status.OFFLINE -> "${pcName.ifEmpty { "PC" }} is offline — retrying"
        Connection.Status.REJECTED -> "$pcName didn't accept this phone — pair again"
    }
}

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Hub.init(this)
    }
}
