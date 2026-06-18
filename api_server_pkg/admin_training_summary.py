"""어드민 학습 synthetic 요약 helper."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_checkpoint_state(output_dir: Path) -> dict[str, Any]:
    states: list[tuple[int, dict[str, Any]]] = []
    for state_path in output_dir.glob("checkpoint-*/trainer_state.json"):
        try:
            step = int(state_path.parent.name.rsplit("-", 1)[-1])
        except ValueError:
            step = 0
        state = _read_json(state_path)
        if state:
            states.append((step, state))
    if not states:
        return {}
    return max(states, key=lambda item: item[0])[1]


def _eval_snapshots(state: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for row in state.get("log_history", []):
        if not isinstance(row, dict) or "eval_macro_f1" not in row:
            continue
        snapshots.append({
            "step": row.get("step"),
            "epoch": row.get("epoch"),
            "eval_loss": row.get("eval_loss"),
            "eval_accuracy": row.get("eval_accuracy"),
            "eval_macro_f1": row.get("eval_macro_f1"),
            "eval_macro_precision": row.get("eval_macro_precision"),
            "eval_macro_recall": row.get("eval_macro_recall"),
        })
    return snapshots


def _synthetic_attempt_summary(session_dir: Path) -> dict[str, Any] | None:
    output_dir = session_dir / "output"
    if not output_dir.exists():
        return None
    label2id = _read_json(output_dir / "label2id.json")
    adapter_config = _read_json(output_dir / "adapter_config.json")
    state = _latest_checkpoint_state(output_dir)
    evals = _eval_snapshots(state)
    final_eval = evals[-1] if evals else {}
    return {
        "session_id": session_dir.name,
        "output_dir": str(output_dir),
        "has_adapter": (output_dir / "adapter_config.json").exists(),
        "saves_classifier_head": "classifier" in adapter_config.get("modules_to_save", []),
        "label_count": len(label2id),
        "global_step": state.get("global_step"),
        "epoch": state.get("epoch"),
        "best_metric": state.get("best_metric"),
        "evals": evals,
        "final_eval": final_eval,
    }


def _latest_synthetic_corpus() -> Path:
    default = Path("data/generated/scamguardian_synthetic_3000.jsonl")
    candidates = list(Path("data/generated").glob("scamguardian_synthetic_*.jsonl"))
    if not candidates:
        return default

    def corpus_size(path: Path) -> int:
        match = re.search(r"scamguardian_synthetic_(\d+)\.jsonl$", path.name)
        if not match:
            return -1
        return int(match.group(1))

    return max(candidates, key=lambda path: (corpus_size(path), path.stat().st_mtime))


def _synthetic_graph(path: Path) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    links: dict[tuple[str, str, str], dict[str, Any]] = {}

    def set_node(node_id: str, label: str, kind: str, group: str, weight: int = 0) -> None:
        nodes[node_id] = {"id": node_id, "label": label, "kind": kind, "group": group, "weight": weight}

    def add_weight(node_id: str, weight: int = 1) -> None:
        node = nodes.setdefault(
            node_id,
            {"id": node_id, "label": node_id, "kind": "unknown", "group": "unknown", "weight": 0},
        )
        node["weight"] = int(node.get("weight", 0)) + weight

    def add_link(source: str, target: str, kind: str, weight: int = 1) -> None:
        key = (source, target, kind)
        link = links.setdefault(
            key,
            {"source": source, "target": target, "kind": kind, "weight": 0},
        )
        link["weight"] = int(link.get("weight", 0)) + weight

    set_node("corpus", "학습 데이터", "corpus", "corpus")
    set_node("axis:classifier", "분류기", "axis", "classifier")
    set_node("axis:extractor", "추출기", "axis", "extractor")
    add_link("corpus", "axis:classifier", "feeds")
    add_link("corpus", "axis:extractor", "feeds")
    if not path.exists():
        return {"nodes": list(nodes.values()), "links": []}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        scam_type = str(row.get("scam_type") or "unknown")
        type_id = f"type:{scam_type}"
        if type_id not in nodes:
            set_node(type_id, scam_type, "scam_type", "classifier")
        add_weight(type_id)
        add_link("axis:classifier", type_id, "has_type")

        for ent in row.get("entities") or []:
            label = str(ent.get("label") or "").strip()
            if not label:
                continue
            ent_id = f"entity_label:{label}"
            if ent_id not in nodes:
                set_node(ent_id, label, "entity_label", "extractor")
            add_weight(ent_id)
            add_link("axis:extractor", ent_id, "has_entity_label")

    return {
        "nodes": sorted(nodes.values(), key=lambda node: (str(node["group"]), str(node["kind"]), -int(node.get("weight", 0)), str(node["id"]))),
        "links": sorted(links.values(), key=lambda link: (str(link["source"]), str(link["target"]))),
    }
