# SG-APK — APK 동적 분석 (redroid + Frida) 구축 전체 흐름

ScamGuardian V3 의 **APK 런타임 동적 분석(Lv3)** 을 격리 VM 에 처음부터 끝까지 동작시킨
기록. WSL2 에서 못 돌던 Android 동적 분석을 Multipass VM 으로 우회해, 의심 APK 를 실제
실행하고 Frida 후킹으로 5개 런타임 위험 신호를 검출한다.

> Identity Boundary 유지 — **검출 보고만, 판정 안 함.** 단일 신호로 사기 단정 X.

날짜: 2026-06-03 · 상태: **DEV stack 동작 검증 완료 (Phase 0~4)**

---

## 0. 왜 별도 VM 인가 (핵심 제약)

| 문제 | 이유 |
|------|------|
| dev WSL2 에서 redroid 못 돌림 | WSL2 기본 커널은 `CONFIG_ANDROID_BINDER_IPC` OFF → `/dev/binder` 없음. redroid(Android-in-Docker)는 KVM 은 불필요하지만 **host 커널 binder/ashmem 모듈 필수** |
| dev 호스트에서 악성 APK 실행 금지 | repo·`.env` 키·`/mnt/c` 노출 → HARD BLOCK 위반 |

→ **Multipass Ubuntu VM**: 자체 커널(binder 모듈 apt 제공) + `/mnt/c` 없음 → dev·real 둘 다 안전.

```
WSL2 (binder 없음) ──✗
        │
Multipass VM "sg-sandbox" (Ubuntu 22.04, 4cpu/6G/30G)
  └ binderfs + redroid 13 + frida-server 16.x + adb
        │
apk_dynamic_server/ (FastAPI, 이 VM 안)
  POST /dynamic-analyze  ◄── production 이 호출하도록 *이미 배선됨*
        │  adb install → frida spawn/attach → 12s 후킹 관찰 → uninstall
        ▼
  { detected_flags: [apk_runtime_*], observations: {...} }
```

---

## 1. 구성 요소

### production 측 (이미 있던 것 — 손 안 댐)
- `pipeline/apk_analyzer.py` 의 `analyze_apk_dynamic()` → `_analyze_apk_dynamic_remote()`
  → `POST {APK_DYNAMIC_REMOTE_URL}/dynamic-analyze` (multipart `apk` + `Authorization: Bearer`).
- 응답 `{detected_flags[], observations}` 를 받아 `DETECTED_FLAGS` 로 재검증.
- runner escalation: **정적(Lv1/Lv2)이 0 신호일 때만** 동적 호출 (정적이 잡으면 동적 불필요).
- 로컬 실행은 HARD BLOCK — `APK_DYNAMIC_BACKEND=remote` + REMOTE_URL/TOKEN 있을 때만.

### VM 측 (이번에 신설) — `apk_dynamic_server/`
| 파일 | 역할 |
|------|------|
| `app.py` | FastAPI: Bearer 인증 + multipart `POST /dynamic-analyze` + `GET /health`. stateless(분석 후 APK 즉시 삭제) |
| `analyzer.py` | adb install `-g` → frida spawn(실패 시 `am start`+attach fallback) → 12s 관찰 → uninstall. 5 flag 매핑 |
| `frida_hooks.js` | 5 flag 런타임 후킹 (SMS·overlay·persistence·식별자 taint·Socket/URL 네트워크 sink) |
| `requirements.txt` | fastapi/uvicorn/python-multipart/**frida<17**/frida-tools<13/pyaxmlparser |
| `README.md` | VM 부트스트랩 + 배포 + 검증 전 과정 |

### 검증용 fixture (이번에 신설)
- `tests/fixtures/dynamic_active_app/` — launch 시 5개 행동을 **실제 실행**하는 active fixture.
  무해함: 네트워크는 RFC5737 비라우팅 대역(`203.0.113.x`/`198.51.100.x`), SMS 는 SIM 없는 redroid.
  빌드: `bash tests/fixtures/dynamic_active_app/build.sh` → `tests/fixtures/dynamic_active.apk`.
- `tests/fixtures/fake_phishing.apk` — 정적 dead-code 샘플. 동적은 행동 없어 `[]` → **음성 대조**용.

---

## 2. 5개 런타임 flag 검출 방법

| flag | 후킹 | active fixture 자극 |
|------|------|----|
| `apk_runtime_c2_network_call` | `Socket.connect`/`Socket.<init>`/`URL.openConnection` → host 가 IP직접·무료TLD(.tk/.ml/.ga/.cf/.gq)·비표준포트·RFC5737 | `203.0.113.7:8888` 연결 |
| `apk_runtime_sms_intercepted` | `SmsManager.sendTextMessage` / `BroadcastReceiver.abortBroadcast` | `sendTextMessage` 호출 |
| `apk_runtime_overlay_attack` | `WindowManagerImpl.addView`/`WindowManagerGlobal.addView` 의 `LayoutParams.type` 이 TYPE_APPLICATION_OVERLAY(2038) 등 | `addView(lp=2038)` |
| `apk_runtime_credential_exfiltration` | taint: `TelephonyManager.getDeviceId` 등 식별자 읽은 뒤 네트워크 송신 | `getDeviceId()` → `198.51.100.9:443` 송신 |
| `apk_runtime_persistence_install` | `DevicePolicyManager.lockNow/setActiveAdmin` / `registerReceiver(BOOT_COMPLETED)` | `lockNow()` + BOOT_COMPLETED 등록 |

---

## 3. VM 부트스트랩 (Phase 0~1 재현)

```bash
# ── Windows PowerShell ──
multipass launch 22.04 --name sg-sandbox --cpus 4 --memory 6G --disk 30G
multipass shell sg-sandbox
```
```bash
# ── VM 안 ──
# binder/ashmem 커널 모듈 (redroid 필수 — WSL2 에서 막혔던 관문)
sudo apt update && sudo apt install -y linux-modules-extra-$(uname -r) adb python3-pip xz-utils
sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
sudo modprobe ashmem_linux 2>/dev/null || true
sudo mount -t binder binder /dev/binderfs 2>/dev/null || true
ls /dev/binderfs/                  # binder, hwbinder, vndbinder → OK
# 영속화
echo -e "binder_linux\nashmem_linux" | sudo tee /etc/modules-load.d/redroid.conf
echo "binder /dev/binderfs binder nofail 0 0" | sudo tee -a /etc/fstab

# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker

# redroid 부팅
docker run -itd --privileged --name redroid -v ~/redroid-data:/data -p 5555:5555 \
  redroid/redroid:13.0.0-latest androidboot.redroid_width=720 androidboot.redroid_height=1280
adb connect localhost:5555
adb shell getprop sys.boot_completed     # 1 = 부팅 완료

# frida 16.x (⚠️ 17 아님) + 버전 일치 frida-server push
pip3 install --user 'frida<17' 'frida-tools<13'
FV=$(python3 -c "import frida; print(frida.__version__)")   # 16.x.x
adb root
wget -q "https://github.com/frida/frida/releases/download/${FV}/frida-server-${FV}-android-x86_64.xz"
unxz -f "frida-server-${FV}-android-x86_64.xz"
adb push "frida-server-${FV}-android-x86_64" /data/local/tmp/frida-server
adb shell chmod 755 /data/local/tmp/frida-server
adb shell "setsid /data/local/tmp/frida-server >/dev/null 2>&1 </dev/null &"
~/.local/bin/frida-ps -U | head          # 프로세스 목록 = 후킹 가능
```

## 4. 서버 실행 + 검증 (Phase 2~4)

현재는 아래 수동 절차 대신 WSL repo 에서 컨트롤러를 쓰는 것을 권장:

```bash
./scripts/apk_dynamic_vm_ctl.sh bootstrap   # 최초 1회
./scripts/apk_dynamic_vm_ctl.sh start       # VM/redroid/frida/API 전부 기동
./scripts/apk_dynamic_vm_ctl.sh apply-env   # 메인 ScamGuardian .env 에 연결값 반영
./scripts/start_stack.sh                    # 메인 서버 재시작
```

```bash
# 코드 전달 (git clone 또는 multipass transfer)
cd ~/sg-apkdyn/apk_dynamic_server      # apk_dynamic_server/ 가 여기 있다고 가정
pip3 install --user -r requirements.txt
export APK_DYNAMIC_SERVER_TOKEN=dev-secret-123
python3 app.py                          # 0.0.0.0:8002

# 다른 셸에서 검증
TOKEN=dev-secret-123
# ① active fixture → 5종 검출
curl -s -X POST localhost:8002/dynamic-analyze -H "Authorization: Bearer $TOKEN" \
  -F "apk=@$HOME/sg-apkdyn/fixtures/dynamic_active.apk" | python3 -m json.tool
# ② fake_phishing → [] (음성 대조)
curl -s -X POST localhost:8002/dynamic-analyze -H "Authorization: Bearer $TOKEN" \
  -F "apk=@$HOME/sg-apkdyn/fixtures/fake_phishing.apk" | python3 -m json.tool
```

**검증 결과 (2026-06-03)**:
- ① `detected_flags`: 5종 전부 (`apk_runtime_c2_network_call`·`credential_exfiltration`·
  `overlay_attack`·`persistence_install`·`sms_intercepted`), HTTP 200, `frida_mode=attach`.
- ② `detected_flags: []` — 행동 없으면 깨끗.

---

## 5. 디버깅 여정 (각 단계 자가진단 마커로 원인 특정)

응답에 `script_loaded` / `java_available` / `script_errors` / `hook_ok` 마커를 실어,
"추측 말고 데이터로" 어디서 끊기는지 매 라운드 좁혔다.

1. **`device.spawn([pkg])` (리스트) → Java 안 올라옴.** 리스트는 네이티브 argv 로 해석됨.
   Android 패키지는 **문자열** `device.spawn(pkg)` 로 (frida CLI `-f` 와 동일).
2. **`ReferenceError: 'Java' is not defined`.** frida **17 은 내장 `Java` 브리지를 코어에서 제거** —
   raw `create_script` 엔 `Java` 없음. (CLI 는 자동 주입돼 "CLI 는 되는데 서버는 안 되는" 함정)
   → **frida 16.x 핀** (python + frida-server 둘 다).
3. **`frida.TimedOutError: waiting for app to launch`.** redroid spawn 게이팅 타임아웃.
   → spawn 실패 시 `am start`+attach **fallback** + fixture 행동 **루프**(늦은 attach 대비).
4. **overlay 만 누락 (hook 은 설치됨).** `addView(View, ViewGroup.LayoutParams)` 의 params 에
   `.type`(서브클래스 필드) 직접 접근이 throw → 조용히 누락.
   → `Java.cast(params, WindowManager$LayoutParams).type.value`.

자세한 패턴은 `tasks/lessons.md` 패턴 9~13.

---

## 6. 남은 것 (Phase 5~6)

상세 계획·체크리스트는 `tasks/todo-phh.md` 의 "V3 동적 분석 VM 구축 계획" + "환경 정리 계획".

- **Phase 5 — production 연결**: `.env` 에 `APK_DYNAMIC_ENABLED=1`/`BACKEND=remote`/REMOTE_URL/TOKEN,
  `_analyze_apk_dynamic_remote` stub 확정, runner escalation E2E(정적 0건→동적→`/apk` UI), tests.
- **Phase 5 (속도)**: spawn-first 가 redroid 에서 항상 ~20s 타임아웃 후 fallback → attach-first 검토.
- **Phase 6 — REAL 하드닝**: mitmproxy egress(C2 캡처/차단) + redroid 스냅샷 복원 + inbound firewall +
  CICMalDroid 등 실제 악성 샘플. VM 서비스화(systemd) + 재현 bootstrap 스크립트.
