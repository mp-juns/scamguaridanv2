"""
ScamGuardian v2 — 중앙 설정 모듈 (facade)

구현은 세 모듈로 분리됨:
- pipeline.config_taxonomy — 스캠 유형 12종·라벨 세트·런타임 확장·Stage 2 라우팅·LABEL_DEFINITIONS
- pipeline.config_gate     — Stage 1 게이트 버킷(5종)·content_label/sample_kind 학습 정책
- pipeline.config_flags    — 검출 신호 카탈로그·FLAG_RATIONALE(학술/법적 근거)·도메인 신뢰도

이 파일에는 런타임 튜닝 노브(모델 식별자·임계값·API 설정)만 남고,
기존 public 이름 전부를 재export 한다 — 소비자(`from pipeline.config import X`)는 무변경.
"""

from __future__ import annotations

import os

from pipeline.config_taxonomy import (  # noqa: F401
    BASE_LABELS,
    COMMON_RISK_LABELS,
    DEFAULT_LABEL_SETS,
    DEFAULT_SCAM_TYPES,
    DEFAULT_SCAM_TYPE_DESCRIPTIONS,
    LABEL_DEFINITIONS,
    LABEL_SETS,
    SCAM_TYPES,
    SCAM_TYPE_DESCRIPTIONS,
    STAGE2_CANDIDATE_TOP_N,
    STAGE2_DOMINANCE_GAP,
    build_scam_taxonomy,
    get_runtime_scam_taxonomy,
)
from pipeline.config_gate import (  # noqa: F401
    CONTENT_LABELS,
    CONTENT_LABELS_FOR_GATE_TRAINING,
    CONTENT_LABELS_REVIEW_ONLY,
    CONTENT_LABEL_SCAM_TYPE_TARGET,
    GATE_BUCKETS,
    GATE_EXECUTION_PROFILE,
    GATE_FALLBACK_BUCKET,
    GATE_LABELS_KO,
    GATE_MIN_CHARS,
    GATE_NORMAL,
    GATE_SCAM_ATTEMPT,
    GATE_SCAM_NEWS_EDU,
    GATE_SUSPICIOUS_INSUFFICIENT,
    GATE_UNDETERMINED,
    SAMPLE_KINDS,
    SAMPLE_KIND_NORMAL,
    SAMPLE_KIND_REAL_SCAM,
    SAMPLE_KIND_REVIEW,
    SAMPLE_KIND_SCAM_NEWS_EDU,
    SAMPLE_KIND_SYNTHETIC_SCAM,
)
from pipeline.config_flags import (  # noqa: F401
    DETECTED_FLAGS,
    DOMAIN_TRUST_SCORES,
    FLAG_LABELS_KO,
    FLAG_RATIONALE,
    TRUSTED_QUERY_A_DOMAINS,
    flag_label_ko,
    flag_rationale,
)

# ──────────────────────────────────────────────
# 모델 식별자
# ──────────────────────────────────────────────
MODELS = {
    "classifier": "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
    "gliner": "taeminlee/gliner_ko",
    "sbert_similarity": "paraphrase-multilingual-MiniLM-L12-v2",
    "whisper": "medium",
}

# ──────────────────────────────────────────────
# GLiNER 추출 설정
# ──────────────────────────────────────────────
GLINER_THRESHOLD: float = 0.4          # 재현율 우선 (미탐 방지)
GLINER_CHUNK_SIZE: int = 300           # 문자 기준 청크 크기
GLINER_CHUNK_OVERLAP: int = 50         # 청크 간 겹침 문자 수

# ──────────────────────────────────────────────
# 분류 설정
# ──────────────────────────────────────────────
CLASSIFICATION_THRESHOLD: float = 0.3  # 이 이하면 "판별 불가"

# 키워드 부스팅: NLI 스코어가 애매할 때 키워드 존재로 보정
KEYWORD_BOOST: dict[str, list[str]] = {
    "투자 사기": ["투자", "수익", "수익률", "보장", "펀드", "주식", "원금", "배당"],
    "건강식품 사기": ["건강식품", "치료", "효능", "완치", "약", "질병", "암", "당뇨", "식품", "보조제", "의사", "박사"],
    "부동산 사기": ["부동산", "아파트", "토지", "분양", "재개발", "임대", "평당", "전세", "월세"],
    "코인 사기": ["코인", "비트코인", "토큰", "거래소", "가상자산", "암호화폐", "이더리움", "채굴"],
    "기관 사칭": ["검찰", "경찰", "금감원", "금융감독원", "수사", "사건번호", "안전계좌", "주민번호", "영장", "압수수색"],
    "대출 사기": ["대출", "저금리", "신용등급", "무담보", "무보증", "당일 입금", "선납", "보증금", "수수료", "서민금융"],
    "메신저 피싱": ["카카오톡", "SNS", "지인", "엄마", "아빠", "급해", "잠깐", "계좌", "보내줘", "빌려줘", "사칭"],
    "로맨스 스캠": ["사랑", "좋아해", "만나고 싶어", "군인", "의사", "해외", "달러", "송금", "선물", "비자", "외교관"],
    "취업·알바 사기": ["재택", "알바", "채용", "일당", "시급", "교육비", "등록금", "선입금", "합격", "취업", "스마트폰"],
    "납치·협박형": ["납치", "잡혀있어", "다쳐", "죽여", "협박", "빨리", "경찰 부르면", "가족", "자녀", "보내지 않으면"],
    "스미싱": ["택배", "결제", "링크", "클릭", "확인하세요", "앱 설치", "본인인증", "보안", "업데이트", "URL"],
    "중고거래 사기": ["중고나라", "당근마켓", "번개장터", "직거래", "운송장", "택배", "에스크로", "안전결제", "선입금"],
}
KEYWORD_BOOST_WEIGHT: float = 0.25  # 키워드 매칭 시 가산할 최대 스코어
KEYWORD_NO_MATCH_PENALTY: float = 0.05  # 키워드가 하나도 없을 때 감점

# ──────────────────────────────────────────────
# Serper API 설정
# ──────────────────────────────────────────────
SERPER_API_URL: str = "https://google.serper.dev/search"
SERPER_DELAY: float = 0.5              # 쿼리 간 딜레이 (초)
SERPER_MAX_CONCURRENT: int = int(os.getenv("SERPER_MAX_CONCURRENT", "3"))
SERPER_BATCH_DELAY: float = float(os.getenv("SERPER_BATCH_DELAY", "0.2"))

# ──────────────────────────────────────────────
# STT 설정
# ──────────────────────────────────────────────
STT_BACKEND: str = os.getenv("STT_BACKEND", "whisper")  # "whisper" | "claude"

# ──────────────────────────────────────────────
# Ollama / LLM 보조 판정 설정
# ──────────────────────────────────────────────
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "15m")
OLLAMA_MAX_TRANSCRIPT_CHARS: int = int(os.getenv("OLLAMA_MAX_TRANSCRIPT_CHARS", "1200"))
OLLAMA_MAX_ENTITY_COUNT: int = int(os.getenv("OLLAMA_MAX_ENTITY_COUNT", "12"))
OLLAMA_MAX_TRIGGERED_FLAG_COUNT: int = int(os.getenv("OLLAMA_MAX_TRIGGERED_FLAG_COUNT", "6"))
OLLAMA_NUM_PREDICT: int = int(os.getenv("OLLAMA_NUM_PREDICT", "384"))
RAG_TOP_K: int = int(os.getenv("SCAMGUARDIAN_RAG_TOP_K", "3"))
RAG_MAX_CASES_IN_PROMPT: int = int(os.getenv("SCAMGUARDIAN_RAG_MAX_CASES_IN_PROMPT", "3"))

LLM_ENTITY_MERGE_THRESHOLD: float = float(os.getenv("LLM_ENTITY_MERGE_THRESHOLD", "0.7"))
# LLM 제안 검출 신호의 confidence 임계값 — 이 값 미만이면 검출 결과로 채택 안 함.
# (이전 LLM_FLAG_SCORE_THRESHOLD 의 의미를 "점수 산정용 신뢰도" → "검출 채택 임계값" 으로 변경)
# env 호환을 위해 새 변수명·기존 변수명 모두 인식.
LLM_FLAG_DETECTION_CONFIDENCE_THRESHOLD: float = float(
    os.getenv(
        "LLM_FLAG_CONFIDENCE_THRESHOLD",
        os.getenv("LLM_FLAG_SCORE_THRESHOLD", "0.75"),
    )
)
LLM_SCAM_TYPE_OVERRIDE_THRESHOLD: float = float(
    os.getenv("LLM_SCAM_TYPE_OVERRIDE_THRESHOLD", "0.7")
)
