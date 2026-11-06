# Protocol test

Runs the Android app's network code on a desktop JVM against the real Windows app.

```bash
# 1. start the Windows app offscreen in test mode (prints URI, SAVE and PCSHA lines)
python windows/tests/serve_for_jvm.py > /tmp/srv.log &

# 2. compile and run the test (needs kotlinc 2.x)
cd android/protocol-test
SRC=../app/src/main/java/com/farhan/clipbridge
kotlinc $SRC/Protocol.kt $SRC/Connection.kt $SRC/PairClient.kt $SRC/Transfers.kt JvmTest.kt \
  -include-runtime -d jvmtest.jar
java -jar jvmtest.jar "$(grep ^URI /tmp/srv.log | cut -d' ' -f2)" \
  "$(grep ^SAVE /tmp/srv.log | cut -d' ' -f2)" "$(grep ^PCSHA /tmp/srv.log | cut -d' ' -f2)"
```

It checks pairing (code match, Allow, Deny, closed pairing), connecting past a dead address, sync messages, file transfer in both directions with SHA-256, keepalive, UDP discovery and wrong-key rejection.
