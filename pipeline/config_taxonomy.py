"""
ScamGuardian — 설정: 스캠 유형 taxonomy + 라벨 세트 + SLIMER D&G 정의

DEFAULT_SCAM_TYPES(12종)·라벨 세트·런타임 확장(build/get_runtime_scam_taxonomy)·
Stage 2 multi-label 라우팅 노브·LABEL_DEFINITIONS.
순수 데이터 + 순수 함수만 — 프로젝트 모듈 import 금지 (db 는 함수 내부 lazy).
외부 소비자는 `pipeline.config` facade 를 통해 import 한다.
"""

from __future__ import annotations

from typing import Any

# ──────────────────────────────────────────────
# 스캠 유형 후보 (zero-shot 분류용)
# ──────────────────────────────────────────────
DEFAULT_SCAM_TYPES: list[str] = [
    "투자 사기",
    "건강식품 사기",
    "부동산 사기",
    "코인 사기",
    "기관 사칭",
    "대출 사기",
    "메신저 피싱",
    "로맨스 스캠",
    "취업·알바 사기",
    "납치·협박형",
    "스미싱",
    "중고거래 사기",
]

# NLI 모델용 설명적 레이블 → 짧은 레이블 매핑
# mDeBERTa가 의미를 더 잘 구분하도록 구체적 설명 사용
DEFAULT_SCAM_TYPE_DESCRIPTIONS: dict[str, str] = {
    "높은 수익률을 보장하며 투자금을 요구": "투자 사기",
    "건강식품이나 약으로 질병 치료를 주장하며 판매": "건강식품 사기",
    "부동산 개발 투자 수익을 약속하며 돈을 요구": "부동산 사기",
    "암호화폐 코인 투자로 큰 수익을 약속": "코인 사기",
    "경찰 검찰 금융감독원 등 정부기관을 사칭하여 개인정보나 송금을 요구": "기관 사칭",
    "저금리 대출을 빙자하여 선납금이나 보증금을 요구": "대출 사기",
    "카카오톡이나 SNS에서 지인이나 가족을 사칭하여 급전을 요청": "메신저 피싱",
    "온라인에서 연애 감정을 이용하여 해외 송금이나 투자금을 요구": "로맨스 스캠",
    "재택알바나 채용을 빙자하여 교육비나 선입금을 요구": "취업·알바 사기",
    "가족을 납치했다고 협박하며 즉각적인 송금을 요구": "납치·협박형",
    "문자 링크를 통해 악성앱 설치를 유도하거나 개인정보를 탈취": "스미싱",
    "중고 물품 거래를 빙자하여 물건을 보내지 않거나 가짜 송금 확인증을 사용": "중고거래 사기",
}

# ──────────────────────────────────────────────
# 공통 베이스 레이블 (모든 스캠 유형에 적용)
# ──────────────────────────────────────────────
BASE_LABELS: list[str] = [
    "사람 이름",
    "회사명 또는 기관명",
    "전화번호",
    "이메일 주소",
    "웹사이트 주소",
    "금액",
    "날짜 또는 기간",
    "명제",
]

# ──────────────────────────────────────────────
# 스캠 유형별 특화 레이블 세트 (베이스 + 특화)
# ──────────────────────────────────────────────
DEFAULT_LABEL_SETS: dict[str, list[str]] = {
    "투자 사기": [
        *BASE_LABELS,
        "수익 퍼센트",
        "투자 상품명",
        "보증 기관명",
        "사업자 등록번호",
        "계좌번호",
    ],
    "건강식품 사기": [
        *BASE_LABELS,
        "제품명",
        "치료 효능 주장",
        "대상 질환명",
        "인증 기관명",
        "전문가 직함",
    ],
    "부동산 사기": [
        *BASE_LABELS,
        "지역명 또는 주소",
        "수익 퍼센트",
        "개발 사업명",
        "인허가 기관명",
        "공인중개사 번호",
    ],
    "코인 사기": [
        *BASE_LABELS,
        "코인 또는 토큰명",
        "거래소명",
        "수익 퍼센트",
        "지갑 주소",
        "백서 또는 프로젝트명",
    ],
    "기관 사칭": [
        *BASE_LABELS,
        "사칭 기관명",
        "직함 또는 직책",
        "사건번호 또는 공문번호",
        "계좌번호",
        "개인정보 항목",
    ],
    "대출 사기": [
        *BASE_LABELS,
        "대출 한도",
        "대출 금리",
        "선납금 또는 수수료",
        "선납금 명목",
        "사칭 금융기관명",
        "계좌번호",
    ],
    "메신저 피싱": [
        *BASE_LABELS,
        "사칭 지인 이름",
        "송금 목적",
        "SNS 또는 메신저 플랫폼",
        "계좌번호",
        "카카오톡 ID",
    ],
    "로맨스 스캠": [
        *BASE_LABELS,
        "사칭 신분 또는 직업",
        "사칭 국적",
        "연락 플랫폼",
        "송금 목적",
        "계좌번호",
    ],
    "취업·알바 사기": [
        *BASE_LABELS,
        "일당 또는 급여",
        "직종명",
        "선납금 명목",
        "선납금 또는 수수료",
        "사칭 회사명",
        "계좌번호",
    ],
    "납치·협박형": [
        *BASE_LABELS,
        "협박 대상 관계",
        "요구 금액",
        "송금 기한",
        "계좌번호",
        "협박 수단",
    ],
    "스미싱": [
        *BASE_LABELS,
        "악성 URL",
        "사칭 기관명",
        "발신 번호",
        "개인정보 항목",
        "사칭 서비스명",
    ],
    "중고거래 사기": [
        *BASE_LABELS,
        "거래 플랫폼명",
        "거래 상품명",
        "허위 운송장 번호",
        "계좌번호",
        "에스크로 회피 수단",
    ],
}


def _normalize_custom_labels(labels: list[str] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for label in labels or []:
        text = str(label).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _custom_description_for_type(scam_type: str) -> str:
    return f"{scam_type}와 관련된 기만, 사칭, 금전 요구를 포함한 사기 수법"


def build_scam_taxonomy(
    custom_types: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scam_types = list(DEFAULT_SCAM_TYPES)
    descriptions = dict(DEFAULT_SCAM_TYPE_DESCRIPTIONS)
    label_sets = {name: list(labels) for name, labels in DEFAULT_LABEL_SETS.items()}

    for item in custom_types or []:
        scam_type = str(item.get("name", "")).strip()
        if not scam_type or scam_type in scam_types:
            continue

        description = str(item.get("description", "")).strip() or _custom_description_for_type(
            scam_type
        )
        labels = _normalize_custom_labels(item.get("labels"))

        scam_types.append(scam_type)
        descriptions[description] = scam_type
        label_sets[scam_type] = labels or list(BASE_LABELS)

    return {
        "scam_types": scam_types,
        "descriptions": descriptions,
        "label_sets": label_sets,
    }


def get_runtime_scam_taxonomy() -> dict[str, Any]:
    custom_types: list[dict[str, Any]] = []
    try:
        from db import repository

        if repository.database_configured():
            custom_types = repository.list_custom_scam_types()
    except Exception:
        custom_types = []

    return build_scam_taxonomy(custom_types)


SCAM_TYPES: list[str] = list(DEFAULT_SCAM_TYPES)
SCAM_TYPE_DESCRIPTIONS: dict[str, str] = dict(DEFAULT_SCAM_TYPE_DESCRIPTIONS)
LABEL_SETS: dict[str, list[str]] = {
    name: list(labels) for name, labels in DEFAULT_LABEL_SETS.items()
}

# ──────────────────────────────────────────────
# Stage 2 — multi-label 추출 라우팅
#
# scam_type 단일 강제 분류는 복합 스캠("코인+로맨스")의 한쪽 엔티티를 통째로
# 놓친다. all_scores 의 상위 N개 후보 유형 LABEL_SET 을 합집합으로 추출 대상에
# 넣는다. scam_type 필드 자체는 바뀌지 않음 — top-1 문자열 유지. 후보(candidate)
# 는 *엔티티 추출 라우팅* 에만 쓰이고 외부 응답에는 노출하지 않는다.
# ──────────────────────────────────────────────
STAGE2_CANDIDATE_TOP_N: int = 3
# top1 - top2 점수 차가 이 이상이면 top-1 이 충분히 우세 → top-1 단독 라우팅
STAGE2_DOMINANCE_GAP: float = 0.30

# 공통 위험 엔티티 라벨 — scam_type 과 무관하게 *항상* 추출 대상에 포함.
# 개인정보 요구·계좌 이체·악성 URL 은 모든 사기 유형에 공통인 위험 신호다.
COMMON_RISK_LABELS: list[str] = ["개인정보 항목", "계좌번호", "악성 URL"]

# ──────────────────────────────────────────────
# SLIMER D&G: 레이블별 정의(Definition) + 가이드라인(Guideline)
# GLiNER 레이블 자체에는 넣지 않고, 검증·스코어링에서 판단 기준으로 활용
# ──────────────────────────────────────────────
LABEL_DEFINITIONS: dict[str, dict[str, str]] = {
    # --- 공통 베이스 ---
    "사람 이름": {
        "definition": "실명으로 언급된 특정 개인",
        "guideline": "화자 본인, 대표자, 보증인 포함. 직함만 있고 이름 없으면 제외",
    },
    "회사명 또는 기관명": {
        "definition": "영상에서 언급된 회사, 단체, 기관 이름",
        "guideline": "실제 존재 여부와 무관하게 추출. 'OO그룹', 'OO투자' 등 포함",
    },
    "전화번호": {
        "definition": "연락처로 제시된 전화번호",
        "guideline": "국제번호 포함. 수신거부나 신고 여부 검색에 활용",
    },
    "이메일 주소": {
        "definition": "연락처로 제시된 이메일",
        "guideline": "도메인 포함 추출",
    },
    "웹사이트 주소": {
        "definition": "언급된 URL 또는 도메인",
        "guideline": "http 없이 도메인만 언급해도 추출",
    },
    "금액": {
        "definition": "투자금, 가격, 수수료 등 화폐 단위 금액",
        "guideline": "숫자+단위 함께 추출. '소액', '저렴' 등 모호한 표현 제외",
    },
    "날짜 또는 기간": {
        "definition": "언급된 날짜, 마감일, 기간",
        "guideline": "긴박감 조성용 기한 포함",
    },
    "명제": {
        "definition": "사실 여부를 판단할 수 있는 단언·주장 (예: 'X는 Y다', 'A가 B를 보장한다')",
        "guideline": "기관·인물·금액·날짜 등 다른 라벨로 커버되지 않는 절 단위 주장. 화자가 사실로 단언하는 진술. 의문문·감탄문 제외. 검증 가능한 claim 위주.",
    },
    # --- 투자 사기 특화 ---
    "수익 퍼센트": {
        "definition": "수익률로 표현된 퍼센트 수치",
        "guideline": "'연 30%', '월 10%' 등. 단위 포함 추출",
    },
    "투자 상품명": {
        "definition": "펀드, 주식, 채권 등 투자 상품 이름",
        "guideline": "정식 상품명이 아닌 자칭 상품명도 포함",
    },
    "보증 기관명": {
        "definition": "수익이나 원금을 보증한다고 주장하는 기관",
        "guideline": "가짜 규제기관 사칭 여부 검증 대상",
    },
    "사업자 등록번호": {
        "definition": "사업자등록번호 또는 법인등록번호",
        "guideline": "숫자 패턴(XXX-XX-XXXXX) 추출",
    },
    "계좌번호": {
        "definition": "송금 대상 은행 계좌번호",
        "guideline": "은행명 포함 시 함께 추출",
    },
    # --- 건강식품 사기 특화 ---
    "제품명": {
        "definition": "건강식품, 의약품, 보조제 이름",
        "guideline": "브랜드명, 성분명 모두 포함",
    },
    "치료 효능 주장": {
        "definition": "특정 질병의 치료·완치를 주장하는 표현",
        "guideline": "'암 완치', '당뇨 치료' 등 의학적 효능 주장",
    },
    "대상 질환명": {
        "definition": "치료 대상으로 언급된 질병명",
        "guideline": "정식 질병명 및 구어체 표현 모두 추출",
    },
    "인증 기관명": {
        "definition": "제품 인증·승인을 받았다고 주장하는 기관",
        "guideline": "식약처, FDA 등 가짜 인증 사칭 포함",
    },
    "전문가 직함": {
        "definition": "권위를 부여하기 위해 사용된 직함",
        "guideline": "'박사', '교수', '한의사' 등. 이름과 함께 추출",
    },
    # --- 부동산 사기 특화 ---
    "지역명 또는 주소": {
        "definition": "투자 대상 부동산의 위치",
        "guideline": "시/군/구, 도로명, 단지명 등",
    },
    "개발 사업명": {
        "definition": "재개발, 신도시, 택지개발 등 사업 이름",
        "guideline": "정부 사업 사칭 여부 검증 대상",
    },
    "인허가 기관명": {
        "definition": "건축·개발 인허가를 내줬다고 주장하는 기관",
        "guideline": "국토부, 시청, 구청 등",
    },
    "공인중개사 번호": {
        "definition": "공인중개사 등록번호",
        "guideline": "자격 확인용",
    },
    # --- 코인 사기 특화 ---
    "코인 또는 토큰명": {
        "definition": "가상자산(암호화폐) 이름",
        "guideline": "비트코인 등 기존 코인 및 신규 토큰 모두 포함",
    },
    "거래소명": {
        "definition": "가상자산 거래소 이름",
        "guideline": "업비트, 바이낸스 등 사칭 여부 확인",
    },
    "지갑 주소": {
        "definition": "암호화폐 지갑 주소",
        "guideline": "긴 영숫자 문자열 패턴",
    },
    "백서 또는 프로젝트명": {
        "definition": "가상자산 프로젝트 또는 백서 이름",
        "guideline": "가짜 프로젝트 여부 확인 대상",
    },
    # --- 기관 사칭 특화 ---
    "사칭 기관명": {
        "definition": "사칭되고 있는 정부 기관·금융 기관 이름",
        "guideline": "금감원, 검찰, 경찰, 은행 등",
    },
    "직함 또는 직책": {
        "definition": "권위를 사칭하기 위한 직함",
        "guideline": "'수사관', '팀장', '검사' 등",
    },
    "사건번호 또는 공문번호": {
        "definition": "가짜 공식 문서의 번호",
        "guideline": "사건번호, 공문번호, 접수번호 등",
    },
    "개인정보 항목": {
        "definition": "요구하는 개인정보의 종류",
        "guideline": "주민번호, 비밀번호, OTP 등",
    },
    # --- 대출 사기 특화 ---
    "대출 한도": {
        "definition": "제시된 대출 가능 금액",
        "guideline": "'최대 1억', '5천만 원' 등 구체적 금액",
    },
    "대출 금리": {
        "definition": "제시된 대출 금리",
        "guideline": "'연 2.9%', '저금리' 등",
    },
    "선납금 또는 수수료": {
        "definition": "대출·취업·거래 전 먼저 요구하는 금액",
        "guideline": "보증금, 수수료, 공증비, 교육비, 등록금 등 명목 불문",
    },
    "선납금 명목": {
        "definition": "선납금을 요구하는 이유나 명목",
        "guideline": "'보험료', '공증비', '교육비', '기자재비' 등",
    },
    "사칭 금융기관명": {
        "definition": "대출 권유 시 사칭하는 금융기관 이름",
        "guideline": "서민금융진흥원, 국민은행 등 실존 기관 사칭",
    },
    # --- 메신저 피싱 특화 ---
    "사칭 지인 이름": {
        "definition": "사칭하는 지인·가족의 이름 또는 관계",
        "guideline": "'엄마', '친구 민수' 등",
    },
    "송금 목적": {
        "definition": "돈을 요청하는 이유",
        "guideline": "'핸드폰 고장', '급하게 필요', '잠깐 빌려줘' 등",
    },
    "SNS 또는 메신저 플랫폼": {
        "definition": "사기에 사용된 메신저/SNS 플랫폼",
        "guideline": "카카오톡, 인스타그램, 페이스북, 라인 등",
    },
    "카카오톡 ID": {
        "definition": "사기에 사용된 카카오톡 또는 SNS 계정 ID",
        "guideline": "아이디 문자열 그대로 추출",
    },
    # --- 로맨스 스캠 특화 ---
    "사칭 신분 또는 직업": {
        "definition": "신뢰를 얻기 위해 사칭하는 신분·직업",
        "guideline": "'UN 소속 의사', '미군 장교', '해외 파견 엔지니어' 등",
    },
    "사칭 국적": {
        "definition": "사칭하는 국적 또는 출신지",
        "guideline": "'미국', '캐나다', '독일' 등",
    },
    "연락 플랫폼": {
        "definition": "로맨스 스캠이 시작된 플랫폼",
        "guideline": "틱톡, 인스타그램, 데이팅앱 등",
    },
    # --- 취업·알바 사기 특화 ---
    "일당 또는 급여": {
        "definition": "제시된 일당, 시급, 월급",
        "guideline": "'일당 15만 원', '시급 5만 원' 등",
    },
    "직종명": {
        "definition": "제시된 업무 종류",
        "guideline": "'재택 데이터 입력', '스마트폰 리뷰' 등",
    },
    "사칭 회사명": {
        "definition": "채용 광고에서 사칭하는 회사 이름",
        "guideline": "대기업·유명 기업 사칭 포함",
    },
    # --- 납치·협박형 특화 ---
    "협박 대상 관계": {
        "definition": "납치·협박 대상으로 언급된 가족 관계",
        "guideline": "'자녀', '배우자', '부모' 등",
    },
    "송금 기한": {
        "definition": "협박에서 요구하는 송금 마감 시간",
        "guideline": "'30분 안에', '지금 당장' 등",
    },
    "협박 수단": {
        "definition": "협박에 사용되는 위협 내용",
        "guideline": "'경찰 부르면 죽인다', '신체 해를 가한다' 등",
    },
    # --- 스미싱 특화 ---
    "악성 URL": {
        "definition": "문자에 포함된 의심 링크",
        "guideline": "단축 URL, 이상한 도메인 등",
    },
    "발신 번호": {
        "definition": "스미싱 문자 발신 번호",
        "guideline": "070, 국제번호, 변작된 번호 포함",
    },
    "사칭 서비스명": {
        "definition": "스미싱에서 사칭하는 서비스·기업명",
        "guideline": "'CJ대한통운', '쿠팡', '국민은행' 등",
    },
    # --- 중고거래 사기 특화 ---
    "거래 플랫폼명": {
        "definition": "사기가 발생한 중고거래 플랫폼",
        "guideline": "중고나라, 당근마켓, 번개장터 등",
    },
    "거래 상품명": {
        "definition": "사기 거래 대상 물품",
        "guideline": "아이폰, 게임기, 티켓 등",
    },
    "허위 운송장 번호": {
        "definition": "발송했다고 속이는 가짜 운송장 번호",
        "guideline": "CJ대한통운, 한진 등 운송사 추적번호 형식",
    },
    "에스크로 회피 수단": {
        "definition": "안전결제를 우회하도록 유도하는 방법",
        "guideline": "'직거래로 해요', '수수료 아끼려고' 등",
    },
}
