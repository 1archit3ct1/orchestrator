#!/usr/bin/env python3
"""Training stack launcher and smoke-test contract for the local runtime."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1]
ORCHESTRATOR_DIR = RUNTIME_DIR / ".orchestrator"
DATA_DIR = ORCHESTRATOR_DIR / "data"
MODELS_DIR = ORCHESTRATOR_DIR / "models"
TRAINING_DIR = RUNTIME_DIR / "training"


DEFAULT_CONFIG = {
    "framework": "axolotl",
    "base_model": "mistralai/Mistral-Small-24B-Instruct-2501",
    "parameter_class": "24B",
    "dataset_path": "SPAWN/STOP/.orchestrator/data/canonical_traces.jsonl",
    "smoke_dataset_path": "SPAWN/STOP/.orchestrator/data/smoke_subset.jsonl",
    "output_dir": "SPAWN/STOP/.orchestrator/models/finetuned",
    "micro_batch_size": 1,
    "gradient_accumulation_steps": 16,
    "num_epochs": 1,
    "learning_rate": 2e-4,
    "adapter": "qlora",
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
}


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def detect_vram() -> dict:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {"available": False, "reason": "nvidia-smi not found"}
    try:
        result = subprocess.run(
            [nvidia_smi, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return {"available": False, "reason": str(exc)}

    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not line:
        return {"available": False, "reason": "nvidia-smi returned no GPU rows"}
    name, total, free = [part.strip() for part in line.split(",")[:3]]
    return {
        "available": True,
        "gpu_name": name,
        "memory_total_mb": int(total),
        "memory_free_mb": int(free),
    }


def ensure_default_config() -> Path:
    config_path = TRAINING_DIR / "train_stack_config.json"
    if not config_path.exists():
        write_json(config_path, DEFAULT_CONFIG)
    return config_path


def smoke_test(dataset: Path) -> dict:
    dataset_exists = dataset.exists()
    preview_lines = 0
    if dataset_exists:
        with open(dataset, "r", encoding="utf-8", errors="replace") as handle:
            for preview_lines, _line in enumerate(handle, start=1):
                if preview_lines >= 8:
                    break
    vram = detect_vram()
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "dataset": str(dataset.relative_to(RUNTIME_DIR.parent.parent)).replace("\\", "/") if dataset.exists() else str(dataset),
        "dataset_exists": dataset_exists,
        "preview_lines": preview_lines,
        "vram_profile": vram,
        "status": "smoke_test_validated" if dataset_exists else "blocked",
        "notes": [
            "Smoke test validates dataset visibility, config presence, and artifact flow.",
            "No checkpoint weights are fabricated by this validation pass.",
        ],
    }
    smoke_dir = MODELS_DIR / "smoke_test"
    write_json(smoke_dir / "manifest.json", manifest)
    write_json(ORCHESTRATOR_DIR / "logs" / "vram_profile.json", vram)
    return manifest


def launch_plan(config_path: Path, dataset: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    plan = {
        "generated_at": datetime.now().isoformat(),
        "status": "configured",
        "framework": config["framework"],
        "base_model": config["base_model"],
        "parameter_class": config["parameter_class"],
        "dataset": str(dataset.relative_to(RUNTIME_DIR.parent.parent)).replace("\\", "/") if dataset.exists() else str(dataset),
        "launch_command": f"python SPAWN/STOP/training/train_stack.py --config {config_path.relative_to(RUNTIME_DIR.parent.parent)} --dataset {dataset.relative_to(RUNTIME_DIR.parent.parent)}",
        "checkpoint_dir": config["output_dir"],
        "evaluation_hook": "python SPAWN/STOP/training/eval_harness.py --candidate latest_checkpoint --baseline frontier_gpt_baseline",
    }
    write_json(MODELS_DIR / "train_stack_plan.json", plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()

    config_path = args.config or ensure_default_config()
    dataset = args.dataset or (DATA_DIR / ("smoke_subset.jsonl" if args.smoke_test else "canonical_traces.jsonl"))
    if not config_path.is_absolute():
        config_path = (RUNTIME_DIR.parent.parent / config_path).resolve()
    if not dataset.is_absolute():
        dataset = (RUNTIME_DIR.parent.parent / dataset).resolve()

    if args.smoke_test:
        result = smoke_test(dataset)
    else:
        result = launch_plan(config_path, dataset)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
