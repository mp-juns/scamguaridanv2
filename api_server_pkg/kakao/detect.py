"""카카오 페이로드 → (source, InputType) 감지 + CDN URL 로컬 다운로드.

`_kakao_detect_input` 은 카카오 *챗봇 채널* 의 실제 동작을 반영한다:
- 표준 블록 파라미터 (image/picture/photo/pdf/document/video/file/attachment)
- action.params 의 *모든* 값을 훑어서 URL 인 것 (utterance 안에 CDN URL 박혀 오는 경우)
- 마지막 fallback: utterance 내부 첫 URL
- APK/EXE/DMG 등 실행 파일은 InputType.FILE 로 분류해 VT 파일 스캔 강제 라우팅
"""

from __future__ import annotations

import logging
import re
import uuid as _uuid
from pathlib import Path

import requests as _requests

from pipeline import kakao_formatter

_URL_RE = re.compile(r"https?://\S+")
_YOUTUBE_RE = re.compile(r"https?://(www\.)?(youtube\.com|youtu\.be)/")
# STT 가능한 영상 호스트 화이트리스트 — yt-dlp 가 안정적으로 음성 추출하는 사이트만.
# 일반 URL 은 아래 목록에 없으면 InputType.URL 로 떨어져 STT 시도 안 함.
_VIDEO_HOST_RE = re.compile(
    r"https?://([a-z0-9-]+\.)*("
    r"youtube\.com|youtu\.be|"
    r"vimeo\.com|"
    r"twitch\.tv|"
    r"tiktok\.com|"
    r"dailymotion\.com|"
    r"tv\.naver\.com|"
    r"tv\.kakao\.com|"
    r"facebook\.com/watch|fb\.watch"
    r")/",
    re.IGNORECASE,
)
_IMAGE_URL_RE = re.compile(r"\.(jpg|jpeg|png|webp|gif|bmp)(\?|$)", re.IGNORECASE)
_PDF_URL_RE = re.compile(r"\.pdf(\?|$)", re.IGNORECASE)
_AUDIO_URL_RE = re.compile(r"\.(mp3|wav|m4a|aac|ogg|flac|opus)(\?|$)", re.IGNORECASE)
# 사기범이 링크로 자주 뿌리는 악성 실행파일 확장자 — 다운로드 후 VT 파일 스캔 강제 라우팅
_EXECUTABLE_URL_RE = re.compile(
    r"\.(apk|exe|dmg|msi|jar|bat|cmd|scr|app|ipa|deb|rpm)(\?|$)", re.IGNORECASE
)
_VIDEO_URL_RE = re.compile(r"\.(mp4|mov|webm|mkv|avi)(\?|$)", re.IGNORECASE)


def _classify_url_input(url: str) -> kakao_formatter.InputType:
    """URL 확장자/호스트 보고 VIDEO/IMAGE/PDF/FILE/URL 구분.

    InputType.VIDEO 는 STT 시도 가능한 영상 호스트(YouTube 등) 또는 영상 확장자 직링크에만 부여.
    그 외 일반 웹 URL 은 InputType.URL — STT skip, Phase 0 VT 만 거쳐 텍스트 분석.
    """
    InputType = kakao_formatter.InputType
    # 영상 호스트 화이트리스트 또는 영상 확장자 직링크 → VIDEO
    if _VIDEO_HOST_RE.search(url) or _VIDEO_URL_RE.search(url):
        return InputType.VIDEO
    if _IMAGE_URL_RE.search(url):
        return InputType.IMAGE
    if _PDF_URL_RE.search(url):
        return InputType.PDF
    if _AUDIO_URL_RE.search(url):
        return InputType.AUDIO
    # APK/EXE/DMG 등 실행 파일 — VT 파일 스캔이 필수. 일반 웹페이지(URL) 스캔이 아니라 다운로드 후 검사로 강제.
    if _EXECUTABLE_URL_RE.search(url):
        return InputType.FILE
    # 일반 웹 URL — STT 안 함, Phase 0 VT + URL 텍스트 분석으로 진행
    return InputType.URL


def _kakao_detect_input(
    utterance: str, action_params: dict
) -> tuple[str, kakao_formatter.InputType]:
    """카카오 페이로드에서 분석 대상 소스와 입력 유형을 감지한다.

    Returns: (source, InputType)
    """
    InputType = kakao_formatter.InputType

    # 1) 정해진 키로 들어온 파일/영상/이미지/PDF URL — 카카오 표준 블록 파라미터.
    for key in (
        "image", "picture", "photo",  # 이미지
        "pdf", "document",            # PDF/문서
        "audio", "voice", "sound",    # 음성
        "video", "video_url",         # 영상
        "file", "attachment",         # 일반 파일 (확장자 보고 재분류)
    ):
        val = action_params.get(key)
        url = ""
        if isinstance(val, str) and val.startswith("http"):
            url = val
        elif isinstance(val, dict):
            v = val.get("url", "")
            if isinstance(v, str) and v.startswith("http"):
                url = v
        if not url:
            continue
        if key in ("image", "picture", "photo"):
            return url, InputType.IMAGE
        if key in ("pdf", "document"):
            return url, InputType.PDF
        if key in ("audio", "voice", "sound"):
            return url, InputType.AUDIO
        if key in ("video", "video_url"):
            return url, InputType.VIDEO
        # file/attachment — URL 확장자 보고 분기
        kind = _classify_url_input(url)
        if kind in (InputType.IMAGE, InputType.PDF, InputType.AUDIO):
            return url, kind
        return url, InputType.FILE

    # 2) 표준 키에 매칭 안 된 경우 — action.params 의 *모든* 값을 훑어서 URL 인 것 중 확장자로 분기.
    for _key, val in action_params.items():
        url = ""
        if isinstance(val, str) and val.startswith("http"):
            url = val
        elif isinstance(val, dict):
            v = val.get("url", "")
            if isinstance(v, str) and v.startswith("http"):
                url = v
        if not url:
            continue
        kind = _classify_url_input(url)
        if kind in (InputType.IMAGE, InputType.PDF, InputType.AUDIO):
            return url, kind
        if _VIDEO_URL_RE.search(url):
            return url, InputType.VIDEO
        return url, InputType.FILE

    # 3) utterance 전체 또는 일부가 URL — 둘 다 첫 매칭 URL 만 사용
    url_match = _URL_RE.search(utterance)
    if url_match:
        url = url_match.group(0)
        return url, _classify_url_input(url)

    # 4) 순수 텍스트
    return utterance, InputType.TEXT


def _kakao_materialize_url(url: str, suffix_hint: str = "") -> str:
    """카카오 CDN 등의 HTTP URL 을 로컬 파일로 다운로드하고 경로 반환."""
    log = logging.getLogger("kakao_dl")

    suffix = suffix_hint
    if not suffix:
        path = url.split("?", 1)[0]
        idx = path.rfind(".")
        if idx > 0 and len(path) - idx <= 6:
            suffix = path[idx:]
    if not suffix:
        suffix = ".bin"

    target_dir = Path(".scamguardian") / "uploads" / "kakao"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{_uuid.uuid4().hex}{suffix}"

    resp = _requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    with target.open("wb") as fp:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                fp.write(chunk)
    log.info("카카오 미디어 다운로드 완료: %s → %s (%d bytes)",
             url[:80], target.name, target.stat().st_size)
    return str(target)
