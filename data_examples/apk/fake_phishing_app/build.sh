#!/usr/bin/env bash
#
# 정적 분석 데모용 합성 피셔 APK 빌드. 무해(dead-code + RFC5737/.tk 비라우팅).
# 산출물: data_examples/apk/fake_phishing.apk
#
# 필요 도구: Android SDK (build-tools;34.0.0 + platforms;android-34) + JDK.
#   ANDROID_SDK_ROOT=$HOME/Android/Sdk JAVAC=$HOME/jdk21/bin/javac bash build.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_APK="$(cd "$HERE/.." && pwd)/fake_phishing.apk"

SDK="${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}"
BT="$SDK/build-tools/34.0.0"
ANDROID_JAR="$SDK/platforms/android-34/android.jar"
AAPT2="$BT/aapt2"; D8="$BT/d8"; ZIPALIGN="$BT/zipalign"; APKSIGNER="$BT/apksigner"

for t in "$AAPT2" "$D8" "$ZIPALIGN" "$APKSIGNER" "$ANDROID_JAR"; do
  [ -e "$t" ] || { echo "❌ 누락: $t — Android SDK build-tools;34.0.0 + platforms;android-34 필요"; exit 1; }
done

JAVAC="${JAVAC:-}"
if [ -z "$JAVAC" ]; then
  if command -v javac >/dev/null 2>&1; then JAVAC="$(command -v javac)";
  elif [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/javac" ]; then JAVAC="$JAVA_HOME/bin/javac";
  elif [ -x "$HOME/jdk21/bin/javac" ]; then JAVAC="$HOME/jdk21/bin/javac";
  else echo "❌ javac 없음 — JDK 필요 (JAVAC=/path/to/javac 지정)"; exit 1; fi
fi
echo "javac: $JAVAC"

BUILD="$HERE/build"
rm -rf "$BUILD"; mkdir -p "$BUILD/gen" "$BUILD/classes" "$BUILD/dexout"

"$AAPT2" link -I "$ANDROID_JAR" --manifest "$HERE/AndroidManifest.xml" \
  --min-sdk-version 24 --target-sdk-version 34 --java "$BUILD/gen" -o "$BUILD/base.apk"
echo "✓ aapt2 link"

find "$HERE/src" "$BUILD/gen" -name '*.java' > "$BUILD/sources.txt"
"$JAVAC" -encoding UTF-8 -source 8 -target 8 -classpath "$ANDROID_JAR" \
  -d "$BUILD/classes" @"$BUILD/sources.txt"
echo "✓ javac ($(wc -l < "$BUILD/sources.txt") files)"

JAR="$(dirname "$JAVAC")/jar"; [ -x "$JAR" ] || JAR="jar"
"$JAR" cf "$BUILD/classes.jar" -C "$BUILD/classes" .
"$D8" --min-api 24 --lib "$ANDROID_JAR" --output "$BUILD/dexout" "$BUILD/classes.jar"
cp "$BUILD/dexout/classes.dex" "$BUILD/classes.dex"
( cd "$BUILD" && zip -q base.apk classes.dex )
echo "✓ d8"

"$ZIPALIGN" -f -p 4 "$BUILD/base.apk" "$BUILD/aligned.apk"
KS="$BUILD/test.jks"
keytool -genkeypair -keystore "$KS" -storepass android -keypass android \
  -alias test -keyalg RSA -keysize 2048 -validity 3650 \
  -dname "CN=Kakao Security, OU=QA, O=Test, L=Gwangju, C=KR" 2>/dev/null
"$APKSIGNER" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$OUT_APK" "$BUILD/aligned.apk"
echo "✓ apksigner"

rm -rf "$BUILD"
echo ""
echo "✅ 완료: $OUT_APK"
