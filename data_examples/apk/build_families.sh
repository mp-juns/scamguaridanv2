#!/usr/bin/env bash
#
# 한국 보이스피싱 패밀리 변종 합성 APK 빌드 (무해 dead-code).
# fake_phishing_app 템플릿을 재사용해 패키지명/라벨만 패밀리별로 바꿔 찍는다.
# 산출물: data_examples/apk/{krbanker,moqhao,secretcalls}.apk
#
#   ANDROID_SDK_ROOT=$HOME/Android/Sdk JAVAC=$HOME/jdk21/bin/javac bash build_families.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$HERE/fake_phishing_app"
TEMPLATE_PKG="com.kakao.talk.secure"

SDK="${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}"
BT="$SDK/build-tools/34.0.0"
ANDROID_JAR="$SDK/platforms/android-34/android.jar"
AAPT2="$BT/aapt2"; D8="$BT/d8"; ZIPALIGN="$BT/zipalign"; APKSIGNER="$BT/apksigner"
JAVAC="${JAVAC:-$HOME/jdk21/bin/javac}"; [ -x "$JAVAC" ] || JAVAC="$(command -v javac)"
JAR="$(dirname "$JAVAC")/jar"; [ -x "$JAR" ] || JAR="jar"

# family: name|package|label
FAMILIES=(
  "krbanker|com.kbstar.kbbank.update|KB국민은행 보안"
  "moqhao|com.cj.delivery.official|CJ대한통운 택배조회"
  "secretcalls|com.secure.vaccine.fake|모바일 백신 보안"
)

build_one() {
  local name="$1" pkg="$2" label="$3"
  local out="$HERE/$name.apk"
  local gen; gen="$(mktemp -d)"
  cp -r "$TEMPLATE/src" "$gen/src"
  cp "$TEMPLATE/AndroidManifest.xml" "$gen/AndroidManifest.xml"

  # 패키지명 치환 (java package decl + manifest 컴포넌트 + class refs)
  grep -rl "$TEMPLATE_PKG" "$gen" | while read -r f; do
    sed -i "s/${TEMPLATE_PKG//./\\.}/$pkg/g" "$f"
  done
  # 앱 라벨 치환 (사용자에게 보이는 이름)
  sed -i "s/android:label=\"[^\"]*\"/android:label=\"$label\"/" "$gen/AndroidManifest.xml"

  local b="$gen/build"; mkdir -p "$b/gen" "$b/classes" "$b/dexout"
  "$AAPT2" link -I "$ANDROID_JAR" --manifest "$gen/AndroidManifest.xml" \
    --min-sdk-version 24 --target-sdk-version 34 --java "$b/gen" -o "$b/base.apk"
  find "$gen/src" "$b/gen" -name '*.java' > "$b/sources.txt"
  "$JAVAC" -encoding UTF-8 -source 8 -target 8 -classpath "$ANDROID_JAR" \
    -d "$b/classes" @"$b/sources.txt" 2>/dev/null
  "$JAR" cf "$b/classes.jar" -C "$b/classes" .
  "$D8" --min-api 24 --lib "$ANDROID_JAR" --output "$b/dexout" "$b/classes.jar" >/dev/null 2>&1
  ( cd "$b" && cp dexout/classes.dex . && zip -q base.apk classes.dex )
  "$ZIPALIGN" -f -p 4 "$b/base.apk" "$b/aligned.apk"
  local ks="$b/test.jks"
  keytool -genkeypair -keystore "$ks" -storepass android -keypass android \
    -alias test -keyalg RSA -keysize 2048 -validity 3650 \
    -dname "CN=$label, OU=QA, O=Test, L=Gwangju, C=KR" 2>/dev/null
  "$APKSIGNER" sign --ks "$ks" --ks-pass pass:android --key-pass pass:android \
    --out "$out" "$b/aligned.apk" >/dev/null
  rm -rf "$gen"
  echo "✅ $name ($pkg) → $out"
}

for spec in "${FAMILIES[@]}"; do
  IFS='|' read -r name pkg label <<< "$spec"
  build_one "$name" "$pkg" "$label"
done
echo "완료."
