# ScamGuardian APK 동적 분석 서버 (`apk_dynamic_server/`)

production 호스트와 **분리된 격리 VM** 안에서 도는 FastAPI 서버. 의심 APK 를 redroid
(Android-in-Docker) 에 설치하고 Frida 후킹으로 런타임 행동을 관찰해, 5개 런타임 flag 를
검출 보고한다. **판정은 안 함 — 검출만** (Identity Boundary).

```
production (pipeline.apk_analyzer._analyze_apk_dynamic_remote)
   │  POST /dynamic-analyze  (multipart files=apk, Authorization: Bearer <token>)
   ▼
apk_dynamic_server (이 VM)
   │  adb install → frida spawn+hooks → 관찰 → uninstall
   ▼
   { "detected_flags": ["apk_runtime_*", ...], "observations": {...} }
```

## 왜 별도 VM 인가
- redroid 는 host 커널 **binder/ashmem** 모듈이 필수 → dev WSL2 기본 커널엔 binder 가 없어 못 돌림.
- 실제 악성 APK 실행은 본질적으로 위험 → production DB·키·`/mnt/c` 가 없는 빈 VM 에서만.
- production 은 `APK_DYNAMIC_BACKEND=remote` + REMOTE_URL/TOKEN 이 있을 때만 호출 (로컬 실행 HARD BLOCK 유지).

## 1. VM 부트스트랩 (Multipass Ubuntu 22.04)

```bash
# Windows 호스트
multipass launch 22.04 --name sg-sandbox --cpus 4 --memory 6G --disk 30G
multipass shell sg-sandbox
```

VM 안:
```bash
# binder/ashmem 커널 모듈 (redroid 필수)
sudo apt update && sudo apt install -y linux-modules-extra-$(uname -r) adb python3-pip xz-utils
sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
sudo modprobe ashmem_linux 2>/dev/null || true
# binderfs 커널이면 /dev/binderfs/{binder,hwbinder,vndbinder} 생성됨
sudo mount -t binder binder /dev/binderfs 2>/dev/null || true
ls /dev/binderfs/        # binder, hwbinder, vndbinder 보이면 OK

# 재부팅 영속화
echo -e "binder_linux\nashmem_linux" | sudo tee /etc/modules-load.d/redroid.conf
echo "binder /dev/binderfs binder nofail 0 0" | sudo tee -a /etc/fstab

# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
```

## 2. redroid + frida-server

```bash
# redroid 부팅
docker run -itd --privileged --name redroid \
  -v ~/redroid-data:/data -p 5555:5555 \
  redroid/redroid:13.0.0-latest \
  androidboot.redroid_width=720 androidboot.redroid_height=1280

adb connect localhost:5555
adb shell getprop sys.boot_completed   # 1 이면 부팅 완료

# frida 16.x 설치 (⚠️ 17 아님 — 아래 경고) + 버전 일치하는 frida-server push
pip3 install --user 'frida-tools<13'                 # frida 16.x 를 자동으로 끌어옴
FRIDA_VER=$(python3 -c "import frida; print(frida.__version__)")   # 16.x.x 여야 함
adb root
adb shell "pkill frida-server" 2>/dev/null || true
wget -q "https://github.com/frida/frida/releases/download/${FRIDA_VER}/frida-server-${FRIDA_VER}-android-x86_64.xz"
unxz -f "frida-server-${FRIDA_VER}-android-x86_64.xz"
adb push "frida-server-${FRIDA_VER}-android-x86_64" /data/local/tmp/frida-server
adb shell chmod 755 /data/local/tmp/frida-server
adb shell "setsid /data/local/tmp/frida-server >/dev/null 2>&1 </dev/null &"
~/.local/bin/frida-ps -U | head      # 프로세스 목록 뜨면 후킹 가능
```

> ⚠️ **frida 는 반드시 16.x 로 핀.** frida **17 은 내장 `Java`/`ObjC` 브리지를 코어에서
> 제거**해, `session.create_script()` 로 raw JS 를 주입하면 `Java` 가 undefined
> (`ReferenceError: 'Java' is not defined`) → 후킹 0 이벤트가 된다. (frida CLI 는 브리지를
> 자동 주입하므로 CLI 로는 동작하는 것처럼 보이는 함정이 있음.) 16.x 는 Java 브리지가 내장이라
> frida_hooks.js 가 번들러 없이 그대로 동작.
> **frida-server(redroid) 와 frida(python) 는 같은 16.x 버전이어야 함.**

## 3. 서버 실행

```bash
# repo 의 apk_dynamic_server/ 를 VM 으로 (git clone 또는 multipass transfer)
cd apk_dynamic_server
pip3 install --user -r requirements.txt

export APK_DYNAMIC_SERVER_TOKEN="<production 과 공유할 비밀>"
# (옵션) export APK_DYNAMIC_ADB_SERIAL=localhost:5555
# (옵션) export APK_DYNAMIC_COLLECT_SECONDS=12
python3 app.py        # 0.0.0.0:8002
```

`GET /health` → `{"status":"ok","redroid_booted":true,...}` 면 준비 완료.

## 4. production 연결

production 호스트(.env):
```bash
APK_DYNAMIC_ENABLED=1
APK_DYNAMIC_BACKEND=remote
APK_DYNAMIC_REMOTE_URL=http://<VM-IP>:8002
APK_DYNAMIC_REMOTE_TOKEN=<3단계와 같은 비밀>
```
정적 분석(Lv1/Lv2)이 **0 신호일 때만** runner 가 이 서버를 호출한다 (정적이 잡으면 동적 불필요).

## 5. 검증 (DEV)

```bash
# active fixture 빌드 (Android SDK 필요 — WSL 또는 VM)
bash tests/fixtures/dynamic_active_app/build.sh   # → tests/fixtures/dynamic_active.apk

# 직접 서버 호출
curl -s -X POST http://<VM-IP>:8002/dynamic-analyze \
  -H "Authorization: Bearer $APK_DYNAMIC_SERVER_TOKEN" \
  -F "apk=@tests/fixtures/dynamic_active.apk" | python3 -m json.tool
```
기대: `detected_flags` 에 5종(`apk_runtime_c2_network_call`, `..._sms_intercepted`,
`..._overlay_attack`, `..._credential_exfiltration`, `..._persistence_install`) 가 검출됨.

반대로 정적 dead-code 샘플(`fake_phishing.apk`)을 던지면 행동이 없어 `detected_flags: []`
— "안전 샘플 → 위험 0" 검증.

## 보안 하드닝 (REAL 샘플 단계)
- **inbound firewall**: production IP 만 8002 허용.
- **egress 통제**: 실제 악성 샘플은 `mitmproxy` 로 redroid 트래픽을 경유시켜 C2 통신을 *기록 + 위험 목적지 차단*. (현재 분석기는 frida 소켓 후킹만 — mitmproxy 통합은 다음 단계.)
- **스냅샷 복원**: 분석마다 redroid `/data` 스냅샷 복원 (현재는 `adb uninstall` 만 — REAL 단계에서 강화).
- VM 에 production DB/키/`/mnt/c` 마운트 **없음** 확인.

## 한계 (정직한 표현)
- 현재 분석기는 **Frida 자바 후킹 기반** — 네이티브(.so)에서 직접 syscall 하거나, frida 탐지·anti-debug 가 있는 정교한 샘플은 회피 가능.
- redroid x86 이미지 — ARM-only 네이티브 lib 악성코드는 houdini 변환 필요(REAL 단계 과제).
- 동적 분석도 단일 신호로 사기 판정 X. 검출 보고만, 판정은 통합 기업 (Identity Boundary).
