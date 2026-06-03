package com.kakao.taik;

import android.telephony.PhoneStateListener;

/**
 * named PhoneStateListener 서브클래스 (anonymous 는 JDK21 javac + d8 desugaring NPE).
 * 통화 상태 가로채기 의심 신호(apk_call_state_listener)용 — 동작 없음.
 */
public class PhishStateListener extends PhoneStateListener {
    @Override
    public void onCallStateChanged(int state, String phoneNumber) {
        // 무해 — dead-code.
    }
}
