package com.kakao.taik;

import android.accessibilityservice.AccessibilityService;
import android.view.accessibility.AccessibilityEvent;

/**
 * AccessibilityService 상속 — apk_accessibility_abuse 신호용. 동작 없음(dead-code).
 * 실제 피셔는 이걸로 다른 앱 화면을 읽거나 자동 입력하지만, 본 픽스처는 빈 구현.
 */
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
