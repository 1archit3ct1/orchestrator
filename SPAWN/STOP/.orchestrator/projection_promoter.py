#!/usr/bin/env python3
"""Promote approved projection state into canonical execution queue safely."""

from __future__ import annotations

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


def save_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def promote_projection(runtime_dir: Path):
    runtime_dir = Path(runtime_dir)
    state_dir = runtime_dir / "state"
    orchestrator_dir = runtime_dir / ".orchestrator"
    projected_tasks_path = state_dir / "projected_tasks.json"
    projection_graph_path = state_dir / "projection_graph.json"
    projection_pipeline_path = state_dir / "projection_pipeline.json"
    promotion_summary_path = state_dir / "projection_promotion.json"
    queue_path = orchestrator_dir / "task_queue.json"

    projected_tasks = load_json(projected_tasks_path, {"tasks": []})
    projection_graph = load_json(projection_graph_path, {"nodes": [], "edges": []})
    pipeline = load_json(projection_pipeline_path, {})
    queue = load_json(queue_path, [])
    if not isinstance(queue, list):
        queue = []

    tasks = projected_tasks.get("tasks", [])
    if not tasks:
        return {"promoted": False, "reason": "no projected tasks are available"}

    promoted_ids = []
    existing_ids = {item.get("id") for item in queue}
    for item in tasks:
        promoted_id = f"projection_exec_{item.get('id')}"
        if promoted_id in existing_ids:
            continue
        queue.append(
            {
                "id": promoted_id,
                "repo": "orchestrator",
                "description": item.get("description", ""),
                "allowed_paths": [
                    "SPAWN/STOP/state/",
                    "SPAWN/STOP/.orchestrator/",
                    "SPAWN/STOP/web/",
                    "README.md",
                ],
                "priority": len(queue) + 1,
                "status": "pending",
                "goal": "projection_first_orchestration",
                "source_id": item.get("source_id"),
                "projected_task_id": item.get("id"),
                "task_id": item.get("task_id"),
                "label": item.get("label"),
            }
        )
        promoted_ids.append(promoted_id)

    for index, item in enumerate(queue, start=1):
        item["priority"] = index
    save_json(queue_path, queue)

    projected_tasks["approval_state"] = "approved"
    projected_tasks["promoted_at"] = datetime.now().isoformat()
    save_json(projected_tasks_path, projected_tasks)

    projection_graph["approval_state"] = "approved"
    projection_graph["promoted_at"] = projected_tasks["promoted_at"]
    save_json(projection_graph_path, projection_graph)

    pipeline["approved"] = True
    pipeline["promotion_ready"] = True
    pipeline["prompt_handoff_ready"] = True
    pipeline["active_stage"] = "prompt_handoff"
    for stage in pipeline.get("stages", []):
        if stage.get("id") in {"extractor", "operator_review", "task_generation", "promotion_gate"}:
            stage["status"] = "complete"
        elif stage.get("id") == "prompt_handoff":
            stage["status"] = "active"
    save_json(projection_pipeline_path, pipeline)

    summary = {
        "canonical": True,
        "generated_at": datetime.now().isoformat(),
        "promoted": True,
        "promoted_count": len(promoted_ids),
        "promoted_ids": promoted_ids,
        "prompt_path": "SPAWN/START/prompt.md",
        "queue_path": "SPAWN/STOP/.orchestrator/task_queue.json",
    }
    save_json(promotion_summary_path, summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(promote_projection(Path(__file__).resolve().parents[1]), indent=2))
