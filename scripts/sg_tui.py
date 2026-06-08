#!/usr/bin/env python3
from __future__ import annotations

import codecs
import curses
import fcntl
import locale
import os
import pty
import re
import select
import shlex
import signal
import struct
import subprocess
import sys
import termios
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / ".scamguardian" / "logs"
TMP_DIR = ROOT / ".scamguardian" / "tmp"
CONDA = Path.home() / "anaconda3" / "bin" / "conda"
CONDA_ENV = os.environ.get("CONDA_ENV", "capstone")
FUNNEL_URL = os.environ.get("SCAMGUARDIAN_FUNNEL_URL", "https://scamguardian.tail7e5dfc.ts.net")
START_SCRIPT = os.environ.get("SG_START_SCRIPT", "./scripts/start_stack.sh")
BACKEND_PORT = os.environ.get("SG_BACKEND_PORT", "8000")
FRONTEND_PORT = os.environ.get("SG_FRONTEND_PORT", "3100")
PUBLIC_MODE = os.environ.get("SG_PUBLIC_MODE", "tailscale")
LOG_SUFFIX = os.environ.get("SG_LOG_SUFFIX", "")
BACKEND_LOG = LOG_DIR / f"backend{LOG_SUFFIX}.log"
FRONTEND_LOG = LOG_DIR / f"frontend{LOG_SUFFIX}.log"
CLOUDFLARED_LOG = LOG_DIR / f"cloudflared{LOG_SUFFIX}.log"


def conda_cmd(command: str) -> str:
    if CONDA.exists():
        return f"{shlex.quote(str(CONDA))} run --no-capture-output -n {shlex.quote(CONDA_ENV)} {command}"
    return command


def stop_dev_cmd() -> str:
    quoted_public = shlex.quote(PUBLIC_MODE)
    return (
        "set +e; "
        "echo '[정지] 공개 터널 정리 중...'; "
        f"if [ {quoted_public} = tailscale ] && command -v tailscale >/dev/null 2>&1; then tailscale funnel off 2>/dev/null || true; fi; "
        "echo '[정지] 포트 리스너 종료 중...'; "
        f"if command -v fuser >/dev/null 2>&1; then fuser -k {BACKEND_PORT}/tcp {FRONTEND_PORT}/tcp 2>/dev/null || true; fi; "
        f"for pat in 'uvicorn api_server:app.*--port {BACKEND_PORT}' 'next dev.*--port {FRONTEND_PORT}' 'next-server.*{FRONTEND_PORT}' 'npm run dev.*--.*{FRONTEND_PORT}' 'cloudflared.*{FRONTEND_PORT}'; do "
        "pids=$(pgrep -f \"$pat\" 2>/dev/null | grep -v -E \"^($$|$PPID)$\" || true); "
        "if [ -n \"$pids\" ]; then echo \"[정지] 종료 $pat -> $pids\"; kill -TERM $pids 2>/dev/null || true; fi; "
        "done; "
        "sleep 1; "
        f"if command -v fuser >/dev/null 2>&1; then fuser -k {BACKEND_PORT}/tcp {FRONTEND_PORT}/tcp 2>/dev/null || true; fi; "
        "free -h; "
        f"ss -ltnp 2>/dev/null | grep -E ':({BACKEND_PORT}|{FRONTEND_PORT})' || true; "
        "echo '[정지] 완료'; "
        "exit 0"
    )


def public_wait_cmd() -> str:
    if PUBLIC_MODE == "cloudflared":
        return (
            " && "
            "printf '\\n[시작] Cloudflare 공개 주소 대기 중...\\n'"
            " && "
            "for i in $(seq 1 90); do "
            f"URL=$(grep -oaE 'https://[a-z0-9]+-[a-z0-9-]+\\.trycloudflare\\.com' {shlex.quote(str(CLOUDFLARED_LOG))} 2>/dev/null | head -1 || true); "
            "if [ -n \"$URL\" ] && curl -fsS -L --max-time 8 \"$URL\" >/dev/null 2>&1; then "
            "printf '[시작] cloudflared 준비 완료 (%s초): %s\\n' \"$i\" \"$URL\"; exit 0; "
            "fi; "
            "if [ \"$i\" -eq 90 ]; then "
            "printf '[시작] cloudflared가 90초 안에 준비되지 않았습니다\\n'; "
            f"tail -n 100 {shlex.quote(str(CLOUDFLARED_LOG))} 2>/dev/null || true; exit 1; "
            "fi; "
            "sleep 1; "
            "done"
        )

    quoted_url = shlex.quote(FUNNEL_URL)
    return (
        " && "
        "printf '\\n[시작] 로컬 서비스 준비 완료 후 Tailscale Funnel 여는 중...\\n'"
        f" && tailscale funnel --bg http://127.0.0.1:{FRONTEND_PORT} || true"
        " && tailscale funnel status 2>/dev/null || true"
        " && "
        "for i in $(seq 1 90); do "
        f"if curl -fsS -L --max-time 8 {quoted_url} >/dev/null 2>&1; then "
        "printf '[시작] Funnel 준비 완료 (%s초)\\n' \"$i\"; exit 0; "
        "fi; "
        "if [ \"$i\" -eq 90 ]; then "
        "printf '[시작] Funnel이 90초 안에 준비되지 않았습니다\\n'; "
        "tailscale funnel status 2>/dev/null || true; "
        f"tail -n 80 {shlex.quote(str(FRONTEND_LOG))} 2>/dev/null || true; exit 1; "
        "fi; "
        "sleep 1; "
        "done"
    )


def start_stack_cmd(skip_warmup: bool) -> str:
    warm = "SCAMGUARDIAN_SKIP_WARMUP=1 " if skip_warmup else ""
    start_env = "ENABLE_FUNNEL=false ENABLE_NGROK=false" if Path(START_SCRIPT).name == "start_stack.sh" else ""
    return (
        f"{warm}{start_env} {shlex.quote(START_SCRIPT)}"
        " && "
        "printf '\\n[시작] 백엔드 /health 대기 중"
        + (" (워밍업 생략)" if skip_warmup else " (모델 워밍업은 시간이 걸릴 수 있음)")
        + "...\\n'"
        " && "
        "for i in $(seq 1 90); do "
        f"if curl -fsS http://127.0.0.1:{BACKEND_PORT}/health >/dev/null 2>&1; then "
        "printf '[시작] 백엔드 준비 완료 (%s초)\\n' \"$i\"; break; "
        "fi; "
        "if [ \"$i\" -eq 90 ]; then "
        "printf '[시작] 백엔드가 90초 안에 준비되지 않았습니다. 백엔드 로그 출력\\n'; "
        f"tail -n 80 {shlex.quote(str(BACKEND_LOG))}; exit 1; "
        "fi; "
        "sleep 1; "
        "done"
        " && "
        "for i in $(seq 1 30); do "
        f"if curl -fsS http://127.0.0.1:{FRONTEND_PORT} >/dev/null 2>&1; then "
        "printf '[시작] 프론트엔드 준비 완료 (%s초)\\n' \"$i\"; break; "
        "fi; "
        "if [ \"$i\" -eq 30 ]; then "
        "printf '[시작] 프론트엔드가 30초 안에 준비되지 않았습니다. 프론트엔드 로그 출력\\n'; "
        f"tail -n 80 {shlex.quote(str(FRONTEND_LOG))}; exit 1; "
        "fi; "
        "sleep 1; "
        "done"
        + public_wait_cmd()
    )


def memory_cmd() -> str:
    return "free -h && printf '\\n--- top rss ---\\n' && ps -eo pid,ppid,comm,rss,etime,args --sort=-rss | head -n 24"


def health_cmd() -> str:
    return f"curl -sS -i http://127.0.0.1:{BACKEND_PORT}/health | sed -n '1,80p'"


def funnel_check_cmd() -> str:
    if PUBLIC_MODE == "cloudflared":
        return (
            "printf '[public] cloudflared log URL\\n' && "
            f"grep -oaE 'https://[a-z0-9]+-[a-z0-9-]+\\.trycloudflare\\.com' {shlex.quote(str(CLOUDFLARED_LOG))} 2>/dev/null | head -5 && "
            f"URL=$(grep -oaE 'https://[a-z0-9]+-[a-z0-9-]+\\.trycloudflare\\.com' {shlex.quote(str(CLOUDFLARED_LOG))} 2>/dev/null | head -1 || true); "
            "if [ -n \"$URL\" ]; then printf '\\n[public] request %s\\n' \"$URL\"; curl -sS -L -i --max-time 15 \"$URL\" | sed -n '1,120p'; else echo '[public] no cloudflared URL found'; fi"
        )
    return (
        "printf '[funnel] status\\n' && "
        "tailscale funnel status 2>&1 && "
        "printf '\\n[funnel] request "
        + shlex.quote(FUNNEL_URL)
        + "\\n' && "
        "curl -sS -L -i --max-time 15 "
        + shlex.quote(FUNNEL_URL)
        + " | sed -n '1,120p'"
    )


def ports_cmd() -> str:
    return f"ss -ltnp 2>/dev/null | grep -E ':({BACKEND_PORT}|{FRONTEND_PORT}|9090|9100)' || true"


def tail_cmd(path: Path) -> str:
    # raw tail: '\r' progress-bar bytes are preserved so the TUI can render them in-place
    return f"tail -n 200 -F {shlex.quote(str(path))}"


# newline-terminated 노이즈만 버린다. tqdm 진행 바('\r' 갱신)는 절대 건드리지 않는다.
NOISE_RE = re.compile(
    r"\[httpx\]|HTTP Request:|huggingface_hub|\[urllib3|\[filelock|\[fsspec|"
    r"unauthenticated requests|resolve-cache|symlinks on Windows"
)


def is_noise(line: str) -> bool:
    return bool(NOISE_RE.search(line))


# ANSI 이스케이프 시퀀스 + 탭/개행 제외 제어문자(널 바이트 포함) — curses addstr 가 거부한다
ANSI_CTRL_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]|[\x00-\x08\x0b-\x1f\x7f]")
WIDE_TRAIL = "\0"


def sanitize(line: str) -> str:
    return ANSI_CTRL_RE.sub("", line)


class MiniTerminal:
    def __init__(self, rows: int, cols: int):
        self.rows = max(1, rows)
        self.cols = max(1, cols)
        self.lines = [[" "] * self.cols for _ in range(self.rows)]
        self.r = 0
        self.c = 0
        self.state = "normal"
        self.buf = ""

    def resize(self, rows: int, cols: int) -> None:
        rows = max(1, rows)
        cols = max(1, cols)
        old = self.display()
        old = old[-rows:]
        self.rows = rows
        self.cols = cols
        self.lines = [[" "] * self.cols for _ in range(self.rows)]
        start = max(0, rows - len(old))
        for i, text in enumerate(old):
            self._write_plain_at(start + i, 0, text[:cols])
        self.r = min(self.r, self.rows - 1)
        self.c = min(self.c, self.cols - 1)

    def display(self) -> list[str]:
        return ["".join(ch for ch in line if ch != WIDE_TRAIL).rstrip() for line in self.lines]

    def write(self, text: str) -> None:
        for ch in text:
            self.feed(ch)

    def feed(self, ch: str) -> None:
        if self.state == "normal":
            self._normal(ch)
        elif self.state == "esc":
            self._esc(ch)
        elif self.state == "csi":
            self._csi(ch)
        elif self.state in {"osc", "str"}:
            self._string(ch)

    def _normal(self, ch: str) -> None:
        if ch == "\x1b":
            self.state = "esc"
            self.buf = ""
        elif ch == "\n":
            self._newline()
        elif ch == "\r":
            self.c = 0
        elif ch == "\b":
            self.c = max(0, self.c - 1)
        elif ch == "\t":
            self.c = min(self.cols - 1, self.c + (8 - self.c % 8))
        elif ord(ch) >= 32:
            self._put(ch)

    def _esc(self, ch: str) -> None:
        if ch == "[":
            self.state = "csi"
            self.buf = ""
        elif ch == "]":
            self.state = "osc"
            self.buf = ""
        elif ch in {"P", "_", "^"}:
            self.state = "str"
            self.buf = ""
        elif ch == "c":
            self._clear()
            self.state = "normal"
        elif ch in {"(", ")", "*", "+", "#"}:
            self.state = "normal"
        else:
            self.state = "normal"

    def _csi(self, ch: str) -> None:
        if "@" <= ch <= "~":
            self._handle_csi(self.buf, ch)
            self.buf = ""
            self.state = "normal"
        elif len(self.buf) < 64:
            self.buf += ch

    def _string(self, ch: str) -> None:
        if ch == "\x07":
            self.state = "normal"
            self.buf = ""
        elif ch == "\x1b":
            self.state = "esc"
            self.buf = ""

    def _put(self, ch: str) -> None:
        width = self._char_width(ch)
        if self.c >= self.cols:
            self._newline()
        if width == 2 and self.c >= self.cols - 1:
            self._newline()
        if self.lines[self.r][self.c] == WIDE_TRAIL:
            if self.c > 0:
                self.lines[self.r][self.c - 1] = " "
            self.lines[self.r][self.c] = " "
        elif self.c + 1 < self.cols and self.lines[self.r][self.c + 1] == WIDE_TRAIL:
            self.lines[self.r][self.c + 1] = " "
        if self.c > 0 and self.lines[self.r][self.c - 1] != WIDE_TRAIL and self._char_width(self.lines[self.r][self.c - 1]) == 2:
            self.lines[self.r][self.c - 1] = " "
        self.lines[self.r][self.c] = ch
        if width == 2 and self.c + 1 < self.cols:
            self.lines[self.r][self.c + 1] = WIDE_TRAIL
        self.c += width
        if self.c >= self.cols:
            self.c = self.cols - 1

    @staticmethod
    def _char_width(ch: str) -> int:
        if not ch or ch == WIDE_TRAIL:
            return 0
        if unicodedata.combining(ch):
            return 0
        return 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1

    def _write_plain_at(self, row: int, col: int, text: str) -> None:
        old_r, old_c = self.r, self.c
        self.r = max(0, min(self.rows - 1, row))
        self.c = max(0, min(self.cols - 1, col))
        for ch in text:
            self._put(ch)
        self.r, self.c = old_r, old_c

    def _newline(self) -> None:
        self.c = 0
        if self.r >= self.rows - 1:
            self.lines.pop(0)
            self.lines.append([" "] * self.cols)
        else:
            self.r += 1

    def _clear(self) -> None:
        self.lines = [[" "] * self.cols for _ in range(self.rows)]
        self.r = 0
        self.c = 0

    def _params(self, raw: str) -> list[int]:
        raw = raw.replace("?", "").replace(">", "").replace("<", "")
        parts = raw.split(";") if raw else [""]
        vals: list[int] = []
        for part in parts:
            try:
                vals.append(int(part) if part else 0)
            except ValueError:
                vals.append(0)
        return vals or [0]

    def _handle_csi(self, raw: str, final: str) -> None:
        vals = self._params(raw)
        first = vals[0] if vals else 0
        if final in {"H", "f"}:
            row = vals[0] if len(vals) >= 1 and vals[0] else 1
            col = vals[1] if len(vals) >= 2 and vals[1] else 1
            self.r = max(0, min(self.rows - 1, row - 1))
            self.c = max(0, min(self.cols - 1, col - 1))
        elif final == "A":
            self.r = max(0, self.r - max(1, first))
        elif final == "B":
            self.r = min(self.rows - 1, self.r + max(1, first))
        elif final == "C":
            self.c = min(self.cols - 1, self.c + max(1, first))
        elif final == "D":
            self.c = max(0, self.c - max(1, first))
        elif final == "G":
            col = first if first else 1
            self.c = max(0, min(self.cols - 1, col - 1))
        elif final == "J":
            if first in {2, 3}:
                self._clear()
            elif first == 0:
                self.lines[self.r][self.c :] = [" "] * (self.cols - self.c)
                for row in range(self.r + 1, self.rows):
                    self.lines[row] = [" "] * self.cols
        elif final == "K":
            if first == 1:
                self.lines[self.r][: self.c + 1] = [" "] * (self.c + 1)
            elif first == 2:
                self.lines[self.r] = [" "] * self.cols
            else:
                self.lines[self.r][self.c :] = [" "] * (self.cols - self.c)


# tqdm 진행 바 한 줄 인식: "...65%|████ | 194/300 [00:07<00:03, 29.59it/s]"
PROGRESS_RE = re.compile(r"(?P<pct>\d+)%\|.*?\|\s*(?P<n>\d+)/(?P<total>\d+)\s*\[")


def bar_pct(line: str) -> int | None:
    m = PROGRESS_RE.search(line)
    return int(m.group("pct")) if m else None


def latest_train_log() -> Path | None:
    base = ROOT / ".scamguardian" / "training_sessions"
    logs = [p for p in base.glob("*/train.log") if p.is_file()]
    if not logs:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime)


def stop_training_cmd() -> str:
    return " ; ".join(
        [
            "pkill -f '[t]raining.train_classifier' 2>/dev/null || true",
            "pkill -f '[t]raining.train_gliner' 2>/dev/null || true",
            "echo '[train] sent SIGTERM to any running classifier/gliner training'",
        ]
    )


def classifier_dry(extra: str = "") -> str:
    arg = f" --extra-jsonl {shlex.quote(extra)}" if extra else ""
    return conda_cmd(f"python -m training.train_classifier --dry-run{arg}")


def gliner_dry(extra: str = "") -> str:
    arg = f" --extra-jsonl {shlex.quote(extra)}" if extra else ""
    return conda_cmd(f"python -m training.train_gliner --dry-run{arg}")


def yn(value: str, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"y", "yes", "1", "true", "on"}


def opt(name: str, value: str | int | float | None) -> list[str]:
    if value is None or value == "":
        return []
    return [name, str(value)]


def qjoin(args: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in args)


@dataclass
class Action:
    name: str
    desc: str
    command: Callable[["App"], str | None]


class App:
    def __init__(self, stdscr: curses.window):
        self.stdscr = stdscr
        self.selected = 0
        self.output: deque[str] = deque(maxlen=2000)
        self.proc: subprocess.Popen[bytes] | None = None
        self.active_name = "idle"
        self.status = "ready"
        self.side_pid: int | None = None
        self.side_fd: int | None = None
        self.side_name = "none"
        self.side_focus = False
        self.side_output: deque[str] = deque(maxlen=1000)
        self.side_current = ""
        self.side_size = (0, 0)
        self.side_screen: MiniTerminal | None = None
        self.side_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        # 진행 중인(아직 '\n' 안 만난) 한 줄 — tqdm 진행 바가 여기서 in-place 갱신된다
        self.current_line = ""
        self._cr = False
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        # 진행 바는 일반 로그와 분리해 bar 별로 한 줄만 유지 (key -> 최신 줄)
        self.bars: dict[str, str] = {}
        self.actions = self._actions()

    def _reset_stream(self) -> None:
        self.current_line = ""
        self._cr = False
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.bars = {}

    def _actions(self) -> list[Action]:
        return [
            Action("서버 정지", "백엔드 + 프론트엔드 + 터널 종료", lambda app: stop_dev_cmd()),
            Action("가볍게 시작", "로컬 준비 후 공개 연결, 워밍업 생략", lambda app: start_stack_cmd(True)),
            Action("전체 시작", "로컬 준비 후 공개 연결, 모델 워밍업 포함", lambda app: start_stack_cmd(False)),
            Action("상태 확인", "로컬 백엔드 /health 호출", lambda app: health_cmd()),
            Action("공개 주소 확인", "Tailscale/cloudflared 공개 URL 확인", lambda app: funnel_check_cmd()),
            Action("메모리 확인", "free + 메모리 사용량 상위 프로세스", lambda app: memory_cmd()),
            Action("포트 확인", "백엔드/프론트엔드/모니터링 리스너 확인", lambda app: ports_cmd()),
            Action("백엔드 로그", f"{BACKEND_LOG.name} 실시간 보기", lambda app: tail_cmd(BACKEND_LOG)),
            Action("프론트 로그", f"{FRONTEND_LOG.name} 실시간 보기", lambda app: tail_cmd(FRONTEND_LOG)),
            Action("학습 로그", "최근 학습 로그 실시간 보기", lambda app: app.tail_train_log()),
            Action("Codex 창", "오른쪽 창 전용; WSL codex 필요", lambda app: app.start_side_terminal("codex", app.codex_side_cmd())),
            Action("Claude 창", "오른쪽 창 전용; Tab으로 포커스 전환", lambda app: app.start_side_terminal("claude", "claude")),
            Action("오른쪽 창 닫기", "Codex/Claude 오른쪽 창 종료", lambda app: app.close_side_terminal()),
            Action("Codex 전체화면", "TUI를 잠시 내려놓고 Codex 실행", lambda app: app.run_interactive("codex")),
            Action("Claude 전체화면", "TUI를 잠시 내려놓고 Claude 실행", lambda app: app.run_interactive("claude")),
            Action("원격 SSH", "런처 저장 비밀번호가 있으면 자동 입력", lambda app: app.run_ssh()),
            Action("분류기 점검", "data/*.jsonl 선택 후 dry-run", lambda app: classifier_dry(app.choose_jsonl())),
            Action("GLiNER 점검", "data/*.jsonl 선택 후 dry-run", lambda app: gliner_dry(app.choose_jsonl())),
            Action("순차 학습", "분류기 -> GLiNER 순서로 학습", lambda app: app.configure_sequential_train()),
            Action("분류기 상세 학습", "epoch/batch/lr/lora/precision 직접 설정", lambda app: app.configure_classifier_train()),
            Action("GLiNER 상세 학습", "epoch/batch/lr/device/steps 직접 설정", lambda app: app.configure_gliner_train()),
            Action("학습 정지", "분리 실행 중인 분류기/GLiNER 학습 종료", lambda app: stop_training_cmd()),
            Action("셸 명령", "직접 명령 입력", lambda app: app.ask("$ ")),
        ]

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.timeout(100)
        while True:
            self.poll_proc()
            self.poll_side_terminal()
            self.draw()
            key = self.stdscr.getch()
            if key == -1:
                continue
            if key == 9:
                if self.side_fd is not None:
                    self.side_focus = not self.side_focus
                continue
            if self.side_focus:
                self.handle_side_key(key)
                continue
            if key in (ord("q"), 27):
                self.stop_proc()
                self.stop_side_terminal()
                return
            if key in (curses.KEY_UP, ord("k")):
                self.selected = (self.selected - 1) % len(self.actions)
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selected = (self.selected + 1) % len(self.actions)
            elif key in (10, 13):
                self.run_selected()
            elif key == ord("x"):
                self.stop_proc()
            elif key == ord("c"):
                self.output.clear()
                self.current_line = ""
                self.bars = {}
            elif key == curses.KEY_RESIZE:
                self.resize_side_terminal()
            elif key == ord(":"):
                cmd = self.ask("$ ")
                if cmd:
                    self.start_command("shell", cmd)

    def start_command(self, name: str, cmd: str) -> None:
        if not cmd:
            return
        self.stop_proc()
        self.output.append(f"$ {cmd}")
        self.active_name = name
        self.status = "running"
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        self._reset_stream()
        # 바이트 스트림으로 받아 '\r' 를 직접 처리한다 (text 모드면 readline 이 '\n' 까지 블록됨)
        self.proc = subprocess.Popen(
            ["bash", "-lc", cmd],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            env=env,
        )

    def run_selected(self) -> None:
        action = self.actions[self.selected]
        cmd = action.command(self)
        if cmd:
            self.start_command(action.name, cmd)

    def ask_default(self, label: str, default: str) -> str:
        value = self.ask(f"{label} [{default}]: ")
        return value if value else default

    def choose_jsonl(self) -> str:
        files = sorted((ROOT / "data").rglob("*.jsonl"))
        if not files:
            return self.ask("추가 jsonl 경로 (비워도 됨): ")

        self.output.append("[jsonl] 비우면 없음, all은 전체 병합, 쉼표로 여러 개 선택 가능")
        for i, path in enumerate(files, start=1):
            rel = path.relative_to(ROOT)
            size_mb = path.stat().st_size / (1024 * 1024)
            self.output.append(f"  {i}. {rel} ({size_mb:.1f} MB)")
        choice = self.ask("jsonl 선택: ")
        if not choice:
            return ""
        if choice.strip().lower() == "all":
            selected = files
        else:
            selected = []
            for part in choice.split(","):
                part = part.strip()
                if not part:
                    continue
                if part.isdigit() and 1 <= int(part) <= len(files):
                    selected.append(files[int(part) - 1])
            if not selected:
                return choice
        if len(selected) == 1:
            return str(selected[0].relative_to(ROOT))

        TMP_DIR.mkdir(parents=True, exist_ok=True)
        out = TMP_DIR / f"selected-extra-{int(time.time())}.jsonl"
        with out.open("wb") as dst:
            for path in selected:
                with path.open("rb") as src:
                    dst.write(src.read())
                    dst.write(b"\n")
        self.output.append(f"[jsonl] {len(selected)}개 파일 병합 -> {out.relative_to(ROOT)}")
        return str(out.relative_to(ROOT))

    def configure_sequential_train(self) -> str | None:
        extra = self.choose_jsonl()
        prefix = self.ask_default("output prefix", ".scamguardian/training_sessions/cli-seq")
        profile = self.ask_default("profile safe/balanced/fast", "balanced").lower()
        dry_run = yn(self.ask_default("dry-run first? y/n", "n"), False)

        if profile == "safe":
            classifier_epochs, classifier_batch = "3", "2"
            gliner_epochs, gliner_batch = "3", "2"
        elif profile == "fast":
            classifier_epochs, classifier_batch = "3", "8"
            gliner_epochs, gliner_batch = "5", "8"
        else:
            classifier_epochs, classifier_batch = "3", "4"
            gliner_epochs, gliner_batch = "4", "4"

        extra_args = opt("--extra-jsonl", extra)
        classifier_out = f"{prefix}/classifier"
        gliner_out = f"{prefix}/gliner"
        classifier_args = [
            "python", "-m", "training.train_classifier",
            *opt("--output-dir", classifier_out),
            *extra_args,
            *opt("--epochs", classifier_epochs),
            *opt("--batch-size", classifier_batch),
            *opt("--lr", "2e-5"),
            "--lora",
            "--bf16",
            *opt("--early-stopping-patience", "2"),
        ]
        gliner_args = [
            "python", "-m", "training.train_gliner",
            *opt("--output-dir", gliner_out),
            *extra_args,
            *opt("--epochs", gliner_epochs),
            *opt("--batch-size", gliner_batch),
            *opt("--lr", "5e-6"),
            *opt("--device", "auto"),
        ]
        if dry_run:
            classifier_args.append("--dry-run")
            gliner_args.append("--dry-run")

        cmd = (
            "mkdir -p "
            + shlex.quote(prefix)
            + " && "
            + "printf '\\n[1/2] classifier training\\n' && "
            + conda_cmd(qjoin(classifier_args))
            + " && "
            + "printf '\\n[2/2] GLiNER training\\n' && "
            + conda_cmd(qjoin(gliner_args))
            + " && "
            + "printf '\\n[done] sequential training outputs: "
            + shlex.quote(prefix)
            + "\\n'"
        )
        return self.launch_training(prefix, cmd)

    def configure_classifier_train(self) -> str | None:
        out = self.ask_default("output dir", ".scamguardian/training_sessions/cli-classifier")
        extra = self.choose_jsonl()
        epochs = self.ask_default("epochs", "3")
        batch = self.ask_default("batch-size", "2")
        lr = self.ask_default("lr", "2e-5")
        max_length = self.ask_default("max-length", "512")
        val_ratio = self.ask_default("val-ratio", "0.1")
        min_per_class = self.ask_default("min-per-class", "5")
        seed = self.ask_default("seed", "17")
        lora = yn(self.ask_default("lora? y/n", "y"), True)
        precision = self.ask_default("precision bf16/fp16/none", "bf16").lower()
        patience = self.ask_default("early-stopping-patience", "2")
        threshold = self.ask_default("early-stopping-threshold", "0.0")
        loss_threshold = self.ask_default("diagnostic-loss-threshold", "3.0")
        max_records = self.ask_default("diagnostic-max-records", "200")
        dry_run = yn(self.ask_default("dry-run first? y/n", "n"), False)

        args = [
            "python", "-m", "training.train_classifier",
            *opt("--output-dir", out),
            *opt("--extra-jsonl", extra),
            *opt("--epochs", epochs),
            *opt("--batch-size", batch),
            *opt("--lr", lr),
            *opt("--max-length", max_length),
            *opt("--val-ratio", val_ratio),
            *opt("--min-per-class", min_per_class),
            *opt("--seed", seed),
            *opt("--early-stopping-patience", patience),
            *opt("--early-stopping-threshold", threshold),
            *opt("--diagnostic-loss-threshold", loss_threshold),
            *opt("--diagnostic-max-records", max_records),
        ]
        if lora:
            args.append("--lora")
            args.extend(opt("--lora-r", self.ask_default("lora-r", "16")))
            args.extend(opt("--lora-alpha", self.ask_default("lora-alpha", "32")))
            args.extend(opt("--lora-dropout", self.ask_default("lora-dropout", "0.1")))
        if precision in {"bf16", "fp16"}:
            args.append(f"--{precision}")
        if yn(self.ask_default("exclude negatives? y/n", "n"), False):
            args.append("--no-negatives")
        if dry_run:
            args.append("--dry-run")

        cmd = qjoin(args)
        return self.launch_training(out, conda_cmd(cmd))

    def configure_gliner_train(self) -> str | None:
        out = self.ask_default("output dir", ".scamguardian/training_sessions/cli-gliner")
        extra = self.choose_jsonl()
        epochs = self.ask_default("epochs", "3")
        batch = self.ask_default("batch-size", "2")
        lr = self.ask_default("lr", "5e-6")
        val_ratio = self.ask_default("val-ratio", "0.1")
        seed = self.ask_default("seed", "17")
        max_types = self.ask_default("max-types", "30")
        max_tokens = self.ask_default("max-tokens", "384")
        device = self.ask_default("device auto/cuda/cpu", "auto")
        max_steps = self.ask("max-steps (blank none): ")
        logging_steps = self.ask_default("logging-steps", "20")
        save_steps = self.ask("save-steps (blank none): ")
        no_bf16 = yn(self.ask_default("no-bf16? y/n", "n"), False)
        no_checkpointing = yn(self.ask_default("disable gradient checkpointing? y/n", "n"), False)
        local_files_only = yn(self.ask_default("local-files-only? y/n", "n"), False)
        dry_run = yn(self.ask_default("dry-run first? y/n", "n"), False)

        args = [
            "python", "-m", "training.train_gliner",
            *opt("--output-dir", out),
            *opt("--extra-jsonl", extra),
            *opt("--epochs", epochs),
            *opt("--batch-size", batch),
            *opt("--lr", lr),
            *opt("--val-ratio", val_ratio),
            *opt("--seed", seed),
            *opt("--max-types", max_types),
            *opt("--max-tokens", max_tokens),
            *opt("--device", device),
            *opt("--max-steps", max_steps),
            *opt("--logging-steps", logging_steps),
            *opt("--save-steps", save_steps),
        ]
        if no_bf16:
            args.append("--no-bf16")
        if no_checkpointing:
            args.append("--no-gradient-checkpointing")
        if local_files_only:
            args.append("--local-files-only")
        if dry_run:
            args.append("--dry-run")

        cmd = qjoin(args)
        return self.launch_training(out, conda_cmd(cmd))

    def launch_training(self, out_dir: str, cmd: str) -> None:
        """학습을 분리(detached)된 세션으로 띄우고, TUI 는 train.log 를 tail 로만 본다.

        이렇게 하면 로그 보기/다른 메뉴 이동/TUI 종료가 학습을 죽이지 않는다.
        실제 학습 중단은 'Stop training' 액션으로만 한다.
        """
        out_dir = out_dir.rstrip("/")
        log = f"{out_dir}/train.log"
        inner = f'{cmd} ; echo "[train exit $?]"'
        launch = (
            "mkdir -p "
            + shlex.quote(out_dir)
            + " && setsid bash -lc "
            + shlex.quote(inner)
            + " >> "
            + shlex.quote(log)
            + " 2>&1 < /dev/null &"
        )
        self.stop_proc()
        self.output.append(f"$ {cmd}")
        self.output.append(f"[train] detached; logging -> {log} (Stop training 로 중단)")
        subprocess.run(["bash", "-lc", launch], cwd=str(ROOT))
        # foreground 은 로그 tail — 이걸 멈춰도(x) 학습은 계속된다 (진행 바는 한 줄에서 갱신)
        self.start_command("train log", tail_cmd(ROOT / log))
        return None

    def tail_train_log(self) -> str | None:
        log = latest_train_log()
        if not log:
            self.output.append(
                "[학습 로그] .scamguardian/training_sessions/* 아래 train.log가 없습니다"
            )
            return None
        self.output.append(f"[학습 로그] {log.relative_to(ROOT)}")
        return tail_cmd(log)

    def run_interactive(self, cmd: str) -> None:
        self.stop_proc()
        curses.endwin()
        try:
            subprocess.call(["bash", "-lc", cmd], cwd=str(ROOT))
            input("\n[Enter를 누르면 ScamGuardian TUI로 돌아갑니다]")
        finally:
            curses.curs_set(0)
            self.stdscr.clear()
        self.output.append(f"[복귀] {cmd}")

    def open_external_terminal(self, name: str) -> None:
        if name == "claude":
            title = "Claude ScamGuardian"
            shell = f"cd {shlex.quote(str(ROOT))} && claude"
            args = ["wt.exe", "new-tab", "--title", title, "wsl.exe", "-e", "bash", "-lc", shell]
        elif name == "codex":
            title = "Codex ScamGuardian"
            try:
                win_root = subprocess.check_output(["wslpath", "-w", str(ROOT)], text=True).strip()
            except subprocess.CalledProcessError:
                win_root = str(ROOT)
            ps = (
                "$ErrorActionPreference='Continue'; "
                f"Set-Location -LiteralPath {self.ps_quote(win_root)}; "
                "codex"
            )
            args = ["wt.exe", "new-tab", "--title", title, "pwsh.exe", "-NoLogo", "-NoExit", "-Command", ps]
        else:
            self.output.append(f"[터미널] 알 수 없는 앱: {name}")
            return None

        try:
            subprocess.Popen(args, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.output.append(f"[터미널] Windows Terminal에서 {name} 열림")
        except FileNotFoundError:
            self.output.append("[터미널] wt.exe를 찾지 못했습니다. Windows Terminal 설치 또는 전체화면 실행을 사용하세요.")
        except OSError as exc:
            self.output.append(f"[터미널] {name} 열기 실패: {exc}")
        return None

    @staticmethod
    def ps_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def codex_side_cmd(self) -> str:
        return (
            "if [ -x \"$HOME/.local/bin/codex\" ]; then exec \"$HOME/.local/bin/codex\"; fi; "
            "if [ -x \"$HOME/.npm-global/bin/codex\" ]; then exec \"$HOME/.npm-global/bin/codex\"; fi; "
            "if [ -x \"/usr/local/bin/codex\" ]; then exec \"/usr/local/bin/codex\"; fi; "
            "FOUND=$(command -v codex 2>/dev/null || true); "
            "case \"$FOUND\" in /mnt/c/*) "
            "echo '[codex] WSL codex is not installed; PATH points to Windows Codex:'; "
            "echo \"        $FOUND\"; "
            "echo '[codex] Install/use a Linux WSL codex binary to run it inside this pane.'; "
            "echo '[codex] Leaving a shell open here.'; exec bash ;; "
            "*) if [ -n \"$FOUND\" ]; then exec \"$FOUND\"; fi ;; "
            "esac; "
            "echo '[codex] WSL codex not found in PATH.'; "
            "echo '[codex] Leaving a shell open here.'; exec bash"
        )

    def start_side_terminal(self, name: str, cmd: str) -> None:
        self.stop_side_terminal()
        self.side_output.clear()
        self.side_current = ""
        self.side_name = name
        self.side_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(str(ROOT))
            os.execvp("bash", ["bash", "-lc", cmd])
        self.side_pid = pid
        self.side_fd = fd
        os.set_blocking(fd, False)
        self.side_focus = True
        self.side_screen = MiniTerminal(24, 80)
        self.side_screen.write(f"$ {name}\n")
        self.resize_side_terminal()
        return None

    def close_side_terminal(self) -> None:
        self.stop_side_terminal()
        return None

    def stop_side_terminal(self) -> None:
        if self.side_pid is not None:
            try:
                os.kill(self.side_pid, signal.SIGTERM)
                time.sleep(0.1)
                done, _status = os.waitpid(self.side_pid, os.WNOHANG)
                if done == 0:
                    os.kill(self.side_pid, signal.SIGKILL)
                    os.waitpid(self.side_pid, 0)
            except (ChildProcessError, ProcessLookupError, OSError):
                pass
        if self.side_fd is not None:
            try:
                os.close(self.side_fd)
            except OSError:
                pass
        self.side_pid = None
        self.side_fd = None
        self.side_name = "none"
        self.side_focus = False
        self.side_size = (0, 0)
        self.side_screen = None

    def resize_side_terminal(self) -> None:
        if self.side_fd is None:
            return
        h, w = self.stdscr.getmaxyx()
        menu_w = min(34, max(24, w // 3))
        out_x = menu_w + 1
        out_w = max(20, w - out_x - 1)
        body_h = h - 3
        term_h = body_h
        rows = max(4, term_h - 2)
        cols = max(20, out_w - 2)
        size = (rows, cols)
        if size == self.side_size:
            return
        self.side_size = size
        if self.side_screen is None:
            self.side_screen = MiniTerminal(rows, cols)
        else:
            self.side_screen.resize(rows, cols)
        try:
            packed = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.side_fd, termios.TIOCSWINSZ, packed)
        except OSError:
            pass

    def handle_side_key(self, key: int) -> None:
        if self.side_fd is None:
            self.side_focus = False
            return
        if key == 29:  # Ctrl+]
            self.stop_side_terminal()
            return
        mapping = {
            curses.KEY_UP: b"\x1b[A",
            curses.KEY_DOWN: b"\x1b[B",
            curses.KEY_RIGHT: b"\x1b[C",
            curses.KEY_LEFT: b"\x1b[D",
            curses.KEY_HOME: b"\x1b[H",
            curses.KEY_END: b"\x1b[F",
            curses.KEY_DC: b"\x1b[3~",
            curses.KEY_NPAGE: b"\x1b[6~",
            curses.KEY_PPAGE: b"\x1b[5~",
            curses.KEY_BACKSPACE: b"\x7f",
        }
        data = mapping.get(key)
        if data is None:
            if key in (10, 13):
                data = b"\n"
            elif key in (127, 8):
                data = b"\x7f"
            elif 0 <= key <= 255:
                data = bytes([key])
        if data:
            try:
                os.write(self.side_fd, data)
            except OSError:
                self.stop_side_terminal()

    def poll_side_terminal(self) -> None:
        if self.side_fd is None:
            return
        while True:
            ready, _, _ = select.select([self.side_fd], [], [], 0)
            if not ready:
                break
            try:
                chunk = os.read(self.side_fd, 65536)
            except BlockingIOError:
                break
            except OSError:
                self.stop_side_terminal()
                return
            if not chunk:
                break
            self.consume_side_output(chunk)

        if self.side_pid is not None:
            try:
                done, status = os.waitpid(self.side_pid, os.WNOHANG)
            except ChildProcessError:
                done, status = self.side_pid, 0
            if done:
                code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status
                if self.side_screen is not None:
                    self.side_screen.write(f"\n[exit {code}] {self.side_name}\n")
                if self.side_fd is not None:
                    try:
                        os.close(self.side_fd)
                    except OSError:
                        pass
                self.side_pid = None
                self.side_fd = None
                self.side_focus = False

    def consume_side_output(self, chunk: bytes) -> None:
        if self.side_screen is None:
            return
        text = self.side_decoder.decode(chunk)
        self.side_screen.write(text)

    def run_ssh(self) -> None:
        user = os.getenv("SG_REMOTE_USER", "mpssh")
        host = os.getenv("SG_REMOTE_HOST", "192.168.0.66")
        port = os.getenv("SG_REMOTE_PORT", "2222")
        password = os.getenv("SG_SSH_PASSWORD", "")
        self.reset_known_host(host, port)
        cmd = self.ssh_command(user, host, port)
        if not password:
            self.run_interactive_ssh(cmd, host, port)
            return

        retries = 0
        max_retries = 1
        self.stop_proc()
        curses.endwin()
        try:
            while True:
                result = self.run_ssh_once(cmd, password)
                if not result["host_key_changed"] or retries >= max_retries:
                    break
                retries += 1
                print(f"\n[ssh] host key changed for {host}; resetting known_hosts entry and retrying once...")
                self.reset_known_host(host, port)
            input("\n[Enter를 누르면 ScamGuardian TUI로 돌아갑니다]")
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            self.stdscr.clear()
        self.output.append(f"[복귀] ssh {user}@{host}")

    def run_interactive_ssh(self, cmd: str, host: str, port: str = "2222") -> None:
        self.stop_proc()
        curses.endwin()
        try:
            code = subprocess.call(["bash", "-lc", cmd], cwd=str(ROOT))
            if code != 0:
                print(f"\n[ssh] if this was a host-key mismatch, resetting {host} and retrying once...")
                self.reset_known_host(host, port)
                subprocess.call(["bash", "-lc", cmd], cwd=str(ROOT))
            input("\n[Enter를 누르면 ScamGuardian TUI로 돌아갑니다]")
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            self.stdscr.clear()
        self.output.append(f"[복귀] {cmd}")

    def ssh_command(self, user: str, host: str, port: str = "2222") -> str:
        return (
            "ssh "
            f"-p {shlex.quote(port)} "
            "-o StrictHostKeyChecking=accept-new "
            f"{shlex.quote(user)}@{shlex.quote(host)}"
        )

    def reset_known_host(self, host: str, port: str = "2222") -> None:
        known_hosts = Path.home() / ".ssh" / "known_hosts"
        known_hosts.parent.mkdir(mode=0o700, exist_ok=True)
        targets = [f"[{host}]:{port}"]
        if port == "22":
            targets.append(host)
        for target in targets:
            subprocess.call(
                ["ssh-keygen", "-f", str(known_hosts), "-R", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def run_ssh_once(self, cmd: str, password: str) -> dict[str, bool]:
        pid, fd = pty.fork()
        if pid == 0:
            os.execvp("bash", ["bash", "-lc", cmd])

        sent_password = False
        transcript = b""
        while True:
            try:
                ready, _, _ = select.select([fd], [], [], 0.2)
                if fd in ready:
                    data = os.read(fd, 4096)
                    if not data:
                        break
                    os.write(sys.stdout.fileno(), data)
                    sys.stdout.flush()
                    transcript = (transcript + data)[-4096:]
                    lowered = transcript.lower()
                    if not sent_password and b"password" in lowered:
                        os.write(fd, (password + "\n").encode())
                        sent_password = True

                done, _status = os.waitpid(pid, os.WNOHANG)
                if done:
                    break
            except OSError:
                break

        lowered = transcript.lower()
        return {
            "host_key_changed": (
                b"remote host identification has changed" in lowered
                or b"host key verification failed" in lowered
            )
        }

    def stop_proc(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                time.sleep(0.1)
                if self.proc.poll() is None:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.output.append("[실행 중인 명령을 정지했습니다]")
        self._commit_current_line()
        self.proc = None
        self.active_name = "idle"
        self.status = "ready"

    def _emit_line(self, line: str) -> None:
        """확정된 한 줄을 분류한다: 노이즈는 버리고, 진행 바는 bar 슬롯에, 나머지는 로그에."""
        if is_noise(line):
            return
        m = PROGRESS_RE.search(line)
        if not m:
            self.output.append(line)
            return
        key = f"{line[: m.start()].strip()}\x00{m.group('total')}"
        self.bars[key] = line
        # 진행 중(<100%)인 바가 갱신되면, 이미 끝난(100%) 다른 바들은 흔적이므로 치운다
        if int(m.group("pct")) < 100:
            self.bars = {
                k: v for k, v in self.bars.items() if k == key or bar_pct(v) != 100
            }

    def _commit_current_line(self) -> None:
        if self.current_line:
            self._emit_line(self.current_line)
            self.current_line = ""

    def _consume(self, chunk: bytes) -> None:
        """바이트 청크를 처리한다. '\\n' 은 줄 확정, '\\r' 은 in-place 갱신."""
        text = self._decoder.decode(chunk)
        for ch in text:
            if ch == "\n":
                self._emit_line(self.current_line)
                self.current_line = ""
                self._cr = False
            elif ch == "\r":
                # CRLF 면 다음 '\n' 이 줄을 확정하므로 여기선 표시만 해둔다
                self._cr = True
            else:
                if self._cr:
                    # '\r' 뒤 실제 글자 → 같은 줄을 덮어쓴다 (tqdm 진행 바)
                    self.current_line = ""
                    self._cr = False
                self.current_line += ch

    def poll_proc(self) -> None:
        if not self.proc:
            return
        pipe = self.proc.stdout
        if pipe:
            fd = pipe.fileno()
            while True:
                ready, _, _ = select.select([fd], [], [], 0)
                if not ready:
                    break
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self._consume(chunk)
        code = self.proc.poll()
        if code is not None:
            self._commit_current_line()
            self.output.append(f"[exit {code}] {self.active_name}")
            self.proc = None
            self.active_name = "idle"
            self.status = "ready"

    def ask(self, label: str) -> str:
        curses.curs_set(1)
        _, w = self.stdscr.getmaxyx()
        value = ""
        while True:
            self.draw(prompt=f"{label}{value}")
            ch = self.stdscr.getch()
            if ch == -1:
                continue
            if ch in (10, 13):
                curses.curs_set(0)
                return value.strip()
            if ch == 27:
                curses.curs_set(0)
                return ""
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                value = value[:-1]
            elif 32 <= ch <= 126 and len(value) < max(10, w - len(label) - 4):
                value += chr(ch)

    @staticmethod
    def display_width(text: str) -> int:
        return sum(MiniTerminal._char_width(ch) for ch in text)

    @classmethod
    def fit_text(cls, text: str, width: int) -> str:
        used = 0
        out = ""
        for ch in text:
            ch_w = MiniTerminal._char_width(ch)
            if used + ch_w > width:
                break
            out += ch
            used += ch_w
        return out

    @classmethod
    def wrap_text(cls, text: str, width: int, max_lines: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if cls.display_width(candidate) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
        return [cls.fit_text(line, width) for line in lines[:max_lines]]

    def draw(self, prompt: str | None = None) -> None:
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()
        if h < 14 or w < 60:
            self.stdscr.addstr(0, 0, "터미널이 너무 작습니다. 최소 60x14 이상으로 키워주세요.")
            self.stdscr.refresh()
            return

        header = f" ScamGuardian TUI | 상태: {self.status} | 실행: {self.active_name} | q 종료 x 정지 c 지우기 "
        self.stdscr.addstr(0, 0, header[: w - 1], curses.A_REVERSE)

        menu_w = min(34, max(24, w // 3))
        out_x = menu_w + 1
        out_w = w - out_x - 1
        body_h = h - 3

        self._box(1, 0, body_h, menu_w, "메뉴")
        desc_rows = 2
        divider_y = 1 + body_h - desc_rows - 2
        item_rows = max(1, divider_y - 2)
        if self.selected < item_rows:
            start_idx = 0
        else:
            start_idx = min(self.selected - item_rows + 1, max(0, len(self.actions) - item_rows))
        visible_actions = self.actions[start_idx : start_idx + item_rows]
        for i, action in enumerate(visible_actions):
            action_idx = start_idx + i
            attr = curses.A_REVERSE if action_idx == self.selected else curses.A_NORMAL
            line = f"{action_idx + 1:2d}. {action.name}"[: menu_w - 2]
            self.stdscr.addstr(2 + i, 1, line.ljust(menu_w - 2), attr)

        if divider_y > 2:
            self.stdscr.addstr(divider_y, 1, "-" * (menu_w - 2), curses.A_DIM)
            desc_lines = self.wrap_text(self.actions[self.selected].desc, menu_w - 2, desc_rows)
            for row in range(desc_rows):
                text = desc_lines[row] if row < len(desc_lines) else ""
                self.stdscr.addstr(divider_y + 1 + row, 1, text.ljust(menu_w - 2), curses.A_DIM)

        has_side = self.side_screen is not None or self.side_fd is not None
        if has_side:
            term_h = body_h
            self.resize_side_terminal()
            title = f"{self.side_name} 창"
            if self.side_focus:
                title += " [포커스: Tab 메뉴, Ctrl+] 닫기]"
            else:
                title += " [Tab 포커스]"
            self._box(1, out_x, term_h, out_w, title)
            term_lines = self.side_screen.display() if self.side_screen is not None else []
            visible_term = term_lines[-(term_h - 2) :]
            for i, line in enumerate(visible_term):
                safe = sanitize(line.replace("\t", "    "))[: out_w - 2]
                try:
                    attr = curses.A_BOLD if self.side_focus and i == len(visible_term) - 1 else curses.A_NORMAL
                    self.stdscr.addstr(2 + i, out_x + 1, safe, attr)
                except curses.error:
                    pass
        else:
            output_h = body_h
            self._box(1, out_x, output_h, out_w, "출력")
            lines = list(self.output)
            # 진행 바는 bar 별 한 줄씩 맨 아래에 (흔적 누적 없이 in-place 갱신)
            lines.extend(self.bars.values())
            if self.current_line:
                lines.append(self.current_line)
            visible = lines[-(output_h - 2) :]
            for i, line in enumerate(visible):
                safe = sanitize(line.replace("\t", "    "))[: out_w - 2]
                try:
                    self.stdscr.addstr(2 + i, out_x + 1, safe)
                except curses.error:
                    pass

        if prompt is not None:
            input_line = prompt
        elif self.side_focus:
            input_line = "> 오른쪽 창 포커스 | Tab: 메뉴 | Ctrl+]: 오른쪽 창 닫기"
        else:
            input_line = "> Enter: 실행 | Tab: 오른쪽 창 | : 직접 명령"
        self.stdscr.addstr(h - 1, 0, input_line[: w - 1], curses.A_REVERSE)
        self.stdscr.refresh()

    def _box(self, y: int, x: int, height: int, width: int, title: str) -> None:
        self.stdscr.addstr(y, x, "+" + "-" * (width - 2) + "+")
        for row in range(y + 1, y + height - 1):
            self.stdscr.addstr(row, x, "|")
            self.stdscr.addstr(row, x + width - 1, "|")
        self.stdscr.addstr(y + height - 1, x, "+" + "-" * (width - 2) + "+")
        self.stdscr.addstr(y, x + 2, f" {title} "[: max(0, width - 4)])


def main() -> None:
    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(lambda stdscr: App(stdscr).run())


if __name__ == "__main__":
    main()
