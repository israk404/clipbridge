package com.farhan.clipbridge

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.app.StatusBarManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.MediaStore
import android.provider.Settings
import android.text.InputType
import android.text.TextUtils
import android.text.format.DateUtils
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject

class MainActivity : Activity() {
    companion object {
        private const val REQ_MEDIA = 11
        private const val REQ_FILES = 12
        private const val REQ_STORAGE = 13
    }

    private lateinit var ui: Ui
    private lateinit var scroll: ScrollView
    private lateinit var headerBox: LinearLayout
    private lateinit var composeCard: LinearLayout
    private lateinit var composeInput: EditText
    private lateinit var dynamic: LinearLayout
    private val progressViews = HashMap<String, Pair<ProgressBar, TextView>>()
    private var clipPreviewKey: String? = null
    private var clipPreview: Bitmap? = null
    private var pendingSave: FileEntry? = null
    private val onHubChanged: () -> Unit = { render() }
    private val onProgress: (FileEntry) -> Unit = { e ->
        progressViews[e.id]?.let { (bar, meta) ->
            bar.progress = permille(e)
            meta.text = fileMeta(e)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Hub.init(this)
        ui = Ui(this, Palette(this))
        scroll = ScrollView(this).apply { setBackgroundColor(ui.p.bg); isFillViewport = true }
        val content = ui.vertical().apply { setPadding(ui.dp(16), ui.dp(12), ui.dp(16), ui.dp(24)) }
        headerBox = ui.vertical()
        composeCard = buildCompose()
        dynamic = ui.vertical()
        content.addView(headerBox)
        content.addView(composeCard)
        content.addView(dynamic)
        scroll.addView(content)
        setContentView(scroll)
        styleSystemBars()
        handleIntent(intent)
        askForNotifications()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        Hub.visibleScreens++
        Hub.addListener(onHubChanged)
        Hub.addProgressListener(onProgress)
        SyncService.start(this)
        Hub.conn.kick()
        render()
    }

    override fun onPause() {
        Hub.visibleScreens--
        Hub.removeListener(onHubChanged)
        Hub.removeProgressListener(onProgress)
        super.onPause()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) Hub.reportPhoneClipboard(this) // only possible while we have focus
    }

    @Deprecated("Activity result API from the framework")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data == null || (requestCode != REQ_MEDIA && requestCode != REQ_FILES)) return
        val uris = ArrayList<Uri>()
        val clip = data.clipData
        if (clip != null) for (i in 0 until clip.itemCount) clip.getItemAt(i).uri?.let { uris.add(it) }
        else data.data?.let { uris.add(it) }
        if (uris.isEmpty()) return
        val r = Hub.sendUris(this, uris)
        val n = if (uris.size == 1) "1 file" else "${uris.size} files"
        Toast.makeText(this, when (r) {
            SendResult.SENT -> "Sending $n to ${Hub.pcName}…"
            SendResult.QUEUED -> "PC not connected — $n will go when it's back"
            else -> "Couldn't read the selected file"
        }, Toast.LENGTH_SHORT).show()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_STORAGE && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            pendingSave?.let { saveEntry(it) }
        }
        pendingSave = null
    }

    // ---------------------------------------------------------------- layout
    private fun styleSystemBars() {
        val p = ui.p
        @Suppress("DEPRECATION")
        run {
            window.statusBarColor = p.bg
            window.navigationBarColor = p.bg
        }
        if (Build.VERSION.SDK_INT >= 30) {
            val light = if (p.dark) 0 else WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
            window.insetsController?.setSystemBarsAppearance(light,
                WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS)
        } else if (!p.dark) {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        }
        // Android 15 draws apps edge-to-edge: keep content clear of the status and navigation bars.
        scroll.setOnApplyWindowInsetsListener { v, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() or WindowInsets.Type.ime())
                v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            } else {
                @Suppress("DEPRECATION")
                v.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                    insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            insets
        }
        scroll.clipToPadding = false
    }

    private fun render() {
        val y = scroll.scrollY
        headerBox.removeAllViews()
        header()
        composeCard.visibility = if (Hub.isPaired) View.VISIBLE else View.GONE
        dynamic.removeAllViews()
        progressViews.clear()
        if (!Hub.isPaired) {
            pairCard()
        } else {
            if (Hub.status == Connection.Status.REJECTED) rejectedCard()
            pcCard()
            phoneCard()
            historySection()
            filesSection()
            settingsCard()
        }
        tips()
        scroll.post { scroll.scrollTo(0, y) }
    }

    private fun header() {
        val p = ui.p
        headerBox.addView(ui.text("ClipBridge", 28f, p.text, bold = true), ui.lp(top = 8, bottom = 6))
        val row = ui.horizontal()
        val color = when (Hub.status) {
            Connection.Status.CONNECTED -> p.ok
            Connection.Status.REJECTED -> p.warn
            else -> p.off
        }
        row.addView(ui.dot(color))
        row.addView(ui.text(Hub.statusText(), 14f, p.muted), ui.lp(0, weight = 1f))
        headerBox.addView(row, ui.lp(bottom = 16))
    }

    private fun buildCompose(): LinearLayout {
        val p = ui.p
        val card = ui.card()
        card.addView(ui.section("Send to PC"), ui.lp(bottom = 8))
        composeInput = EditText(this).apply {
            hint = "Type something to send to your PC…"
            setHintTextColor(p.muted)
            setTextColor(p.text)
            textSize = 16f
            minLines = 2
            maxLines = 6
            gravity = Gravity.TOP or Gravity.START
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            background = ui.rounded(p.bg, 14f, p.border)
            setPadding(ui.dp(14), ui.dp(12), ui.dp(14), ui.dp(12))
        }
        card.addView(composeInput, ui.lp(bottom = 10))
        card.addView(ui.primary("Send text") { sendComposed() }, ui.lp(bottom = 8))
        val row = ui.horizontal()
        row.addView(ui.tonal("Photo / video") { pickMedia() }, ui.lp(0, weight = 1f, end = 8))
        row.addView(ui.tonal("Any file") { pickFiles() }, ui.lp(0, weight = 1f))
        card.addView(row)
        return card
    }

    private fun pairCard() {
        val card = ui.card()
        card.addView(ui.text("Connect to your PC", 20f, bold = true), ui.lp(bottom = 8))
        card.addView(ui.text(
            "1. On your PC, open ClipBridge and click “Pair phone”.\n" +
                "2. Make sure this phone is on the same Wi-Fi.\n" +
                "3. Tap “Find my PC” and check the code matches.", 15f, ui.p.muted), ui.lp(bottom = 16))
        card.addView(ui.primary("Find my PC") { findPc() }, ui.lp(bottom = 8))
        card.addView(ui.tonal("Paste pairing link") { pasteLinkDialog() })
        dynamic.addView(card)
    }

    private fun rejectedCard() {
        val card = ui.card().apply { background = ui.rounded(ui.p.warnBg, 20f) }
        card.addView(ui.text("Your PC didn't accept this phone", 16f, bold = true), ui.lp(bottom = 4))
        card.addView(ui.text("The pairing key changed on the PC (someone pressed “New key”). Pair again: " +
            "click “Pair phone” on the PC, then tap below.", 14f, ui.p.muted), ui.lp(bottom = 12))
        card.addView(ui.primary("Find my PC") { findPc() })
        dynamic.addView(card)
    }

    private fun imageView(bmp: Bitmap?, maxHeightDp: Int): View {
        if (bmp == null) return ui.text("🖼  Image", 15f, ui.p.muted)
        return ImageView(this).apply {
            setImageBitmap(bmp)
            adjustViewBounds = true
            maxHeight = ui.dp(maxHeightDp)
            scaleType = ImageView.ScaleType.FIT_START
            clipToOutline = true
            background = ui.rounded(ui.p.bg, 12f)
        }
    }

    private fun clipCard(title: String, body: String, empty: Boolean, meta: String, image: Bitmap?, isImage: Boolean,
                         action: String?, onAction: () -> Unit) {
        val p = ui.p
        val card = ui.card()
        card.addView(ui.section(title), ui.lp(bottom = 8))
        if (isImage) card.addView(imageView(image, 220), ui.lp(ViewGroupWrap, bottom = 12))
        else card.addView(ui.text(body, if (empty) 14f else 16f, if (empty) p.muted else p.text, maxLines = 6), ui.lp(bottom = 12))
        val row = ui.horizontal()
        row.addView(ui.text(meta, 13f, p.muted, maxLines = 1), ui.lp(0, weight = 1f, end = 8))
        if (action != null) row.addView(ui.primary(action, onAction))
        card.addView(row)
        dynamic.addView(card)
    }

    private val ViewGroupWrap = android.view.ViewGroup.LayoutParams.WRAP_CONTENT

    private fun pcCard() {
        val item = Hub.pcClip
        val connected = Hub.isConnected
        if (item != null && item.isImage && item.note == null) {
            val meta = "Image ${item.w}×${item.h} · " + (if (connected) "" else "last seen ") + ago(item.ts)
            clipCard("PC clipboard", "", false, meta, Media.bitmapFromB64(item.id, item.thumb), true, "Copy to phone") {
                if (Hub.copyItemToPhone(item)) copiedToast()
            }
            return
        }
        val (body, empty) = when {
            item == null || item.note == "empty" -> "Nothing copied on the PC yet." to true
            item.note == "hidden" -> "🔒 Copied from a password manager on the PC — not synced." to true
            item.note == "nontext" -> "The PC copied something that isn't text or an image." to true
            item.note == "files" -> "📎 The PC copied files. Send them from the PC (Send to phone) to get them here." to true
            item.note == "toolarge" -> "Too large to sync." to true
            else -> item.text to false
        }
        val meta = if (item == null) "" else (if (connected) "" else "Last seen · ") + ago(item.ts)
        clipCard("PC clipboard", body, empty, meta, null, false, if (empty) null else "Copy to phone") {
            if (item != null && Hub.copyItemToPhone(item)) copiedToast()
        }
    }

    private fun phoneCard() {
        val uri = Hub.phoneClipImage
        if (uri != null) {
            val key = uri.toString()
            if (clipPreviewKey != key) {
                clipPreviewKey = key
                clipPreview = Media.thumbForUri(this, uri, 600)
            }
            val meta = if (Hub.imageShared(uri)) "PC can see this" else "Image"
            clipCard("This phone's clipboard", "", false, meta, clipPreview, true, "Send to PC") {
                val mime = contentResolver.getType(uri) ?: "image/png"
                sendResultToast(Hub.sendClipImage(this, uri, mime, "send"), image = true)
            }
            return
        }
        val text = Hub.phoneClip
        val (body, empty) = when {
            Hub.phoneClipSensitive -> "🔒 A password is on this phone's clipboard — it won't be shared." to true
            text == null -> "Nothing copied on this phone yet." to true
            else -> text to false
        }
        val meta = if (!empty && Hub.wasShared(text)) "PC can see this" else ""
        clipCard("This phone's clipboard", body, empty, meta, null, false, if (empty) null else "Send to PC") {
            sendResultToast(Hub.sendToPc(text))
        }
    }

    private fun rowBackground(): android.graphics.drawable.Drawable {
        val p = ui.p
        return android.graphics.drawable.RippleDrawable(
            ColorStateList.valueOf(if (p.dark) 0x33FFFFFF else 0x22000000),
            ui.rounded(p.card, 16f, p.border), ui.rounded(android.graphics.Color.WHITE, 16f))
    }

    private fun historySection() {
        val p = ui.p
        val head = ui.horizontal()
        head.addView(ui.section("Recent · both devices"), ui.lp(0, weight = 1f))
        if (Hub.history.any { !it.pinned }) head.addView(ui.ghost("Clear") { confirmClear() })
        dynamic.addView(head, ui.lp(top = 8, bottom = 6, start = 4))
        if (Hub.history.isEmpty()) {
            dynamic.addView(ui.text("Copies from your PC and phone show up here — the last 5, plus anything you pin.",
                14f, p.muted), ui.lp(start = 4, bottom = 16))
            return
        }
        for (item in Hub.history) {
            val row = ui.horizontal().apply {
                setPadding(ui.dp(14), ui.dp(12), ui.dp(10), ui.dp(12))
                background = rowBackground()
                isClickable = true
                setOnClickListener { if (Hub.copyItemToPhone(item)) copiedToast() }
                setOnLongClickListener { itemMenu(item); true }
            }
            row.addView(ui.badge(item.fromPc), ui.lp(ui.dp(54), end = 12).apply { gravity = Gravity.TOP })
            val col = ui.vertical()
            if (item.isImage) col.addView(imageView(Media.bitmapFromB64(item.id, item.thumb), 90), ui.lp(ViewGroupWrap, bottom = 4))
            else col.addView(ui.text(item.text.replace(Regex("\\s+"), " ").trim(), 15f, maxLines = 2))
            val who = if (item.fromPc) Hub.pcName.ifEmpty { "PC" } else item.device.ifEmpty { "Phone" }
            val kind = if (item.isImage) "Image · " else ""
            col.addView(ui.text((if (item.pinned) "📌 Pinned · " else "") + kind + who + " · " + ago(item.ts), 12.5f, p.muted))
            row.addView(col, ui.lp(0, weight = 1f))
            row.addView(ui.ghost("⋯") { itemMenu(item) })
            dynamic.addView(row, ui.lp(bottom = 8))
        }
        dynamic.addView(ui.text("Tap to copy · long-press for more", 12.5f, p.muted), ui.lp(start = 4, top = 2, bottom = 16))
    }

    private fun permille(e: FileEntry): Int = if (e.size > 0) (e.progress * 1000 / e.size).toInt().coerceIn(0, 1000) else 0

    private fun fileMeta(e: FileEntry): String {
        val who = if (e.incoming) "From ${e.device.ifEmpty { "PC" }}" else "To ${e.device.ifEmpty { "PC" }}"
        return when (e.status) {
            "receiving", "sending" -> {
                val pct = if (e.size > 0) "${permille(e) / 10}%" else Media.humanSize(e.progress)
                "$who · ${if (e.incoming) "Receiving" else "Sending"} $pct of ${Media.humanSize(e.size)}"
            }
            "done" -> "$who · ${Media.humanSize(e.size)} · " + (if (e.incoming) (if (e.saved) "Saved to gallery ✓" else "Ready") else "Delivered ✓") + " · " + ago(e.ts)
            "sent" -> "$who · ${Media.humanSize(e.size)} · Sent · ${ago(e.ts)}"
            "cancelled" -> "$who · Cancelled"
            else -> "$who · Failed"
        }
    }

    private fun glyph(mime: String) = when {
        mime.startsWith("image/") -> "🖼"
        mime.startsWith("video/") -> "🎬"
        mime.startsWith("audio/") -> "🎵"
        mime == "application/pdf" -> "📕"
        else -> "📄"
    }

    private fun filesSection() {
        val p = ui.p
        dynamic.addView(ui.section("Files"), ui.lp(top = 8, bottom = 6, start = 4))
        if (Hub.files.isEmpty()) {
            dynamic.addView(ui.text("Photos, videos and files shared with your PC show up here. " +
                "Tap Photo / video above, or use Share → Send to PC from any app.", 14f, p.muted),
                ui.lp(start = 4, bottom = 16))
            return
        }
        for (e in Hub.files.take(15)) {
            val row = ui.horizontal().apply {
                setPadding(ui.dp(12), ui.dp(10), ui.dp(8), ui.dp(10))
                background = rowBackground()
                isClickable = true
                setOnClickListener { if (e.incoming && e.status == "done") openEntry(e) else fileMenu(e) }
                setOnLongClickListener { fileMenu(e); true }
            }
            val f = e.file
            val thumb = if (f != null && e.isMedia && e.status == "done") Media.thumbFor(f, e.mime, 160) else null
            if (thumb != null) {
                row.addView(ImageView(this).apply {
                    setImageBitmap(thumb)
                    scaleType = ImageView.ScaleType.CENTER_CROP
                    clipToOutline = true
                    background = ui.rounded(p.bg, 10f)
                }, LinearLayout.LayoutParams(ui.dp(48), ui.dp(48)).apply { marginEnd = ui.dp(12) })
            } else {
                row.addView(ui.text(glyph(e.mime), 26f).apply { gravity = Gravity.CENTER },
                    LinearLayout.LayoutParams(ui.dp(48), ui.dp(48)).apply { marginEnd = ui.dp(12) })
            }
            val col = ui.vertical()
            col.addView(ui.text(e.name, 15f, maxLines = 1).apply { ellipsize = TextUtils.TruncateAt.MIDDLE })
            val meta = ui.text(fileMeta(e), 12.5f, p.muted, maxLines = 1)
            col.addView(meta)
            if (e.active) {
                val bar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
                    max = 1000
                    progress = permille(e)
                    isIndeterminate = e.size <= 0
                    progressTintList = ColorStateList.valueOf(p.accent)
                }
                col.addView(bar, ui.lp(top = 4))
                progressViews[e.id] = bar to meta
            }
            row.addView(col, ui.lp(0, weight = 1f))
            row.addView(ui.ghost(if (e.active) "Cancel" else "⋯") { if (e.active) Hub.cancelTransfer(e) else fileMenu(e) })
            dynamic.addView(row, ui.lp(bottom = 8))
        }
        dynamic.addView(View(this), ui.lp(h = ui.dp(8)))
    }

    private fun settingsCard() {
        val card = ui.card()
        card.addView(ui.section("Settings"), ui.lp(bottom = 4))
        card.addView(ui.switchRow("Auto-sync from PC", "Everything you copy on the PC (text or image) lands on this phone automatically",
            Hub.autoSync) { Hub.setAutoSync(it) })
        card.addView(ui.switchRow("Auto-copy what the PC sends", "Skip the Copy button on the notification",
            Hub.autoCopyPush) { Hub.autoCopyPush = it })
        card.addView(ui.switchRow("Save received photos & videos", "Put them in the gallery automatically (Pictures/ClipBridge)",
            Hub.autoSaveMedia) {
            Hub.autoSaveMedia = it
            if (it && Media.needsStoragePermission(this)) requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), REQ_STORAGE)
        })
        card.addView(ui.switchRow("Stay connected in background", "Needed to get the PC's messages instantly",
            Hub.keepAlive) { Hub.keepAlive = it; if (it) SyncService.start(this) })
        card.addView(ui.divider())
        card.addView(ui.tonal("Add Quick Settings tiles") { addTiles() }, ui.lp(top = 8, bottom = 8))
        val pm = getSystemService(PowerManager::class.java)!!
        if (!pm.isIgnoringBatteryOptimizations(packageName)) {
            card.addView(ui.tonal("Allow running in background") { askBatteryExemption() }, ui.lp(bottom = 8))
        }
        val row = ui.horizontal()
        row.addView(ui.ghost("Pair again") { findPc() })
        row.addView(View(this), ui.lp(0, weight = 1f))
        row.addView(ui.ghost("Unpair") { confirmUnpair() })
        card.addView(row, ui.lp(top = 4))
        dynamic.addView(card)
    }

    private fun tips() {
        dynamic.addView(ui.text(
            "Tips\n• Swipe down → “Send to PC” tile sends whatever you copied (text or image).\n" +
                "• Select text in any app → ⋮ → “Send to PC”.\n" +
                "• Gallery or any app → Share → “Send to PC” sends photos, videos and files.",
            13f, ui.p.muted), ui.lp(start = 4, top = 4))
    }

    // ---------------------------------------------------------------- actions
    private fun ago(ts: Long): String =
        if (ts <= 0) "" else if (System.currentTimeMillis() - ts < 45_000) "just now"
        else DateUtils.getRelativeTimeSpanString(ts, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS).toString()

    private fun copiedToast() {
        if (Build.VERSION.SDK_INT < 33) Toast.makeText(this, "Copied ✓", Toast.LENGTH_SHORT).show()
        render()
    }

    private fun sendResultToast(r: SendResult, image: Boolean = false) {
        val msg = when (r) {
            SendResult.SENT -> if (image) "Image sending to ${Hub.pcName}…" else "Sent to ${Hub.pcName} ✓"
            SendResult.QUEUED -> "PC not connected — will send when it's back"
            SendResult.EMPTY -> "Nothing to send"
            SendResult.NOT_PAIRED -> "Pair with your PC first"
            SendResult.TOO_LONG -> "Too large to send"
        }
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
        render()
    }

    private fun sendComposed() {
        val text = composeInput.text.toString()
        if (text.isBlank()) {
            Toast.makeText(this, "Type something first", Toast.LENGTH_SHORT).show()
            return
        }
        val r = Hub.sendToPc(text)
        if (r == SendResult.SENT || r == SendResult.QUEUED) composeInput.setText("")
        sendResultToast(r)
    }

    private fun pickMedia() {
        val intent = if (Build.VERSION.SDK_INT >= 33) {
            Intent(MediaStore.ACTION_PICK_IMAGES).putExtra(MediaStore.EXTRA_PICK_IMAGES_MAX, MediaStore.getPickImagesMaxLimit())
        } else {
            Intent(Intent.ACTION_GET_CONTENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE)
                .putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("image/*", "video/*"))
                .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        }
        launchPicker(intent, REQ_MEDIA)
    }

    private fun pickFiles() {
        launchPicker(Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE)
            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true), REQ_FILES)
    }

    private fun launchPicker(intent: Intent, req: Int) {
        if (!Hub.isConnected) Toast.makeText(this, "PC not connected — files will go when it's back", Toast.LENGTH_SHORT).show()
        try {
            @Suppress("DEPRECATION")
            startActivityForResult(intent, req)
        } catch (e: Exception) {
            Toast.makeText(this, "No file picker found on this phone", Toast.LENGTH_SHORT).show()
        }
    }

    private fun openEntry(e: FileEntry) {
        val f = e.file ?: return Toast.makeText(this, "That file is gone", Toast.LENGTH_SHORT).show()
        try {
            startActivity(Media.viewIntent(this, f, e.mime))
        } catch (ex: Exception) {
            Toast.makeText(this, "No app can open this file", Toast.LENGTH_SHORT).show()
        }
    }

    private fun saveEntry(e: FileEntry) {
        if (Media.needsStoragePermission(this)) {
            pendingSave = e
            requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), REQ_STORAGE)
            return
        }
        val where = if (e.isMedia) "gallery" else "Downloads"
        Toast.makeText(this, "Saving…", Toast.LENGTH_SHORT).show()
        Hub.saveToGallery(e) { ok ->
            Toast.makeText(this, if (ok) "Saved to $where ✓" else "Couldn't save", Toast.LENGTH_SHORT).show()
        }
    }

    private fun fileMenu(e: FileEntry) {
        val options = ArrayList<Pair<String, () -> Unit>>()
        if (e.active) options.add("Cancel" to { Hub.cancelTransfer(e) })
        if (e.incoming && e.status == "done" && e.file != null) {
            options.add("Open" to { openEntry(e) })
            if (!e.saved) options.add((if (e.isMedia) "Save to gallery" else "Save to Downloads") to { saveEntry(e) })
            options.add("Share" to {
                try { startActivity(Media.shareIntent(this, e.file!!, e.mime)) } catch (_: Exception) {}
            })
            if (e.mime.startsWith("image/")) options.add("Copy image" to {
                if (Hub.writeClipboardImage(e.file!!)) copiedToast()
            })
        }
        options.add((if (e.incoming) "Delete" else "Remove from list") to { Hub.deleteFile(e) })
        AlertDialog.Builder(this)
            .setTitle(e.name)
            .setItems(options.map { it.first }.toTypedArray()) { _, which -> options[which].second() }
            .show()
    }

    private fun itemMenu(item: Item) {
        val options = ArrayList<Pair<String, () -> Unit>>()
        options.add((if (item.isImage) "Copy image to this phone" else "Copy to this phone") to {
            if (Hub.copyItemToPhone(item)) copiedToast()
        })
        if (!item.isImage) options.add("Send to PC (shows a popup there)" to { sendResultToast(Hub.sendToPc(item.text)) })
        if (!item.isImage && Media.isLink(item.text)) options.add("Open link" to {
            try { startActivity(Media.linkIntent(item.text)) } catch (_: Exception) {}
        })
        options.add((if (item.pinned) "Unpin" else "Pin to top") to { Hub.pin(item, !item.pinned) })
        options.add("Delete" to { Hub.delete(item) })
        AlertDialog.Builder(this)
            .setTitle(if (item.isImage) "Image" else item.text.replace(Regex("\\s+"), " ").take(60))
            .setItems(options.map { it.first }.toTypedArray()) { _, which -> options[which].second() }
            .show()
    }

    private fun confirmClear() {
        AlertDialog.Builder(this).setTitle("Clear history?")
            .setMessage("Removes everything except pinned items, on both devices.")
            .setPositiveButton("Clear") { _, _ -> Hub.clearHistory() }
            .setNegativeButton("Cancel", null).show()
    }

    private fun confirmUnpair() {
        AlertDialog.Builder(this).setTitle("Unpair from ${Hub.pcName}?")
            .setMessage("You'll need to pair again to reconnect.")
            .setPositiveButton("Unpair") { _, _ -> Hub.unpair() }
            .setNegativeButton("Cancel", null).show()
    }

    // ---------------------------------------------------------------- pairing
    private fun handleIntent(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme == "clipbridge") applyPairing(data.toString())
    }

    private fun applyPairing(raw: String) {
        val p = Pairing.parse(raw)
        if (p == null) {
            Toast.makeText(this, "That isn't a ClipBridge pairing code", Toast.LENGTH_LONG).show()
            return
        }
        Hub.pair(p)
        Toast.makeText(this, "Paired with ${p.pcName} — connecting…", Toast.LENGTH_SHORT).show()
        render()
    }

    // "Find my PC": discover → show code → wait for Allow on the PC.
    @Volatile private var pairing: PairClient.Attempt? = null
    @Volatile private var pairCancelled = false

    private fun findPc() {
        pairCancelled = false
        val dlg = AlertDialog.Builder(this)
            .setTitle("Looking for your PC…")
            .setMessage("On the PC, open ClipBridge and click “Pair phone”. Both need to be on the same Wi-Fi.")
            .setNegativeButton("Cancel") { _, _ -> pairCancelled = true }
            .setCancelable(false)
            .show()
        Thread {
            var found: List<PairClient.Found> = emptyList()
            val deadline = System.currentTimeMillis() + 45_000
            while (!pairCancelled && found.isEmpty() && System.currentTimeMillis() < deadline) {
                found = try { PairClient.discover(2_500) } catch (e: Exception) { emptyList() }
            }
            runOnUiThread {
                if (isFinishing || pairCancelled) return@runOnUiThread
                dlg.dismiss()
                when {
                    found.isEmpty() -> AlertDialog.Builder(this).setTitle("No PC found")
                        .setMessage("Check that “Pair phone” is open on the PC and both are on the same Wi-Fi " +
                            "(set to Private on Windows). Guest Wi-Fi networks often block this.")
                        .setPositiveButton("Try again") { _, _ -> findPc() }
                        .setNeutralButton("Paste link") { _, _ -> pasteLinkDialog() }
                        .setNegativeButton("Cancel", null).show()
                    found.size == 1 -> beginPairing(found[0])
                    else -> AlertDialog.Builder(this).setTitle("Which PC?")
                        .setItems(found.map { "${it.name}  (${it.host})" }.toTypedArray()) { _, i -> beginPairing(found[i]) }
                        .setNegativeButton("Cancel", null).show()
                }
            }
        }.start()
    }

    private fun beginPairing(pc: PairClient.Found) {
        pairCancelled = false
        val waiting = AlertDialog.Builder(this).setTitle("Connecting to ${pc.name}…")
            .setNegativeButton("Cancel") { _, _ -> pairCancelled = true; pairing?.cancel() }
            .setCancelable(false).show()
        Thread {
            try {
                val attempt = PairClient.begin(pc, Hub.deviceName())
                pairing = attempt
                runOnUiThread {
                    if (pairCancelled) { attempt.cancel(); return@runOnUiThread }
                    waiting.setTitle(attempt.code.substring(0, 3) + " " + attempt.code.substring(3))
                    waiting.setMessage("Check that ${pc.name} shows this same code, then click Allow on the PC.")
                }
                val answer = JSONObject(attempt.await())
                runOnUiThread {
                    waiting.dismiss()
                    if (!answer.optBoolean("ok")) {
                        message("Not paired", "The PC said no. You can try again any time.")
                        return@runOnUiThread
                    }
                    val hosts = ArrayList<String>().apply {
                        add(pc.host)  // the address that just worked comes first
                        val arr = answer.optJSONArray("h")
                        if (arr != null) for (i in 0 until arr.length()) arr.optString(i).let { if (it.isNotBlank() && it != pc.host) add(it) }
                    }
                    val key = try { java.util.Base64.getUrlDecoder().decode(answer.optString("k")) } catch (e: Exception) { null }
                    if (key == null || key.size != 32) {
                        message("Pairing failed", "The PC sent an invalid key.")
                        return@runOnUiThread
                    }
                    val pairingInfo = Pairing(key, answer.optInt("p", pc.port), hosts, answer.optString("n", pc.name))
                    Hub.pair(pairingInfo)
                    Toast.makeText(this, "Paired with ${pairingInfo.pcName} ✓", Toast.LENGTH_SHORT).show()
                    render()
                }
            } catch (e: PairException) {
                runOnUiThread {
                    waiting.dismiss()
                    if (!pairCancelled && !isFinishing) message("Not paired", e.message ?: "Something went wrong")
                }
            } catch (e: Exception) {
                runOnUiThread {
                    waiting.dismiss()
                    if (!pairCancelled && !isFinishing) message("Not paired", e.message ?: "Something went wrong")
                }
            } finally {
                pairing = null
            }
        }.start()
    }

    private fun message(title: String, text: String) {
        if (isFinishing) return
        AlertDialog.Builder(this).setTitle(title).setMessage(text).setPositiveButton("OK", null).show()
    }

    private fun pasteLinkDialog() {
        val input = EditText(this).apply {
            hint = "clipbridge://pair?…"
            setSingleLine(false)
            maxLines = 4
            val clip = (Hub.readClip(this@MainActivity) as? Clip.Text)?.text
            if (clip != null && clip.trim().startsWith("clipbridge://")) setText(clip.trim())
        }
        val box = ui.vertical(20).apply { addView(input) }
        AlertDialog.Builder(this)
            .setTitle("Paste pairing link")
            .setMessage("On the PC: Pair phone → scan its small QR with Google Lens and copy the text, or use “Copy pairing link” and send it to yourself.")
            .setView(box)
            .setPositiveButton("Pair") { _, _ -> applyPairing(input.text.toString()) }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ---------------------------------------------------------------- permissions & setup
    private fun askForNotifications() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    private fun addTiles() {
        if (Build.VERSION.SDK_INT >= 33) {
            val sbm = getSystemService(StatusBarManager::class.java)!!
            val tiles = listOf(
                Triple(SendTileService::class.java, "Send to PC", R.drawable.ic_tile_send),
                Triple(CopyTileService::class.java, "Copy from PC", R.drawable.ic_tile_copy),
            )
            fun ask(i: Int) {
                if (i >= tiles.size) return
                val (cls, label, icon) = tiles[i]
                try {
                    sbm.requestAddTileService(ComponentName(this, cls), label, Icon.createWithResource(this, icon),
                        mainExecutor) { _ -> runOnUiThread { ask(i + 1) } }
                } catch (e: Exception) {
                    ask(i + 1)
                }
            }
            ask(0)
        } else {
            AlertDialog.Builder(this).setTitle("Add the tiles")
                .setMessage("1. Swipe down twice from the top of the screen.\n2. Tap the ✏️ (edit) button.\n" +
                    "3. Drag “Send to PC” and “Copy from PC” into your tiles.")
                .setPositiveButton("OK", null).show()
        }
    }

    private fun askBatteryExemption() {
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        } catch (e: Exception) {
            try { startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) } catch (_: Exception) {}
        }
    }
}
