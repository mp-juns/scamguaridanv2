#!/usr/bin/env bash
#
# 동적 분석 검증용 ACTIVE 테스트 APK 빌드. 무해(RFC5737 비라우팅 + SIM 없는 redroid).
# fake_phishing_app/build.sh 와 동일 툴체인 — 난독화용 더미 클래스만 제외.
#
# 필요 도구: Android SDK (build-tools;34.0.0 + platforms;android-34) + JDK.
# 산출물: tests/fixtures/dynamic_active.apk
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_APK="$(cd "$HERE/.." && pwd)/dynamic_active.apk"

SDK="${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}"
BT="$SDK/build-tools/34.0.0"
ANDROID_JAR="$SDK/platforms/android-34/android.jar"
AAPT2="$BT/aapt2"; D8="$BT/d8"; ZIPALIGN="$BT/zipalign"; APKSIGNER="$BT/apksigner"

for t in "$AAPT2" "$D8" "$ZIPALIGN" "$APKSIGNER" "$ANDROID_JAR"; do
  [ -e "$t" ] || { echo "❌ 누락: $t — Android SDK build-tools;34.0.0 + platforms;android-34 설치 필요"; exit 1; }
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

# 1) aapt2 link — 바이너리 매니페스트 + resources.arsc
"$AAPT2" link -I "$ANDROID_JAR" --manifest "$HERE/AndroidManifest.xml" \
  --min-sdk-version 24 --target-sdk-version 34 --java "$BUILD/gen" -o "$BUILD/base.apk"
echo "✓ aapt2 link"

# 2) javac
find "$HERE/src" "$BUILD/gen" -name '*.java' > "$BUILD/sources.txt"
"$JAVAC" -encoding UTF-8 -source 8 -target 8 -classpath "$ANDROID_JAR" \
  -d "$BUILD/classes" @"$BUILD/sources.txt"
echo "✓ javac ($(wc -l < "$BUILD/sources.txt") files)"

# 3) d8 → classes.dex
JAR="$(dirname "$JAVAC")/jar"; [ -x "$JAR" ] || JAR="jar"
"$JAR" cf "$BUILD/classes.jar" -C "$BUILD/classes" .
"$D8" --min-api 24 --lib "$ANDROID_JAR" --output "$BUILD/dexout" "$BUILD/classes.jar"
cp "$BUILD/dexout/classes.dex" "$BUILD/classes.dex"
( cd "$BUILD" && zip -q base.apk classes.dex )
echo "✓ d8"

# 4) zipalign + 자체 서명
"$ZIPALIGN" -f -p 4 "$BUILD/base.apk" "$BUILD/aligned.apk"
KS="$BUILD/test.jks"
keytool -genkeypair -keystore "$KS" -storepass android -keypass android \
  -alias test -keyalg RSA -keysize 2048 -validity 3650 \
  -dname "CN=ScamGuardian DynTest, OU=QA, O=Test, L=Gwangju, C=KR" 2>/dev/null
"$APKSIGNER" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$OUT_APK" "$BUILD/aligned.apk"
echo "✓ apksigner"

rm -rf "$BUILD"
echo ""
echo "✅ 완료: $OUT_APK"
