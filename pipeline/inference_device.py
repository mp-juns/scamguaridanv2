"""추론 디바이스 선택 — 게이트·분류기·GLiNER 공용.

`SCAMGUARDIAN_INFERENCE_DEVICE` (기본 `auto`):
  - `auto` — CUDA 사용 가능하면 `cuda`, 아니면 `cpu` (Render 등 GPU 없는 배포는 자동 cpu)
  - `cpu` / `cuda` / `cuda:N` — 명시 고정. cuda 요청인데 불가하면 cpu 로 안전 fallback

학습(training/)은 자체 device 인자를 쓰므로 여기 영향 없음. dtype 은 디바이스와 무관하게
fp32 통일 (classifier._load_finetuned_model / extractor._get_model 의 .float() 참조).
"""

from __future__ import annotations

import os

_ENV = "SCAMGUARDIAN_INFERENCE_DEVICE"


def get_inference_device() -> str:
    pref = (os.getenv(_ENV) or "auto").strip().lower()
    if pref == "cpu":
        return "cpu"

    import torch

    cuda_ok = torch.cuda.is_available()
    if pref == "auto":
        return "cuda" if cuda_ok else "cpu"
    if pref == "cuda" or pref.startswith("cuda:"):
        if cuda_ok:
            return pref
        print(f"[device] {_ENV}={pref} 요청됐지만 CUDA 사용 불가 — cpu 로 fallback")
        return "cpu"
    print(f"[device] {_ENV}={pref!r} 인식 불가 — auto 처리")
    return "cuda" if cuda_ok else "cpu"
