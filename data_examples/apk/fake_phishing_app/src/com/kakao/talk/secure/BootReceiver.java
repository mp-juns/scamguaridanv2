package com.kakao.talk.secure;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** 매니페스트 선언 BOOT_COMPLETED receiver (persistence 신호 보강). 동작 없음. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        // 무해 — 아무것도 하지 않음.
    }
}
