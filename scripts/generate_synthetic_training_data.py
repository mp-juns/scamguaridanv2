"""Generate synthetic ScamGuardian training JSONL.

The generated rows follow the schema documented in docs/labeling_guide.md:
text, content_label, scam_type, sample_kind, source_ref, entities, risk_flags.
They also include RAG-oriented structure: scenario_id, scenario_ko, slots,
relations, rag_texts, and flag_groups.

Design choice:
- Text contains natural fictional values, not literal placeholders such as
  "[사람이름]". Entity labels are stored separately in entities[].
- source_ref is template-family scoped so group-aware splits can keep variants
  from the same template in a single fold.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pipeline.flag_groups import group_of


SCAM_TYPES = [
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


RISK_FLAGS: dict[str, list[str]] = {
    "투자 사기": [
        "abnormal_return_rate",
        "urgent_transfer_demand",
        "fss_not_registered",
        "authority_context_mismatch",
    ],
    "건강식품 사기": [
        "medical_claim_unverified",
        "fake_certification",
        "urgent_transfer_demand",
    ],
    "부동산 사기": [
        "business_not_registered",
        "prepayment_requested",
        "abnormal_return_rate",
        "fake_certification",
    ],
    "코인 사기": [
        "fake_exchange",
        "abnormal_return_rate",
        "website_scam_reported",
        "prepayment_requested",
    ],
    "기관 사칭": [
        "fake_government_agency",
        "personal_info_request",
        "urgent_transfer_demand",
        "threat_or_coercion",
    ],
    "대출 사기": [
        "prepayment_requested",
        "personal_info_request",
        "urgent_transfer_demand",
    ],
    "메신저 피싱": [
        "impersonation_family",
        "urgent_transfer_demand",
        "personal_info_request",
    ],
    "로맨스 스캠": [
        "romance_foreign_identity",
        "prepayment_requested",
        "urgent_transfer_demand",
    ],
    "취업·알바 사기": [
        "job_deposit_requested",
        "prepayment_requested",
        "personal_info_request",
    ],
    "납치·협박형": [
        "threat_or_coercion",
        "urgent_transfer_demand",
    ],
    "스미싱": [
        "smishing_link_detected",
        "personal_info_request",
        "suspicious_url_signal",
    ],
    "중고거래 사기": [
        "fake_escrow_bypass",
        "prepayment_requested",
        "account_scam_reported",
        "urgent_transfer_demand",
    ],
}


SCENARIO_KO: dict[str, str] = {
    "투자 사기": "고수익·원금보장·유명인/기업 권위를 이용해 투자를 유도",
    "건강식품 사기": "검증되지 않은 치료 효능과 가짜 인증으로 구매를 압박",
    "부동산 사기": "개발 호재·인허가·선점 기회를 내세워 예약금/투자금을 요구",
    "코인 사기": "상장·에어드랍·출금 복구·내부 정보를 내세워 코인 투자를 유도",
    "기관 사칭": "수사기관·금융기관을 사칭해 개인정보·안전계좌 이체를 요구",
    "대출 사기": "저금리·고한도 대출을 미끼로 선납금과 개인정보를 요구",
    "메신저 피싱": "가족·지인·상사를 사칭해 긴급 송금이나 인증정보를 요구",
    "로맨스 스캠": "감정적 신뢰를 쌓은 뒤 해외 신분·위기 상황을 빌미로 송금을 요구",
    "취업·알바 사기": "채용·재택알바를 미끼로 보증금·교육비·개인정보를 요구",
    "납치·협박형": "가족 위해·사진 유포·채무 위협으로 즉각 송금을 압박",
    "스미싱": "택배·환급·결제·보안 업데이트를 사칭한 링크 클릭과 정보 입력 유도",
    "중고거래 사기": "안전결제 회피·예약금·가짜 운송장으로 선입금을 요구",
}


SLOTS: dict[str, list[str]] = {
    "person": [
        "김도윤", "박서준", "이하린", "최민재", "정유나", "한지후", "오세린", "문태오",
        "강지민", "서하늘", "윤재원", "임수아", "배준호", "노유진", "차민석", "송가은",
    ],
    "celebrity": [
        "장민혁", "서이준", "도현우", "윤태민", "한서진", "오지안", "류하준", "백도겸",
    ],
    "company": [
        "한빛전자", "세림테크", "도담바이오", "누리금융", "태경건설", "바른에셋",
        "미래솔루션", "라온모빌리티", "하나로마켓", "지오헬스", "은하투자", "솔라젠",
    ],
    "agency": [
        "서울중앙지검", "금융감독원", "경찰청 사이버수사대", "국세청 조사국",
        "서울남부지검", "금융범죄합동수사단", "검찰청 민원센터", "소비자보호원",
    ],
    "bank": [
        "한빛은행", "누리저축은행", "새봄캐피탈", "도담금융", "라온뱅크",
        "미래상호저축", "세림캐피탈", "국민희망론센터",
    ],
    "product": [
        "셀케어 골드", "홍삼파워 엑스", "관절닥터 플러스", "혈당제로 캡슐",
        "청명환 프리미엄", "리버케어 365", "면역업 부스터", "비전큐 아이케어",
    ],
    "disease": [
        "당뇨", "고혈압", "관절염", "백내장", "간 기능 저하", "위염", "불면증", "전립선 질환",
    ],
    "region": [
        "평택 고덕", "세종 금남면", "부산 명지", "인천 검단", "용인 남사",
        "김포 장기", "대전 유성", "광주 첨단지구",
    ],
    "development": [
        "첨단물류단지", "복합환승센터", "신도시 배후지", "역세권 개발지",
        "산업단지 예정지", "관광특구 개발", "반도체 클러스터", "항만 배후단지",
    ],
    "coin": [
        "K-루멘", "메타링크", "블루체인", "페이노바", "오로라토큰", "에코월드코인",
        "드림체인", "스마트비트",
    ],
    "exchange": [
        "코리아비트", "글로벌코인랩", "넥스트월렛", "비트세이프", "메타거래소",
    ],
    "platform": [
        "카카오톡", "인스타그램", "라인", "페이스북", "텔레그램", "데이팅앱", "틱톡",
    ],
    "job": [
        "재택 데이터 입력", "쇼핑몰 리뷰 작성", "상품 검수 알바", "채팅 상담",
        "영상 자막 검수", "간단 송장 정리", "앱 테스트", "구매대행 보조",
    ],
    "market": [
        "당근마켓", "중고나라", "번개장터", "헬로마켓", "네이버 카페", "지역맘카페",
    ],
    "item": [
        "아이폰 16", "플레이스테이션 5", "콘서트 티켓", "노트북", "캠핑 텐트",
        "그래픽카드", "한정판 운동화", "태블릿",
    ],
    "courier": [
        "CJ대한통운", "한진택배", "롯데택배", "우체국택배", "로젠택배", "쿠팡로지스틱스",
    ],
    "service": [
        "국민건강보험", "정부24", "카카오페이", "쿠팡", "네이버페이", "우체국",
        "교통민원24", "국세청 홈택스",
    ],
    "country": [
        "미국", "캐나다", "영국", "호주", "독일", "프랑스", "뉴질랜드", "싱가포르",
    ],
    "identity": [
        "UN 파견 의사", "해외 건설 엔지니어", "미군 장교", "국제 구호단체 직원",
        "선박 기관사", "항공 정비사", "원유 시추 기술자", "외교관 보좌관",
    ],
    "relation": ["아들", "딸", "남편", "아내", "동생", "엄마", "아버지", "조카"],
    "deadline": ["30분 안에", "오늘 오후 3시까지", "지금 바로", "1시간 안에", "은행 마감 전"],
    "purpose": [
        "휴대폰 액정 수리비", "병원 보증금", "사고 합의금", "인증 오류 해결비",
        "항공권 변경 수수료", "통관 보증금", "숙소 연장비", "긴급 치료비",
    ],
    "fee_reason": [
        "보증보험료", "공증비", "계좌 활성화 비용", "교육비", "기자재 보증금",
        "통관 수수료", "안전결제 인증비", "전산 처리비",
    ],
    "personal_info": [
        "주민등록번호", "계좌 비밀번호", "OTP 번호", "신분증 사진",
        "보안카드 번호", "공동인증서 비밀번호", "카드 CVC", "휴대폰 인증번호",
    ],
}


def _money(rng: random.Random) -> str:
    values = [30, 50, 80, 120, 150, 200, 300, 500, 700, 1000, 1500, 3000, 5000]
    unit = rng.choice(["만원", "만 원"])
    return f"{rng.choice(values)}{unit}"


def _large_money(rng: random.Random) -> str:
    values = ["3000만원", "5000만원", "8000만원", "1억 원", "1억 5000만원", "2억 원"]
    return rng.choice(values)


def _percent(rng: random.Random) -> str:
    prefix = rng.choice(["월", "연", "매월", "3개월"])
    value = rng.choice([18, 20, 25, 30, 35, 40, 50, 70, 100])
    return f"{prefix} {value}%"


def _phone(rng: random.Random) -> str:
    return f"010-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"


def _account(rng: random.Random) -> str:
    bank = rng.choice(["한빛은행", "누리은행", "도담은행", "라온뱅크"])
    return f"{bank} {rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(100000, 999999)}"


def _url(rng: random.Random) -> str:
    host = rng.choice(["safe-check", "parcel-kr", "gov24-help", "pay-auth", "quick-verify"])
    tld = rng.choice(["site", "click", "shop", "info", "top"])
    path = rng.choice(["login", "auth", "update", "delivery", "install"])
    return f"https://{host}{rng.randint(10, 99)}.{tld}/{path}"


def _case_no(rng: random.Random) -> str:
    return f"제{rng.randint(2024, 2026)}-{rng.randint(10000, 99999)}호"


def _biz_no(rng: random.Random) -> str:
    return f"{rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(10000, 99999)}"


def _wallet(rng: random.Random) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "0x" + "".join(rng.choice(alphabet) for _ in range(34))


GENERATORS = {
    "money": _money,
    "large_money": _large_money,
    "percent": _percent,
    "phone": _phone,
    "account": _account,
    "url": _url,
    "case_no": _case_no,
    "biz_no": _biz_no,
    "wallet": _wallet,
}


Template = dict[str, Any]


TEMPLATES: dict[str, list[Template]] = {
    "투자 사기": [
        {
            "id": "investment_celebrity_support",
            "text": "{company:회사명 또는 기관명}의 {person:사람 이름} 대표가 비공개로 진행하는 긴급 투자 지원입니다. {money:금액}만 넣으면 {percent:수익 퍼센트} 수익을 보장하고, 오늘 신청자는 {phone:전화번호}로 바로 배정됩니다.",
        },
        {
            "id": "investment_principal_guarantee",
            "text": "{company:회사명 또는 기관명} 프리IPO 물량이 남았습니다. 원금은 {agency:보증 기관명}이 보장하고 {large_money:금액} 한도까지 참여 가능하며, 마감 전에 {account:계좌번호}로 예약금 입금해주세요.",
        },
        {
            "id": "investment_vip_room",
            "text": "{celebrity:사람 이름} 애널리스트 VIP방입니다. {company:회사명 또는 기관명} 내부 정보로 {percent:수익 퍼센트} 목표가 확정됐고, 선착순 회원은 {money:금액}부터 입장 가능합니다.",
        },
        {
            "id": "investment_registration",
            "text": "사업자번호 {biz_no:사업자 등록번호}로 등록된 {company:회사명 또는 기관명} 투자조합입니다. 오늘 {money:금액} 입금하면 다음 주부터 배당이 지급되고 중도 해지도 보장됩니다.",
        },
        {
            "id": "investment_recovery",
            "text": "기존 투자 손실을 복구해드리는 {company:회사명 또는 기관명} 특별팀입니다. {person:사람 이름} 팀장이 직접 관리하며 {money:금액} 추가 납입 시 {percent:수익 퍼센트} 회복을 약속합니다.",
        },
    ],
    "건강식품 사기": [
        {
            "id": "health_cure_claim",
            "text": "{product:제품명}은 {disease:대상 질환명}을 2주 안에 개선하는 특허 제품입니다. {agency:인증 기관명} 인증을 받았고 오늘 결제하면 {money:금액} 할인됩니다.",
        },
        {
            "id": "health_doctor_authority",
            "text": "{person:사람 이름} 박사가 개발한 {product:제품명}은 병원 치료 없이 {disease:대상 질환명} 완화가 가능합니다. 상담 후 바로 주문하면 추가 사은품을 드립니다.",
        },
        {
            "id": "health_limited_stock",
            "text": "방송 이후 {product:제품명} 물량이 거의 소진됐습니다. {disease:대상 질환명} 때문에 고생하신다면 오늘 {money:금액} 선입금으로 마지막 물량을 확보하세요.",
        },
        {
            "id": "health_fake_cert",
            "text": "{agency:인증 기관명} 임상 승인을 받은 {product:제품명}입니다. 약을 끊고도 {disease:대상 질환명} 관리가 가능하니 신분증 사진과 배송비 {money:금액}을 보내주세요.",
        },
        {
            "id": "health_family_target",
            "text": "부모님 {disease:대상 질환명} 때문에 걱정이시면 {product:제품명} 체험분을 먼저 보내드립니다. 단, 보증금 {money:금액}은 {account:계좌번호}로 입금해야 합니다.",
        },
    ],
    "부동산 사기": [
        {
            "id": "realestate_development",
            "text": "{region:지역명 또는 주소} {development:개발 사업명} 토지 지분을 선착순 분양합니다. {agency:인허가 기관명} 인허가가 끝나 {percent:수익 퍼센트} 시세차익이 예상됩니다.",
        },
        {
            "id": "realestate_down_payment",
            "text": "{region:지역명 또는 주소} 역세권 물건이 급매로 나왔습니다. 계약금 {money:금액}만 먼저 보내면 등기 전까지 단독 배정하고 공인중개사 번호는 {biz_no:공인중개사 번호}입니다.",
        },
        {
            "id": "realestate_gov_backed",
            "text": "{agency:인허가 기관명} 협력 {development:개발 사업명}입니다. 일반 공개 전이라 {large_money:금액} 이상 넣으면 조합원 가격으로 전환됩니다.",
        },
        {
            "id": "realestate_fake_permit",
            "text": "{company:회사명 또는 기관명} 시행사가 {region:지역명 또는 주소} 개발 허가를 받았습니다. 오늘 {money:금액} 예약금을 넣으면 잔여 필지를 잡아드립니다.",
        },
        {
            "id": "realestate_resale",
            "text": "{region:지역명 또는 주소} 분양권이 곧 전매 제한 해제됩니다. {person:사람 이름} 실장이 관리하는 물건이라 {percent:수익 퍼센트} 차익이 가능하고, 안전계좌로 {money:금액} 보내주세요.",
        },
    ],
    "코인 사기": [
        {
            "id": "coin_listing",
            "text": "{coin:코인 또는 토큰명}이 {exchange:거래소명} 상장을 앞두고 있습니다. 지금 {money:금액} 매수하면 상장 당일 {percent:수익 퍼센트} 수익이 예상됩니다.",
        },
        {
            "id": "coin_fake_exchange",
            "text": "{exchange:거래소명} VIP 계정 개설 안내입니다. {coin:코인 또는 토큰명} 에어드랍을 받으려면 지갑 {wallet:지갑 주소}을 등록하고 인증비 {money:금액}을 입금하세요.",
        },
        {
            "id": "coin_recovery",
            "text": "동결된 코인 출금을 복구해드리는 {company:회사명 또는 기관명}입니다. {fee_reason:선납금 명목} {money:선납금 또는 수수료}만 처리하면 {coin:코인 또는 토큰명} 전량 출금됩니다.",
        },
        {
            "id": "coin_project_whitepaper",
            "text": "{coin:코인 또는 토큰명} 백서 사전 참여자 모집입니다. {company:백서 또는 프로젝트명} 프로젝트라 원금 보장과 {percent:수익 퍼센트} 보상이 확정됐습니다.",
        },
        {
            "id": "coin_romance_pigbutchering",
            "text": "제가 {exchange:거래소명} 내부 지인을 통해 {coin:코인 또는 토큰명} 정보를 받았어요. 우리 같이 {money:금액}만 넣으면 이번 달에 {percent:수익 퍼센트} 만들 수 있어요.",
        },
    ],
    "기관 사칭": [
        {
            "id": "agency_prosecutor_case",
            "text": "{agency:사칭 기관명} {person:사람 이름} 수사관입니다. 사건번호 {case_no:사건번호 또는 공문번호}에 본인 명의 계좌가 연루되어 {deadline:송금 기한} {account:계좌번호}로 검증 이체가 필요합니다.",
        },
        {
            "id": "agency_fss_safe_account",
            "text": "{agency:사칭 기관명}입니다. 피해 방지를 위해 보유 금액 {large_money:금액}을 안전계좌로 옮겨야 합니다. 거부하면 계좌가 지급정지될 수 있습니다.",
        },
        {
            "id": "agency_personal_info",
            "text": "{agency:사칭 기관명} 민원팀입니다. 본인 확인을 위해 본인정보({personal_info:개인정보 항목})와 통장 사본을 보내주세요. 확인 지연 시 수사가 불리하게 진행됩니다.",
        },
        {
            "id": "agency_warrant_threat",
            "text": "{agency:사칭 기관명}에서 공문번호 {case_no:사건번호 또는 공문번호}로 연락드립니다. {deadline:송금 기한} 출석하지 않으면 체포영장이 발부되니 보증금 {money:금액}을 납부하세요.",
        },
        {
            "id": "agency_app_install",
            "text": "{agency:사칭 기관명} 보안 앱 설치 안내입니다. 아래 링크 {url:웹사이트 주소}에서 앱을 설치하고 {personal_info:개인정보 항목} 인증을 완료해야 사건 조회가 가능합니다.",
        },
    ],
    "대출 사기": [
        {
            "id": "loan_pre_fee",
            "text": "{bank:사칭 금융기관명} 대출 상담사 {person:사람 이름}입니다. 최대 {large_money:대출 한도} 승인 가능하지만 {fee_reason:선납금 명목} {money:선납금 또는 수수료}을 먼저 입금해야 실행됩니다.",
        },
        {
            "id": "loan_low_rate",
            "text": "정부지원 저금리 전환대출 대상자로 확인됐습니다. {bank:사칭 금융기관명}에서 {percent:대출 금리} 금리로 가능하며, 보증보험료 {money:선납금 또는 수수료}을 오늘 처리해주세요.",
        },
        {
            "id": "loan_credit_fix",
            "text": "신용점수 보정 후 {large_money:대출 한도}까지 가능합니다. 전산 처리비 {money:선납금 또는 수수료}와 본인정보({personal_info:개인정보 항목})를 보내주시면 바로 승인됩니다.",
        },
        {
            "id": "loan_duplicate_repayment",
            "text": "{bank:사칭 금융기관명}입니다. 기존 대출 일부를 상환해야 신규 한도 {large_money:대출 한도}가 열립니다. {deadline:송금 기한} {account:계좌번호}로 상환금을 보내세요.",
        },
        {
            "id": "loan_mobile_auth",
            "text": "모바일 대출 심사 중 오류가 발생했습니다. {personal_info:개인정보 항목} 인증과 {fee_reason:선납금 명목} {money:선납금 또는 수수료} 납부가 필요합니다.",
        },
    ],
    "메신저 피싱": [
        {
            "id": "messenger_child_phone",
            "text": "{relation:사칭 지인 이름}인데 휴대폰이 고장나서 {platform:SNS 또는 메신저 플랫폼}으로만 연락해. {purpose:송금 목적} 때문에 {money:금액}만 {account:계좌번호}로 보내줘.",
        },
        {
            "id": "messenger_giftcard",
            "text": "엄마 나 급해. 인증이 안 돼서 상품권을 대신 사야 해. {deadline:송금 기한} {money:금액} 보내주고 {personal_info:개인정보 항목}도 알려줘.",
        },
        {
            "id": "messenger_friend_accident",
            "text": "{person:사칭 지인 이름} 친구야. 교통사고 합의 때문에 지금 통화가 안 돼. {platform:SNS 또는 메신저 플랫폼} 아이디 {person:카카오톡 ID}로 확인하고 {money:금액} 부탁해.",
        },
        {
            "id": "messenger_boss_request",
            "text": "대표님 지시입니다. 거래처 결제가 막혀서 {deadline:송금 기한} {large_money:금액}을 먼저 이체해야 합니다. 입금 후 영수증만 보내주세요.",
        },
        {
            "id": "messenger_verification",
            "text": "나 {relation:사칭 지인 이름}인데 폰 초기화돼서 본인 인증이 필요해. {personal_info:개인정보 항목}만 보내주면 바로 전화할게.",
        },
    ],
    "로맨스 스캠": [
        {
            "id": "romance_foreign_doctor",
            "text": "저는 {country:사칭 국적} 출신 {identity:사칭 신분 또는 직업}입니다. 당신을 진심으로 믿어요. 한국에 가려면 {purpose:송금 목적} 때문에 {money:금액}이 필요합니다.",
        },
        {
            "id": "romance_customs_fee",
            "text": "당신에게 선물을 보냈는데 세관에서 멈췄어요. {fee_reason:송금 목적} {money:금액}만 내면 바로 배송됩니다. 제 마음을 믿어주세요.",
        },
        {
            "id": "romance_investment",
            "text": "{platform:연락 플랫폼}에서 만난 당신에게만 말해요. 제가 쓰는 {exchange:거래소명} 계정으로 {money:금액} 넣으면 둘의 미래 자금이 {percent:수익 퍼센트} 늘어납니다.",
        },
        {
            "id": "romance_emergency",
            "text": "현장에서 여권을 잃어버렸고 병원비가 필요합니다. 저는 {country:사칭 국적} {identity:사칭 신분 또는 직업}이고, 당신 말고 부탁할 사람이 없어요. {money:금액}만 도와주세요.",
        },
        {
            "id": "romance_release_document",
            "text": "파견 종료 서류 비용이 막혀 한국행이 늦어지고 있어요. {fee_reason:송금 목적} {money:금액}을 보내주면 이번 주에 당신을 만나러 갈 수 있습니다.",
        },
    ],
    "취업·알바 사기": [
        {
            "id": "job_deposit",
            "text": "{company:사칭 회사명} 채용팀입니다. {job:직종명} 업무로 일당 {money:일당 또는 급여} 지급되며, 시작 전 {fee_reason:선납금 명목} {money:선납금 또는 수수료} 입금이 필요합니다.",
        },
        {
            "id": "job_equipment",
            "text": "재택근무 장비를 보내드리려면 기자재 보증금 {money:선납금 또는 수수료}이 필요합니다. {company:사칭 회사명} 계약서 작성용으로 {personal_info:개인정보 항목}도 보내주세요.",
        },
        {
            "id": "job_review_purchase",
            "text": "{job:직종명} 알바입니다. 상품 구매 후 리뷰를 쓰면 원금과 수당 {money:일당 또는 급여}을 돌려드립니다. 첫 미션 결제금 {money:선납금 또는 수수료}을 준비해주세요.",
        },
        {
            "id": "job_training_fee",
            "text": "{company:사칭 회사명} 단기 채용 합격 안내입니다. 교육비 {money:선납금 또는 수수료} 납부 후 바로 근무 가능하며 월급은 {large_money:일당 또는 급여}까지 가능합니다.",
        },
        {
            "id": "job_account_lending",
            "text": "정산 업무 보조라 본인 계좌로 입출금 테스트가 필요합니다. 본인정보({personal_info:개인정보 항목})와 계좌번호를 보내면 {job:직종명} 일당 {money:일당 또는 급여} 지급됩니다.",
        },
    ],
    "납치·협박형": [
        {
            "id": "threat_family_kidnap",
            "text": "당신 {relation:협박 대상 관계}를 데리고 있다. 경찰에 신고하면 다친다. {deadline:송금 기한} {large_money:요구 금액}을 {account:계좌번호}로 보내라.",
        },
        {
            "id": "threat_voice_imitation",
            "text": "{relation:협박 대상 관계}가 사고를 냈고 상대가 크게 다쳤다. 합의금 {large_money:요구 금액}을 {deadline:송금 기한} 보내지 않으면 가족에게 알리겠다.",
        },
        {
            "id": "threat_photo_leak",
            "text": "당신 개인정보와 사진을 가지고 있다. 유포를 막으려면 {deadline:송금 기한} {money:요구 금액}을 보내라. 거부하면 바로 공개한다.",
        },
        {
            "id": "threat_debt_collector",
            "text": "{relation:협박 대상 관계}가 빚을 남겼다. 지금 {large_money:요구 금액}을 갚지 않으면 집으로 찾아가겠다. 통화 끊지 말고 송금해라.",
        },
        {
            "id": "threat_police_block",
            "text": "신고하면 위치를 알고 있어서 위험해진다. {deadline:송금 기한} {money:요구 금액} 보내면 조용히 끝내겠다.",
        },
    ],
    "스미싱": [
        {
            "id": "smishing_delivery",
            "text": "[{courier:사칭 서비스명}] 주소 오류로 배송이 보류되었습니다. {deadline:날짜 또는 기간} 전 {url:악성 URL}에서 주소와 본인정보({personal_info:개인정보 항목})를 확인하세요. 발신 {phone:발신 번호}",
        },
        {
            "id": "smishing_tax_refund",
            "text": "[{service:사칭 서비스명}] 환급금이 발생했습니다. 본인 확인을 위해 {url:악성 URL} 접속 후 본인정보({personal_info:개인정보 항목})를 입력해주세요.",
        },
        {
            "id": "smishing_payment",
            "text": "[{service:사칭 서비스명}] 미납 결제 {money:금액}이 확인되었습니다. 연체 방지를 위해 {url:악성 URL}에서 즉시 납부하세요.",
        },
        {
            "id": "smishing_invitation",
            "text": "[모바일 청첩장] {person:사람 이름}님이 초대장을 보냈습니다. 사진 확인 {url:악성 URL} 설치 후 열람 가능합니다.",
        },
        {
            "id": "smishing_bank_security",
            "text": "[{bank:사칭 기관명}] 보안등급 만료 안내. {deadline:날짜 또는 기간}까지 {url:악성 URL}에서 앱을 업데이트하고 {personal_info:개인정보 항목} 인증을 완료하세요.",
        },
    ],
    "중고거래 사기": [
        {
            "id": "market_direct_payment",
            "text": "{market:거래 플랫폼명}에서 {item:거래 상품명} 판매합니다. 안전결제는 수수료가 커서 어렵고 {account:계좌번호}로 {money:금액} 먼저 보내주시면 바로 발송합니다.",
        },
        {
            "id": "market_fake_tracking",
            "text": "{item:거래 상품명} 이미 보냈고 운송장 {case_no:허위 운송장 번호}입니다. 택배 조회 반영 전에 잔금 {money:금액}을 입금해주세요.",
        },
        {
            "id": "market_escrow_link",
            "text": "{market:거래 플랫폼명} 안전결제 오류라 대체 링크 {url:웹사이트 주소}로 결제해야 합니다. 공식 앱보다 빠르고 수수료도 없습니다.",
        },
        {
            "id": "market_reserved",
            "text": "{item:거래 상품명} 문의가 많아 예약금 {money:금액} 먼저 주신 분께 판매합니다. 직거래는 어렵고 택배만 가능합니다.",
        },
        {
            "id": "market_family_account",
            "text": "제가 지금 계좌가 막혀서 가족 계좌 {account:계좌번호}로 입금 부탁드립니다. {item:거래 상품명}은 오늘 바로 편의점 택배로 보내겠습니다.",
        },
    ],
}


def _slot_value(slot: str, rng: random.Random) -> str:
    if slot in GENERATORS:
        return GENERATORS[slot](rng)
    values = SLOTS.get(slot)
    if not values:
        raise KeyError(f"unknown slot: {slot}")
    return rng.choice(values)


def _render(
    template: str,
    rng: random.Random,
) -> tuple[str, list[dict[str, Any]], dict[str, list[str]]]:
    """Render a template and collect entity spans.

    Placeholders have the shape {slot:entity_label}. The same rendered value can
    appear multiple times in a sentence; spans are recorded from replacement
    positions rather than by string search to avoid ambiguity.
    """
    text_parts: list[str] = []
    entities: list[dict[str, Any]] = []
    slots: dict[str, list[str]] = {}
    i = 0
    out_len = 0
    while i < len(template):
        if template[i] != "{":
            text_parts.append(template[i])
            out_len += 1
            i += 1
            continue
        end = template.find("}", i)
        if end < 0:
            raise ValueError(f"unclosed placeholder in template: {template}")
        raw = template[i + 1:end]
        if ":" not in raw:
            raise ValueError(f"placeholder must be slot:label, got {raw!r}")
        slot, label = raw.split(":", 1)
        value = _slot_value(slot, rng)
        slots.setdefault(slot, [])
        if value not in slots[slot]:
            slots[slot].append(value)
        start = out_len
        stop = start + len(value)
        text_parts.append(value)
        entities.append({
            "text": value,
            "label": label,
            "start": start,
            "end": stop,
        })
        out_len = stop
        i = end + 1
    return "".join(text_parts), _dedupe_entities(entities), slots


def _dedupe_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[int, int, str]] = set()
    out: list[dict[str, Any]] = []
    for ent in entities:
        key = (int(ent["start"]), int(ent["end"]), str(ent["label"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(ent)
    return out


def _risk_flags_for(scam_type: str, rng: random.Random) -> list[str]:
    flags = list(RISK_FLAGS[scam_type])
    rng.shuffle(flags)
    keep = rng.randint(2, min(4, len(flags)))
    return sorted(flags[:keep])


def _flag_groups_for(flags: list[str]) -> list[str]:
    groups: list[str] = []
    seen: set[str] = set()
    for flag in flags:
        group_id = group_of(flag)
        if group_id in seen:
            continue
        seen.add(group_id)
        groups.append(group_id)
    return sorted(groups)


def _entity_labels(entities: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ent in entities:
        label = str(ent["label"])
        if label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out


def _relations(
    *,
    scam_type: str,
    entities: list[dict[str, Any]],
    risk_flags: list[str],
    flag_groups: list[str],
) -> list[dict[str, str]]:
    """Build lightweight relation triples for future graph/RAG indexing."""
    relations: list[dict[str, str]] = []
    for flag in risk_flags:
        relations.append({
            "subject": flag,
            "predicate": "supports",
            "object": scam_type,
        })
    for group_id in flag_groups:
        relations.append({
            "subject": group_id,
            "predicate": "groups_signal_for",
            "object": scam_type,
        })
    for ent in entities:
        relations.append({
            "subject": str(ent["text"]),
            "predicate": "typed_as",
            "object": str(ent["label"]),
        })
    for ent in entities[:4]:
        for flag in risk_flags[:3]:
            relations.append({
                "subject": str(ent["text"]),
                "predicate": "evidence_candidate_for",
                "object": flag,
            })
    return relations


def _rag_texts(
    *,
    scam_type: str,
    scenario_ko: str,
    text: str,
    entities: list[dict[str, Any]],
    risk_flags: list[str],
    flag_groups: list[str],
) -> dict[str, str]:
    labels = _entity_labels(entities)
    values = [str(ent["text"]) for ent in entities[:5]]
    return {
        "case": f"{scam_type} 사례: {text}",
        "scenario": scenario_ko,
        "pattern": f"{scam_type} + {' + '.join(flag_groups)} + {' + '.join(risk_flags)}",
        "entity_pattern": ", ".join(labels),
        "evidence_terms": ", ".join(values),
    }


def generate_records(total: int, seed: int) -> list[dict[str, Any]]:
    if total < len(SCAM_TYPES):
        raise ValueError(f"total must be at least {len(SCAM_TYPES)}")
    rng = random.Random(seed)
    base = total // len(SCAM_TYPES)
    remainder = total % len(SCAM_TYPES)

    records: list[dict[str, Any]] = []
    for type_idx, scam_type in enumerate(SCAM_TYPES):
        n = base + (1 if type_idx < remainder else 0)
        templates = TEMPLATES[scam_type]
        for i in range(n):
            tmpl = templates[i % len(templates)]
            text, entities, slots = _render(tmpl["text"], rng)
            risk_flags = _risk_flags_for(scam_type, rng)
            flag_groups = _flag_groups_for(risk_flags)
            scenario_id = str(tmpl["id"])
            scenario_ko = f"{SCENARIO_KO[scam_type]} ({scenario_id})"
            records.append({
                "text": text,
                "content_label": "scam_attempt",
                "scam_type": scam_type,
                "sample_kind": "synthetic_scam_message",
                "source_ref": f"synthetic_template/{scam_type}/{tmpl['id']}",
                "template_id": tmpl["id"],
                "scenario_id": scenario_id,
                "scenario_ko": scenario_ko,
                "synthetic_id": f"sg-synth-{len(records) + 1:05d}",
                "slots": slots,
                "entities": entities,
                "risk_flags": risk_flags,
                "flag_groups": flag_groups,
                "relations": _relations(
                    scam_type=scam_type,
                    entities=entities,
                    risk_flags=risk_flags,
                    flag_groups=flag_groups,
                ),
                "rag_texts": _rag_texts(
                    scam_type=scam_type,
                    scenario_ko=scenario_ko,
                    text=text,
                    entities=entities,
                    risk_flags=risk_flags,
                    flag_groups=flag_groups,
                ),
            })
    rng.shuffle(records)
    return records


def validate(records: list[dict[str, Any]]) -> None:
    for idx, rec in enumerate(records, 1):
        text = rec["text"]
        if rec.get("content_label") != "scam_attempt":
            raise ValueError(f"row {idx}: invalid content_label")
        if rec.get("scam_type") not in SCAM_TYPES:
            raise ValueError(f"row {idx}: invalid scam_type")
        if not rec.get("entities"):
            raise ValueError(f"row {idx}: no entities")
        for ent in rec["entities"]:
            start = ent.get("start")
            end = ent.get("end")
            if not isinstance(start, int) or not isinstance(end, int) or start >= end:
                raise ValueError(f"row {idx}: invalid span {ent}")
            if text[start:end] != ent["text"]:
                raise ValueError(
                    f"row {idx}: span mismatch {ent!r}, got {text[start:end]!r}"
                )
        if not rec.get("risk_flags"):
            raise ValueError(f"row {idx}: no risk_flags")
        if not rec.get("scenario_id") or not rec.get("scenario_ko"):
            raise ValueError(f"row {idx}: missing scenario metadata")
        if not isinstance(rec.get("slots"), dict) or not rec["slots"]:
            raise ValueError(f"row {idx}: missing slots")
        if not rec.get("flag_groups"):
            raise ValueError(f"row {idx}: missing flag_groups")
        if not rec.get("relations"):
            raise ValueError(f"row {idx}: missing relations")
        rag_texts = rec.get("rag_texts")
        if not isinstance(rag_texts, dict) or not all(
            rag_texts.get(k) for k in ("case", "scenario", "pattern", "entity_pattern")
        ):
            raise ValueError(f"row {idx}: invalid rag_texts")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="data/generated/scamguardian_synthetic_3000.jsonl",
        help="Output JSONL path.",
    )
    parser.add_argument("--total", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=20260601)
    args = parser.parse_args()

    records = generate_records(args.total, args.seed)
    validate(records)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fp:
        for rec in records:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")

    by_type = Counter(rec["scam_type"] for rec in records)
    by_template = Counter(rec["source_ref"] for rec in records)
    print(f"wrote {len(records)} rows -> {output}")
    print("by scam_type:")
    for scam_type in SCAM_TYPES:
        print(f"  {scam_type}: {by_type[scam_type]}")
    print(f"template families: {len(by_template)}")
    print(f"rows per template: min={min(by_template.values())}, max={max(by_template.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
