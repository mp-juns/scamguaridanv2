'use strict';
//
// ScamGuardian APK 동적 분석 — Frida 런타임 후킹.
//
// redroid(Android) 안에서 대상 앱에 attach 되어, 5개 런타임 flag 에 해당하는
// API 호출을 가로채 host(analyzer.py)로 send() 한다. 실행을 *막지는 않음* —
// 관찰(observe)만 하고 원래 동작을 그대로 진행시킨다 (Identity Boundary: 검출만).
//
// emit 메시지 형태:
//   { flag: "apk_runtime_*", api: "...", ...detail }   ← 검출 신호
//   { marker: "sensitive_read", api: "..." }           ← taint source (flag 아님)
//
// 모든 후킹은 safe() 로 감싼다 — 클래스/메서드가 해당 기기/앱에 없어도 죽지 않게.

function emit(o) { send(o); }

// taint: 민감 식별자를 읽은 적 있으면 이후 네트워크 송신을 자격증명 유출로 본다.
var sensitiveRead = false;

function safe(label, fn) {
  try { fn(); } catch (e) { /* 해당 심볼 없음 — 무시 */ }
}

// 네트워크 목적지 분류 → C2 / 자격증명 유출 판정.
function flagNet(host, port, api) {
  host = host || '';
  var reasons = [];
  if (/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host)) reasons.push('ip_literal');
  if (/\.(tk|ml|ga|cf|gq)$/i.test(host)) reasons.push('free_tld');
  if (port && port !== 80 && port !== 443 && port !== -1) reasons.push('nonstd_port:' + port);
  // RFC 5737 / RFC 3849 문서화 전용(비라우팅) 대역 — 안전 fixture 의 가짜 C2.
  if (/^(203\.0\.113\.|198\.51\.100\.|192\.0\.2\.)/.test(host)) reasons.push('test_c2');

  if (reasons.length) {
    emit({ flag: 'apk_runtime_c2_network_call', api: api, host: host, port: port, reasons: reasons });
  }
  if (sensitiveRead) {
    emit({ flag: 'apk_runtime_credential_exfiltration', api: api, host: host, port: port });
  }
}

// 진단: 스크립트가 로드된 즉시 + Java 브리지 가용 여부 보고 (Java.perform 전).
try {
  send({ marker: 'script_loaded', java_available: (typeof Java !== 'undefined') && Java.available });
} catch (e) {
  send({ marker: 'script_loaded', java_available: false, err: '' + e });
}

Java.perform(function () {

  // ── 1. SMS 자동 발송 / 가로채기 ──────────────────────────────
  safe('SmsManager', function () {
    var Sms = Java.use('android.telephony.SmsManager');
    ['sendTextMessage', 'sendMultipartTextMessage', 'sendDataMessage'].forEach(function (m) {
      if (!Sms[m]) return;
      Sms[m].overloads.forEach(function (ov) {
        ov.implementation = function () {
          var dest = arguments.length > 0 ? '' + arguments[0] : null;
          emit({ flag: 'apk_runtime_sms_intercepted', api: 'SmsManager.' + m, dest: dest });
          try { return ov.apply(this, arguments); } catch (e) { return; }
        };
      });
    });
  });
  safe('abortBroadcast', function () {
    var BR = Java.use('android.content.BroadcastReceiver');
    var abort = BR.abortBroadcast.overload();
    abort.implementation = function () {
      emit({ flag: 'apk_runtime_sms_intercepted', api: 'BroadcastReceiver.abortBroadcast' });
      return abort.call(this);
    };
  });

  // ── 2. 오버레이 공격 ────────────────────────────────────────
  // TYPE_PHONE=2002, TYPE_SYSTEM_ALERT=2003, TYPE_SYSTEM_OVERLAY=2006, TYPE_APPLICATION_OVERLAY=2038
  var WMLayoutParams = Java.use('android.view.WindowManager$LayoutParams');
  function checkOverlayParams(params, api) {
    try {
      // addView 시그니처는 ViewGroup.LayoutParams 라 .type 직접 접근이 실패 →
      // 런타임 실제 타입(WindowManager.LayoutParams)으로 캐스트해야 type 필드가 보인다.
      var t = Java.cast(params, WMLayoutParams).type.value;
      if (t === 2038 || t === 2003 || t === 2002 || t === 2006) {
        emit({ flag: 'apk_runtime_overlay_attack', api: api, type: t });
      }
    } catch (e) {}
  }
  safe('WindowManagerImpl.addView', function () {
    var WMImpl = Java.use('android.view.WindowManagerImpl');
    WMImpl.addView.overloads.forEach(function (ov) {
      ov.implementation = function () {
        if (arguments.length >= 2) checkOverlayParams(arguments[1], 'WindowManagerImpl.addView');
        return ov.apply(this, arguments);
      };
    });
    send({ marker: 'hook_ok', target: 'WindowManagerImpl.addView' });
  });
  safe('WindowManagerGlobal.addView', function () {
    var WMG = Java.use('android.view.WindowManagerGlobal');
    WMG.addView.overloads.forEach(function (ov) {
      ov.implementation = function () {
        // addView(view, params, display, parentWindow, ...) — params 는 두 번째 인자
        if (arguments.length >= 2) checkOverlayParams(arguments[1], 'WindowManagerGlobal.addView');
        return ov.apply(this, arguments);
      };
    });
    send({ marker: 'hook_ok', target: 'WindowManagerGlobal.addView' });
  });

  // ── 3. 지속성(persistence): DeviceAdmin + BOOT_COMPLETED ─────
  safe('DevicePolicyManager', function () {
    var DPM = Java.use('android.app.admin.DevicePolicyManager');
    ['lockNow', 'setActiveAdmin'].forEach(function (m) {
      if (!DPM[m]) return;
      DPM[m].overloads.forEach(function (ov) {
        ov.implementation = function () {
          emit({ flag: 'apk_runtime_persistence_install', api: 'DevicePolicyManager.' + m });
          try { return ov.apply(this, arguments); } catch (e) { return; }
        };
      });
    });
  });
  safe('registerReceiver', function () {
    var Ctx = Java.use('android.content.ContextWrapper');
    Ctx.registerReceiver.overloads.forEach(function (ov) {
      ov.implementation = function () {
        try {
          var filter = arguments[1];
          if (filter) {
            var n = filter.countActions();
            for (var i = 0; i < n; i++) {
              var a = '' + filter.getAction(i);
              if (a.indexOf('BOOT_COMPLETED') >= 0 || a.indexOf('QUICKBOOT') >= 0 || a.indexOf('LOCKED_BOOT') >= 0) {
                emit({ flag: 'apk_runtime_persistence_install', api: 'registerReceiver', action: a });
              }
            }
          }
        } catch (e) {}
        return ov.apply(this, arguments);
      };
    });
  });

  // ── 4. 민감 식별자 읽기 (taint source — flag 아님) ──────────
  safe('TelephonyManager-id', function () {
    var TM = Java.use('android.telephony.TelephonyManager');
    ['getDeviceId', 'getImei', 'getSubscriberId', 'getLine1Number', 'getSimSerialNumber'].forEach(function (m) {
      if (!TM[m]) return;
      TM[m].overloads.forEach(function (ov) {
        ov.implementation = function () {
          sensitiveRead = true;
          emit({ marker: 'sensitive_read', api: 'TelephonyManager.' + m });
          try { return ov.apply(this, arguments); } catch (e) { return null; }
        };
      });
    });
  });
  safe('AccountManager', function () {
    var AM = Java.use('android.accounts.AccountManager');
    if (AM.getAccounts) AM.getAccounts.implementation = function () {
      sensitiveRead = true;
      emit({ marker: 'sensitive_read', api: 'AccountManager.getAccounts' });
      return this.getAccounts();
    };
  });

  // ── 5. 네트워크 sink: Socket / URL ──────────────────────────
  safe('Socket.connect', function () {
    var Socket = Java.use('java.net.Socket');
    var InetSocketAddress = Java.use('java.net.InetSocketAddress');
    Socket.connect.overloads.forEach(function (ov) {
      ov.implementation = function () {
        try {
          var isa = Java.cast(arguments[0], InetSocketAddress);
          flagNet('' + isa.getHostString(), isa.getPort(), 'Socket.connect');
        } catch (e) {}
        return ov.apply(this, arguments);
      };
    });
  });
  safe('Socket.ctor', function () {
    var Socket = Java.use('java.net.Socket');
    Socket.$init.overloads.forEach(function (ov) {
      ov.implementation = function () {
        try {
          if (arguments.length >= 2 && typeof arguments[1] === 'number') {
            flagNet('' + arguments[0], arguments[1], 'Socket.<init>');
          }
        } catch (e) {}
        return ov.apply(this, arguments);
      };
    });
  });
  safe('URL.openConnection', function () {
    var URL = Java.use('java.net.URL');
    URL.openConnection.overloads.forEach(function (ov) {
      ov.implementation = function () {
        try { flagNet('' + this.getHost(), this.getPort(), 'URL.openConnection'); } catch (e) {}
        return ov.apply(this, arguments);
      };
    });
  });

  emit({ marker: 'hooks_installed' });
});
