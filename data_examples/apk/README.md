# APK 분석 데모 샘플 (합성·무해)

ScamGuardian APK 검출(정적 Lv1/Lv2 + 동적 Lv3)을 시연하기 위한 **자체 제작 무해 테스트 APK**.
실제 멀웨어가 아니라, 탐지 대상 API/문자열/권한을 박아 분석기가 신호를 잡는지 보여주는 fixture다.

> ⚠️ 절대 실제 단말에 설치하지 말 것. 분석기 테스트/시연 전용.
> 동적 실행은 격리 VM(redroid)에서만 — 호스트 실행은 HARD BLOCK.

## 샘플

### `fake_phishing.apk` — 정적 신호 9종 (Lv1+Lv2)
소스: [`fake_phishing_app/`](fake_phishing_app/). 행동 없음(dead-code). 카카오톡 사칭.

| Tier | 신호 |
|---|---|
| Lv1 | `apk_suspicious_package_name` (`com.kakao.talk.secure` ← `com.kakao.talk` 사칭), `apk_dangerous_permissions_combo`, `apk_self_signed` |
| Lv2 | `apk_sms_auto_send_code`, `apk_call_state_listener`, `apk_accessibility_abuse`, `apk_impersonation_keywords`, `apk_hardcoded_c2_url`, `apk_device_admin_lock` |

정적에서 신호가 잡히므로 동적(Lv3)은 게이팅으로 **생략**(`skipped_static`)된다.

### `dynamic_active.apk` — 동적 신호 5종 (Lv3)
소스: [`../../tests/fixtures/dynamic_active_app/`](../../tests/fixtures/dynamic_active_app/).
정적 신호 0 → 격리 VM(redroid+Frida)에서 실제 실행 → 런타임 행동 관찰:
`apk_runtime_c2_network_call`, `apk_runtime_sms_intercepted`, `apk_runtime_overlay_attack`,
`apk_runtime_credential_exfiltration`, `apk_runtime_persistence_install`.

무해 근거: C2 목적지는 RFC5737 문서화 비라우팅 IP / `.tk` 가짜 도메인, SMS 는 더미 번호 + SIM 없는 redroid.

## 사용법

**웹 콘솔** (`http://localhost:3100/admin/apk-dynamic`):
- `fake_phishing.apk` 업로드 (동적 강제 OFF) → 정적 9종
- `dynamic_active.apk` 업로드 (동적 강제 ON, VM 기동 후) → 동적 5종

**메인 페이지**: APK 다운로드 URL 을 붙여넣으면 받아서 동일 파이프라인으로 분석.

## 재빌드

```bash
cd fake_phishing_app
ANDROID_SDK_ROOT=$HOME/Android/Sdk JAVAC=$HOME/jdk21/bin/javac bash build.sh
```

필요: Android SDK build-tools;34.0.0 + platforms;android-34, JDK, `androguard`(호스트 정적 분석).
