#!/usr/bin/env python3
"""Persist projection pipeline outcomes into repo memory and retrieval stores."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


def load_json(path: Path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except (OSError, json.JSONDecodeError):
        pass
    return default


def append_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def save_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_projection_feedback(runtime_dir: Path):
    runtime_dir = Path(runtime_dir)
    state_dir = runtime_dir / "state"
    orchestrator_dir = runtime_dir / ".orchestrator"
    memory_path = runtime_dir / "MEMORY.md"
    retrieval_log = runtime_dir / "retrieval_log.jsonl"
    vector_dir = orchestrator_dir / "vector_store"
    iterations_dir = orchestrator_dir / "iterations"
    data_dir = orchestrator_dir / "data"

    extraction = load_json(state_dir / "extraction.json", {})
    overrides = load_json(state_dir / "operator_overrides.json", {})
    projected_tasks = load_json(state_dir / "projected_tasks.json", {})
    promotion = load_json(state_dir / "projection_promotion.json", {})

    timestamp = datetime.now().isoformat()
    slug = hashlib.sha1(timestamp.encode("utf-8")).hexdigest()[:12]
    summary = (
        f"Projection pipeline promoted {len(projected_tasks.get('tasks', []))} tasks from "
        f"{len(extraction.get('structures', []))} extracted structures with "
        f"{sum(len(overrides.get(key, [])) for key in ('renames', 'merges', 'splits', 'suppressions', 'notes'))} overrides."
    )

    append_text(
        memory_path,
        (
            f"\n## Projection Feedback - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- Summary: {summary}\n"
            f"- Promotion Ready: {promotion.get('promoted', False)}\n"
            f"- Prompt Handoff: {promotion.get('prompt_path', 'SPAWN/START/prompt.md')}\n"
        ),
    )

    feedback_payload = {
        "id": f"projection_feedback_{slug}",
        "timestamp": timestamp,
        "type": "projection_feedback",
        "summary": summary,
        "structures": extraction.get("structures", []),
        "overrides": overrides,
        "projected_tasks": projected_tasks.get("tasks", []),
        "promotion": promotion,
    }
    save_json(vector_dir / f"projection_feedback_{slug}.json", feedback_payload)
    save_json(iterations_dir / f"projection_feedback_{slug}.json", feedback_payload)
    append_text(data_dir / f"projection_feedback_{slug}.jsonl", json.dumps(feedback_payload) + "\n")
    append_text(
        retrieval_log,
        json.dumps(
            {
                "timestamp": timestamp,
                "query": "projection pipeline feedback",
                "top_hits": [
                    "SPAWN/STOP/state/extraction.json",
                    "SPAWN/STOP/state/projected_tasks.json",
                    "SPAWN/STOP/state/projection_promotion.json",
                ],
                "notes": summary,
                "source": "projection_feedback",
            }
        )
        + "\n",
    )
    return feedback_payload


if __name__ == "__main__":
    print(json.dumps(write_projection_feedback(Path(__file__).resolve().parents[1]), indent=2))
