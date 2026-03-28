#!/usr/bin/env python3
"""Canonical training-data helpers for the local orchestrator runtime."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


RUNTIME_DIR = Path(__file__).resolve().parents[1]
ORCHESTRATOR_DIR = RUNTIME_DIR / ".orchestrator"
DATA_DIR = ORCHESTRATOR_DIR / "data"
ITERATIONS_DIR = ORCHESTRATOR_DIR / "iterations"
VECTOR_DIR = ORCHESTRATOR_DIR / "vector_store"
MEMORY_PATH = RUNTIME_DIR / "MEMORY.md"
RETRIEVAL_LOG_PATH = RUNTIME_DIR / "retrieval_log.jsonl"


@dataclass
class QualityThresholds:
    min_instruction_chars: int = 12
    min_output_chars: int = 12
    min_quality_score: float = 0.45


def load_json(path: Path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default
    return default


def load_jsonl(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        return records
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    payload = {"raw": line}
                payload["_source_path"] = str(path.relative_to(RUNTIME_DIR)).replace("\\", "/")
                records.append(payload)
    except OSError:
        return records
    return records


def iter_iteration_payloads() -> Iterable[tuple[Path, dict]]:
    if not ITERATIONS_DIR.exists():
        return
    for path in sorted(ITERATIONS_DIR.rglob("*.json")):
        payload = load_json(path, None)
        if isinstance(payload, dict):
            yield path, payload


def read_memory_blocks(limit: int = 160) -> list[str]:
    if not MEMORY_PATH.exists():
        return []
    text = MEMORY_PATH.read_text(encoding="utf-8", errors="replace")
    blocks = []
    current = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            blocks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block][:limit]


def parse_retrieval_lines(limit: int = 200) -> list[dict]:
    return load_jsonl(RETRIEVAL_LOG_PATH)[:limit]


def detect_signal(path: Path, payload: dict) -> str:
    lowered_name = path.name.lower()
    payload_type = str(payload.get("type", "")).lower()
    if "dec_" in lowered_name or "decision" in payload_type or payload.get("decision"):
        return "steering"
    if "miss" in lowered_name or "miss" in payload_type:
        return "miss"
    if payload.get("status") == "error":
        return "error"
    return "success"


def extract_instruction(payload: dict, fallback: str = "") -> str:
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    prompt = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
    options = [
        decision.get("question"),
        payload.get("summary"),
        payload.get("description"),
        payload.get("query"),
        prompt.get("user"),
        fallback,
    ]
    for value in options:
        if value:
            return str(value).strip()
    return ""


def extract_output(payload: dict) -> str:
    outcome = payload.get("outcome") if isinstance(payload.get("outcome"), dict) else {}
    response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
    details = payload.get("details")
    options = [
        outcome.get("lesson"),
        outcome.get("result"),
        response.get("content"),
        payload.get("summary"),
        json.dumps(details, default=str) if details else "",
    ]
    for value in options:
        if value:
            return str(value).strip()
    return ""


def quality_score(record: dict, thresholds: QualityThresholds) -> float:
    score = 0.0
    instruction = record.get("instruction", "")
    output = record.get("output", "")
    if len(instruction) >= thresholds.min_instruction_chars:
        score += 0.35
    if len(output) >= thresholds.min_output_chars:
        score += 0.35
    if record.get("signal") == "steering":
        score += 0.15
    if record.get("source_type") in {"iteration", "data", "retrieval"}:
        score += 0.1
    if record.get("session_id"):
        score += 0.05
    return round(min(score, 1.0), 3)


def normalize_records(thresholds: QualityThresholds | None = None) -> list[dict]:
    thresholds = thresholds or QualityThresholds()
    normalized: list[dict] = []

    for path, payload in iter_iteration_payloads():
        signal = detect_signal(path, payload)
        instruction = extract_instruction(payload, fallback=path.stem.replace("_", " "))
        output = extract_output(payload)
        session_id = payload.get("session_id") or payload.get("iteration_id") or payload.get("id")
        record = {
            "record_id": path.stem,
            "timestamp": payload.get("timestamp") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "session_id": session_id,
            "node_id": payload.get("dag_node_id") or payload.get("node_id"),
            "instruction": instruction,
            "input": json.dumps(payload.get("context", {}), default=str) if payload.get("context") else "",
            "output": output,
            "signal": signal,
            "source_type": "iteration",
            "source_path": str(path.relative_to(RUNTIME_DIR)).replace("\\", "/"),
            "tags": [signal, "iteration"],
        }
        record["quality_score"] = quality_score(record, thresholds)
        record["accepted"] = record["quality_score"] >= thresholds.min_quality_score
        normalized.append(record)

    for path in sorted(DATA_DIR.glob("*.jsonl")):
        for index, payload in enumerate(load_jsonl(path), start=1):
            signal = "steering" if "decision" in path.name.lower() or "steering" in path.name.lower() else "data"
            instruction = extract_instruction(payload, fallback=path.stem.replace("_", " "))
            output = extract_output(payload) or str(payload.get("raw", "")).strip()
            record = {
                "record_id": f"{path.stem}_{index:04d}",
                "timestamp": payload.get("timestamp") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "session_id": payload.get("session_id") or path.stem,
                "node_id": payload.get("dag_node_id") or payload.get("node_id"),
                "instruction": instruction,
                "input": json.dumps(payload.get("details", {}), default=str) if payload.get("details") else "",
                "output": output,
                "signal": signal,
                "source_type": "data",
                "source_path": str(path.relative_to(RUNTIME_DIR)).replace("\\", "/"),
                "tags": [signal, "data"],
            }
            record["quality_score"] = quality_score(record, thresholds)
            record["accepted"] = record["quality_score"] >= thresholds.min_quality_score
            normalized.append(record)

    for index, payload in enumerate(parse_retrieval_lines(), start=1):
        query = str(payload.get("query", "")).strip()
        notes = str(payload.get("notes", "")).strip()
        if not query and not notes:
            continue
        record = {
            "record_id": f"retrieval_{index:04d}",
            "timestamp": payload.get("timestamp") or datetime.now().isoformat(),
            "session_id": payload.get("session_id"),
            "node_id": None,
            "instruction": query or "retrieval event",
            "input": json.dumps(payload.get("top_hits", []), default=str),
            "output": notes or query,
            "signal": "retrieval",
            "source_type": "retrieval",
            "source_path": "SPAWN/STOP/retrieval_log.jsonl",
            "tags": ["retrieval"],
        }
        record["quality_score"] = quality_score(record, thresholds)
        record["accepted"] = record["quality_score"] >= thresholds.min_quality_score
        normalized.append(record)

    for index, block in enumerate(read_memory_blocks(), start=1):
        title = block.splitlines()[0].replace("##", "").strip() if block.splitlines() else f"memory block {index}"
        record = {
            "record_id": f"memory_{index:04d}",
            "timestamp": datetime.fromtimestamp(MEMORY_PATH.stat().st_mtime).isoformat() if MEMORY_PATH.exists() else datetime.now().isoformat(),
            "session_id": "memory-ledger",
            "node_id": None,
            "instruction": title,
            "input": "",
            "output": block,
            "signal": "memory",
            "source_type": "memory",
            "source_path": "SPAWN/STOP/MEMORY.md",
            "tags": ["memory"],
        }
        record["quality_score"] = quality_score(record, thresholds)
        record["accepted"] = record["quality_score"] >= thresholds.min_quality_score
        normalized.append(record)

    return normalized


def deduplicate_records(records: list[dict]) -> tuple[list[dict], dict]:
    unique = []
    seen = {}
    duplicates = 0
    for record in records:
        signature = hashlib.sha1(
            json.dumps(
                {
                    "instruction": record.get("instruction"),
                    "input": record.get("input"),
                    "output": record.get("output"),
                    "signal": record.get("signal"),
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        if signature in seen:
            duplicates += 1
            continue
        record["content_hash"] = signature
        seen[signature] = record["record_id"]
        unique.append(record)
    return unique, {"duplicate_count": duplicates, "unique_count": len(unique)}


def storage_index() -> dict:
    def index_dir(base: Path, pattern: str) -> list[dict]:
        if not base.exists():
            return []
        return [
            {
                "path": str(path.relative_to(RUNTIME_DIR)).replace("\\", "/"),
                "size_bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
            for path in sorted(base.rglob(pattern))
            if path.is_file()
        ]

    return {
        "generated_at": datetime.now().isoformat(),
        "data_jsonl": index_dir(DATA_DIR, "*.jsonl"),
        "vector_json": index_dir(VECTOR_DIR, "*.json"),
        "iteration_json": index_dir(ITERATIONS_DIR, "*.json"),
        "memory_markdown": [
            {
                "path": "SPAWN/STOP/MEMORY.md",
                "size_bytes": MEMORY_PATH.stat().st_size if MEMORY_PATH.exists() else 0,
                "modified_at": datetime.fromtimestamp(MEMORY_PATH.stat().st_mtime).isoformat() if MEMORY_PATH.exists() else None,
            }
        ],
    }


def storage_contract() -> dict:
    return {
        "generated_at": datetime.now().isoformat(),
        "roles": {
            "data_jsonl": "Canonical line-oriented training and replay records derived from runtime traces.",
            "vector_json": "Ranked retrieval memory entries and session/miss summaries for semantic context lookup.",
            "iteration_json": "Raw iteration, decision, and miss artifacts preserving per-event provenance.",
            "memory_markdown": "Human-readable append-only ledger of runtime lessons and high-value summaries.",
        },
        "normalization_rules": {
            "required_fields": ["record_id", "timestamp", "instruction", "output", "signal", "source_type", "source_path"],
            "optional_fields": ["session_id", "node_id", "input", "quality_score", "accepted", "tags", "content_hash"],
            "signal_values": ["success", "steering", "miss", "error", "data", "retrieval", "memory"],
        },
        "downstream_guarantees": {
            "canonical_dataset": "SPAWN/STOP/.orchestrator/data/canonical_traces.jsonl",
            "metrics": "SPAWN/STOP/.orchestrator/data/clean_dataset_metrics.json",
            "storage_index": "SPAWN/STOP/.orchestrator/data/trace_storage_index.json",
            "smoke_subset": "SPAWN/STOP/.orchestrator/data/smoke_subset.jsonl",
        },
    }
