package com.kakao.talk.secure;

import android.telephony.PhoneStateListener;

/** named PhoneStateListener 서브클래스 (anonymous 는 JDK21 javac + d8 desugaring NPE). dead-code. */
public class PhishStateListener extends PhoneStateListener {
    @Override
    public void onCallStateChanged(int state, String phoneNumber) {
        // 무해 — dead-code.
    }
}
