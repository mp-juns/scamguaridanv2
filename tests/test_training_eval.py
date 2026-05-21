"""학습·평가 파이프라인 검증 — dataset_summary / splits / eval_* / baseline 비교.

요구 테스트:
- scam_news_edu, normal 이 scam_type 평가에서 제외됨
- scam_attempt 만 scam_type 평가에 포함됨
- suspicious_insufficient, undetermined 가 gate 평가에서 제외됨 (3-class only)
- source_ref 같은 샘플이 한 fold 로만 배정됨 (leakage 없음)
- baseline vs current 라벨 커버리지 비교가 실제로 차이를 잡아냄
"""

from __future__ import annotations

import json

import pytest

from training import dataset_summary as ds
from training import eval_gate, eval_scam_type, eval_signals
from training.data import ClassifierExample
from training.splits import group_train_val_test_split, split_summary


# ── 공통 픽스처 ──

@pytest.fixture
def sample_jsonl(tmp_path):
    records = [
        {"text": "원금 보장 월 30%", "content_label": "scam_attempt",
         "scam_type": "투자 사기", "sample_kind": "real_scam_message"},
        {"text": "지금 입금하면 월 30% 배당", "content_label": "scam_attempt",
         "scam_type": "투자 사기", "sample_kind": "synthetic_scam_message",
         "source_ref": "https://news.ex/1"},
        {"text": "고수익 보장 코인 거래소", "content_label": "scam_attempt",
         "scam_type": "코인 사기", "sample_kind": "real_scam_message"},
        {"text": "보이스피싱 피해 급증 경찰 경고", "content_label": "scam_news_edu",
         "sample_kind": "scam_news_education", "source_ref": "https://news.ex/9"},
        {"text": "내일 회의 자료 공유드립니다", "content_label": "normal",
         "sample_kind": "normal_content"},
        {"text": "음... 잘 모르겠네요", "content_label": "undetermined"},
        {"text": "조금 이상하긴 한데", "content_label": "suspicious_insufficient"},
    ]
    p = tmp_path / "samples.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return p


# ── dataset_summary ──

def test_summary_counts_by_content_label(sample_jsonl):
    s = ds.summarize_dataset(extra_jsonl=sample_jsonl)
    assert s["total"] == 7
    assert s["by_content_label"]["scam_attempt"] == 3
    assert s["by_content_label"]["scam_news_edu"] == 1
    assert s["by_content_label"]["normal"] == 1
    assert s["by_content_label"]["undetermined"] == 1
    assert s["by_content_label"]["suspicious_insufficient"] == 1


def test_summary_scam_type_only_within_scam_attempt(sample_jsonl):
    s = ds.summarize_dataset(extra_jsonl=sample_jsonl)
    # 뉴스 sample 은 scam_type 통계에서 제외 — content_label != scam_attempt
    assert "투자 사기" in s["by_scam_type_in_scam_attempt"]
    assert s["by_scam_type_in_scam_attempt"]["투자 사기"] == 2
    assert s["by_scam_type_in_scam_attempt"]["코인 사기"] == 1


def test_summary_excluded_count(sample_jsonl):
    s = ds.summarize_dataset(extra_jsonl=sample_jsonl)
    # suspicious_insufficient + undetermined = 2
    assert s["excluded_from_training"] == 2


def test_summary_by_sample_kind(sample_jsonl):
    s = ds.summarize_dataset(extra_jsonl=sample_jsonl)
    assert s["by_sample_kind"]["real_scam_message"] == 2
    assert s["by_sample_kind"]["synthetic_scam_message"] == 1
    assert s["by_sample_kind"]["scam_news_education"] == 1


def test_summary_format_text_runs(sample_jsonl):
    s = ds.summarize_dataset(extra_jsonl=sample_jsonl)
    out = ds.format_summary(s)
    assert "전체 샘플" in out
    assert "투자 사기" in out


# ── splits — source_ref leakage 검증 ──

def _ex(content_label: str, source_ref: str | None = None, text: str = "x") -> ClassifierExample:
    return ClassifierExample(
        text=text, label="투자 사기", content_label=content_label, source_ref=source_ref,
    )


def test_group_split_keeps_same_source_ref_in_one_fold():
    # 두 source_ref 각 5개 + singleton 10개
    examples: list[ClassifierExample] = []
    for i in range(5):
        examples.append(_ex("scam_attempt", "https://A", f"a-{i}"))
    for i in range(5):
        examples.append(_ex("scam_attempt", "https://B", f"b-{i}"))
    for i in range(10):
        examples.append(_ex("scam_attempt", None, f"s-{i}"))
    tr, va, te = group_train_val_test_split(examples, val_ratio=0.2, test_ratio=0.2, seed=1)
    # source_ref 별 fold 위치 추적
    def folds_of(ref: str) -> set[str]:
        out = set()
        for fold, name in ((tr, "train"), (va, "val"), (te, "test")):
            if any(e.source_ref == ref for e in fold):
                out.add(name)
        return out
    assert len(folds_of("https://A")) == 1, "https://A 가 여러 fold 에 흩어짐 — leakage"
    assert len(folds_of("https://B")) == 1, "https://B 가 여러 fold 에 흩어짐 — leakage"


def test_group_split_ratios_best_effort():
    # 전부 singleton — 비율이 그대로 적용됨
    examples = [_ex("scam_attempt", None, f"s-{i}") for i in range(100)]
    tr, va, te = group_train_val_test_split(examples, val_ratio=0.15, test_ratio=0.15, seed=7)
    assert len(tr) + len(va) + len(te) == 100
    # train > val, train > test
    assert len(tr) > len(va)
    assert len(tr) > len(te)


def test_group_split_summary():
    examples = [
        _ex("scam_attempt", "https://A"),
        _ex("scam_attempt", "https://A"),
        _ex("scam_news_edu", None),
        _ex("normal", None),
    ]
    tr, va, te = group_train_val_test_split(examples, val_ratio=0.25, test_ratio=0.25, seed=1)
    summary = split_summary(tr, va, te)
    assert summary["sizes"]["train"] + summary["sizes"]["val"] + summary["sizes"]["test"] == 4
    # https://A 는 한 fold 에만
    fold_with_a = sum(
        1 for f in (tr, va, te) if any(e.source_ref == "https://A" for e in f)
    )
    assert fold_with_a == 1


def test_group_split_empty():
    assert group_train_val_test_split([], 0.15, 0.15) == ([], [], [])


# ── eval_gate ──

def test_eval_gate_excludes_suspicious_and_undetermined():
    records = [
        {"content_label_gt": "scam_attempt", "content_label_predicted": "scam_attempt"},
        {"content_label_gt": "normal", "content_label_predicted": "normal"},
        {"content_label_gt": "scam_news_edu", "content_label_predicted": "scam_news_edu"},
        {"content_label_gt": "suspicious_insufficient", "content_label_predicted": "scam_attempt"},
        {"content_label_gt": "undetermined", "content_label_predicted": "normal"},
    ]
    m = eval_gate.evaluate_gate(records)
    assert m["n"] == 3  # 3-class only
    assert m["skipped_out_of_scope"] == 2
    assert m["accuracy"] == 1.0


def test_eval_gate_per_class_metrics():
    # 4 normal correct, 1 normal mispredicted as scam_attempt
    records = [
        {"content_label_gt": "normal", "content_label_predicted": "normal"},
        {"content_label_gt": "normal", "content_label_predicted": "normal"},
        {"content_label_gt": "normal", "content_label_predicted": "normal"},
        {"content_label_gt": "normal", "content_label_predicted": "normal"},
        {"content_label_gt": "normal", "content_label_predicted": "scam_attempt"},
        {"content_label_gt": "scam_attempt", "content_label_predicted": "scam_attempt"},
    ]
    m = eval_gate.evaluate_gate(records)
    assert m["n"] == 6
    assert abs(m["accuracy"] - 5/6) < 1e-9
    normal_m = m["per_class"]["normal"]
    assert normal_m["support"] == 5
    assert abs(normal_m["recall"] - 4/5) < 1e-9


def test_eval_gate_confusion_matrix_includes_other_when_pred_out_of_scope():
    records = [
        {"content_label_gt": "scam_attempt", "content_label_predicted": "undetermined"},
    ]
    m = eval_gate.evaluate_gate(records)
    assert m["confusion_matrix"]["scam_attempt"]["_other"] == 1


# ── eval_scam_type ──

def test_scam_type_eval_excludes_news_and_normal():
    records = [
        {"content_label_gt": "scam_news_edu", "scam_type_gt": "투자 사기", "scam_type_predicted": "투자 사기"},
        {"content_label_gt": "normal", "scam_type_gt": "투자 사기", "scam_type_predicted": "투자 사기"},
        {"content_label_gt": "scam_attempt", "scam_type_gt": "투자 사기", "scam_type_predicted": "투자 사기"},
    ]
    m = eval_scam_type.evaluate_scam_type(records)
    assert m["n"] == 1
    assert m["skipped_non_scam_attempt"] == 2
    assert m["top1_accuracy"] == 1.0


def test_scam_type_eval_only_scam_attempt():
    records = [
        {"content_label_gt": "scam_attempt", "scam_type_gt": "투자 사기", "scam_type_predicted": "투자 사기"},
        {"content_label_gt": "scam_attempt", "scam_type_gt": "코인 사기", "scam_type_predicted": "투자 사기"},
        {"content_label_gt": "scam_attempt", "scam_type_gt": "코인 사기", "scam_type_predicted": "코인 사기"},
    ]
    m = eval_scam_type.evaluate_scam_type(records)
    assert m["n"] == 3
    # 2/3 top-1 correct
    assert abs(m["top1_accuracy"] - 2/3) < 1e-9


def test_scam_type_top3_accuracy_uses_topk_predicted():
    records = [
        {
            "content_label_gt": "scam_attempt",
            "scam_type_gt": "코인 사기",
            "scam_type_predicted": "투자 사기",  # top-1 틀림
            "top_k_predicted": ["투자 사기", "코인 사기", "대출 사기"],
        },
    ]
    m = eval_scam_type.evaluate_scam_type(records)
    assert m["top1_accuracy"] == 0.0
    assert m["top3_accuracy"] == 1.0


def test_scam_type_top3_falls_back_to_all_scores():
    records = [
        {
            "content_label_gt": "scam_attempt",
            "scam_type_gt": "대출 사기",
            "scam_type_predicted": "투자 사기",
            "all_scores": {"투자 사기": 0.5, "코인 사기": 0.3, "대출 사기": 0.2, "스미싱": 0.05},
        },
    ]
    m = eval_scam_type.evaluate_scam_type(records)
    assert m["top3_accuracy"] == 1.0  # 대출 사기 는 top-3 안에


# ── eval_signals — flag / group ──

def test_eval_flags_basic():
    records = [
        {
            "triggered_flags_gt": [{"flag": "personal_info_request"}, {"flag": "urgent_transfer_demand"}],
            "triggered_flags_predicted": [{"flag": "personal_info_request"}],  # TP=1, FN=1
        },
        {
            "triggered_flags_gt": [{"flag": "abnormal_return_rate"}],
            "triggered_flags_predicted": [{"flag": "abnormal_return_rate"}, {"flag": "fake_government_agency"}],  # TP=1, FP=1
        },
    ]
    m = eval_signals.evaluate_flags(records)
    assert m["micro"]["tp"] == 2
    assert m["micro"]["fp"] == 1
    assert m["micro"]["fn"] == 1
    assert m["per_flag"]["personal_info_request"]["recall"] == 1.0


def test_eval_groups_buckets_flags_via_group_of():
    records = [
        {
            # personal_info_request → personal_sensitive_request group
            # urgent_transfer_demand → financial_demand
            "triggered_flags_gt": [{"flag": "personal_info_request"}, {"flag": "urgent_transfer_demand"}],
            "triggered_flags_predicted": [{"flag": "sandbox_password_form_detected"}],
            # sandbox_password_form_detected 도 personal_sensitive_request 그룹 → group-level 에선 TP=1
        },
    ]
    m = eval_signals.evaluate_groups(records)
    # personal_sensitive_request: gt+pred 둘 다 있음 → TP=1
    assert "personal_sensitive_request" in m["per_group"]
    assert m["per_group"]["personal_sensitive_request"]["precision"] == 1.0
    assert m["per_group"]["personal_sensitive_request"]["recall"] == 1.0
    # financial_demand: gt 만 — FN
    assert m["per_group"]["financial_demand"]["recall"] == 0.0


# ── baseline vs current 라벨 커버리지 ──

def test_baseline_vs_current_label_coverage_catches_personal_info():
    # 투자 사기 LABEL_SET 에 "개인정보 항목" 없음 → baseline 미커버, current 커버 (COMMON_RISK_LABELS)
    records = [
        {
            "content_label_gt": "scam_attempt",
            "scam_type_gt": "투자 사기",
            "entities_gt": [
                {"label": "수익 퍼센트", "text": "연 30%"},
                {"label": "개인정보 항목", "text": "주민번호"},
            ],
        },
    ]
    m = eval_signals.compare_label_coverage(records)
    assert m["n_records"] == 1
    by = m["by_key_label"]["개인정보 항목"]
    assert by["support"] == 1
    assert by["baseline_rate"] == 0.0
    assert by["current_rate"] == 1.0
    assert by["delta"] > 0


def test_coverage_skips_non_scam_attempt():
    records = [
        {"content_label_gt": "scam_news_edu", "scam_type_gt": "투자 사기", "entities_gt": []},
        {"content_label_gt": "normal", "scam_type_gt": "", "entities_gt": []},
    ]
    m = eval_signals.compare_label_coverage(records)
    assert m["n_records"] == 0
    assert m["skipped_non_scam_attempt"] == 2


def test_coverage_uses_candidates_when_present():
    # 투자 사기 top-1 인데 candidates 에 스미싱 포함 → 악성 URL 라벨이 current 에 포함됨
    records = [
        {
            "content_label_gt": "scam_attempt",
            "scam_type_gt": "투자 사기",
            "candidate_scam_types": ["투자 사기", "스미싱"],
            "entities_gt": [{"label": "악성 URL", "text": "http://bad.example"}],
        },
    ]
    m = eval_signals.compare_label_coverage(records)
    by = m["by_key_label"]["악성 URL"]
    assert by["support"] == 1
    assert by["baseline_rate"] == 0.0  # 투자 사기 LABEL_SET 에 악성 URL 없음
    assert by["current_rate"] == 1.0  # COMMON_RISK + 스미싱 LABEL_SET 둘 중 하나에서 커버
