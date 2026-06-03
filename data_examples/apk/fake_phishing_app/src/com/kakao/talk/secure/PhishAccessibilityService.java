package com.kakao.talk.secure;

import android.accessibilityservice.AccessibilityService;
import android.view.accessibility.AccessibilityEvent;

/** AccessibilityService 상속 — apk_accessibility_abuse 신호용. 동작 없음(dead-code). */
public class PhishAccessibilityService extends AccessibilityService {
    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // 무해 — 아무것도 안 함.
    }

    @Override
    public void onInterrupt() {
        // 무해.
    }
}
