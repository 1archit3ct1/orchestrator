#!/usr/bin/env python3
"""Build canonical datasets and metrics from local runtime traces."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from trace_pipeline import (
    DATA_DIR,
    ORCHESTRATOR_DIR,
    QualityThresholds,
    deduplicate_records,
    normalize_records,
    storage_contract,
    storage_index,
)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, default=str) + "\n")


def main() -> int:
    thresholds = QualityThresholds()
    normalized = normalize_records(thresholds)
    unique, dedup = deduplicate_records(normalized)
    accepted = [row for row in unique if row.get("accepted")]
    signal_counts = Counter(row.get("signal", "unknown") for row in accepted)
    source_counts = Counter(row.get("source_type", "unknown") for row in accepted)

    canonical_path = DATA_DIR / "canonical_traces.jsonl"
    smoke_subset_path = DATA_DIR / "smoke_subset.jsonl"
    metrics_path = DATA_DIR / "clean_dataset_metrics.json"
    contract_path = DATA_DIR / "trace_storage_contract.json"
    index_path = DATA_DIR / "trace_storage_index.json"
    framework_path = ORCHESTRATOR_DIR / "data" / "training_framework_contract.json"

    write_jsonl(canonical_path, accepted)
    write_jsonl(smoke_subset_path, accepted[: min(64, len(accepted))])
    write_json(contract_path, storage_contract())
    write_json(index_path, storage_index())

    metrics = {
        "generated_at": datetime.now().isoformat(),
        "thresholds": thresholds.__dict__,
        "raw_records": len(normalized),
        "unique_records": len(unique),
        "clean_records": len(accepted),
        "duplicate_count": dedup["duplicate_count"],
        "clean_ratio": round((len(accepted) / len(unique)), 4) if unique else 0.0,
        "signal_counts": dict(signal_counts),
        "source_counts": dict(source_counts),
        "dataset_paths": {
            "canonical": str(canonical_path.relative_to(DATA_DIR.parent.parent)).replace("\\", "/"),
            "smoke_subset": str(smoke_subset_path.relative_to(DATA_DIR.parent.parent)).replace("\\", "/"),
            "contract": str(contract_path.relative_to(DATA_DIR.parent.parent)).replace("\\", "/"),
            "storage_index": str(index_path.relative_to(DATA_DIR.parent.parent)).replace("\\", "/"),
        },
    }
    write_json(metrics_path, metrics)

    framework_contract = {
        "generated_at": datetime.now().isoformat(),
        "framework": "axolotl",
        "dataset_format": "jsonl instruction-tuning with explicit signal labels",
        "launch_contract": "python SPAWN/STOP/training/train_stack.py --config SPAWN/STOP/training/train_stack_config.json --dataset SPAWN/STOP/.orchestrator/data/canonical_traces.jsonl",
        "smoke_test_contract": "python SPAWN/STOP/training/train_stack.py --smoke-test --dataset SPAWN/STOP/.orchestrator/data/smoke_subset.jsonl",
    }
    write_json(framework_path, framework_contract)

    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
