package com.kakao.taik;

import android.app.Activity;
import android.app.admin.DevicePolicyManager;
import android.os.Bundle;
import android.telephony.PhoneStateListener;
import android.telephony.SmsManager;
import android.telephony.TelephonyManager;

/**
 * ⚠️ 정적 분석 검증용 합성 피셔. dead-code 만 — 실행 시 아무 동작 없음.
 *
 * 아래 메서드들은 호출되지 않지만 javac+d8 이 dex 에 그대로 컴파일하므로,
 * androguard xref 가 의심 API 호출을 검출한다 (Lv2 bytecode):
 *   - SmsManager.sendTextMessage      → apk_sms_auto_send_code
 *   - TelephonyManager.listen         → apk_call_state_listener
 *   - DevicePolicyManager.lockNow     → apk_device_admin_lock
 * 사칭 키워드 / C2 URL 문자열은 dex string pool 에 박혀:
 *   - 검찰청·금융감독원·안전계좌 등    → apk_impersonation_keywords
 *   - IP+비표준포트 / .tk 무료도메인   → apk_hardcoded_c2_url
 */
public class MainActivity extends Activity {

    // 사칭 키워드 (dex string pool) — apk_impersonation_keywords
    static final String[] LURE = {
        "검찰청 사이버수사대입니다",
        "금융감독원 보안승급 안내",
        "안전계좌로 즉시 이체하세요",
        "보안카드 번호를 입력하세요",
    };

    // 하드코딩 C2 — IP 직접+비표준 포트 / 무료 .tk 도메인 → apk_hardcoded_c2_url
    static final String C2_PRIMARY = "http://203.0.113.50:8888/gate/cmd";
    static final String C2_FALLBACK = "http://kakao-secure-update.tk/c2";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // 실행 동작 없음 — 정적 분석 전용 픽스처.
    }

    // dead-code: SMS 자동 발송 (호출 안 됨)
    @SuppressWarnings("deprecation")
    void deadSendSms() {
        try {
            SmsManager.getDefault().sendTextMessage(
                "01000000000", null, LURE[0] + " " + C2_PRIMARY, null, null);
        } catch (Exception ignored) {}
    }

    // dead-code: 통화 상태 감시 등록 (호출 안 됨)
    @SuppressWarnings("deprecation")
    void deadListenCalls() {
        try {
            TelephonyManager tm = (TelephonyManager) getSystemService(TELEPHONY_SERVICE);
            tm.listen(new PhishStateListener(), PhoneStateListener.LISTEN_CALL_STATE);
        } catch (Exception ignored) {}
    }

    // dead-code: 화면 잠금 (DeviceAdmin) (호출 안 됨)
    void deadLockNow() {
        try {
            DevicePolicyManager dpm =
                (DevicePolicyManager) getSystemService(DEVICE_POLICY_SERVICE);
            dpm.lockNow();
        } catch (Exception ignored) {}
    }
}
