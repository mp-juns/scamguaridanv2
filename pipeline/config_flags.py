"""
ScamGuardian — 설정: 검출 신호 카탈로그 + 학술/법적 근거

DETECTED_FLAGS·FLAG_LABELS_KO·FLAG_RATIONALE(절대 변경 금지)·도메인 신뢰도.
Identity (CLAUDE.md): 점수·등급 산정 없음 — 검출 사실만 보고.
순수 데이터 + 순수 함수만 — 프로젝트 모듈 import 금지.
외부 소비자는 `pipeline.config` facade 를 통해 import 한다.
"""

from __future__ import annotations

# ──────────────────────────────────────────────
# 검출 가능한 위험 신호 list
# ──────────────────────────────────────────────
# Identity (CLAUDE.md): ScamGuardian 은 점수·등급을 산정하지 않는다 — 검출 사실만 보고.
# 통합 기업이 자기 risk tolerance 에 따라 판정 logic 구현.
#
# 각 flag 의 학술/법적 근거는 FLAG_RATIONALE 에 보존 (절대 변경 금지).
# 한국어 라벨은 FLAG_LABELS_KO 에 매핑.
DETECTED_FLAGS: list[str] = [
    # ── 일반 검증 신호 ──
    "business_not_registered",          # 사업자 미등록
    "phone_scam_reported",              # 전화번호 스캠 신고 이력
    "ceo_name_mismatch",                # 대표명 불일치
    "fss_not_registered",               # 금감원 미등록
    "fake_certification",               # 가짜 인증기관
    "website_scam_reported",            # 웹사이트 피싱 신고
    "abnormal_return_rate",             # 비정상 고수익 주장 (>20%)
    "fake_government_agency",           # 정부기관 사칭
    "personal_info_request",            # 개인정보 요구
    "medical_claim_unverified",         # 미인증 의료 효능 주장
    "fake_exchange",                    # 가짜 거래소
    "account_scam_reported",            # 계좌 스캠 신고 이력
    "prepayment_requested",             # 선납금/수수료 먼저 요구
    "urgent_transfer_demand",           # 즉각 송금·이체 요구
    "threat_or_coercion",               # 협박·강요 발화 감지
    "impersonation_family",             # 가족·지인 사칭
    "romance_foreign_identity",         # 해외 신분 사칭
    "job_deposit_requested",            # 취업·알바 선입금 요구
    "smishing_link_detected",           # 스미싱 링크 포함
    "fake_escrow_bypass",               # 직거래·가짜 에스크로 유도

    # ── v3 Phase 0: VirusTotal 안전성 필터 ──
    "malware_detected",                 # 파일이 VT 에서 다중 엔진 악성 판정
    "phishing_url_confirmed",           # URL 이 VT 에서 다중 엔진 피싱·악성 판정
    "suspicious_file_signal",           # 파일이 VT 에서 일부 엔진만 의심
    "suspicious_url_signal",            # URL 이 VT 에서 일부 엔진만 의심

    # ── v3.5 Phase 0.5: URL 디토네이션 (격리 Chromium) ──
    "sandbox_password_form_detected",   # 격리 환경 navigate 결과 비밀번호 입력폼 발견
    "sandbox_sensitive_form_detected",  # 민감 정보 입력 필드 노출
    "sandbox_auto_download_attempt",    # drive-by download 시도
    "sandbox_cloaking_detected",        # 도메인 위장 (target ≠ final URL)
    "sandbox_excessive_redirects",      # 3회 초과 리디렉션

    # ── BERT 유사도 / 쿼리 A-B-C 신호 ──
    "authority_context_mismatch",       # 화자 프로파일 vs 발화 맥락 의미 불일치
    "authority_context_uncertain",      # 의미가 애매
    "query_a_confirmed",                # 신뢰 언론에서 화자+발언 동시 히트
    "query_a_unconfirmed",              # 신뢰 언론 동시 히트 부재
    "query_b_factcheck_found",          # 팩트체크 결과 스캠 단서
    "query_b_confirmed",                # 팩트체크에서 사실 확인
    "query_c_scam_pattern_found",       # 스캠 패턴 단서 발견

    # ── Stage 2: APK 정적 분석 Lv 1 (manifest·권한·서명) ──
    "apk_dangerous_permissions_combo",  # SEND_SMS + READ_SMS + ACCESSIBILITY 등 4종 이상
    "apk_self_signed",                  # 자체 서명 인증서 (Google Play 미배포)
    "apk_suspicious_package_name",      # 정상 앱 패키지명 typo-squatting

    # ── Stage 3: APK 심화 정적 분석 Lv 2 (dex bytecode 패턴) ──
    "apk_sms_auto_send_code",           # SmsManager.sendTextMessage 호출
    "apk_call_state_listener",          # TelephonyManager.listen(LISTEN_CALL_STATE)
    "apk_accessibility_abuse",          # AccessibilityService 상속
    "apk_impersonation_keywords",       # dex string 의 사칭 키워드 (검찰·금감원·은행 등)
    "apk_hardcoded_c2_url",             # IP 직접 / 무료 도메인 / 비표준 포트 URL
    "apk_string_obfuscation",           # 짧은 random 클래스명 비율 임계 초과
    "apk_device_admin_lock",            # DevicePolicyManager.lockNow 호출

    # ── Stage 4: APK 동적 분석 Lv 3 (격리 VM 안 에뮬레이터 behavior 모니터링) ──
    # ⚠️ 로컬 실행 절대 금지 — 별도 VM 안 Android 에뮬레이터 stack 에서만 동작.
    # 현재는 인터페이스 + flag 카탈로그만 박힘 (APK_DYNAMIC_ENABLED=0 기본).
    "apk_runtime_c2_network_call",      # 에뮬레이터 안에서 알려진 C&C 도메인·IP 호출 관찰
    "apk_runtime_sms_intercepted",      # 가상 SMS 수신 시 자동 가로채기·재전송 관찰
    "apk_runtime_overlay_attack",       # 다른 앱(은행) 위에 가짜 화면 띄움 관찰
    "apk_runtime_credential_exfiltration",  # 자격증명/민감정보 외부 송신 관찰
    "apk_runtime_persistence_install",  # boot-completed receiver / DeviceAdmin enable / 자동 시작 관찰
]


# 사용자 노출용 한국어 플래그 라벨 — 위 DETECTED_FLAGS 와 1:1 매핑
FLAG_LABELS_KO: dict[str, str] = {
    "business_not_registered": "사업자 미등록",
    "phone_scam_reported": "전화번호 스캠 신고 이력",
    "ceo_name_mismatch": "대표자명 불일치",
    "fss_not_registered": "금감원 미등록 업체",
    "fake_certification": "가짜 인증기관",
    "website_scam_reported": "웹사이트 피싱·사기 신고",
    "abnormal_return_rate": "비정상적 고수익 주장",
    "fake_government_agency": "정부기관 사칭",
    "personal_info_request": "개인정보 요구",
    "medical_claim_unverified": "미인증 의료 효능 주장",
    "fake_exchange": "가짜 거래소",
    "account_scam_reported": "계좌 스캠 신고 이력",
    "prepayment_requested": "선납금·수수료 요구",
    "urgent_transfer_demand": "즉각 송금·이체 요구",
    "threat_or_coercion": "협박·강요 발화",
    "impersonation_family": "가족·지인 사칭",
    "romance_foreign_identity": "해외 신분 사칭",
    "job_deposit_requested": "취업·알바 선입금 요구",
    "smishing_link_detected": "스미싱 의심 링크",
    "fake_escrow_bypass": "에스크로 회피 유도",
    "malware_detected": "악성코드 탐지",
    "phishing_url_confirmed": "피싱 URL 확인",
    "suspicious_file_signal": "의심 파일 신호",
    "suspicious_url_signal": "의심 URL 신호",
    "sandbox_password_form_detected": "샌드박스: 비밀번호 입력폼 발견",
    "sandbox_sensitive_form_detected": "샌드박스: 민감 입력 필드 발견",
    "sandbox_auto_download_attempt": "샌드박스: 자동 다운로드 시도",
    "sandbox_cloaking_detected": "샌드박스: 도메인 위장 (클로킹)",
    "sandbox_excessive_redirects": "샌드박스: 과도한 리디렉션",
    "authority_context_mismatch": "발화 맥락 불일치",
    "authority_context_uncertain": "발화 맥락 애매",
    "query_a_confirmed": "신뢰 언론에서 확인됨",
    "query_a_unconfirmed": "신뢰 언론 확인 불가",
    "query_b_factcheck_found": "팩트체크 결과 의심",
    "query_b_confirmed": "팩트체크에서 사실 확인",
    "query_c_scam_pattern_found": "스캠 패턴 단서",
    # APK 정적 분석 Lv 1
    "apk_dangerous_permissions_combo": "APK: 위험 권한 조합 (4종 이상)",
    "apk_self_signed": "APK: 자체 서명 인증서",
    "apk_suspicious_package_name": "APK: 패키지명 위장 의심",
    # APK 심화 정적 분석 Lv 2
    "apk_sms_auto_send_code": "APK: SMS 자동 발송 코드",
    "apk_call_state_listener": "APK: 통화 상태 가로채기",
    "apk_accessibility_abuse": "APK: 접근성 서비스 악용",
    "apk_impersonation_keywords": "APK: 사칭 키워드 string",
    "apk_hardcoded_c2_url": "APK: 의심 URL 하드코딩",
    "apk_string_obfuscation": "APK: 난독화 흔적",
    "apk_device_admin_lock": "APK: 화면 잠금 권한",
    # APK 동적 분석 Lv 3 (격리 VM 에뮬레이터)
    "apk_runtime_c2_network_call": "APK: C&C 서버 호출 (런타임)",
    "apk_runtime_sms_intercepted": "APK: SMS 가로채기 (런타임)",
    "apk_runtime_overlay_attack": "APK: 화면 오버레이 공격 (런타임)",
    "apk_runtime_credential_exfiltration": "APK: 자격증명 탈취 (런타임)",
    "apk_runtime_persistence_install": "APK: 지속성 설치 (런타임)",
}


def flag_label_ko(flag: str) -> str:
    """플래그 영문 키를 한국어 라벨로. 매핑 없으면 원본 반환."""
    return FLAG_LABELS_KO.get(flag, flag)


# 플래그 점수의 정당성·근거 — 사용자/라벨러에게 "왜 이 점수인가요?" 답변용.
# 공식 출처(KISA, 금감원, 경찰청)와 학술 자료(Cialdini 영향력 원리, Whitty 스캠
# 설득 모델, FBI IC3 등) 를 함께 인용해 점수의 정당성을 강화한다.
#
# 공통 학술 프레임워크:
# - Cialdini, R. B. (2021). Influence, New and Expanded: The Psychology of
#   Persuasion. Harper Business. — 권위(authority)·희소성(scarcity)·
#   사회적 증거(social proof) 6대 영향력 원리
# - Whitty, M. T. (2013). The Scammers Persuasive Techniques Model.
#   British Journal of Criminology, 53(4), 665–684. — 사기범 설득 단계 모델
# - Stajano, F., & Wilson, P. (2011). Understanding scam victims: Seven
#   principles for systems security. CACM, 54(3), 70–75. — 사회공학 7원칙
# - FBI IC3 Annual Internet Crime Report — 글로벌 사기 통계
# - 금융감독원 보이스피싱·유사수신 감독사례집 (연간) — 국내 통계
FLAG_RATIONALE: dict[str, dict[str, str]] = {
    "business_not_registered": {
        "rationale": "정상 사업자라면 국세청 사업자등록 조회에 노출됨. 미등록 = 비공식 거래 → 사기 위험 높음. 점수 20점은 단독으로는 위험 등급(41~70)에 못 미치지만 추가 신호와 결합 시 결정적 가산점.",
        "source": "국세청 사업자등록상태조회 / 전자상거래법 제12조 / Stajano & Wilson (2011) Principle 1: Distraction (위장된 정상성)",
    },
    "phone_scam_reported": {
        "rationale": "신고 이력 있는 번호는 재범 확률 매우 높음. KISA 통계 기준 신고 번호의 70%+ 가 추가 신고 발생. 25점은 단일 플래그 최고 등급으로, 신고 DB 매칭만으로도 '주의→위험' 격상이 가능함.",
        "source": "KISA 보이스피싱 동향 보고서 / Anderson, R. (2008) Security Engineering Ch.2 — 재범자 베이지안 사전확률",
    },
    "ceo_name_mismatch": {
        "rationale": "법인 대표자명이 공식 등록 정보와 다르면 사칭 가능성. 단독 신호로는 애매할 수 있어 15점 (보조 신호급).",
        "source": "금융감독원 유사수신 감독사례집 / Cialdini (2021) — 권위(Authority) 원리 악용 패턴",
    },
    "fss_not_registered": {
        "rationale": "투자권유는 금감원 등록 업체만 합법. 미등록 업체 권유는 자본시장법 위반. 법적 위반이지만 합법 자문업자 가장 사례도 있어 15점 보수적 책정.",
        "source": "자본시장과 금융투자업에 관한 법률 제11조 / 금융감독원 불법금융 동향 보고서",
    },
    "fake_certification": {
        "rationale": "존재하지 않거나 위조된 인증기관 명칭 사용은 표시·광고 공정화법 위반 + 사기 표지. Cialdini 의 권위 원리 악용 — '인증' 단어만으로 신뢰 형성.",
        "source": "표시·광고의 공정화에 관한 법률 제3조 / Cialdini (2021) — Authority Heuristic / Whitty (2013) — Authority cue 단계",
    },
    "website_scam_reported": {
        "rationale": "도메인이 피싱·사기 신고 DB에 등록된 경우. 동일 도메인 재범률 80%+. APWG 글로벌 통계도 동일 추세.",
        "source": "KISA 피싱사이트 신고센터 / phishtank / APWG Phishing Activity Trends Report (분기 발행)",
    },
    "abnormal_return_rate": {
        "rationale": "연 20% 이상 수익 보장은 자본시장법상 불법 권유 신호. 정상 주식·채권 펀드의 장기 평균 수익률은 연 5~10% (S&P 500 historical 약 10% 명목). 보장형 + 고수익은 Ponzi 사기 핵심 패턴.",
        "source": "금융감독원 보이스수신 감독사례집 / SEC Investor Bulletin: Affinity Fraud / Frankel, T. (2012) The Ponzi Scheme Puzzle, Oxford UP",
    },
    "fake_government_agency": {
        "rationale": "검찰·경찰·금감원 등 공공기관은 전화·문자로 자금 이체 요구 절대 안 함. Cialdini 의 권위 원리를 가장 강하게 악용. 25점은 단독 만으로 '주의→위험' 격상 가능한 최고 등급.",
        "source": "검찰청·경찰청·금감원 합동 보이스피싱 예방 가이드 / Cialdini (2021) — Authority / Modic & Lea (2013) Scam compliance and the psychology of persuasion, SSRN",
    },
    "personal_info_request": {
        "rationale": "주민번호·계좌번호·OTP 등 민감정보를 요구하는 패턴은 보이스피싱 핵심 지표. 정상 금융기관은 비밀번호·OTP 를 절대 묻지 않음.",
        "source": "KISA 보이스피싱 행위 분석 / 개인정보보호법 제15조 / Hadnagy, C. (2018) Social Engineering: The Science of Human Hacking, Wiley",
    },
    "medical_claim_unverified": {
        "rationale": "식약처 미인증 효능 주장은 약사법 위반. 건강식품 사기는 노년층 표적이며 Cialdini 의 사회적 증거(가짜 후기) + 권위(가짜 박사) 결합 패턴.",
        "source": "약사법 제68조 / 식품의약품안전처 부당 광고 단속 / FTC Health Fraud Reports / Cialdini (2021) — Social Proof",
    },
    "fake_exchange": {
        "rationale": "금감원·금융위 등록되지 않은 거래소는 자금 출금 불가 사례 다수. 코인 사기 핵심. Pig butchering(殺豬盤) 사기의 표준 단계.",
        "source": "특정금융거래정보법 제7조 / FBI IC3 Cryptocurrency Fraud Report / Cross, C. (2023) Romance fraud and pig butchering, Trends & Issues in Crime, AIC",
    },
    "account_scam_reported": {
        "rationale": "계좌가 사기 이용 신고 이력 있음. 즉각 송금 차단 권고. 통신사기피해환급법상 의심 계좌는 지급정지 대상. 25점 최고 등급.",
        "source": "전기통신금융사기 피해 방지 및 환급에 관한 특별법 / 금융감독원 사기 이용계좌 통계",
    },
    "prepayment_requested": {
        "rationale": "취업·대출 명목 선납금 요구는 사기죄 + 대부업법 위반. 실제 합법 업체는 선납 없음. Stajano & Wilson 의 'Need and Greed' 원칙(절박한 상황 표적) 악용.",
        "source": "대부업 등의 등록 및 금융이용자 보호에 관한 법률 / 직업안정법 / Stajano & Wilson (2011) Principle 4: Need and Greed",
    },
    "urgent_transfer_demand": {
        "rationale": "즉각 송금 요구는 보이스피싱 1순위 패턴. 사고력 마비 유도(visceral influence). Loewenstein (1996) 의 hot-cold empathy gap 이론으로 설명되는 의사결정 왜곡.",
        "source": "경찰청 사이버수사국 보이스피싱 통계 / Cialdini (2021) — Scarcity / Loewenstein, G. (1996) Out of control: Visceral influences on behavior, OBHDP, 65(3) / Whitty (2013) — Urgency 단계",
    },
    "threat_or_coercion": {
        "rationale": "협박·강요 발화는 형법 제283조 협박죄. 정상 거래에는 절대 등장 안 함. 공포(fear appeal) 활용 사회공학 — Witte (1992) Extended Parallel Process Model 로 설명.",
        "source": "형법 제283조 / KISA 통계 / Witte, K. (1992) Putting the fear back into fear appeals, Communication Monographs, 59(4)",
    },
    "impersonation_family": {
        "rationale": "가족 사칭은 메신저피싱 표준 패턴. 영상통화 거부 시 100% 사기. Cialdini 의 호감(Liking) 원리 + 절박감 결합. 노년층·부모층 피해 집중.",
        "source": "경찰청 메신저피싱 예방 가이드 / 금융감독원 메신저피싱 통계 / Cialdini (2021) — Liking / Whitty (2013) — emotional manipulation",
    },
    "romance_foreign_identity": {
        "rationale": "해외 군인·의사·외교관 사칭은 로맨스 스캠 표준. FBI IC3 2023 보고서 기준 로맨스 스캠 피해액 6.5억 달러. Whitty 의 스캠 설득 모델 4단계(grooming) 핵심.",
        "source": "FBI IC3 2023 Internet Crime Report / Whitty, M. T. (2013) The Scammers Persuasive Techniques Model, Br J Criminology, 53(4) / Whitty & Buchanan (2012) The online romance scam, Cyberpsychology, 15(3)",
    },
    "job_deposit_requested": {
        "rationale": "정상 채용은 입사 전 금전 요구 없음. 직업안정법 위반. 청년·구직자 표적의 절박감 악용.",
        "source": "직업안정법 제32조 / 고용노동부 채용 사기 단속 / Stajano & Wilson (2011) — Need and Greed",
    },
    "smishing_link_detected": {
        "rationale": "단축 URL 또는 비정상 도메인 포함 SMS 는 스미싱 의심. KISA 차단 통계 다수. APWG 보고서상 SMS phishing(smishing)은 2022 이후 이메일 피싱 능가하는 주요 채널.",
        "source": "KISA 스미싱 차단 시스템 / 방송통신위원회 스미싱 통계 / APWG Phishing Activity Trends Report",
    },
    "fake_escrow_bypass": {
        "rationale": "공식 에스크로 회피 유도는 중고거래 사기 표준. 안전결제 우회 = 위험 신호. 가격 할인 명분으로 정상 절차 무력화 — Stajano & Wilson 의 'Distraction' 원칙.",
        "source": "경찰청 사이버범죄 통계 / 한국인터넷진흥원 중고거래 사기 동향 / Stajano & Wilson (2011) Principle 1: Distraction",
    },
    "malware_detected": {
        "rationale": "VirusTotal 다중 안티바이러스 엔진(보통 70+개)이 첨부 파일을 악성코드로 탐지. 30점은 단독으로 '매우 위험' 등급 직행 — 메신저 피싱의 결정적 증거.",
        "source": "VirusTotal Public API v3 / NIST SP 800-83 Guide to Malware Incident Prevention",
    },
    "phishing_url_confirmed": {
        "rationale": "VirusTotal 의 URL 분석에서 다중 엔진이 피싱·악성으로 분류. APWG·Google Safe Browsing·PhishTank 등 다중 출처 합의 신호.",
        "source": "VirusTotal URL Scan / APWG Phishing Activity Trends Report / Google Safe Browsing Transparency Report",
    },
    "suspicious_file_signal": {
        "rationale": "일부 엔진만 의심으로 판정 (false positive 가능성 잔존). 확정적 차단보단 사용자에게 주의 환기 목적의 보조 가산점.",
        "source": "VirusTotal API / 자체 임계값 설계",
    },
    "suspicious_url_signal": {
        "rationale": "URL 이 일부 엔진에서만 의심 — 신생 도메인이거나 평판 낮은 호스팅. 다른 신호와 결합 시 결정적 단서.",
        "source": "VirusTotal URL Scan / APWG 신생 피싱 도메인 통계",
    },
    "sandbox_password_form_detected": {
        "rationale": "격리 헤드리스 Chromium 으로 의심 URL 을 직접 navigate 한 결과 비밀번호 입력 필드(<input type=password>) 발견. 정상 사이트가 검색·뉴스 링크에서 비번을 요구하는 경우는 거의 없음 — zero-day 피싱 페이지의 강력한 직접 증거.",
        "source": "OWASP Top 10 (A07: Identification & Authentication Failures) / APWG Phishing Activity Trends 2024",
    },
    "sandbox_sensitive_form_detected": {
        "rationale": "주민번호·카드번호·CVC·OTP·계좌 등 민감 정보 입력 필드 검출. 정상 가맹점 결제·인증 외 컨텍스트에서 노출 시 피싱 의심.",
        "source": "PCI DSS 4.0 / 개인정보보호법 시행령 별표1 (민감정보 정의)",
    },
    "sandbox_auto_download_attempt": {
        "rationale": "사용자 클릭 없이 페이지 진입만으로 다운로드 트리거 — drive-by download 패턴. 악성 APK·exe 배포의 전형.",
        "source": "Google Safe Browsing Transparency Report / Mavroeidis & Bromander (2017) Cyber Threat Intelligence Model",
    },
    "sandbox_cloaking_detected": {
        "rationale": "사용자에게 보여준 URL 의 호스트와 실제 최종 도착지 호스트가 다름 — 도메인 위장(cloaking) 패턴. 단축 URL 남용·가짜 리디렉션 체인.",
        "source": "APWG Cloaking Techniques Report / Mavroeidis & Bromander (2017)",
    },
    "sandbox_excessive_redirects": {
        "rationale": "리디렉션 3회 초과 — 추적 회피·트래픽 세탁·국가별 분기 라우팅 의심. 단독 결정적이진 않으나 다른 신호와 결합 시 의미.",
        "source": "Google Safe Browsing 휴리스틱 / 자체 임계값 설계",
    },
    "authority_context_mismatch": {
        "rationale": "발화자 직업·신원 vs 발화 내용의 SBERT 임베딩 코사인 유사도가 임계 미만 → 사칭 의심. 의미적 일관성 분석 기법.",
        "source": "Reimers & Gurevych (2019) Sentence-BERT, EMNLP / Cer et al. (2017) STS Benchmark",
    },
    "authority_context_uncertain": {
        "rationale": "유사도 경계선상 — 명확하지 않지만 낮은 가산 점수로 보수적 반영. 5점은 단독으론 등급 변화 없으며 다른 신호의 보조 가중치 역할.",
        "source": "자체 임계값 튜닝 / Reimers & Gurevych (2019) SBERT",
    },
    "query_a_confirmed": {
        "rationale": "신뢰 언론(Reuters/Bloomberg/연합 등)에서 화자+발언 동시 확인 → 신뢰도 ↑, 차감. 출처 다중 검증 원칙.",
        "source": "Domain Trust Score (자체 스펙) / Graves, L. (2016) Deciding What's True: The Rise of Political Fact-Checking, Columbia UP",
    },
    "query_a_unconfirmed": {
        "rationale": "신뢰 언론에서 확인 불가 = 출처 검증 실패. 권위 인용의 진위 불명 시 회의 원칙.",
        "source": "Domain Trust Score (자체 스펙) / SIFT 미디어 리터러시 모델 (Caulfield, 2017)",
    },
    "query_b_factcheck_found": {
        "rationale": "팩트체크 결과에서 사기 단서가 발견됨. 독립 검증 기관의 사후 판정 활용.",
        "source": "SNU FactCheck / Snopes / IFCN (International Fact-Checking Network) Code of Principles",
    },
    "query_b_confirmed": {
        "rationale": "팩트체크에서 사실 확인됨 → 신뢰도 보정. 가짜 양성(false positive) 완화 장치.",
        "source": "SNU FactCheck / IFCN",
    },
    "query_c_scam_pattern_found": {
        "rationale": "검색 결과에서 동일/유사 사기 패턴 단서 발견. 사회적 증거(피해자 후기·뉴스)로 추가 가중.",
        "source": "Serper API 검색 휴리스틱 / Cialdini (2021) — Social Proof",
    },

    # ──────────────────────────────────────────────
    # Stage 2: APK 정적 분석 Lv 1 (manifest·권한·서명)
    # ──────────────────────────────────────────────
    "apk_dangerous_permissions_combo": {
        "rationale": "한국 보이스피싱 패밀리(SecretCalls·KrBanker·MoqHao 등 S2W TALON 보고서)의 공통 기술 시그니처. SEND_SMS + READ_SMS + BIND_ACCESSIBILITY_SERVICE + SYSTEM_ALERT_WINDOW 4종 이상 동시 요구는 통화 가로채기·SMS 인증번호 탈취·화면 오버레이 공격의 기술적 전제. 정상 메신저 앱도 일부 권한 요구하나 4종 이상 조합은 매우 의심.",
        "source": "S2W TALON 위협 인텔리전스 보고서 (SecretCalls 분석) / 안랩 보이스피싱 분석 리포트 / 정보통신망법 제48조 (악성프로그램 유포 금지) / 통신사기피해환급법 제2조 제2호",
    },
    "apk_self_signed": {
        "rationale": "Google Play Store 정식 등록 앱은 회사 verified keystore 로 서명 (subject ≠ issuer). 사이드로딩 APK 는 거의 자체 서명 (subject == issuer). 단독으로는 정상 개발자 사이드로딩 가능성도 있어 보조 신호급 — 다른 신호와 결합 시 강해짐.",
        "source": "Android 보안 가이드라인 (Google: Sign your app) / KISA 모바일 앱 보안 점검 가이드 / Android Developer Documentation",
    },
    "apk_suspicious_package_name": {
        "rationale": "정상 앱 패키지명 prefix (`com.kakao.talk`, `com.nhn.android.search`, `kr.co.shinhan` 등) 포함하면서 정확히 일치 안 하는 typo-squatting 패턴. KrBanker 류 은행 사칭 APK 의 표준 수법. fake/test/official 등 의심 suffix 도 동일 분류.",
        "source": "S2W TALON KrBanker 보고서 / S2W TALON SecretCrow 보고서 / KISA 모바일 사칭 앱 통계 / Cialdini (2021) — Authority Heuristic",
    },

    # ──────────────────────────────────────────────
    # Stage 3: APK 심화 정적 분석 Lv 2 (dex bytecode 패턴 매칭)
    # ⚠️ 정확한 학술 용어: "심화 정적 분석" / "bytecode pattern matching" — 코드 *읽기만*, 실행 X.
    # 진짜 동적 분석 (에뮬레이터 behavior 모니터링) 은 future work.
    # ⚠️ 단일 신호로 사기 판정 X — 누적 + 조합으로만 강함 (false positive 주의).
    # ──────────────────────────────────────────────
    "apk_sms_auto_send_code": {
        "rationale": "bytecode 분석에서 SmsManager.sendTextMessage 호출 발견. 한국 보이스피싱 패밀리(SecretCalls·MoqHao 등)의 SMS 인증번호 가로채기 핵심 기술. 정상 메신저 앱도 SMS 인증에 사용 가능 — 권한 조합·서명 등과 결합 시 강한 신호.",
        "source": "S2W TALON SecretCalls 분석 보고서 / Android SmsManager API Documentation / 정보통신망법 제48조 / 통신사기피해환급법 제2조 제2호",
    },
    "apk_call_state_listener": {
        "rationale": "TelephonyManager.listen(LISTEN_CALL_STATE) 등록은 통화 수신·발신 모두 모니터링. 피해자가 경찰·금감원에 전화 걸 때 가로채는 SecretCalls 의 핵심 메커니즘. 정상 앱(통화 녹음 등)도 가능하나 다른 위험 신호 결합 시 강함.",
        "source": "S2W TALON SecretCalls 보고서 / Android TelephonyManager API Documentation / KISA 통화 가로채기 악성앱 분석",
    },
    "apk_accessibility_abuse": {
        "rationale": "AccessibilityService 를 상속한 클래스 발견. 다른 앱 화면 읽기·자동 클릭·자동 입력 가능 — KrBanker 의 가짜 은행 UI 오버레이 핵심. 정상 장애인 보조 앱도 사용하므로 단독 신호로는 약함 — 권한 조합·은행 사칭 패키지명 등 누적 시 강함.",
        "source": "OWASP Mobile Top 10 / Google Play Accessibility Policy / S2W TALON KrBanker 보고서 / Android AccessibilityService API Documentation",
    },
    "apk_impersonation_keywords": {
        "rationale": "dex string pool 에서 검찰·경찰·금감원·은행·보안·수사·구속·안전계좌 등 사칭 시나리오 키워드 발견. UI 텍스트나 푸시 알림에 사용되어 사용자 신뢰 형성 — Cialdini 의 권위(Authority) 원리 + Stajano-Wilson 의 시간 압박 원리 결합 패턴. 뉴스 앱도 일부 키워드 가능 — 다수 조합 시 강함.",
        "source": "Cialdini (2021) Influence — Authority Heuristic / Stajano & Wilson (2011) Understanding scam victims, CACM 54(3) — Time Pressure / S2W TALON 한국 보이스피싱 패밀리 분석 / 형법 제283조 (협박)",
    },
    "apk_hardcoded_c2_url": {
        "rationale": "dex string pool 에서 IP 주소 직접 박힘 또는 무료 도메인 (.tk/.ml/.ga/.cf/.gq) 또는 비표준 포트 발견. C&C 서버 통신 패턴 — 정상 앱은 도메인 + 표준 포트 (80/443) 사용. SecretCalls 패밀리에서 자주 보이는 인프라 시그니처.",
        "source": "S2W TALON SecretCalls 인프라 분석 / KISA 사이버 위협 인텔리전스 보고서 / 정보통신망법 제48조 / Mavroeidis & Bromander (2017) Cyber Threat Intelligence Model",
    },
    "apk_string_obfuscation": {
        "rationale": "1-2 글자 짧은 클래스명 비율이 30% 초과 + 클래스 50개 이상 — ProGuard/DexGuard 등 난독화 도구 사용 흔적. 정상 앱도 ProGuard 사용하나 보이스피싱 패밀리는 분석 회피 목적으로 *과도하게* 사용. 단독 신호로는 약함 — 다른 패턴과 결합 시 강함.",
        "source": "Allix et al. (2016) AndroZoo: Collecting Millions of Android Apps for Research, MSR / Wei et al. (2018) Deep Ground Truth Analysis of Current Android Malware / KISA 모바일 악성앱 동향 분석",
    },
    "apk_device_admin_lock": {
        "rationale": "DevicePolicyManager.lockNow 호출 — 화면 강제 잠금. 랜섬웨어성 보이스피싱 (피해자가 거부할 수 없도록 화면 잠그고 신고 차단) 패턴. 정상 보안·기업 MDM 앱도 가능하나 다른 위험 신호와 결합 시 매우 강함.",
        "source": "Android DevicePolicyManager API / KISA 안드로이드 랜섬웨어 동향 / S2W TALON 보고서",
    },

    # ──────────────────────────────────────────────
    # Stage 4: APK 동적 분석 Lv 3 (격리 VM Android 에뮬레이터 behavior 모니터링)
    # ⚠️ 로컬 실행 절대 금지. 별도 VM 안에서만 동작. 현재는 인터페이스 + flag 카탈로그만.
    # ⚠️ 동적 분석 신호는 *직접 행동 관찰* 이라 정적 패턴보다 false positive 적음.
    #     하지만 단독 신호 단정 X (Identity Boundary) — 검출 보고만, 판정은 통합 기업.
    # ──────────────────────────────────────────────
    "apk_runtime_c2_network_call": {
        "rationale": "격리 에뮬레이터 안에서 APK 가 알려진 C&C 도메인 또는 의심 IP 로 outbound 호출 시도. 정적 분석 (`apk_hardcoded_c2_url`) 이 *문자열* 만 보는 데 비해 동적은 *실제 통신* 관찰 — false positive 거의 없음. 정상 앱은 사전 등록된 도메인만 호출하므로 미등록 IP/저평판 도메인 호출은 결정적 증거.",
        "source": "S2W TALON 보이스피싱 인프라 분석 / KISA 사이버 위협 인텔리전스 / Mavroeidis & Bromander (2017) Cyber Threat Intelligence Model / Frida 동적 인스트루먼테이션",
    },
    "apk_runtime_sms_intercepted": {
        "rationale": "가상 SMS 수신을 에뮬레이터에서 시뮬레이션 했을 때 APK 가 자동으로 가로채 외부 서버로 재전송하는 동작 관찰. 정적 분석 (`apk_sms_auto_send_code`) 은 *코드 존재* 만 검증, 동적은 *실제 가로채기 행동* 관찰 — 매우 강한 증거. SecretCalls 류 SMS 인증번호 탈취 핵심 동작.",
        "source": "S2W TALON SecretCalls 분석 보고서 / 통신사기피해환급법 제2조 제2호 / 정보통신망법 제48조",
    },
    "apk_runtime_overlay_attack": {
        "rationale": "에뮬레이터에 정상 은행 앱이 설치된 상태에서 의심 APK 가 SYSTEM_ALERT_WINDOW 권한으로 가짜 로그인 화면을 *실제로* 띄우는 동작 관찰. 정적 분석 (`apk_accessibility_abuse`) 은 *권한 + 코드 존재* 만 봄, 동적은 *실제 오버레이 시도* 관찰 — KrBanker 류 핵심 공격 동작.",
        "source": "S2W TALON KrBanker 분석 / OWASP Mobile Top 10 — M2 Insecure Data Storage / Android SYSTEM_ALERT_WINDOW Policy",
    },
    "apk_runtime_credential_exfiltration": {
        "rationale": "에뮬레이터에 가상 자격증명 (계정·비밀번호·OTP) 입력 시 APK 가 외부 서버로 *실제로* 송신하는 동작 관찰. Frida hook 으로 HTTP/HTTPS payload 관찰. 정상 앱도 자격증명 송신하지만 *서버 도메인 일치* 확인으로 false positive 차단.",
        "source": "Frida 동적 인스트루먼테이션 / OWASP Mobile Top 10 — M3 Insecure Communication / KISA 모바일 자격증명 탈취 동향",
    },
    "apk_runtime_persistence_install": {
        "rationale": "에뮬레이터 재부팅 시뮬레이션 시 APK 가 자동 시작되는지 (`BOOT_COMPLETED` receiver) + DeviceAdmin enable 시도 관찰. 한국 보이스피싱 패밀리는 피해자가 앱 종료해도 다시 살아나도록 지속성 설치 — 사용자 의도와 어긋나는 자동 실행은 강한 신호.",
        "source": "Android BOOT_COMPLETED Permission Documentation / Android DevicePolicyManager API / KISA 안드로이드 악성앱 동향 / S2W TALON",
    },
}


def flag_rationale(flag: str) -> dict[str, str]:
    """플래그 점수의 정당성·출처 반환. 매핑 없으면 빈 dict."""
    return FLAG_RATIONALE.get(flag, {})

# ──────────────────────────────────────────────
# 도메인 신뢰도 등급 (노션 스펙 반영)
# ──────────────────────────────────────────────
DOMAIN_TRUST_SCORES: dict[str, int] = {
    # S
    "reuters.com": 3,
    "bloomberg.com": 3,
    "bbc.com": 3,
    "ap.org": 3,
    # A
    "yonhap.co.kr": 2,
    "chosun.com": 2,
    "joongang.co.kr": 2,
}

TRUSTED_QUERY_A_DOMAINS: list[str] = list(DOMAIN_TRUST_SCORES.keys())
