#!/usr/bin/env python3
"""Repo-defined coding evaluation harness."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = RUNTIME_DIR / ".orchestrator" / "data"
ITERATIONS_DIR = RUNTIME_DIR / ".orchestrator" / "iterations"


def build_suite() -> dict:
    return {
        "generated_at": datetime.now().isoformat(),
        "suite_name": "nextaura_repo_coding_eval",
        "scoring": {
            "pass_rate_weight": 0.55,
            "repair_weight": 0.25,
            "repo_truth_weight": 0.20,
        },
        "tasks": [
            {
                "id": "routing_truth_001",
                "prompt": "Keep repo-truth frontend state aligned with canonical dashboard payloads.",
                "expected_artifact": "repo-truth frontend remains hydrated from /api/repo-truth/dashboard",
                "category": "frontend_truth",
            },
            {
                "id": "training_pipeline_001",
                "prompt": "Normalize runtime traces into a canonical JSONL dataset with signal labels and quality gates.",
                "expected_artifact": "canonical_traces.jsonl and clean_dataset_metrics.json are produced",
                "category": "training_data",
            },
            {
                "id": "runtime_security_001",
                "prompt": "Preserve task-scoped lock and audit behavior while updating local runtime flows.",
                "expected_artifact": "repo-freeze and mutex state remain visible from live endpoints",
                "category": "security",
            },
        ],
    }


def run_bootstrap(candidate: str, baseline: str) -> dict:
    suite = build_suite()
    result = {
        "generated_at": datetime.now().isoformat(),
        "candidate": candidate,
        "baseline": baseline,
        "suite_name": suite["suite_name"],
        "status": "bootstrap_ready",
        "task_count": len(suite["tasks"]),
        "notes": [
            "Harness definitions are live and repo-backed.",
            "No candidate checkpoints were executed during bootstrap.",
        ],
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ITERATIONS_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "eval_suite.json").write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
    (ITERATIONS_DIR / "eval_harness_bootstrap.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="candidate_24b")
    parser.add_argument("--baseline", default="frontier_gpt_baseline")
    args = parser.parse_args()
    result = run_bootstrap(args.candidate, args.baseline)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
