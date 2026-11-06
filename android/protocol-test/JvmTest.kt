import com.farhan.clipbridge.*
import java.net.InetAddress
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

class TestListener(private val p: Pairing?, private val lastGood: Pair<String, Int>? = null) : Connection.Listener {
    val incoming = java.util.concurrent.ConcurrentHashMap<String, Incoming>()
    val finished = LinkedBlockingQueue<Pair<String, Boolean>>()
    var conn: Connection? = null
    override fun onBinary(frame: ByteArray) {
        val id = String(frame, 1, 12, Charsets.US_ASCII)
        incoming[id]?.write(frame, 13, frame.size - 13)
    }
    val statuses = LinkedBlockingQueue<Connection.Status>()
    val messages = LinkedBlockingQueue<String>()
    var good: Pair<String, Int>? = null
    override fun pairing() = p
    override fun deviceName() = "Redmi \"Note\" 13"
    override fun lastGoodAddress() = lastGood
    override fun onGoodAddress(host: String, port: Int) { good = host to port }
    override fun onStatus(status: Connection.Status) { statuses.add(status) }
    override fun onMessage(json: String) {
        val id = Regex("\"id\":\"([0-9a-f]{12})\"").find(json)?.groupValues?.get(1)
        if (json.startsWith("{\"t\":\"file_offer\"") && id != null) {
            incoming[id] = Incoming(id, java.io.File.createTempFile("incoming", ".bin"), -1, null)
        } else if (json.startsWith("{\"t\":\"file_done\"") && id != null) {
            val sha = Regex("\"sha256\":\"([0-9a-f]+)\"").find(json)!!.groupValues[1]
            val inc = incoming.remove(id)!!
            val ok = inc.finish(sha)
            finished.add(sha to ok)
            conn?.send("{\"t\":\"file_ack\",\"id\":\"$id\",\"ok\":$ok}")
        }
        messages.add(json)
    }
    override fun log(msg: String) { println("    log: $msg") }
    fun waitStatus(s: Connection.Status, sec: Long = 15): Boolean {
        val end = System.currentTimeMillis() + sec * 1000
        while (System.currentTimeMillis() < end) { if (statuses.poll(500, TimeUnit.MILLISECONDS) == s) return true }
        return false
    }
    fun waitMsg(type: String, sec: Long = 10): String? {
        val end = System.currentTimeMillis() + sec * 1000
        while (System.currentTimeMillis() < end) { val m = messages.poll(500, TimeUnit.MILLISECONDS) ?: continue; if (m.contains("\"t\":\"$type\"")) return m }
        return null
    }
}

var failures = 0
fun check(name: String, ok: Boolean, detail: Any? = "") { println((if (ok) "PASS " else "FAIL ") + name + " " + (detail ?: "")); if (!ok) failures++ }

fun main(args: Array<String>) {
    val uri = args[0]
    val local = listOf(InetAddress.getByName("127.0.0.1"))

    // 0) "Find my PC" pairing
    val found = PairClient.discover(3000, local)
    check("pairing discovery finds the PC", found.any { it.port == 47821 }, found)
    val pcFound = found.first { it.port == 47821 }.copy(host = "127.0.0.1")
    val attempt = PairClient.begin(pcFound, "Tester Allow")
    val answer = attempt.await()
    check("Allow returns the key", answer.contains("\"ok\": true") && answer.contains("\"k\""), answer.take(80))
    check("both sides show the same code", answer.contains("\"test_code\": \"${attempt.code}\""), attempt.code)
    val keyB64 = Regex("\"k\": \"([^\"]+)\"").find(answer)!!.groupValues[1]
    val denied = PairClient.begin(pcFound, "Tester Deny").await()
    check("Deny is reported", denied.contains("\"ok\": false"), denied)
    val late = try { PairClient.begin(pcFound, "Tester Late"); "no error" } catch (e: PairException) { e.message ?: "" }
    check("pairing closed is explained", late.contains("Pair phone"), late)
    check("closed pairing isn't discoverable", PairClient.discover(1500, local).isEmpty())

    val p = Pairing.parse(uri)!!
    check("paired key matches the PC's key", p.keyText() == keyB64)
    check("pairing URI parses", p.key.size == 32 && p.port == 47821, p.hosts)
    check("bad URI rejected", Pairing.parse("https://example.com") == null && Pairing.parse("clipbridge://pair?k=abc") == null)

    // 1) unreachable address first, then localhost: falls through to the working one
    val p1 = Pairing(p.key, p.port, listOf("10.255.255.1", "127.0.0.1"), p.pcName)
    val l1 = TestListener(p1)
    val c1 = Connection(l1); l1.conn = c1; c1.start()
    check("connects (after skipping dead IP)", l1.waitStatus(Connection.Status.CONNECTED, 20))
    val state = l1.waitMsg("state")
    check("state from PC", state != null && state.contains("\"pc_name\""), state?.take(120))
    check("remembers working address", l1.good == ("127.0.0.1" to 47821), l1.good)
    c1.send("{\"t\":\"send\",\"text\":\"Sent from Kotlin — বাংলা ✓\"}")
    val h = l1.waitMsg("history")
    check("send reaches PC history (unicode intact)", h != null && h.contains("বাংলা"), h?.take(160))
    val pc = l1.waitMsg("pc_clip", 10)
    check("receives pc_clip when PC copies", pc != null && pc.contains("copied on the PC"), pc?.take(140))
    val push = l1.waitMsg("push", 10)
    check("receives push from PC", push != null && push.contains("copied on the PC"), push?.take(140))
    val got = l1.finished.poll(20, TimeUnit.SECONDS)
    check("PC → phone file arrives intact (sha256)", got != null && got.second && got.first == args[2], got)

    // phone → PC file, with a progress callback
    val data = ByteArray(2_500_000) { (it * 31 % 251).toByte() }
    val tid = Proto.newId()
    val offer = "{\"t\":\"file_offer\",\"id\":\"$tid\",\"kind\":\"file\",\"name\":\"from-phone.mp4\",\"mime\":\"video/mp4\",\"size\":${data.size}}"
    val outgoing = Outgoing(tid, offer, java.io.ByteArrayInputStream(data), data.size.toLong())
    var progressCalls = 0
    val sentOk = LinkedBlockingQueue<Boolean>()
    outgoing.onProgress = { progressCalls++ }
    outgoing.onFinished = { _, ok -> sentOk.add(ok) }
    check("file queued", c1.sendFile(outgoing))
    check("upload finished", sentOk.poll(20, TimeUnit.SECONDS) == true, "progress callbacks: $progressCalls")
    val ack = l1.waitMsg("file_ack", 10)
    check("PC verified the upload", ack != null && ack.contains("\"ok\":true") && ack.contains(tid), ack)
    val savedFile = java.io.File(args[1], "from-phone.mp4")
    check("PC saved identical bytes", savedFile.exists() && savedFile.readBytes().contentEquals(data), savedFile)
    println("  waiting 25s to check keepalive ping/pong…")
    val pong = l1.waitMsg("pong", 30)
    check("keepalive ping answered", pong != null)
    check("still connected", c1.isConnected)
    c1.stop()

    // 2) all QR addresses dead -> UDP discovery finds the PC
    val p2 = Pairing(p.key, p.port, listOf("10.255.255.1"), p.pcName)
    val l2 = TestListener(p2)
    val c2 = Connection(l2); c2.extraDiscoveryTargets = listOf(InetAddress.getByName("127.0.0.1")); c2.start()
    check("discovery used", l2.waitStatus(Connection.Status.SEARCHING, 15))
    check("connected via discovery", l2.waitStatus(Connection.Status.CONNECTED, 15), l2.good)
    c2.stop()

    // 3) wrong key -> REJECTED
    val bad = Pairing(ByteArray(32) { 7 }, p.port, listOf("127.0.0.1"), p.pcName)
    val l3 = TestListener(bad)
    val c3 = Connection(l3); c3.start()
    check("wrong key reported as REJECTED", l3.waitStatus(Connection.Status.REJECTED, 15))
    c3.stop()
    println(if (failures == 0) "ALL JVM CHECKS PASSED" else "$failures FAILED")
    System.exit(if (failures == 0) 0 else 1)
}
