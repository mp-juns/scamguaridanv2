package com.kakao.talk.secure;

import android.app.Activity;
import android.app.admin.DevicePolicyManager;
import android.os.Bundle;
import android.telephony.PhoneStateListener;
import android.telephony.SmsManager;
import android.telephony.TelephonyManager;

/**
 * ⚠️ 정적 분석 데모용 합성 피셔. dead-code 만 — 실행 시 아무 동작 없음.
 *
 * 호출되지 않는 메서드들이지만 javac+d8 이 dex 에 그대로 컴파일 → androguard xref 가
 * 의심 API 호출을 검출(Lv2):
 *   - SmsManager.sendTextMessage   → apk_sms_auto_send_code
 *   - TelephonyManager.listen      → apk_call_state_listener
 *   - DevicePolicyManager.lockNow  → apk_device_admin_lock
 * dex string pool 의 사칭 키워드/C2 URL:
 *   - 검찰청·금융감독원·안전계좌    → apk_impersonation_keywords
 *   - IP+비표준포트 / .tk 무료도메인 → apk_hardcoded_c2_url
 * 패키지명 com.kakao.talk.secure (정상 com.kakao.talk 사칭) → apk_suspicious_package_name
 */
public class MainActivity extends Activity {

    static final String[] LURE = {
        "검찰청 사이버수사대입니다",
        "금융감독원 보안승급 안내",
        "안전계좌로 즉시 이체하세요",
        "보안카드 번호를 입력하세요",
    };

    static final String C2_PRIMARY = "http://203.0.113.50:8888/gate/cmd";
    static final String C2_FALLBACK = "http://kakao-secure-update.tk/c2";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // 실행 동작 없음 — 정적 분석 전용 픽스처.
    }

    @SuppressWarnings("deprecation")
    void deadSendSms() {
        try {
            SmsManager.getDefault().sendTextMessage(
                "01000000000", null, LURE[0] + " " + C2_PRIMARY, null, null);
        } catch (Exception ignored) {}
    }

    @SuppressWarnings("deprecation")
    void deadListenCalls() {
        try {
            TelephonyManager tm = (TelephonyManager) getSystemService(TELEPHONY_SERVICE);
            tm.listen(new PhishStateListener(), PhoneStateListener.LISTEN_CALL_STATE);
        } catch (Exception ignored) {}
    }

    void deadLockNow() {
        try {
            DevicePolicyManager dpm =
                (DevicePolicyManager) getSystemService(DEVICE_POLICY_SERVICE);
            dpm.lockNow();
        } catch (Exception ignored) {}
    }
}
