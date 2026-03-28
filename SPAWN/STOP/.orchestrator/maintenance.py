#!/usr/bin/env python3
"""
Maintenance jobs for the orchestrator runtime.

Current job:
- parse_duplicates: detect and remove duplicate memory/training artifacts
  once they have been safely canonicalized.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from dashboard_state import sync_dashboard_state


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def append_jsonl(path: Path, entry: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")


def canonical_json_signature(payload):
    if isinstance(payload, dict):
        filtered = {}
        for key in sorted(payload):
            if key in {"timestamp", "generated_at", "id"}:
                continue
            filtered[key] = canonical_json_signature(payload[key])
        return filtered
    if isinstance(payload, list):
        return [canonical_json_signature(item) for item in payload]
    return payload


def canonical_memory_block_signature(block: str) -> str:
    lines = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("- Timestamp:"):
            continue
        if stripped.startswith("## ") and re.search(r"\d{4}-\d{2}-\d{2}", stripped):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def dedupe_json_files(files: list[Path]) -> list[str]:
    signatures = {}
    removed = []
    for path in sorted(files, key=lambda item: item.stat().st_mtime):
        payload = load_json(path, None)
        if payload is None:
            continue
        signature = json.dumps(canonical_json_signature(payload), sort_keys=True, default=str)
        if signature in signatures:
            path.unlink(missing_ok=True)
            removed.append(str(path))
        else:
            signatures[signature] = path
    return removed


def dedupe_jsonl_file(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0

    try:
        original_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0, 0

    seen = set()
    kept = []
    removed = 0
    for line in original_lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            signature = json.dumps(canonical_json_signature(payload), sort_keys=True, default=str)
        except json.JSONDecodeError:
            signature = line.strip()
        if signature in seen:
            removed += 1
            continue
        seen.add(signature)
        kept.append(line)

    if removed:
        rendered = "\n".join(kept)
        if rendered:
            rendered += "\n"
        path.write_text(rendered, encoding="utf-8")
    return len(kept), removed


def dedupe_memory_md(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0

    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return 0, 0

    prefix = ""
    body = text
    if "\n## " in text:
        split_at = text.index("\n## ") + 1
        prefix = text[:split_at]
        body = text[split_at:]

    raw_blocks = body.split("\n## ")
    normalized_blocks = []
    seen = set()
    removed = 0

    for index, block in enumerate(raw_blocks):
        if not block.strip():
            continue
        full_block = ("## " + block) if index > 0 or not block.startswith("## ") else block
        signature = canonical_memory_block_signature(full_block)
        if signature in seen:
            removed += 1
            continue
        seen.add(signature)
        normalized_blocks.append(full_block.strip("\n"))

    if removed:
        rendered = prefix.rstrip("\n")
        if rendered:
            rendered += "\n\n"
        rendered += "\n\n".join(normalized_blocks).rstrip() + "\n"
        path.write_text(rendered, encoding="utf-8")
    return len(normalized_blocks), removed


def run_duplicate_parse(runtime_dir: Path) -> dict:
    orchestrator_dir = runtime_dir / ".orchestrator"
    vector_dir = orchestrator_dir / "vector_store"
    data_dir = orchestrator_dir / "data"
    iterations_dir = orchestrator_dir / "iterations"
    decisions_dir = iterations_dir / "decisions"
    logs_dir = orchestrator_dir / "logs" / "maintenance"
    memory_path = runtime_dir / "MEMORY.md"
    retrieval_log = runtime_dir / "retrieval_log.jsonl"

    removed = {
        "vector_store": dedupe_json_files(list(vector_dir.glob("*.json"))) if vector_dir.exists() else [],
        "iterations": dedupe_json_files(list(iterations_dir.glob("iter_*.json"))) if iterations_dir.exists() else [],
        "decisions": dedupe_json_files(list(decisions_dir.glob("dec_*.json"))) if decisions_dir.exists() else [],
    }

    data_counts = {}
    if data_dir.exists():
        for path in sorted(data_dir.glob("*.jsonl")):
            kept, deleted = dedupe_jsonl_file(path)
            data_counts[str(path)] = {"kept": kept, "deleted": deleted}

    retrieval_kept, retrieval_deleted = dedupe_jsonl_file(retrieval_log)
    memory_kept, memory_deleted = dedupe_memory_md(memory_path)

    report = {
        "timestamp": datetime.now().isoformat(),
        "job": "parse_duplicates",
        "status": "completed",
        "duplicates_found": any([
            removed["vector_store"],
            removed["iterations"],
            removed["decisions"],
            any(item["deleted"] for item in data_counts.values()),
            retrieval_deleted,
            memory_deleted,
        ]),
        "removed": removed,
        "jsonl": {
            "data_files": data_counts,
            "retrieval_log": {"kept": retrieval_kept, "deleted": retrieval_deleted},
        },
        "memory_md": {"kept": memory_kept, "deleted": memory_deleted},
    }

    logs_dir.mkdir(parents=True, exist_ok=True)
    report_path = logs_dir / f"duplicate_parse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_json(report_path, report)

    append_jsonl(
        runtime_dir / "retrieval_log.jsonl",
        {
            "timestamp": report["timestamp"],
            "query": "maintenance duplicate parse",
            "top_hits": [
                "SPAWN/STOP/MEMORY.md",
                "SPAWN/STOP/retrieval_log.jsonl",
                str(report_path.relative_to(runtime_dir.parent.parent)),
            ],
            "notes": "Removed exact duplicate memory/training artifacts when canonical signatures matched.",
        },
    )

    return report


def queue_duplicate_parse_if_needed(runtime_dir: Path) -> dict:
    orchestrator_dir = runtime_dir / ".orchestrator"
    config_path = orchestrator_dir / "config.json"
    queue_path = orchestrator_dir / "task_queue.json"

    config = load_json(config_path, {})
    duplicate_cfg = config.setdefault("maintenance", {}).setdefault("duplicate_parse", {})
    if not duplicate_cfg.get("enabled", True):
        return {"queued": False, "reason": "disabled"}

    dashboard_state = sync_dashboard_state(runtime_dir)
    current_tokens = int(dashboard_state.get("model", {}).get("memory_collected_tokens", 0) or 0)
    threshold = int(duplicate_cfg.get("token_threshold", 3000) or 3000)
    last_requested = int(duplicate_cfg.get("last_requested_tokens", 0) or 0)

    if current_tokens < threshold or (current_tokens - last_requested) < threshold:
        return {
            "queued": False,
            "reason": "threshold_not_crossed",
            "current_tokens": current_tokens,
            "threshold": threshold,
            "last_requested_tokens": last_requested,
        }

    queue = load_json(queue_path, [])
    if not isinstance(queue, list):
        queue = queue.get("pending", [])

    if any(task.get("id") == "maintenance_parse_duplicates" for task in queue):
        return {"queued": False, "reason": "already_queued", "current_tokens": current_tokens}

    queue.append(
        {
            "id": "maintenance_parse_duplicates",
            "repo": "orchestrator",
            "job": "parse_duplicates",
            "description": "Parse memory/training artifacts for duplicates and delete exact duplicates when found.",
            "allowed_paths": [
                "SPAWN/STOP/MEMORY.md",
                "SPAWN/STOP/retrieval_log.jsonl",
                "SPAWN/STOP/.orchestrator/vector_store/",
                "SPAWN/STOP/.orchestrator/data/",
                "SPAWN/STOP/.orchestrator/iterations/",
                "SPAWN/STOP/.orchestrator/logs/maintenance/",
            ],
            "priority": 999,
            "status": "pending",
            "trigger": {
                "type": "token_threshold",
                "memory_collected_tokens": current_tokens,
                "threshold": threshold,
                "cron_schedule": duplicate_cfg.get("cron_schedule", "*/15 * * * *"),
            },
            "prompt_load_path": "SPAWN/STOP/.orchestrator/task_queue.json",
        }
    )

    duplicate_cfg["last_requested_tokens"] = current_tokens
    save_json(queue_path, queue)
    save_json(config_path, config)
    return {"queued": True, "current_tokens": current_tokens, "threshold": threshold}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", choices=["parse_duplicates", "queue_duplicate_parse_if_needed"], required=True)
    parser.add_argument("--runtime-dir", required=True)
    args = parser.parse_args()

    runtime_dir = Path(args.runtime_dir).resolve()
    if args.job == "parse_duplicates":
        run_duplicate_parse(runtime_dir)
    elif args.job == "queue_duplicate_parse_if_needed":
        queue_duplicate_parse_if_needed(runtime_dir)


if __name__ == "__main__":
    main()
