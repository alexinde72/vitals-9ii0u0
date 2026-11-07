#!/bin/bash
# Build tv/vitals-tv.apk with plain SDK tools (no Gradle). Tools live in ../.tools (see README).
set -euo pipefail
cd "$(dirname "$0")"
T="$(cd ../.tools && pwd)"
export JAVA_HOME="$T/jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"
BT="$(ls -d "$T"/android/bt/*/ | head -1)"
JAR="$(ls "$T"/android/plat/*/android.jar | head -1)"
OUT=build
rm -rf "$OUT" && mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"

# icon + banner (drawn with Java2D so we need no image tools)
java Art.java res

"$BT/aapt2" compile --dir res -o "$OUT/res.zip"
"$BT/aapt2" link -I "$JAR" --manifest AndroidManifest.xml -o "$OUT/base.apk" "$OUT/res.zip" \
  --min-sdk-version 21 --target-sdk-version 34 --version-code "${VERSION_CODE:-1}" --version-name "${VERSION_NAME:-1.0}" \
  --java "$OUT/gen"
javac -nowarn -source 8 -target 8 -bootclasspath "$JAR" -d "$OUT/classes" \
  $(find "$OUT/gen" src -name '*.java') 2>&1 | grep -v "bootstrap\|source value 8\|target value 8\|To suppress\|^warning\|^[0-9] warning" || true
"$BT/d8" --release --lib "$JAR" --min-api 21 --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q -j ../unsigned.apk classes.dex)
"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

KS="$T/vitals-tv.keystore"
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -storepass vitalstv -keypass vitalstv -alias vitals \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Vitals TV" >/dev/null 2>&1
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:vitalstv --key-pass pass:vitalstv --out vitals-tv.apk "$OUT/aligned.apk"
"$BT/apksigner" verify vitals-tv.apk && echo "Built $(pwd)/vitals-tv.apk ($(du -h vitals-tv.apk | cut -f1))"
