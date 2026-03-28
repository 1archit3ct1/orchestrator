#!/usr/bin/env python3
"""
Orchestrator Dashboard - Flask Backend

Serves the designed dashboard from `state/design.html` and hydrates it with
live orchestrator state so the browser always reflects the repo as-built.
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_from_directory


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "orchestrator.log")),
    ],
)
logger = logging.getLogger("orchestrator")

app = Flask(__name__, template_folder="templates", static_folder="static")


SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = SCRIPT_DIR.parent
ORCHESTRATOR_DIR = RUNTIME_DIR / ".orchestrator"
STATE_DIR = RUNTIME_DIR / "state"
LOGS_DIR = ORCHESTRATOR_DIR / "logs"
DATA_DIR = ORCHESTRATOR_DIR / "data"
MODELS_DIR = ORCHESTRATOR_DIR / "models"
VECTOR_STORE_DIR = ORCHESTRATOR_DIR / "vector_store"
REPOS_DIR = RUNTIME_DIR / "repos"
TRAINING_DIR = RUNTIME_DIR / "training"
LOCKS_DIR = ORCHESTRATOR_DIR / "locks"

CONFIG_PATH = ORCHESTRATOR_DIR / "config.json"
TASK_QUEUE_PATH = ORCHESTRATOR_DIR / "task_queue.json"
DESIGN_GRAPH_PATH = STATE_DIR / "design_graph.json"
TASKS_PATH = STATE_DIR / "tasks.json"
MEMORY_PATH = RUNTIME_DIR / "MEMORY.md"
DESIGN_HTML_PATH = STATE_DIR / "design.html"
SECURITY_AUDIT_LOG_PATH = LOGS_DIR / "security" / "security_audit.log"
ORCHESTRATOR_LOG_PATH = LOGS_DIR / "orchestrator.log"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from dashboard_state import sync_dashboard_state


def load_json(path: Path, default):
    """Load JSON safely and fall back to a caller-provided default."""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load %s: %s", path, exc)
    return default


def read_text(path: Path, default=""):
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.error("Failed to read %s: %s", path, exc)
    return default


def tail_lines(path: Path, limit=20):
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return [line.rstrip() for line in handle.readlines()[-limit:]]
    except OSError as exc:
        logger.error("Failed to tail %s: %s", path, exc)
        return []


def format_bytes(num_bytes):
    units = ["B", "KB", "MB", "GB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(num_bytes)} B"


def count_files(path: Path):
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def rel_runtime_path(path: Path):
    try:
        return str(path.relative_to(RUNTIME_DIR)).replace("\\", "/")
    except ValueError:
        return str(path)


def summarize_path_entry(path: Path):
    stat = path.stat()
    return {
        "name": path.name,
        "path": rel_runtime_path(path),
        "size_bytes": stat.st_size,
        "size": format_bytes(stat.st_size),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }


def collect_recent_files(base_dir: Path, patterns, limit=6):
    if not base_dir.exists():
        return []
    paths = []
    for pattern in patterns:
        paths.extend(path for path in base_dir.rglob(pattern) if path.is_file())
    unique_paths = sorted(set(paths), key=lambda item: item.stat().st_mtime, reverse=True)
    return [summarize_path_entry(path) for path in unique_paths[:limit]]


def collect_training_queue_items(limit=6):
    queue = load_json(TASK_QUEUE_PATH, [])
    if not isinstance(queue, list):
        return []

    keywords = ("train", "training", "dataset", "model", "eval", "trace", "fine-tune")
    items = []
    for item in queue:
        haystack = " ".join(
            str(item.get(key, "")) for key in ["id", "description", "goal", "job"]
        ).lower()
        if any(keyword in haystack for keyword in keywords):
            items.append(
                {
                    "id": item.get("id"),
                    "status": item.get("status", "pending"),
                    "priority": item.get("priority"),
                    "description": item.get("description", ""),
                    "goal": item.get("goal"),
                    "allowed_paths": item.get("allowed_paths", []),
                }
            )
    return items[:limit]


def build_training_run_payload():
    config = load_json(CONFIG_PATH, {})
    dashboard = build_dashboard_payload()
    training_config = config.get("training_config", {}) if isinstance(config, dict) else {}
    output_dir = training_config.get("output_dir")
    output_path = Path(output_dir) if output_dir else None
    if output_path and not output_path.is_absolute():
        output_path = RUNTIME_DIR.parent.parent / output_path

    training_scripts = collect_recent_files(TRAINING_DIR, ["*.py", "*.sh", "*.yaml", "*.yml", "*.json"], limit=8)
    model_artifacts = collect_recent_files(MODELS_DIR, ["*.pt", "*.bin", "*.safetensors", "*.json", "*.ckpt"], limit=8)
    dataset_artifacts = collect_recent_files(DATA_DIR, ["*.jsonl", "*.json", "*.csv"], limit=8)
    training_logs = []
    for path in [LOGS_DIR / "spawn_runner.log", LOGS_DIR / "loop-actual.err.log", LOGS_DIR / "loop-test.err.log"]:
        if path.exists():
            training_logs.append(
                {
                    "path": rel_runtime_path(path),
                    "tail": tail_lines(path, 5),
                }
            )

    blockers = []
    if not training_scripts:
        blockers.append("No training scripts are present under SPAWN/STOP/training/.")
    if not dataset_artifacts:
        blockers.append("No dataset artifacts are present under SPAWN/STOP/.orchestrator/data/.")
    if not model_artifacts:
        blockers.append("No model checkpoints are present under SPAWN/STOP/.orchestrator/models/.")
    if not training_config.get("integrated"):
        blockers.append("training_config.integrated is false in .orchestrator/config.json.")

    memory_model = dashboard.get("model", {})
    return {
        "canonical": True,
        "generated_at": datetime.now().isoformat(),
        "task_id": "T04",
        "active_task": dashboard.get("active_task"),
        "training_config": {
            "integrated": bool(training_config.get("integrated", False)),
            "model_name": training_config.get("model_name"),
            "output_dir": output_dir,
        },
        "runtime": {
            "gpu_enabled": bool(config.get("gpu_enabled", False)),
            "spawn_state": config.get("spawn_loop", {}).get("state", "stopped"),
            "output_dir_exists": bool(output_path and output_path.exists()),
            "training_dir_exists": TRAINING_DIR.exists(),
            "models_dir_exists": MODELS_DIR.exists(),
            "data_dir_exists": DATA_DIR.exists(),
        },
        "artifacts": {
            "training_scripts": training_scripts,
            "dataset_files": dataset_artifacts,
            "model_files": model_artifacts,
            "counts": {
                "training_scripts": len(training_scripts),
                "dataset_files": len(dataset_artifacts),
                "model_files": len(model_artifacts),
            },
        },
        "queue": collect_training_queue_items(),
        "recent_logs": training_logs,
        "memory_progress": {
            "collected_tokens": memory_model.get("memory_collected_tokens", 0),
            "target_tokens": memory_model.get("memory_target_tokens", 0),
            "collection_percent": memory_model.get("collection_progress", 0),
            "minimum_tuning_tokens": memory_model.get("minimum_tuning_tokens", 0),
            "retrieval_lines": memory_model.get("retrieval_lines", 0),
        },
        "blockers": blockers,
    }


def build_dataset_payload():
    dashboard = build_dashboard_payload()
    queue = load_json(TASK_QUEUE_PATH, [])
    dataset_files = collect_recent_files(DATA_DIR, ["*.jsonl", "*.json", "*.csv"], limit=12)
    export_targets = {
        "jsonl_ready": any(item["path"].endswith(".jsonl") for item in dataset_files),
        "alpaca_ready": any(item["path"].endswith(".jsonl") for item in dataset_files),
        "sharegpt_ready": any(item["path"].endswith(".jsonl") for item in dataset_files),
        "steering_ready": any("steering" in item["name"].lower() or "decision" in item["name"].lower() for item in dataset_files),
    }
    dataset_queue = []
    if isinstance(queue, list):
        for item in queue:
            haystack = " ".join(str(item.get(key, "")) for key in ["id", "description", "goal"]).lower()
            if any(token in haystack for token in ["dataset", "trace", "export", "schema", "training data"]):
                dataset_queue.append(
                    {
                        "id": item.get("id"),
                        "priority": item.get("priority"),
                        "status": item.get("status", "pending"),
                        "description": item.get("description", ""),
                    }
                )
    model = dashboard.get("model", {})
    return {
        "canonical": True,
        "generated_at": datetime.now().isoformat(),
        "task_id": "T05",
        "counts": {
            "dataset_files": len(dataset_files),
            "retrieval_lines": int(model.get("retrieval_lines", 0) or 0),
            "training_traces": int(dashboard.get("summary", {}).get("training_traces", 0) or 0),
        },
        "files": dataset_files,
        "export_targets": export_targets,
        "queue": dataset_queue[:8],
        "paths": {
            "data_dir": rel_runtime_path(DATA_DIR),
            "retrieval_log": rel_runtime_path(RUNTIME_DIR / "retrieval_log.jsonl"),
        },
    }


def normalize_event_entries(events):
    normalized = []
    for index, entry in enumerate(events or [], start=1):
        normalized.append(
            {
                "id": f"event_{index:02d}",
                "title": "STRAY EVENT DETECTED" if index == 1 else f"EVENT {index:02d}",
                "text": str(entry),
            }
        )
    return normalized


def build_audit_events_payload():
    dashboard = build_dashboard_payload()
    return {
        "canonical": True,
        "generated_at": dashboard.get("generated_at"),
        "task_id": "T08",
        "count": len(dashboard.get("stray_events", [])),
        "events": normalize_event_entries(dashboard.get("stray_events", [])),
        "security_tail": tail_lines(SECURITY_AUDIT_LOG_PATH, 12),
        "orchestrator_tail": tail_lines(ORCHESTRATOR_LOG_PATH, 12),
    }


def build_stray_events_payload():
    dashboard = build_dashboard_payload()
    return {
        "canonical": True,
        "generated_at": dashboard.get("generated_at"),
        "task_id": "T10",
        "count": len(dashboard.get("stray_events", [])),
        "events": normalize_event_entries(dashboard.get("stray_events", [])),
        "active_task": dashboard.get("active_task"),
        "audit_tail": tail_lines(SECURITY_AUDIT_LOG_PATH, 12),
    }


def build_trace_capture_payload():
    dashboard = build_dashboard_payload()
    iterations_dir = ORCHESTRATOR_DIR / "iterations"
    return {
        "canonical": True,
        "generated_at": dashboard.get("generated_at"),
        "task_id": "T11",
        "entries": dashboard.get("trace_entries", []),
        "artifacts": collect_recent_files(iterations_dir, ["iter_*.json", "dec_*.json"], limit=10),
        "trace_count": len(dashboard.get("trace_entries", [])),
        "training_traces": dashboard.get("summary", {}).get("training_traces", 0),
    }


def build_steering_events_payload():
    dashboard = build_dashboard_payload()
    decisions_dir = ORCHESTRATOR_DIR / "iterations" / "decisions"
    events = dashboard.get("steering_events", [])
    return {
        "canonical": True,
        "generated_at": dashboard.get("generated_at"),
        "task_id": "T12",
        "count": len(events),
        "events": [
            {
                "id": f"steering_{index:02d}",
                "text": str(item),
            }
            for index, item in enumerate(events, start=1)
        ],
        "artifacts": collect_recent_files(decisions_dir, ["*.json"], limit=10),
    }


def collect_lock_files():
    if not LOCKS_DIR.exists():
        return []
    locks = []
    for path in sorted(LOCKS_DIR.rglob("*.lock")):
        if path.is_file():
            locks.append(
                {
                    "name": path.name,
                    "path": rel_runtime_path(path),
                    "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                    "content": read_text(path, "").strip(),
                }
            )
    return locks


def build_repo_freeze_payload():
    dashboard = build_dashboard_payload()
    repo_freeze = dashboard.get("repo_freeze", {})
    return {
        "canonical": True,
        "generated_at": dashboard.get("generated_at"),
        "task_id": "T09/T22",
        "mutex_held": bool(repo_freeze.get("mutex_held")),
        "lock_path": repo_freeze.get("lock_path"),
        "allowed_paths": repo_freeze.get("allowed_paths", []),
        "active_task": dashboard.get("active_task"),
        "lock_files": collect_lock_files(),
    }


def build_bootstrap_step_payload(step_id: str):
    steps = build_dashboard_payload().get("bootstrap_steps", [])
    step = next((item for item in steps if str(item.get("id")) == str(step_id)), None)
    return {
        "canonical": True,
        "generated_at": datetime.now().isoformat(),
        "task_id": "T13",
        "step": step,
    }


def build_repo_structure_payload(node_key: str):
    structure = build_dashboard_payload().get("repo_structure", {})
    group, _, item_key = node_key.partition(":")
    items = structure.get(group, []) if group in {"start", "stop"} else []
    item = next((entry for entry in items if entry.get("name") == item_key), None)
    return {
        "canonical": True,
        "generated_at": datetime.now().isoformat(),
        "task_id": "T14",
        "group": group,
        "item": item,
    }


def build_vector_phase_payload(phase_name: str):
    phases = build_dashboard_payload().get("vector_phases", [])
    item = next((phase for phase in phases if phase.get("name") == phase_name), None)
    return {
        "canonical": True,
        "generated_at": datetime.now().isoformat(),
        "task_id": "T15",
        "phase": item,
    }


def build_memory_file_payload(file_name: str):
    dashboard = build_dashboard_payload()
    item = next((entry for entry in dashboard.get("memory_files", []) if entry.get("name") == file_name), None)
    path_map = {
        "MEMORY.md": MEMORY_PATH,
        "TASK.md": RUNTIME_DIR / "TASK.md",
        "AGENTS.md": RUNTIME_DIR / "AGENTS.md",
        "retrieval_log.jsonl": RUNTIME_DIR / "retrieval_log.jsonl",
        "vector_store/": VECTOR_STORE_DIR,
    }
    source = path_map.get(file_name)
    preview = []
    if source and source.is_file():
        preview = tail_lines(source, 10)
    elif source and source.is_dir():
        preview = [entry["path"] for entry in collect_recent_files(source, ["*"], limit=10)]
    return {
        "canonical": True,
        "generated_at": datetime.now().isoformat(),
        "task_id": "T16",
        "item": item,
        "preview": preview,
    }


def load_dataset_records(limit=200):
    records = []
    for path in sorted(DATA_DIR.glob("*.jsonl")):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        records.append({"raw": line})
                    if len(records) >= limit:
                        return records
        except OSError:
            continue
    return records


def build_export_payload(export_format: str):
    records = load_dataset_records(limit=200)
    steering_records = []
    decisions_dir = ORCHESTRATOR_DIR / "iterations" / "decisions"
    if decisions_dir.exists():
        for path in sorted(decisions_dir.glob("*.json"))[:50]:
            payload = load_json(path, {})
            if payload:
                steering_records.append(payload)

    if export_format == "jsonl":
        preview = records[:12]
    elif export_format == "alpaca":
        preview = [
            {
                "instruction": item.get("summary") or item.get("type") or item.get("miss_type") or "repo event",
                "input": json.dumps(item.get("details", {}), default=str),
                "output": item.get("summary") or item.get("raw") or "",
            }
            for item in records[:12]
        ]
    elif export_format == "sharegpt":
        preview = [
            {
                "conversations": [
                    {"from": "human", "value": item.get("summary") or item.get("type") or "repo event"},
                    {"from": "gpt", "value": json.dumps(item.get("details", {}), default=str)},
                ]
            }
            for item in records[:12]
        ]
    else:
        preview = [
            {
                "decision_id": item.get("decision_id"),
                "question": item.get("decision", {}).get("question"),
                "chosen": item.get("decision", {}).get("chosen"),
                "lesson": item.get("outcome", {}).get("lesson"),
            }
            for item in steering_records[:12]
        ]

    return {
        "canonical": True,
        "generated_at": datetime.now().isoformat(),
        "format": export_format,
        "record_count": len(preview),
        "preview": preview,
    }


def build_model_status_payload():
    dashboard = build_dashboard_payload()
    return {
        "canonical": True,
        "generated_at": dashboard.get("generated_at"),
        "task_id": "T23",
        "model": dashboard.get("model", {}),
        "scale_analysis": dashboard.get("scale_analysis", {}),
        "readiness": dashboard.get("readiness", []),
        "verification": dashboard.get("verification", {}),
    }


def derive_tasks_from_graph():
    graph = load_json(DESIGN_GRAPH_PATH, {"nodes": [], "edges": []})
    nodes = graph.get("nodes", [])
    normalized = []

    for index, node in enumerate(nodes, start=1):
        display_status = node.get("display_status")
        if not display_status:
            if node.get("status") == "green":
                display_status = "completed"
            elif node.get("progress"):
                display_status = "active"
            else:
                display_status = "pending"

        task_id = node.get("task_id") or f"T{index:02d}"
        normalized.append(
            {
                "id": f"task_{index:03d}",
                "task_id": task_id,
                "dag_node_id": node.get("id"),
                "label": node.get("task_name") or node.get("label") or node.get("id"),
                "description": node.get("description", ""),
                "allowed_paths": node.get("allowed_paths", []),
                "dependencies": node.get("dependencies", []),
                "status": display_status,
                "priority": index,
                "progress": node.get("progress", 0),
            }
        )

    return normalized


def get_task_records():
    tasks = load_json(TASKS_PATH, [])
    if isinstance(tasks, list) and tasks:
        records = []
        for index, task in enumerate(tasks, start=1):
            records.append(
                {
                    "id": task.get("id", f"task_{index:03d}"),
                    "task_id": task.get("task_id", f"T{index:02d}"),
                    "dag_node_id": task.get("dag_node_id"),
                    "label": task.get("label") or task.get("task_name") or task.get("dag_node_id") or f"task-{index}",
                    "description": task.get("description", ""),
                    "allowed_paths": task.get("allowed_paths", []),
                    "dependencies": task.get("dependencies", []),
                    "status": task.get("status", "pending"),
                    "priority": task.get("priority", index),
                    "progress": task.get("progress", 0),
                }
            )
        return records

    return derive_tasks_from_graph()


def get_active_task(tasks):
    for task in tasks:
        if task.get("status") in {"active", "in_progress"}:
            return task
    for task in tasks:
        if task.get("status") == "pending":
            return task
    return tasks[0] if tasks else None


def get_dag_status():
    graph = load_json(DESIGN_GRAPH_PATH, {"nodes": []})
    nodes = graph.get("nodes", [])
    total = len(nodes)
    green = sum(1 for node in nodes if node.get("status") == "green")
    red = sum(1 for node in nodes if node.get("status") == "red")
    yellow = sum(1 for node in nodes if node.get("status") == "yellow")
    return {
        "total": total,
        "green": green,
        "red": red,
        "yellow": yellow,
        "progress": (green / total * 100) if total else 0,
    }


def get_task_status(tasks=None):
    tasks = tasks or get_task_records()
    total = len(tasks)
    pending = sum(1 for task in tasks if task.get("status") == "pending")
    in_progress = sum(1 for task in tasks if task.get("status") in {"active", "in_progress"})
    completed = sum(1 for task in tasks if task.get("status") in {"completed", "complete"})
    return {
        "total": total,
        "pending": pending,
        "in_progress": in_progress,
        "completed": completed,
    }


def get_recent_logs(limit=50):
    entries = []
    if LOGS_DIR.exists():
        log_files = sorted(
            [path for path in LOGS_DIR.rglob("*.log") if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for log_file in log_files[:5]:
            for line in tail_lines(log_file, max(1, limit // 5)):
                entries.append(
                    {
                        "source": str(log_file.relative_to(LOGS_DIR)),
                        "content": line,
                        "timestamp": datetime.fromtimestamp(log_file.stat().st_mtime).isoformat(),
                    }
                )
    return entries[:limit]


def get_repo_status():
    repos = []
    if REPOS_DIR.exists():
        for repo_dir in sorted(path for path in REPOS_DIR.iterdir() if path.is_dir()):
            repo_tasks = load_json(repo_dir / "SPAWN" / "STOP" / "state" / "tasks.json", [])
            repo_status = "idle"
            current_task = None
            if isinstance(repo_tasks, list):
                for task in repo_tasks:
                    if task.get("status") in {"active", "in_progress"}:
                        repo_status = "active"
                        current_task = task.get("label") or task.get("dag_node_id")
                        break

            repos.append(
                {
                    "name": repo_dir.name,
                    "status": repo_status,
                    "current_task": current_task,
                }
            )
    return repos


def get_security_events(limit=10):
    events = []
    for path in [SECURITY_AUDIT_LOG_PATH, ORCHESTRATOR_LOG_PATH]:
        for line in tail_lines(path, limit):
            lowered = line.lower()
            if any(token in lowered for token in ["stray", "blocked", "policy", "outside", "halt"]):
                events.append(line)
    return events[-limit:]


def build_trace_entries(tasks):
    graph = load_json(DESIGN_GRAPH_PATH, {"nodes": []})
    entries = []

    for line in tail_lines(ORCHESTRATOR_LOG_PATH, 8):
        entries.append({"type": "log", "text": line})

    for node in graph.get("nodes", []):
        status = node.get("display_status") or node.get("status", "pending")
        label = node.get("task_name") or node.get("label") or node.get("id")
        if status in {"active", "in_progress"}:
            entries.append({"type": "task", "text": f"task.started - {node.get('task_id', node.get('id'))} {label}"})
        elif status in {"complete", "completed"} or node.get("status") == "green":
            entries.append({"type": "task", "text": f"task.completed - {node.get('task_id', node.get('id'))} {label}"})

    if not entries:
        entries.append({"type": "loop", "text": "loop.idle - waiting for orchestrator activity"})

    return entries[-6:]


def get_metrics(tasks=None):
    config = load_json(CONFIG_PATH, {})
    dag_status = get_dag_status()
    task_status = get_task_status(tasks)

    vector_count = count_files(VECTOR_STORE_DIR)
    data_count = count_files(DATA_DIR)
    model_count = len(list(MODELS_DIR.rglob("*.pt"))) + len(list(MODELS_DIR.rglob("*.bin"))) + len(list(MODELS_DIR.rglob("*.safetensors")))
    repo_count = len([path for path in REPOS_DIR.iterdir() if path.is_dir()]) if REPOS_DIR.exists() else 0
    log_count = len([path for path in LOGS_DIR.rglob("*.log") if path.is_file()]) if LOGS_DIR.exists() else 0

    return {
        "cycles": config.get("cycle_count", 0),
        "dag_progress": dag_status,
        "task_status": task_status,
        "vector_store_entries": vector_count,
        "training_data_files": data_count,
        "model_checkpoints": model_count,
        "child_repos": repo_count,
        "log_files": log_count,
        "gpu_enabled": config.get("gpu_enabled", False),
        "timestamp": datetime.now().isoformat(),
        "model_name": config.get("training_config", {}).get("model_name", "Configured model"),
    }


def build_dashboard_payload():
    return sync_dashboard_state(RUNTIME_DIR)


LIVE_DASHBOARD_SCRIPT = r"""
<script>
(function () {
  const state = window.__ORCH_DASHBOARD_STATE__ || {};

  function qs(selector) { return document.querySelector(selector); }
  function qsa(selector) { return Array.from(document.querySelectorAll(selector)); }
  function ensureOperationalStyles() {
    if (document.getElementById('operational-panel-styles')) return;
    const style = document.createElement('style');
    style.id = 'operational-panel-styles';
    style.textContent = `
      .card-operational {
        border-color: rgba(34,197,94,0.22) !important;
        box-shadow: inset 0 0 24px rgba(34,197,94,0.04), 0 0 0 1px rgba(34,197,94,0.05);
        background: linear-gradient(135deg, rgba(34,197,94,0.05) 0%, rgba(255,255,255,0.028) 55%, rgba(34,197,94,0.02) 100%) !important;
      }
      .card-operational::before {
        background: linear-gradient(135deg, rgba(34,197,94,0.05) 0%, transparent 60%) !important;
      }
      .card-operational .panel-title,
      .card-operational .stat-meta {
        color: rgba(140,255,180,0.65) !important;
      }
      .card-operational .panel-icon,
      .card-operational .stat-delta {
        color: var(--green) !important;
      }
      .card-operational .model-name,
      .card-operational .eta-num,
      .card-operational .trace-box-val,
      .card-operational .coll-pct {
        color: var(--green) !important;
        text-shadow: 0 0 22px var(--green-glow) !important;
      }
      .card-operational .model-sub,
      .card-operational .eta-unit,
      .card-operational .eta-label,
      .card-operational .coll-row span,
      .card-operational .trace-box-label,
      .card-operational .memory-graph-caption {
        color: rgba(140,255,180,0.62) !important;
      }
      .card-operational .stat-val {
        text-shadow: 0 0 22px var(--green-glow) !important;
      }
      .card-operational .trace-box,
      .card-operational .storage-meter,
      .card-operational .memory-graph,
      .card-operational .steering-log-panel {
        border-color: rgba(34,197,94,0.24) !important;
        background: rgba(34,197,94,0.05) !important;
        box-shadow: inset 0 0 18px rgba(34,197,94,0.03);
      }
      .card-operational .prog-track {
        border-color: rgba(34,197,94,0.18) !important;
        background: rgba(34,197,94,0.05) !important;
      }
      .memory-graph {
        margin-top: 12px;
        border: 1px solid var(--border-dim);
        border-radius: 8px;
        background: rgba(34,197,94,0.04);
        padding: 10px 12px 8px;
      }
      .memory-graph-label {
        font-size: 8px;
        letter-spacing: 1.8px;
        color: rgba(140,255,180,0.62);
        margin-bottom: 8px;
      }
      .memory-graph svg {
        display: block;
        width: 100%;
        height: 86px;
      }
      .memory-graph-caption {
        margin-top: 7px;
        font-size: 8px;
        letter-spacing: 1.2px;
        color: var(--text-dim);
      }
      .storage-meter {
        margin-top: 10px;
        border: 1px solid var(--border-dim);
        border-radius: 8px;
        background: rgba(34,197,94,0.03);
        padding: 10px 12px;
      }
      .storage-meter-label {
        font-size: 8px;
        letter-spacing: 1.8px;
        color: rgba(140,255,180,0.62);
        margin-bottom: 6px;
      }
      .storage-meter-line {
        font-size: 9px;
        color: var(--text);
        line-height: 1.7;
      }
      .storage-meter-line strong {
        color: var(--green);
        font-weight: 700;
      }
      .stray-log {
        margin-top: 10px;
        max-height: 220px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding-right: 4px;
      }
      .stray-log::-webkit-scrollbar {
        width: 6px;
      }
      .stray-log::-webkit-scrollbar-thumb {
        background: rgba(255,107,32,0.28);
        border-radius: 999px;
      }
      .event-log {
        margin-top: 10px;
        max-height: 220px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding-right: 4px;
      }
      .event-log::-webkit-scrollbar {
        width: 6px;
      }
      .event-log::-webkit-scrollbar-thumb {
        background: rgba(34,197,94,0.25);
        border-radius: 999px;
      }
      .steering-log-panel {
        margin-top: 12px;
        border: 1px solid var(--border-dim);
        border-radius: 8px;
        background: rgba(34,197,94,0.04);
        padding: 10px 12px;
      }
      .steering-log-panel .panel-title-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 8px;
      }
      .steering-log-panel .panel-badge {
        position: static;
      }
      .steering-log-panel .steering-entry,
      .audit-log-panel .audit-entry {
        border: 1px solid var(--border-dim);
        border-radius: 8px;
        background: rgba(255,255,255,0.02);
        padding: 10px 12px;
      }
      .audit-log-panel {
        margin-top: 8px;
      }
      .trace-body {
        max-height: 260px;
        overflow-y: auto;
        padding-right: 4px;
      }
      .trace-body::-webkit-scrollbar {
        width: 6px;
      }
      .trace-body::-webkit-scrollbar-thumb {
        background: rgba(34,197,94,0.25);
        border-radius: 999px;
      }
      .scale-analysis-grid {
        display: grid;
        grid-template-columns: 1.1fr 0.9fr;
        gap: 12px;
      }
      .scale-analysis-col {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .scale-box {
        border: 1px solid var(--border-dim);
        border-radius: 8px;
        background: rgba(255,255,255,0.02);
        padding: 12px;
      }
      .scale-box-title {
        font-size: 8px;
        letter-spacing: 2px;
        color: rgba(140,255,180,0.62);
        margin-bottom: 8px;
      }
      .scale-kpi {
        font-family: var(--sans);
        font-size: 28px;
        color: var(--green);
        line-height: 1;
        letter-spacing: -1px;
        margin-bottom: 6px;
      }
      .scale-line {
        font-size: 9px;
        line-height: 1.7;
        color: var(--text);
      }
      .scale-line strong {
        color: var(--green);
      }
      .scale-list {
        max-height: 260px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding-right: 4px;
      }
      .scale-list::-webkit-scrollbar {
        width: 6px;
      }
      .scale-list::-webkit-scrollbar-thumb {
        background: rgba(34,197,94,0.25);
        border-radius: 999px;
      }
      .scale-item {
        border: 1px solid var(--border-dim);
        border-radius: 8px;
        background: rgba(255,255,255,0.02);
        padding: 10px 12px;
      }
      .scale-item-key {
        font-size: 8px;
        letter-spacing: 1.8px;
        color: rgba(140,255,180,0.62);
        margin-bottom: 5px;
      }
      .scale-item-val {
        font-size: 9px;
        line-height: 1.6;
        color: var(--text);
      }
      .task-map-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 2px 6px;
        border-radius: 999px;
        border: 1px solid rgba(255,32,32,0.28);
        background: rgba(255,32,32,0.08);
        color: var(--red);
        font-size: 8px;
        letter-spacing: 1.4px;
        line-height: 1;
        margin-left: 8px;
        white-space: nowrap;
      }
      .task-map-badge.nav-task-badge {
        margin-left: auto;
      }
    `;
    document.head.appendChild(style);
  }
  function setText(el, value) { if (el) el.textContent = value; }
  function textOr(value, fallback) {
    return value === null || value === undefined || value === '' ? fallback : value;
  }
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, function (char) {
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;', "'":'&#39;'})[char];
    });
  }
  function formatClock(dateString) {
    const date = dateString ? new Date(dateString) : new Date();
    return date.toLocaleTimeString([], {hour12:false});
  }
  function formatDate(dateString) {
    const date = dateString ? new Date(dateString) : new Date();
    return date.toLocaleDateString([], {month:'long', day:'numeric', year:'numeric'}).toUpperCase();
  }
  function taskStatusLabel(task) {
    const status = task.status || 'pending';
    if (status === 'completed' || status === 'complete') return 'COMPLETE';
    if (status === 'active' || status === 'in_progress') return 'ACTIVE';
    return 'PENDING';
  }
  function taskStatusClass(task) {
    const status = task.status || 'pending';
    if (status === 'completed' || status === 'complete') return 'status-complete';
    if (status === 'active' || status === 'in_progress') return 'status-active';
    return 'status-pending';
  }
  function taskRowClass(task) {
    const status = task.status || 'pending';
    if (status === 'completed' || status === 'complete') return 'dag-task complete';
    if (status === 'active' || status === 'in_progress') return 'dag-task active';
    return 'dag-task';
  }
  function traceTagClass(type) {
    if (type === 'task') return 't-task';
    if (type === 'mem') return 't-mem';
    if (type === 'model') return 't-model';
    return 't-loop';
  }
  function setOperational(el, live) {
    if (!el) return;
    el.classList.toggle('card-operational', !!live);
  }
  function compactNumber(value) {
    const num = Number(value || 0);
    if (num >= 1e12) return (num / 1e12).toFixed(2) + 'T';
    if (num >= 1e9) return (num / 1e9).toFixed(2) + 'B';
    if (num >= 1e6) return (num / 1e6).toFixed(2) + 'M';
    if (num >= 1e3) return (num / 1e3).toFixed(2) + 'K';
    return num.toLocaleString();
  }
  function formatStorageBytes(value) {
    const num = Number(value || 0);
    const gb = 1024 * 1024 * 1024;
    const mb = 1024 * 1024;
    if (num >= gb) return (num / gb).toFixed(2) + ' GB';
    if (num >= mb) return (num / mb).toFixed(2) + ' MB';
    if (num >= 1024) return (num / 1024).toFixed(2) + ' KB';
    return num.toFixed(0) + ' B';
  }
  function buildMemoryGraph(points) {
    const series = Array.isArray(points) ? points : [];
    if (!series.length) {
      return '<div class="memory-graph"><div class="memory-graph-label">LIVE MEMORY TOWARD GOAL</div><div class="memory-graph-caption">No repo-backed memory injections recorded yet.</div></div>';
    }

    const width = 560;
    const height = 86;
    const padding = 8;
    const maxCount = Math.max.apply(null, series.map(function (point) { return point.count || 0; })) || 1;
    const stepX = series.length === 1 ? 0 : (width - padding * 2) / (series.length - 1);
    const path = series.map(function (point, index) {
      const x = padding + (stepX * index);
      const y = height - padding - (((point.count || 0) / maxCount) * (height - padding * 2));
      return (index === 0 ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2);
    }).join(' ');
    const area = path + ' L ' + (padding + stepX * (series.length - 1)).toFixed(2) + ' ' + (height - padding) + ' L ' + padding + ' ' + (height - padding) + ' Z';
    const latest = series[series.length - 1];

    return ''
      + '<div class="memory-graph">'
      + '<div class="memory-graph-label">LIVE MEMORY TOWARD GOAL</div>'
      + '<svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" aria-hidden="true">'
      + '<path d="' + area + '" fill="rgba(34,197,94,0.10)"></path>'
      + '<path d="' + path + '" fill="none" stroke="rgba(34,197,94,0.95)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></path>'
      + '</svg>'
      + '<div class="memory-graph-caption">Latest injected memory unit: ' + escapeHtml(String(latest.count || 0)) + '</div>'
      + '</div>';
  }
  function buildStorageMeter(model) {
    return ''
      + '<div class="storage-meter">'
      + '<div class="storage-meter-label">DATASET SIZE TOWARD TUNING START</div>'
      + '<div class="storage-meter-line"><strong>' + escapeHtml(formatStorageBytes(model && model.memory_collected_bytes)) + '</strong> collected so far</div>'
      + '<div class="storage-meter-line"><strong>' + escapeHtml(formatStorageBytes(model && model.minimum_tuning_bytes)) + '</strong> needed to begin training/tuning</div>'
      + '<div class="storage-meter-line"><strong>' + escapeHtml(formatStorageBytes(model && model.memory_target_bytes)) + '</strong> full 24B goal corpus estimate</div>'
      + '</div>';
  }
  function buildSteeringLogPanel(data) {
    const steeringEvents = Array.isArray(data.steering_events) ? data.steering_events : [];
    const body = steeringEvents.length
      ? steeringEvents.map(function (entry, index) {
          return ''
            + '<div class="steering-entry">'
            + '<div class="steering-tags"><span class="stag stag-arch">LIVE</span><span class="stag stag-resolved">STATE</span><span class="stag">EVENT ' + escapeHtml(String(index + 1).padStart(2, '0')) + '</span></div>'
            + '<div class="steering-text">' + escapeHtml(entry) + '</div>'
            + '<div class="steering-note">Trace: NEXTAURA // ORCHESTRATOR · ' + escapeHtml(formatClock(data.generated_at)) + '</div>'
            + '</div>';
        }).join('')
      : '<div class="steering-entry"><div class="steering-text">No high-priority steering trace has been captured yet.</div></div>';

    return ''
      + '<div class="steering-log-panel">'
      + '<div class="panel-title-row"><div class="panel-title"><span class="panel-icon">...</span>STEERING EVENT LOG</div><div class="panel-badge">LIVE TRAINING SIGNAL</div></div>'
      + '<div class="event-log">' + body + '</div>'
      + '</div>';
  }
  function buildScaleItems(items) {
    return Object.keys(items || {}).map(function (key) {
      return ''
        + '<div class="scale-item">'
        + '<div class="scale-item-key">' + escapeHtml(key) + '</div>'
        + '<div class="scale-item-val">' + escapeHtml(items[key]) + '</div>'
        + '</div>';
    }).join('');
  }
  function renderScaleAnalysis(data) {
    const body = qs('.scale-analysis-body');
    if (!body) return;
    const analysis = data.scale_analysis || {};
    body.innerHTML = ''
      + '<div class="scale-analysis-grid">'
      + '<div class="scale-analysis-col">'
      + '<div class="scale-box">'
      + '<div class="scale-box-title">READINESS SNAPSHOT</div>'
      + '<div class="scale-kpi">' + escapeHtml(String((analysis.known_count || 0) + '/' + (analysis.questions_scanned || 0))) + '</div>'
      + '<div class="scale-line"><strong>Known:</strong> ' + escapeHtml(String(analysis.known_count || 0)) + ' · <strong>Partial:</strong> ' + escapeHtml(String(analysis.partial_count || 0)) + ' · <strong>Unknown:</strong> ' + escapeHtml(String(analysis.unknown_count || 0)) + '</div>'
      + '<div class="scale-line"><strong>Current collected:</strong> ' + escapeHtml(formatStorageBytes(analysis.current_collected_bytes)) + ' · ' + escapeHtml(compactNumber(analysis.current_collected_tokens || 0)) + ' tokens</div>'
      + '<div class="scale-line"><strong>Current JSONL files:</strong> ' + escapeHtml(String(analysis.current_jsonl_files || 0)) + ' · <strong>Decision files:</strong> ' + escapeHtml(String(analysis.current_decision_files || 0)) + '</div>'
      + '</div>'
      + '<div class="scale-box">'
      + '<div class="scale-box-title">MODEL SCALE DECISION</div>'
      + '<div class="scale-line"><strong>24B minimum tune start:</strong> ' + escapeHtml(formatStorageBytes(analysis.target_24b_minimum_tuning_bytes)) + '</div>'
      + '<div class="scale-line"><strong>24B full corpus:</strong> ' + escapeHtml(formatStorageBytes(analysis.target_24b_bytes)) + '</div>'
      + '<div class="scale-line"><strong>9B minimum tune start:</strong> ' + escapeHtml(formatStorageBytes(analysis.target_9b_minimum_tuning_bytes)) + '</div>'
      + '<div class="scale-line"><strong>9B full corpus:</strong> ' + escapeHtml(formatStorageBytes(analysis.target_9b_bytes)) + '</div>'
      + '<div class="scale-line"><strong>Fine-tune path ready:</strong> ' + escapeHtml(analysis.fine_tune_path_ready ? 'PARTIAL / DATA EXISTS' : 'NOT YET') + '</div>'
      + '<div class="scale-line"><strong>Train from scratch:</strong> ' + escapeHtml(analysis.can_train_from_scratch ? 'SUPPORTED' : 'NOT JUSTIFIED BY CURRENT REPO STATE') + '</div>'
      + '</div>'
      + '<div class="scale-box">'
      + '<div class="scale-box-title">RECOMMENDATION</div>'
      + '<div class="scale-line">' + escapeHtml(analysis.recommendation || 'No recommendation available.') + '</div>'
      + '</div>'
      + '</div>'
      + '<div class="scale-analysis-col">'
      + '<div class="scale-box">'
      + '<div class="scale-box-title">KNOWN / PARTIAL / UNKNOWN</div>'
      + '<div class="scale-list">'
      + buildScaleItems(analysis.known || {})
      + buildScaleItems(analysis.partial || {})
      + buildScaleItems(analysis.unknown || {})
      + '</div>'
      + '</div>'
      + '</div>'
      + '</div>';
    setOperational(body.closest('.card'), !!data.canonical);
  }
  function taskMapConfig() {
    return {
      nav: {
        'dag-view': 'T02',
        'spawn-loop': 'T03',
        'training-run': 'T04',
        'dataset': 'T05',
        'eta-tracker': 'T06',
        'scale-analysis': 'T07',
        'audit-log': 'T08',
        'repo-freeze': 'T09',
        'stray-monitor': 'T10',
        'trace-capture': 'T11',
        'steering-log': 'T12',
        'export': 'T17-T20',
        'orchestrator': 'T01'
      },
      panels: {
        'TASK DAG': 'T02',
        'MODEL STATUS': 'T23',
        'LLM AUDIT & SECURITY LOG': 'T08',
        'SPAWN LOOP': 'T03',
        'FINE-TUNE SCALE ANALYSIS': 'T07',
        'BOOTSTRAP ZONE': 'T13',
        'REPO STRUCTURE': 'T14',
        'VECTOR MEMORY': 'T15',
        'REPO FREEZE': 'T09',
        'TASK-SCOPED WRITE POLICY': 'T22',
        'STRAY MONITOR': 'T10',
        'TRACE CAPTURE': 'T11',
        'MEMORY FILES': 'T16',
        'EXPORT': 'T17-T20',
        'READINESS TRACKER': 'T21',
        'STEERING EVENT LOG': 'T12'
      },
      special: {
        repoLock: 'T22'
      },
      itemGroups: {
        bootStep: 'T13',
        repoZone: 'T14',
        vecPhase: 'T15',
        memFile: 'T16',
        readiness: 'T21'
      }
    };
  }
  function ensureTaskBadge(host, text, extraClass) {
    if (!host || !text) return;
    let badge = host.querySelector('.' + (extraClass || 'task-map-badge'));
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'task-map-badge' + (extraClass ? (' ' + extraClass) : '');
      host.appendChild(badge);
    }
    badge.textContent = text;
  }
  function renderTaskSurfaceMap() {
    const config = taskMapConfig();
    qsa('#sidebar .nav-item[data-nav]').forEach(function (item) {
      const key = item.getAttribute('data-nav');
      const value = config.nav[key];
      if (!value) return;
      ensureTaskBadge(item, value, 'nav-task-badge');
    });

    qsa('.panel-title').forEach(function (title) {
      const label = (title.textContent || '').trim();
      const value = config.panels[label];
      if (!value) return;
      ensureTaskBadge(title, value, 'panel-task-badge');
    });

    const repoLock = qs('.repo-lock-label');
    if (repoLock) ensureTaskBadge(repoLock, config.special.repoLock, 'panel-task-badge');
    qsa('.boot-step').forEach(function (el) { ensureTaskBadge(el, config.itemGroups.bootStep, 'panel-task-badge'); });
    qsa('.zone-box').forEach(function (el) { ensureTaskBadge(el.querySelector('.zone-title') || el, config.itemGroups.repoZone, 'panel-task-badge'); });
    qsa('.vec-phase').forEach(function (el) { ensureTaskBadge(el.querySelector('.vec-phase-name') || el, config.itemGroups.vecPhase, 'panel-task-badge'); });
    qsa('.mem-file').forEach(function (el) { ensureTaskBadge(el, config.itemGroups.memFile, 'panel-task-badge'); });
    qsa('.readiness-row').forEach(function (el) { ensureTaskBadge(el, config.itemGroups.readiness, 'panel-task-badge'); });
  }
  function handleNavPanel(panelKey) {
    const selected = panelKey || 'orchestrator';
    qsa('#sidebar .nav-item[data-nav]').forEach(function (item) {
      item.classList.toggle('active', item.getAttribute('data-nav') === selected);
    });
    qsa('#content [data-panel]').forEach(function (panel) {
      const keys = (panel.getAttribute('data-panel') || '').split(/\s+/).filter(Boolean);
      const visible = selected === 'orchestrator' || keys.includes('all') || keys.includes(selected);
      panel.style.display = visible ? '' : 'none';
    });
  }
  function bindNavPanels() {
    qsa('#sidebar .nav-item[data-nav]').forEach(function (item) {
      if (item.dataset.navBound === 'true') return;
      item.dataset.navBound = 'true';
      item.addEventListener('click', function () {
        handleNavPanel(item.getAttribute('data-nav'));
      });
    });
  }

  function renderTopBar(data) {
    const meta = qs('.tb-meta');
    if (meta) {
      meta.innerHTML = '<div>' + escapeHtml(formatDate(data.generated_at)) + '</div><div>' + escapeHtml(formatClock(data.generated_at)) + '</div>';
    }

    const pills = qsa('#topbar .pill');
    if (pills[0]) pills[0].innerHTML = '<div class="pill-dot"></div>' + escapeHtml((data.summary.dag_active || 0) + ' SPAWN ACTIVE');
    if (pills[1]) pills[1].innerHTML = '<div class="pill-dot"></div>' + escapeHtml((data.summary.stray_count || 0) + ' STRAY EVENT');

    const navBadges = qsa('#sidebar .nav-badge');
    if (navBadges[0]) setText(navBadges[0], String(data.metrics.task_status.total || 0));
    if (navBadges[1]) setText(navBadges[1], String(data.summary.stray_count || 0));

    const version = qs('.version-tag');
    if (version) setText(version, 'live');
  }

  function renderStatRow(data) {
    const cards = qsa('.stat-row .stat-card');
    if (cards.length < 4) return;
    setText(cards[0].querySelector('.stat-val'), String(data.summary.loops_executed || 0));
    setText(cards[0].querySelector('.stat-meta'), 'autonomous cycles');

    setText(cards[1].querySelector('.stat-val'), Number(data.summary.training_traces || 0).toLocaleString());
    setText(cards[1].querySelector('.stat-delta'), String((data.model && data.model.success_traces) || 0) + ' success · ' + String((data.model && data.model.steering_traces) || 0) + ' steering');

    setText(cards[2].querySelector('.stat-val'), String(data.summary.dag_total || 0));
    setText(cards[2].querySelector('.stat-meta'), String((data.summary.dag_pending || 0) + ' pending · ' + (data.summary.dag_active || 0) + ' active'));

    setText(cards[3].querySelector('.stat-val'), String(data.summary.stray_count || 0));
    setText(cards[3].querySelector('.stat-meta'), (data.summary.stray_count || 0) ? 'policy events detected' : 'no stray events logged');
    cards.forEach(function (card) { setOperational(card, !!data.canonical); });
  }

  function renderDagList(data) {
    const dagList = qs('.dag-list');
    if (!dagList) return;
    dagList.innerHTML = data.tasks.map(function (task) {
      const progress = (task.status === 'active' || task.status === 'in_progress') && task.progress
        ? '<div class="task-progress-wrap"><div class="task-progress-bar" style="width:' + escapeHtml(task.progress) + '%"></div></div>'
        : '';
      return ''
        + '<div class="' + taskRowClass(task) + '" data-dag-node="' + escapeHtml(task.task_id || task.id) + '">'
        + '<span class="task-id">' + escapeHtml(task.task_id || task.id) + '</span>'
        + '<span class="task-name">' + escapeHtml(task.label) + '</span>'
        + '<span class="task-status ' + taskStatusClass(task) + '">' + escapeHtml(taskStatusLabel(task)) + '</span>'
        + progress
        + '</div>';
    }).join('');
    setOperational(dagList.closest('.card'), Array.isArray(data.tasks) && data.tasks.length > 0);
  }

  function openDagTaskDetails(taskId) {
    fetch('/api/task/' + encodeURIComponent(taskId), {cache: 'no-store'})
      .then(function(response) {
        if (!response.ok) throw new Error('dag task request failed');
        return response.json();
      })
      .then(function(data) {
        renderDagTaskDetails(data);
        const modal = document.getElementById('task-drilldown-modal');
        if (modal) modal.style.display = 'flex';
      })
      .catch(function(error) {
        console.error('[dag] drilldown failed', error);
      });
  }

  function closeDagTaskDetails() {
    const modal = document.getElementById('task-drilldown-modal');
    if (modal) modal.style.display = 'none';
  }

  function openRepoDetailModal(title, summary, payload) {
    const modal = document.getElementById('repo-detail-modal');
    if (!modal) return;
    setText(document.getElementById('repo-detail-title'), title || 'Repo Detail');
    setText(document.getElementById('repo-detail-summary'), summary || 'No detail available.');
    const payloadEl = document.getElementById('repo-detail-payload');
    if (payloadEl) {
      payloadEl.innerHTML = Object.keys(payload || {}).map(function(key) {
        const value = payload[key];
        const rendered = Array.isArray(value)
          ? value.map(function(item) { return '<code>' + escapeHtml(typeof item === 'string' ? item : JSON.stringify(item)) + '</code>'; }).join('')
          : '<code>' + escapeHtml(typeof value === 'string' ? value : JSON.stringify(value)) + '</code>';
        return '<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:8px;"><strong>' + escapeHtml(key) + '</strong>' + rendered + '</div>';
      }).join('') || '<span style="color:var(--text-ghost);">No payload data.</span>';
    }
    modal.style.display = 'flex';
  }

  function closeRepoDetailModal() {
    const modal = document.getElementById('repo-detail-modal');
    if (modal) modal.style.display = 'none';
  }

  function bindRepoDetailModal() {
    const modal = document.getElementById('repo-detail-modal');
    if (!modal || modal.dataset.bound === 'true') return;
    modal.dataset.bound = 'true';
    const closeBtn = document.getElementById('repo-detail-close');
    if (closeBtn) closeBtn.addEventListener('click', closeRepoDetailModal);
    modal.addEventListener('click', function (event) {
      if (event.target === modal) closeRepoDetailModal();
    });
  }

  function fetchRepoDetail(url, title, summaryBuilder, payloadBuilder) {
    fetch(url, {cache: 'no-store'})
      .then(function(response) {
        if (!response.ok) throw new Error('detail request failed');
        return response.json();
      })
      .then(function(data) {
        openRepoDetailModal(title, summaryBuilder(data), payloadBuilder(data));
      })
      .catch(function(error) {
        console.error('[detail] request failed', error);
      });
  }

  function openBootstrapStep(stepId) {
    fetchRepoDetail('/api/bootstrap/steps/' + encodeURIComponent(stepId), 'Bootstrap Step ' + stepId, function(data) {
      const step = data.step || {};
      return textOr(step.name, 'Unknown bootstrap step') + ' · ' + textOr(step.status, 'missing');
    }, function(data) {
      return data.step || {};
    });
  }

  function openRepoStructureNode(nodeKey) {
    fetchRepoDetail('/api/repo-structure/' + encodeURIComponent(nodeKey), 'Repo Structure', function(data) {
      const item = data.item || {};
      return textOr(item.name, nodeKey) + ' · ' + textOr(item.detail, 'no detail');
    }, function(data) {
      return data.item || {group: data.group};
    });
  }

  function openVectorPhase(phaseName) {
    fetchRepoDetail('/api/vector-phases/' + encodeURIComponent(phaseName), phaseName, function(data) {
      const phase = data.phase || {};
      return textOr(phase.detail, 'No phase detail available.');
    }, function(data) {
      return data.phase || {};
    });
  }

  function openMemoryFile(fileName) {
    fetchRepoDetail('/api/memory-files/' + encodeURIComponent(fileName), fileName, function(data) {
      const item = data.item || {};
      return textOr(item.size, 'No size metadata available.');
    }, function(data) {
      return {item: data.item || {}, preview: data.preview || []};
    });
  }

  function openMutexLockDetails() {
    fetchRepoDetail('/api/repo-freeze/state', 'Mutex Lock State', function(data) {
      return data.mutex_held ? 'A lock is currently gating writes.' : 'No lock is currently held.';
    }, function(data) {
      return {
        active_task: data.active_task || {},
        lock_files: data.lock_files || [],
        allowed_paths: data.allowed_paths || []
      };
    });
  }

  function openExportPreview(format) {
    fetchRepoDetail('/api/export/' + encodeURIComponent(format), 'Export ' + format.toUpperCase(), function(data) {
      return 'Repo-backed preview with ' + String(data.record_count || 0) + ' records.';
    }, function(data) {
      return {preview: data.preview || []};
    });
  }

  function renderDagTaskDetails(data) {
    const node = data.node || {};
    const taskRecord = data.task_record || {};
    const status = node.status || taskRecord.status || 'pending';
    const statusEl = document.querySelector('.task-detail-status');
    const verifiedEl = document.querySelector('.task-detail-verified');
    const descriptionEl = document.querySelector('.task-detail-description');
    const dependenciesEl = document.querySelector('.task-detail-dependencies');
    const dependentsEl = document.querySelector('.task-detail-dependents');
    const allowedPathsEl = document.querySelector('.task-detail-allowed-paths');
    const verificationEl = document.querySelector('.task-detail-verification');

    setText(document.querySelector('.task-drilldown-id'), data.task_id || 'UNKNOWN');
    setText(document.querySelector('.task-drilldown-label'), node.label || taskRecord.label || 'Unknown Task');
    if (descriptionEl) descriptionEl.textContent = node.description || taskRecord.description || 'No description available.';

    if (statusEl) {
      statusEl.className = 'task-detail-status status-badge ' + status;
      statusEl.textContent = status;
    }
    if (verifiedEl) {
      const verified = !!(node.verified_live || (data.verification && data.verification.verified_live));
      verifiedEl.textContent = verified ? 'VERIFIED LIVE' : 'NOT VERIFIED';
      verifiedEl.className = 'task-detail-verified' + (verified ? ' verified' : '');
    }
    if (dependenciesEl) {
      dependenciesEl.innerHTML = (data.dependencies || []).length
        ? data.dependencies.map(function(dep) { return '<code>' + escapeHtml(dep) + '</code>'; }).join('')
        : '<span style="color:var(--text-ghost);">None</span>';
    }
    if (dependentsEl) {
      dependentsEl.innerHTML = (data.dependents || []).length
        ? data.dependents.map(function(dep) { return '<code>' + escapeHtml(dep) + '</code>'; }).join('')
        : '<span style="color:var(--text-ghost);">None</span>';
    }
    if (allowedPathsEl) {
      allowedPathsEl.innerHTML = (data.allowed_paths || []).length
        ? data.allowed_paths.map(function(path) { return '<code>' + escapeHtml(path) + '</code>'; }).join('')
        : '<span style="color:var(--text-ghost);">No restrictions</span>';
    }
    if (verificationEl) {
      verificationEl.textContent = (data.verification && data.verification.verification_reason) || node.verification_reason || 'No verification data available.';
    }
  }

  function bindDagTaskDetails() {
    qsa('.dag-task[data-dag-node]').forEach(function (item) {
      if (item.dataset.dagBound === 'true') return;
      item.dataset.dagBound = 'true';
      item.addEventListener('click', function () {
        openDagTaskDetails(item.getAttribute('data-dag-node'));
      });
    });

    const modal = document.getElementById('task-drilldown-modal');
    if (!modal || modal.dataset.dagModalBound === 'true') return;
    modal.dataset.dagModalBound = 'true';
    const closeBtn = modal.querySelector('.task-drilldown-close');
    if (closeBtn) closeBtn.addEventListener('click', closeDagTaskDetails);
    modal.addEventListener('click', function (event) {
      if (event.target === modal) closeDagTaskDetails();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && modal.style.display !== 'none') closeDagTaskDetails();
    });
  }

  function bindBootstrapStepDetails() {
    qsa('[data-boot-step]').forEach(function(item) {
      if (item.dataset.bootBound === 'true') return;
      item.dataset.bootBound = 'true';
      item.addEventListener('click', function() {
        openBootstrapStep(item.getAttribute('data-boot-step'));
      });
    });
  }

  function bindRepoStructureDetails() {
    qsa('[data-structure-node]').forEach(function(item) {
      if (item.dataset.structureBound === 'true') return;
      item.dataset.structureBound = 'true';
      item.addEventListener('click', function() {
        openRepoStructureNode(item.getAttribute('data-structure-node'));
      });
    });
  }

  function bindVectorPhaseDetails() {
    qsa('[data-vec-phase]').forEach(function(item) {
      if (item.dataset.vecBound === 'true') return;
      item.dataset.vecBound = 'true';
      item.addEventListener('click', function() {
        openVectorPhase(item.getAttribute('data-vec-phase'));
      });
    });
  }

  function bindMemoryFileDetails() {
    qsa('[data-memory-file]').forEach(function(item) {
      if (item.dataset.memBound === 'true') return;
      item.dataset.memBound = 'true';
      item.addEventListener('click', function() {
        openMemoryFile(item.getAttribute('data-memory-file'));
      });
    });
  }

  function bindExportButtons() {
    qsa('[data-export-format]').forEach(function(item) {
      if (item.dataset.exportBound === 'true') return;
      item.dataset.exportBound = 'true';
      item.addEventListener('click', function() {
        openExportPreview(item.getAttribute('data-export-format'));
      });
    });
  }

  function renderModelPanel(data) {
    const modelCard = qs('.model-name') ? qs('.model-name').closest('.card') : null;
    setText(qs('.model-name'), textOr(data.model.name, '0.0000% OF 24B GOAL DATA COLLECTED'));
    setText(qs('.model-sub'), textOr(data.model.sub, 'LIVE MEMORY INJECTION TOWARD 24B CODING MODEL TARGET'));
    setText(qs('.eta-num'), compactNumber((data.model && data.model.memory_collected_tokens) || 0));
    setText(qs('.eta-unit'), 'TOKENS');
    setText(qs('.eta-label'), 'REPO-BACKED TOKENS COLLECTED TOWARD 24B MODEL DATA TARGET');
    setText(qs('.coll-pct'), String(Number(data.model.collection_progress || 0).toFixed(1) + '%'));

    const progressFill = qs('.prog-fill');
    if (progressFill) progressFill.style.width = (data.model.collection_progress || 0) + '%';

    const collRow = qs('.coll-row');
    if (collRow) {
      const spans = collRow.querySelectorAll('span');
      if (spans[0]) spans[0].textContent = 'MODEL DATA COLLECTION';
    }

    const traceVals = qsa('.trace-box-val');
    const traceLabels = qsa('.trace-box-label');
    if (traceLabels[0]) setText(traceLabels[0], 'COLLECTED TOKENS');
    if (traceLabels[1]) setText(traceLabels[1], 'TARGET TOKENS');
    if (traceVals[0]) setText(traceVals[0], compactNumber((data.model && data.model.memory_collected_tokens) || 0));
    if (traceVals[1]) setText(traceVals[1], compactNumber((data.model && data.model.memory_target_tokens) || 0));

    const traceSplit = qs('.trace-split');
    if (traceSplit) {
      let graph = qs('.memory-graph');
      if (graph) graph.remove();
      let storageMeter = qs('.storage-meter');
      if (storageMeter) storageMeter.remove();
      let steeringPanel = qs('.steering-log-panel');
      if (steeringPanel) steeringPanel.remove();
      traceSplit.insertAdjacentHTML('afterend', buildMemoryGraph(data.model && data.model.memory_graph));
      qs('.memory-graph').insertAdjacentHTML('afterend', buildStorageMeter(data.model || {}));
      qs('.storage-meter').insertAdjacentHTML('afterend', buildSteeringLogPanel(data));
    }

    setOperational(modelCard, !!(data.canonical && data.model));
  }

  async function renderAuditPanels(data) {
    const auditBody = qs('.audit-body');
    try {
      const response = await fetch('/api/audit/events', {cache: 'no-store'});
      if (!response.ok) throw new Error('audit events request failed');
      const detail = await response.json();
      if (auditBody) {
        const events = Array.isArray(detail.events) ? detail.events : [];
        const body = events.length
          ? events.map(function (event) {
              return ''
                + '<div class="audit-entry">'
                + '<div class="stray-hdr"><span class="stray-icon">!</span> ' + escapeHtml(event.title || 'AUDIT EVENT') + '</div>'
                + '<div class="stray-body">' + escapeHtml(event.text || '') + '</div>'
                + '</div>';
            }).join('')
          : '<div class="audit-entry"><div class="stray-hdr"><span class="stray-icon">!</span> AUDIT LOG CLEAR</div><div class="stray-body">No stray writes detected in recent security logs.</div></div>';
        auditBody.innerHTML = '<div class="audit-log-panel"><div class="event-log">' + body + '</div></div>';
      }
      setOperational(auditBody ? auditBody.closest('.card') : null, !!detail.canonical);
    } catch (error) {
      console.error('[audit] render failed', error);
    }

    const warnBadge = qs('.panel-badge.warn');
    if (warnBadge) setText(warnBadge, String((data.summary.stray_count || 0) + ' ALERT'));
  }

  function renderSpawnPanel(data) {
    const spawnLoop = data.spawn_loop || { state: 'stopped', active_spawns: 0 };
    const activeTask = data.active_task || {};
    
    // Update spawn loop state display
    const stateBadge = qs('#spawn-loop-badge');
    const activeCount = qs('#spawn-active-count');
    const loopState = qs('#spawn-loop-state');
    const pulseIndicator = qs('#spawn-pulse-indicator');
    const labelText = qs('#spawn-label-text');
    const currentTask = qs('#spawn-current-task');
    const progress = qs('#spawn-progress');
    
    if (stateBadge) {
      stateBadge.textContent = spawnLoop.state.toUpperCase();
      stateBadge.style.color = spawnLoop.state === 'running' ? 'var(--green)' : (spawnLoop.state === 'paused' ? 'var(--amber)' : 'var(--text-dim)');
      stateBadge.style.borderColor = spawnLoop.state === 'running' ? 'var(--green)' : (spawnLoop.state === 'paused' ? 'var(--amber)' : 'var(--border)');
    }
    if (activeCount) setText(activeCount, String(spawnLoop.active_spawns || 0));
    if (loopState) setText(loopState, spawnLoop.state.toUpperCase());
    if (pulseIndicator) {
      pulseIndicator.style.display = spawnLoop.state === 'running' ? 'block' : 'none';
    }
    if (labelText) setText(labelText, spawnLoop.state === 'running' ? 'SPAWN ACTIVE' : 'SPAWN IDLE');
    if (currentTask) setText(currentTask, (activeTask.task_id || '--') + ' -> ' + (activeTask.label || 'waiting'));
    if (progress) setText(progress, activeTask.progress === null || activeTask.progress === undefined ? '--' : String(activeTask.progress) + '%');
    
    setOperational(qs('.spawn-body') ? qs('.spawn-body').closest('.card') : null, !!data.canonical);
  }

  function renderPolicyAndStray(data) {
    const policyVals = qsa('.policy-body .policy-val');
    const activeTask = data.active_task || {};
    if (policyVals[0]) {
      const allowed = (activeTask.allowed_paths || []).map(function (path) {
        return '<code>' + escapeHtml(path) + '</code>';
      }).join(' ') || '<code>waiting for task assignment</code>';
      policyVals[0].innerHTML = allowed;
    }
    if (policyVals[1]) setText(policyVals[1], 'All paths not in TASK.md frontmatter');
    if (policyVals[2]) policyVals[2].innerHTML = '<code>enforce_policy()</code> in loop.py';
    if (policyVals[3]) setText(policyVals[3], 'Flag -> audit log -> steering trace -> HALT');

    const strayNum = qs('.stray-num');
    if (strayNum) setText(strayNum, String(data.summary.stray_count || 0));
    const strayMeta = qs('.stray-meta');
    if (strayMeta) {
      const stamp = formatClock(data.generated_at);
      strayMeta.innerHTML = 'LIVE EVENTS<br/>LAST CHECK<br/>' + escapeHtml(stamp);
    }
    const strayTime = qs('.stray-event-time');
    if (strayTime) setText(strayTime, formatClock(data.generated_at) + ' · LIVE');
    const strayDesc = qs('.stray-event-desc');
    if (strayDesc) setText(strayDesc, data.stray_events[0] || 'No stray write attempts were found in the latest security scan.');
    setOperational(qs('.stray-mon-body') ? qs('.stray-mon-body').closest('.card') : null, !!data.canonical);
  }

  async function renderRepoFreeze() {
    try {
      const response = await fetch('/api/repo-freeze/state', {cache: 'no-store'});
      if (!response.ok) throw new Error('repo freeze request failed');
      const data = await response.json();
      const mutexBadge = qs('.repo-lock .mutex-badge');
      const freezeLabel = qs('.freeze-label');
      const freezeNote = qs('.freeze-note');
      const toggle = qs('.toggle-wrap');
      const toggleThumb = qs('.toggle-thumb');
      const held = !!data.mutex_held;

      if (mutexBadge) mutexBadge.innerHTML = '<div class="mutex-dot"></div>' + (held ? 'MUTEX HELD' : 'MUTEX OPEN');
      const badgeDot = qs('.repo-lock .mutex-dot');
      if (badgeDot) {
        badgeDot.style.background = held ? 'var(--red)' : 'var(--green)';
        badgeDot.style.boxShadow = held ? '0 0 8px var(--red-glow)' : '0 0 8px var(--green-glow)';
      }
      if (freezeLabel) freezeLabel.textContent = held ? 'WRITE LOCK ACTIVE' : 'WRITE LOCK OPEN';
      if (freezeNote) {
        freezeNote.textContent = held
          ? 'Mutex held. All writes are currently gated by the active task scope.'
          : 'No active lock is held. Writes should only occur after the next task lock is acquired.';
      }
      if (toggle) {
        toggle.style.background = held ? 'var(--red)' : 'rgba(34,197,94,0.25)';
        toggle.style.borderColor = held ? 'var(--border)' : 'rgba(34,197,94,0.35)';
      }
      if (toggleThumb) {
        toggleThumb.style.left = held ? '24px' : '2px';
        toggleThumb.style.background = held ? 'var(--red)' : 'var(--green)';
        toggleThumb.style.boxShadow = held ? '0 0 8px var(--red-glow)' : '0 0 8px var(--green-glow)';
      }
      setOperational(qs('[data-control="repo-freeze"]'), !!data.canonical);
    } catch (error) {
      console.error('[repo-freeze] render failed', error);
    }
  }

  function bindRepoFreezeControls() {
    qsa('[data-control="repo-freeze"]').forEach(function(item) {
      if (item.dataset.repoFreezeBound === 'true') return;
      item.dataset.repoFreezeBound = 'true';
      item.addEventListener('click', function(event) {
        if (event.target.closest('.repo-lock')) {
          openMutexLockDetails();
          return;
        }
        if (!event.target.closest('[data-freeze-action="toggle"]')) return;
        fetch('/api/control/repo-freeze', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({action: 'toggle'})
        })
          .then(function(response) { return response.json(); })
          .then(function() {
            refreshFromServer();
          })
          .catch(function(error) {
            console.error('[repo-freeze] toggle failed', error);
          });
      });
    });

    const repoLock = qs('.repo-lock');
    if (repoLock && repoLock.dataset.repoLockBound !== 'true') {
      repoLock.dataset.repoLockBound = 'true';
      repoLock.addEventListener('click', openMutexLockDetails);
    }
  }

  async function renderStrayLog(data) {
    const strayMonBody = qs('.stray-mon-body');
    if (!strayMonBody) return;
    const header = strayMonBody.querySelector('.stray-stat-row');
    try {
      const response = await fetch('/api/stray/events', {cache: 'no-store'});
      if (!response.ok) throw new Error('stray events request failed');
      const detail = await response.json();
      const strayEvents = Array.isArray(detail.events) ? detail.events : [];
      const logHtml = strayEvents.length
        ? strayEvents.map(function (event) {
            return ''
              + '<div class="stray-event-item">'
              + '<div class="stray-event-time">' + escapeHtml(event.title || 'LIVE') + '</div>'
              + '<div class="stray-event-desc">' + escapeHtml(event.text || '') + '</div>'
              + '</div>';
          }).join('')
        : '<div class="stray-event-item"><div class="stray-event-time">LIVE</div><div class="stray-event-desc">No stray write attempts were found in the latest security scan.</div></div>';

      strayMonBody.innerHTML = ''
        + (header ? header.outerHTML : '')
        + '<div class="stray-log">' + logHtml + '</div>';
      setOperational(strayMonBody.closest('.card'), !!detail.canonical);
    } catch (error) {
      console.error('[stray] render failed', error);
    }
  }

  async function renderTraceCapture(data) {
    const traceBody = qs('.trace-body');
    if (!traceBody) return;
    try {
      const response = await fetch('/api/traces', {cache: 'no-store'});
      if (!response.ok) throw new Error('trace capture request failed');
      const detail = await response.json();
      const entries = Array.isArray(detail.entries) ? detail.entries : [];
      traceBody.innerHTML = entries.map(function (entry) {
        return ''
          + '<div class="trace-entry">'
          + '<span class="trace-time">' + escapeHtml(textOr(entry.timestamp, formatClock(data.generated_at))) + '</span>'
          + '<span class="trace-event">' + escapeHtml(entry.text) + '</span>'
          + '<span class="trace-tag ' + traceTagClass(entry.type) + '">' + escapeHtml((entry.type || 'loop').toUpperCase()) + '</span>'
          + '</div>';
      }).join('');

      const tracePanelBadge = qsa('.bento3 .panel-badge');
      if (tracePanelBadge[0]) setText(tracePanelBadge[0], '+' + String(detail.training_traces || 0) + ' canonical');
      setOperational(traceBody.closest('.card'), !!detail.canonical);
    } catch (error) {
      console.error('[trace] render failed', error);
    }
  }

  function renderMemoryFiles(data) {
    const container = qs('.mem-files');
    if (!container) return;
    container.innerHTML = data.memory_files.map(function (item) {
      return ''
        + '<div class="mem-file" data-memory-file="' + escapeHtml(item.name) + '">'
        + '<span class="mem-file-icon">[]</span>'
        + '<span class="mem-file-name">' + escapeHtml(item.name) + '</span>'
        + '<span class="mem-file-size">' + escapeHtml(item.size) + '</span>'
        + '</div>';
    }).join('');
  }

  async function renderTrainingRunDetails() {
    const root = qs('[data-training-run-root]');
    try {
      const response = await fetch('/api/training/run', {cache: 'no-store'});
      if (!response.ok) throw new Error('training run request failed');
      const detail = await response.json();
      const summary = root ? root.querySelector('[data-training-summary]') : null;
      const artifacts = root ? root.querySelector('[data-training-artifacts]') : null;
      const queue = root ? root.querySelector('[data-training-queue]') : null;
      const logs = root ? root.querySelector('[data-training-logs]') : null;
      const blockers = root ? root.querySelector('[data-training-blockers]') : null;
      const inlineBadge = qs('[data-training-inline-badge]');
      const inlineSummary = qs('[data-training-inline-summary]');
      const inlineBlockers = qs('[data-training-inline-blockers]');

      if (inlineBadge) {
        const statusText = detail.training_config && detail.training_config.integrated ? 'training integrated' : 'training run live';
        inlineBadge.textContent = statusText;
      }

      if (inlineSummary) {
        inlineSummary.innerHTML = ''
          + '<div class="trace-box"><div class="trace-box-label">CONFIG</div><div class="trace-box-val" style="font-size:18px;">' + escapeHtml(detail.training_config && detail.training_config.integrated ? 'LIVE' : 'PENDING') + '</div></div>'
          + '<div class="trace-box"><div class="trace-box-label">DATA FILES</div><div class="trace-box-val" style="font-size:18px;">' + escapeHtml(String(detail.artifacts && detail.artifacts.counts && detail.artifacts.counts.dataset_files || 0)) + '</div></div>'
          + '<div class="trace-box"><div class="trace-box-label">MODEL FILES</div><div class="trace-box-val" style="font-size:18px;">' + escapeHtml(String(detail.artifacts && detail.artifacts.counts && detail.artifacts.counts.model_files || 0)) + '</div></div>';
      }

      if (inlineBlockers) {
        const items = Array.isArray(detail.blockers) ? detail.blockers : [];
        inlineBlockers.innerHTML = items.length ? items.slice(0, 3).map(function(item) {
          return '<div class="training-run-blocker">' + escapeHtml(item) + '</div>';
        }).join('') : '<div class="training-run-empty">No current blockers detected from repo state.</div>';
      }

      if (summary) {
        summary.innerHTML = ''
          + '<div class="training-run-kv"><span>CONFIG</span><strong>' + escapeHtml(detail.training_config && detail.training_config.integrated ? 'INTEGRATED' : 'PENDING') + '</strong></div>'
          + '<div class="training-run-kv"><span>GPU</span><strong>' + escapeHtml(detail.runtime && detail.runtime.gpu_enabled ? 'ENABLED' : 'DISABLED') + '</strong></div>'
          + '<div class="training-run-kv"><span>SPAWN LOOP</span><strong>' + escapeHtml(textOr(detail.runtime && detail.runtime.spawn_state, 'stopped').toUpperCase()) + '</strong></div>'
          + '<div class="training-run-kv"><span>TOKENS</span><strong>' + escapeHtml(compactNumber(detail.memory_progress && detail.memory_progress.collected_tokens || 0)) + ' / ' + escapeHtml(compactNumber(detail.memory_progress && detail.memory_progress.target_tokens || 0)) + '</strong></div>'
          + '<div class="training-run-kv"><span>RETRIEVAL LINES</span><strong>' + escapeHtml(compactNumber(detail.memory_progress && detail.memory_progress.retrieval_lines || 0)) + '</strong></div>'
          + '<div class="training-run-kv"><span>OUTPUT DIR</span><strong>' + escapeHtml(detail.runtime && detail.runtime.output_dir_exists ? 'PRESENT' : 'MISSING') + '</strong></div>';
      }

      if (artifacts) {
        const groups = [
          { label: 'Scripts', items: detail.artifacts && detail.artifacts.training_scripts },
          { label: 'Datasets', items: detail.artifacts && detail.artifacts.dataset_files },
          { label: 'Models', items: detail.artifacts && detail.artifacts.model_files }
        ];
        artifacts.innerHTML = groups.map(function(group) {
          const items = Array.isArray(group.items) ? group.items : [];
          const body = items.length ? items.map(function(item) {
            return '<div class="training-run-item"><span>' + escapeHtml(item.path) + '</span><strong>' + escapeHtml(item.size) + '</strong></div>';
          }).join('') : '<div class="training-run-empty">No repo-backed artifacts found.</div>';
          return '<div class="training-run-group"><div class="training-run-group-title">' + escapeHtml(group.label) + '</div>' + body + '</div>';
        }).join('');
      }

      if (queue) {
        const items = Array.isArray(detail.queue) ? detail.queue : [];
        queue.innerHTML = items.length ? items.map(function(item) {
          return '<div class="training-run-item"><span>' + escapeHtml((item.id || 'queue-item') + ' · ' + (item.status || 'pending')) + '</span><strong>' + escapeHtml('P' + String(item.priority || '--')) + '</strong></div><div class="training-run-subitem">' + escapeHtml(textOr(item.description, '')) + '</div>';
        }).join('') : '<div class="training-run-empty">No queued training-adjacent tasks found.</div>';
      }

      if (logs) {
        const items = Array.isArray(detail.recent_logs) ? detail.recent_logs : [];
        logs.innerHTML = items.length ? items.map(function(item) {
          return '<div class="training-run-group"><div class="training-run-group-title">' + escapeHtml(item.path) + '</div><pre class="training-run-log">' + escapeHtml((item.tail || []).join('\n')) + '</pre></div>';
        }).join('') : '<div class="training-run-empty">No training-related log files found.</div>';
      }

      if (blockers) {
        const items = Array.isArray(detail.blockers) ? detail.blockers : [];
        blockers.innerHTML = items.length ? items.map(function(item) {
          return '<div class="training-run-blocker">' + escapeHtml(item) + '</div>';
        }).join('') : '<div class="training-run-empty">No current blockers detected from repo state.</div>';
      }

      if (root) setOperational(root.closest('.card'), !!detail.canonical);
      const modelCard = qs('.model-name') ? qs('.model-name').closest('.card') : null;
      setOperational(modelCard, !!detail.canonical);
    } catch (error) {
      console.error('[training-run] render failed', error);
    }
  }

  async function renderDatasetDetails() {
    const root = qs('[data-dataset-root]');
    if (!root) return;
    try {
      const response = await fetch('/api/dataset/details', {cache: 'no-store'});
      if (!response.ok) throw new Error('dataset details request failed');
      const detail = await response.json();
      const summary = root.querySelector('[data-dataset-summary]');
      const files = root.querySelector('[data-dataset-files]');
      const queue = root.querySelector('[data-dataset-queue]');
      const exports = root.querySelector('[data-dataset-exports]');

      if (summary) {
        summary.innerHTML = ''
          + '<div class="trace-box"><div class="trace-box-label">DATASET FILES</div><div class="trace-box-val" style="font-size:18px;">' + escapeHtml(String(detail.counts && detail.counts.dataset_files || 0)) + '</div></div>'
          + '<div class="trace-box"><div class="trace-box-label">RETRIEVAL LINES</div><div class="trace-box-val" style="font-size:18px;">' + escapeHtml(String(detail.counts && detail.counts.retrieval_lines || 0)) + '</div></div>'
          + '<div class="trace-box"><div class="trace-box-label">TRAINING TRACES</div><div class="trace-box-val" style="font-size:18px;">' + escapeHtml(String(detail.counts && detail.counts.training_traces || 0)) + '</div></div>';
      }
      if (files) {
        const items = Array.isArray(detail.files) ? detail.files : [];
        files.innerHTML = items.length ? items.map(function(item) {
          return '<div class="training-run-item"><span>' + escapeHtml(item.path) + '</span><strong>' + escapeHtml(item.size) + '</strong></div>';
        }).join('') : '<div class="training-run-empty">No dataset artifacts found.</div>';
      }
      if (queue) {
        const items = Array.isArray(detail.queue) ? detail.queue : [];
        queue.innerHTML = items.length ? items.map(function(item) {
          return '<div class="training-run-item"><span>' + escapeHtml((item.id || 'queue-item') + ' · ' + (item.status || 'pending')) + '</span><strong>' + escapeHtml('P' + String(item.priority || '--')) + '</strong></div><div class="training-run-subitem">' + escapeHtml(textOr(item.description, '')) + '</div>';
        }).join('') : '<div class="training-run-empty">No dataset backlog items found.</div>';
      }
      if (exports) {
        const targets = detail.export_targets || {};
        exports.innerHTML = Object.keys(targets).map(function(key) {
          return '<div class="training-run-item"><span>' + escapeHtml(key.replace('_', ' ').toUpperCase()) + '</span><strong>' + escapeHtml(targets[key] ? 'READY' : 'PENDING') + '</strong></div>';
        }).join('');
      }
      setOperational(root.closest('.card'), !!detail.canonical);
    } catch (error) {
      console.error('[dataset] render failed', error);
    }
  }

  function renderEtaTracker(data) {
    const root = qs('[data-eta-root]');
    if (!root) return;
    const summary = root.querySelector('[data-eta-summary]');
    const tiers = root.querySelector('[data-eta-tiers]');
    const model = data.model || {};
    const analysis = data.scale_analysis || {};
    const collected = Number(model.memory_collected_tokens || 0);
    const minimum = Number(model.minimum_tuning_tokens || 0);
    const target = Number(model.memory_target_tokens || 0);
    const pctToMinimum = minimum ? Math.min(100, (collected / minimum) * 100) : 0;
    const pctToTarget = target ? Math.min(100, (collected / target) * 100) : 0;
    const phases = [
      {
        label: 'SMOKE TEST',
        detail: minimum ? ('Reach ' + compactNumber(Math.min(minimum, 5000000)) + ' tokens for tiny pipeline validation') : 'Waiting for minimum token threshold',
        value: collected >= Math.min(minimum || 0, 5000000) && minimum ? 'READY' : 'PENDING'
      },
      {
        label: 'MINIMUM TUNING',
        detail: compactNumber(collected) + ' / ' + compactNumber(minimum) + ' tokens toward minimum tuning threshold',
        value: collected >= minimum && minimum ? 'READY' : (pctToMinimum.toFixed(1) + '%')
      },
      {
        label: '24B TARGET',
        detail: compactNumber(collected) + ' / ' + compactNumber(target) + ' tokens toward full corpus estimate',
        value: pctToTarget.toFixed(pctToTarget >= 1 ? 1 : 2) + '%'
      }
    ];

    if (summary) {
      summary.innerHTML = ''
        + '<div class="trace-box"><div class="trace-box-label">COLLECTED</div><div class="trace-box-val" style="font-size:18px;">' + escapeHtml(compactNumber(collected)) + '</div></div>'
        + '<div class="trace-box"><div class="trace-box-label">MINIMUM</div><div class="trace-box-val" style="font-size:18px;">' + escapeHtml(compactNumber(minimum)) + '</div></div>'
        + '<div class="trace-box"><div class="trace-box-label">PATH</div><div class="trace-box-val" style="font-size:18px;">' + escapeHtml(analysis.fine_tune_path_ready ? 'FINE-TUNE' : 'BLOCKED') + '</div></div>';
    }

    if (tiers) {
      tiers.innerHTML = phases.map(function(item) {
        return ''
          + '<div class="training-run-item">'
          + '<span>' + escapeHtml(item.label + ' · ' + item.detail) + '</span>'
          + '<strong>' + escapeHtml(item.value) + '</strong>'
          + '</div>';
      }).join('');
    }

    setOperational(root.closest('.card'), !!data.canonical);
  }

  function renderBootstrapPanel(data) {
    const bootBody = qs('.boot-body');
    if (bootBody && Array.isArray(data.bootstrap_steps)) {
      bootBody.innerHTML = data.bootstrap_steps.map(function (step) {
        const live = step.status === 'complete';
        return ''
          + '<div class="boot-step" data-boot-step="' + escapeHtml(step.id) + '">'
          + '<span class="boot-step-num">' + escapeHtml(step.id) + '</span>'
          + '<span class="boot-step-name">' + escapeHtml(step.name + (step.has_prompt ? ' / prompt' : '')) + '</span>'
          + '<div class="boot-step-status" style="background:' + (live ? 'var(--green)' : 'var(--red)') + ';box-shadow:0 0 8px ' + (live ? 'var(--green-glow)' : 'var(--red-glow)') + ';"></div>'
          + '</div>';
      }).join('');
    }
    const flow = qs('.repo-flow');
    if (flow) {
      flow.innerHTML = '<span>Clone</span><span class="flow-arrow">→</span><span>prompt.md</span><span class="flow-arrow">→</span><span>SPAWN/START</span><span class="flow-arrow">→</span><span>SPAWN/STOP</span>';
    }
  }

  function renderRepoStructurePanel(data) {
    const zoneBoxes = qsa('.repo-zone .zone-box');
    const structure = data.repo_structure || {};
    if (zoneBoxes[0]) {
      zoneBoxes[0].innerHTML = '<div class="zone-title">START/ (BOOTSTRAP)</div>' + (structure.start || []).map(function (item) {
        return '<div class="zone-item" data-structure-node="start:' + escapeHtml(item.name) + '">' + escapeHtml(item.name) + (item.detail ? ' <span style="color:var(--text-ghost)">· ' + escapeHtml(item.detail) + '</span>' : '') + '</div>';
      }).join('');
    }
    if (zoneBoxes[1]) {
      zoneBoxes[1].innerHTML = '<div class="zone-title">STOP/ (AGENT ZONE)</div>' + (structure.stop || []).map(function (item) {
        return '<div class="zone-item" data-structure-node="stop:' + escapeHtml(item.name) + '">' + escapeHtml(item.name) + (item.detail ? ' <span style="color:var(--text-ghost)">· ' + escapeHtml(item.detail) + '</span>' : '') + '</div>';
      }).join('');
    }
  }

  function renderVectorMemoryPanel(data) {
    const phases = qs('.vec-phases');
    if (!phases || !Array.isArray(data.vector_phases)) return;
    phases.innerHTML = data.vector_phases.map(function (phase) {
      const live = phase.status === 'complete';
      return ''
        + '<div class="vec-phase" data-vec-phase="' + escapeHtml(phase.name) + '">'
        + '<div class="vec-phase-hdr"><span class="vec-phase-name">' + escapeHtml(phase.name) + '</span><span class="vec-phase-badge">' + escapeHtml(live ? 'LIVE' : 'PENDING') + '</span></div>'
        + '<div class="vec-phase-desc">' + escapeHtml(phase.detail || '') + '</div>'
        + '</div>';
    }).join('');
  }

  function renderExportPanel(data) {
    const exportBody = qs('.export-body');
    if (!exportBody) return;
    const verification = data.verification || {};
    const exportItems = [
      { task: 'T17', key: 'gui_export_jsonl', title: 'EXPORT JSONL', format: 'jsonl' },
      { task: 'T18', key: 'gui_export_alpaca', title: 'EXPORT ALPACA', format: 'alpaca' },
      { task: 'T19', key: 'gui_export_sharegpt', title: 'EXPORT SHAREGPT', format: 'sharegpt' },
      { task: 'T20', key: 'gui_export_steering', title: 'EXPORT STEERING ONLY', format: 'steering' }
    ];
    exportBody.innerHTML = exportItems.map(function (item) {
      const live = !!(verification[item.key] && verification[item.key].live);
      const detail = live ? 'Repo-backed export endpoint is live.' : 'Pending repo-backed export endpoint.';
      return ''
        + '<button class="export-btn" type="button" data-export-format="' + escapeHtml(item.format) + '">'
        + '<span class="export-btn-icon">' + escapeHtml(item.task) + '</span>'
        + '<div>'
        + '<div>' + escapeHtml(item.title) + '</div>'
        + '<div class="export-desc">' + escapeHtml(detail) + '</div>'
        + '</div>'
        + '</button>';
    }).join('');
  }

  function renderReadinessTracker(data) {
    const trackerCard = qsa('.bento2 .card').find(function (card) {
      const title = card.querySelector('.panel-title');
      return title && title.textContent.trim() === 'READINESS TRACKER';
    });
    if (!trackerCard) return;
    const body = trackerCard.querySelector('div[style*="padding:14px 16px"]');
    if (!body || !Array.isArray(data.readiness)) return;
    const rows = data.readiness.map(function (item) {
      let color = 'var(--text-dim)';
      if (item.status === 'live') color = 'var(--green)';
      if (item.status === 'warn') color = 'var(--amber)';
      return ''
        + '<div class="readiness-row" data-readiness-key="' + escapeHtml(item.label) + '" style="display:flex;justify-content:space-between;font-size:9px;padding:7px 9px;border:1px solid var(--border-dim);border-radius:5px;background:rgba(255,255,255,0.02);">'
        + '<span style="color:var(--text-dim);">' + escapeHtml(item.label) + '</span>'
        + '<span style="color:' + color + ';">' + escapeHtml(item.value) + '</span>'
        + '</div>';
    }).join('');
    body.innerHTML = '<div style="font-size:8px;letter-spacing:2px;color:var(--text-ghost);margin-bottom:8px;">CURRENT READINESS</div><div style="display:flex;flex-direction:column;gap:6px;">' + rows + '</div>';
  }

  async function renderModelStatusDetails() {
    const root = qs('[data-model-status-root]');
    if (!root) return;
    try {
      const response = await fetch('/api/model/status', {cache: 'no-store'});
      if (!response.ok) throw new Error('model status request failed');
      const detail = await response.json();
      let detailBlock = root.querySelector('[data-model-status-detail]');
      if (!detailBlock) {
        detailBlock = document.createElement('div');
        detailBlock.setAttribute('data-model-status-detail', 'true');
        detailBlock.style.display = 'grid';
        detailBlock.style.gridTemplateColumns = 'repeat(auto-fit,minmax(160px,1fr))';
        detailBlock.style.gap = '8px';
        detailBlock.style.marginTop = '12px';
        root.appendChild(detailBlock);
      }
      detailBlock.innerHTML = ''
        + '<div class="training-run-item"><span>READINESS ROWS</span><strong>' + escapeHtml(String((detail.readiness || []).length)) + '</strong></div>'
        + '<div class="training-run-item"><span>FINE-TUNE PATH</span><strong>' + escapeHtml(detail.scale_analysis && detail.scale_analysis.fine_tune_path_ready ? 'READY' : 'BLOCKED') + '</strong></div>'
        + '<div class="training-run-item"><span>TRAIN FROM SCRATCH</span><strong>' + escapeHtml(detail.scale_analysis && detail.scale_analysis.can_train_from_scratch ? 'SUPPORTED' : 'NO') + '</strong></div>';
      setOperational(root.closest('.card'), !!detail.canonical);
    } catch (error) {
      console.error('[model-status] render failed', error);
    }
  }

  async function renderSteeringDetails() {
    const body = qs('.steering-body');
    if (!body) return;
    try {
      const response = await fetch('/api/steering/events', {cache: 'no-store'});
      if (!response.ok) throw new Error('steering events request failed');
      const detail = await response.json();
      const items = Array.isArray(detail.events) ? detail.events : [];
      body.innerHTML = items.length ? items.map(function(item, index) {
        return ''
          + '<div class="steering-entry">'
          + '<div class="steering-tags"><span class="stag stag-arch">LIVE</span><span class="stag stag-resolved">STATE</span><span class="stag">EVENT ' + escapeHtml(String(index + 1).padStart(2, '0')) + '</span></div>'
          + '<div class="steering-text">' + escapeHtml(item.text || '') + '</div>'
          + '<div class="steering-note">Trace: NEXTAURA // ORCHESTRATOR · ' + escapeHtml(formatClock(detail.generated_at)) + '</div>'
          + '</div>';
      }).join('') : '<div class="steering-entry"><div class="steering-text">No high-priority steering trace has been captured yet.</div></div>';
      setOperational(body.closest('.card'), !!detail.canonical);
    } catch (error) {
      console.error('[steering] render failed', error);
    }
  }

  function renderStatusbar(data) {
    const segments = qsa('#statusbar .sb-seg');
    if (segments[0]) segments[0].querySelector('.sb-live').textContent = data.summary.dag_active ? 'SPAWN ACTIVE' : 'SPAWN IDLE';
    if (segments[1]) segments[1].querySelector('span').textContent = 'MUTEX HELD';
    if (segments[2]) segments[2].querySelector('span').textContent = (data.active_task ? (data.active_task.task_id + ' -> ' + data.active_task.label + ' · ' + (data.active_task.progress || 0) + '%') : 'WAITING FOR TASK');
    if (segments[3]) segments[3].textContent = 'WARN ' + (data.summary.stray_count || 0) + ' STRAY EVENT';
  }

  renderStatusbar = function (data) {
    const segments = qsa('#statusbar .sb-seg');
    if (segments[0]) segments[0].querySelector('.sb-live').textContent = data.summary.dag_active ? 'SPAWN ACTIVE' : 'SPAWN IDLE';
    if (segments[1]) segments[1].querySelector('span').textContent = data.repo_freeze && data.repo_freeze.mutex_held ? 'MUTEX HELD' : 'MUTEX OPEN';
    if (segments[2]) {
      segments[2].querySelector('span').textContent = data.active_task
        ? (data.active_task.task_id + ' -> ' + data.active_task.label + (data.active_task.progress ? ' | ' + data.active_task.progress + '%' : ''))
        : 'WAITING FOR TASK';
    }
    if (segments[3]) segments[3].textContent = 'WARN ' + (data.summary.stray_count || 0) + ' STRAY EVENT';
  }

  function bindSpawnControls() {
    const startBtn = qs('#spawn-start-btn');
    const pauseBtn = qs('#spawn-pause-btn');
    function postSpawnAction(action) {
      return fetch('/api/control/spawn-loop', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: action})
      })
        .then(function(response) { return response.json(); })
        .then(function(data) {
          console.log('[spawn] action:', data);
          refreshFromServer();
        })
        .catch(function(error) {
          console.error('[spawn] control failed', error);
        });
    }
    
    if (startBtn) {
      startBtn.addEventListener('click', function() {
        postSpawnAction('start');
      });
    }
    
    if (pauseBtn) {
      pauseBtn.addEventListener('click', function() {
        postSpawnAction('pause');
      });
    }
  }

  function applyState(data) {
    ensureOperationalStyles();
    bindNavPanels();
    bindSpawnControls();
    bindRepoFreezeControls();
    bindRepoDetailModal();
    renderTopBar(data);
    renderStatRow(data);
    renderDagList(data);
    bindDagTaskDetails();
    bindBootstrapStepDetails();
    bindRepoStructureDetails();
    bindVectorPhaseDetails();
    bindMemoryFileDetails();
    bindExportButtons();
    renderModelPanel(data);
    renderAuditPanels(data);
    renderSpawnPanel(data);
    renderRepoFreeze();
    renderPolicyAndStray(data);
    renderStrayLog(data);
    renderTraceCapture(data);
    renderBootstrapPanel(data);
    renderRepoStructurePanel(data);
    renderVectorMemoryPanel(data);
    renderMemoryFiles(data);
    renderSteeringDetails();
    renderTrainingRunDetails();
    renderDatasetDetails();
    renderEtaTracker(data);
    renderExportPanel(data);
    renderReadinessTracker(data);
    renderScaleAnalysis(data);
    renderModelStatusDetails();
    bindBootstrapStepDetails();
    bindRepoStructureDetails();
    bindVectorPhaseDetails();
    bindMemoryFileDetails();
    bindExportButtons();
    renderStatusbar(data);
    renderTaskSurfaceMap();
    const activeNav = qs('#sidebar .nav-item.active[data-nav]');
    handleNavPanel(activeNav ? activeNav.getAttribute('data-nav') : 'orchestrator');
  }

  async function refreshFromServer() {
    try {
      const response = await fetch('/api/dashboard', {cache: 'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      window.__ORCH_DASHBOARD_STATE__ = data;
      applyState(data);
    } catch (error) {
      console.error('[dashboard] refresh failed', error);
    }
  }

  function connectEvents() {
    try {
      const source = new EventSource('/events');
      source.addEventListener('dashboard', function (event) {
        const payload = JSON.parse(event.data);
        window.__ORCH_DASHBOARD_STATE__ = payload;
        applyState(payload);
      });
      source.onerror = function () {
        source.close();
        setTimeout(connectEvents, 5000);
      };
    } catch (error) {
      console.error('[dashboard] sse unavailable', error);
    }
  }

  applyState(state);
  connectEvents();
  setInterval(refreshFromServer, 15000);
})();
</script>
"""


@app.route("/api/task/<task_id>")
def api_task_details(task_id):
    """Return detailed information for a specific task by ID (e.g., T02, task_002)."""
    graph = load_json(DESIGN_GRAPH_PATH, {"nodes": [], "edges": []})
    tasks = load_json(TASKS_PATH, [])

    node = None
    task_record = None

    for n in graph.get("nodes", []):
        if n.get("id") == task_id or n.get("task_id") == task_id:
            node = n
            break

    for t in tasks:
        if t.get("id") == task_id or t.get("task_id") == task_id:
            task_record = t
            break

    if not node and not task_record:
        return jsonify({"error": f"Task {task_id} not found"}), 404

    result = {
        "task_id": task_id,
        "node": node,
        "task_record": task_record,
        "dependencies": [],
        "dependents": [],
        "allowed_paths": node.get("allowed_paths", []) if node else task_record.get("allowed_paths", []),
        "verification": {
            "verified_live": node.get("verified_live", False) if node else False,
            "verification_reason": node.get("verification_reason", "") if node else "",
        },
    }

    edges = graph.get("edges", [])
    for edge in edges:
        if edge.get("from") == (node.get("id") if node else ""):
            result["dependents"].append(edge.get("to"))
        if edge.get("to") == (node.get("id") if node else ""):
            result["dependencies"].append(edge.get("from"))

    return jsonify(result)


# Track spawn runner process
spawn_runner_process = None


def update_spawn_loop_state(action: str):
    global spawn_runner_process
    action = (action or "").strip().lower()
    if action not in {"start", "pause"}:
        return {"error": "Unsupported spawn-loop action", "action": action}, 400

    config = load_json(CONFIG_PATH, {})

    if action == "start":
        config["spawn_loop"] = {"state": "running", "started_at": datetime.utcnow().isoformat() + "Z"}
        save_json(CONFIG_PATH, config)

        spawn_runner_script = ORCHESTRATOR_DIR / "spawn_runner.py"
        if spawn_runner_script.exists():
            if spawn_runner_process is None or spawn_runner_process.poll() is not None:
                logger.info("Starting spawn_runner.py background process...")
                spawn_runner_process = subprocess.Popen(
                    [sys.executable, str(spawn_runner_script)],
                    cwd=str(ORCHESTRATOR_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                logger.info(f"spawn_runner started with PID {spawn_runner_process.pid}")
            else:
                logger.info("spawn_runner already running")

        logger.info("Spawn loop started via API")
        return {"status": "started", "state": "running", "action": "start", "timestamp": config["spawn_loop"]["started_at"]}, 200

    config["spawn_loop"] = {"state": "paused", "paused_at": datetime.utcnow().isoformat() + "Z"}
    save_json(CONFIG_PATH, config)

    if spawn_runner_process is not None and spawn_runner_process.poll() is None:
        logger.info("Stopping spawn_runner.py...")
        spawn_runner_process.terminate()
        try:
            spawn_runner_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            spawn_runner_process.kill()
            spawn_runner_process.wait()
        logger.info("spawn_runner stopped")
        spawn_runner_process = None

    logger.info("Spawn loop paused via API")
    return {"status": "paused", "state": "paused", "action": "pause", "timestamp": config["spawn_loop"]["paused_at"]}, 200


@app.route("/api/control/spawn-loop", methods=["POST"])
def api_control_spawn_loop():
    payload = request.get_json(silent=True) or {}
    action = payload.get("action") or request.args.get("action")
    result, status = update_spawn_loop_state(action)
    return jsonify(result), status

@app.route("/api/spawn/start", methods=["POST"])
def api_spawn_start():
    """Start the autonomous spawn loop."""
    result, status = update_spawn_loop_state("start")
    return jsonify(result), status


@app.route("/api/spawn/pause", methods=["POST"])
def api_spawn_pause():
    """Pause the autonomous spawn loop."""
    result, status = update_spawn_loop_state("pause")
    return jsonify(result), status


@app.route("/api/spawn/status")
def api_spawn_status():
    """Return current spawn loop state."""
    global spawn_runner_process
    config = load_json(CONFIG_PATH, {})
    spawn_loop = config.get("spawn_loop", {"state": "stopped"})
    spawn_loop["runner_pid"] = spawn_runner_process.pid if spawn_runner_process and spawn_runner_process.poll() is None else None
    spawn_loop["runner_running"] = spawn_runner_process is not None and spawn_runner_process.poll() is None
    return jsonify(spawn_loop)


@app.route("/api/training/run")
def api_training_run():
    """Return canonical repo-backed training run details for the training dashboard panel."""
    return jsonify(build_training_run_payload())


@app.route("/api/dataset/details")
def api_dataset_details():
    """Return canonical repo-backed dataset details for the dataset dashboard panel."""
    return jsonify(build_dataset_payload())


@app.route("/api/audit/events")
def api_audit_events():
    return jsonify(build_audit_events_payload())


@app.route("/api/stray/events")
def api_stray_events():
    return jsonify(build_stray_events_payload())


@app.route("/api/traces")
def api_traces():
    return jsonify(build_trace_capture_payload())


@app.route("/api/steering/events")
def api_steering_events():
    return jsonify(build_steering_events_payload())


@app.route("/api/repo-freeze/state")
def api_repo_freeze_state():
    return jsonify(build_repo_freeze_payload())


@app.route("/api/control/repo-freeze", methods=["POST"])
def api_control_repo_freeze():
    payload = request.get_json(silent=True) or {}
    action = payload.get("action") or "toggle"
    lock_path = LOCKS_DIR / "global_write.lock"
    held = lock_path.exists()

    if action == "hold" or (action == "toggle" and not held):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps(
                {
                    "owner": "dashboard",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "reason": "manual repo freeze toggle",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif lock_path.exists():
        lock_path.unlink()

    return jsonify(build_repo_freeze_payload())


@app.route("/api/bootstrap/steps/<step_id>")
def api_bootstrap_step(step_id):
    return jsonify(build_bootstrap_step_payload(step_id))


@app.route("/api/repo-structure/<path:node_key>")
def api_repo_structure_detail(node_key):
    return jsonify(build_repo_structure_payload(node_key))


@app.route("/api/vector-phases/<path:phase_name>")
def api_vector_phase_detail(phase_name):
    return jsonify(build_vector_phase_payload(phase_name))


@app.route("/api/memory-files/<path:file_name>")
def api_memory_file_detail(file_name):
    return jsonify(build_memory_file_payload(file_name))


@app.route("/api/export/jsonl")
def api_export_jsonl():
    return jsonify(build_export_payload("jsonl"))


@app.route("/api/export/alpaca")
def api_export_alpaca():
    return jsonify(build_export_payload("alpaca"))


@app.route("/api/export/sharegpt")
def api_export_sharegpt():
    return jsonify(build_export_payload("sharegpt"))


@app.route("/api/export/steering")
def api_export_steering():
    return jsonify(build_export_payload("steering"))


@app.route("/api/model/status")
def api_model_status():
    return jsonify(build_model_status_payload())


def render_live_design_html():
    if not DESIGN_HTML_PATH.exists():
        return "<h1>design.html not found</h1>"

    html = DESIGN_HTML_PATH.read_text(encoding="utf-8", errors="replace")
    payload = json.dumps(build_dashboard_payload())
    injection = f"<script>window.__ORCH_DASHBOARD_STATE__ = {payload};</script>{LIVE_DASHBOARD_SCRIPT}"
    return html.replace("</body>", injection + "\n</body>")


@app.route("/")
@app.route("/design")
def design_dashboard():
    """Serve the as-designed live dashboard."""
    return Response(render_live_design_html(), mimetype="text/html")


@app.route("/classic")
def classic_dashboard():
    """Preserve access to the older template dashboard."""
    return render_template("index.html")


@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)


@app.route("/api/status")
def api_status():
    payload = build_dashboard_payload()
    return jsonify({"status": "running", "metrics": payload["metrics"], "timestamp": payload["generated_at"]})


@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(build_dashboard_payload())


@app.route("/api/dag")
def api_dag():
    return jsonify(load_json(DESIGN_GRAPH_PATH, {"nodes": [], "edges": []}))


@app.route("/api/tasks")
def api_tasks():
    return jsonify(get_task_records())


@app.route("/api/logs")
def api_logs():
    limit = int(request.args.get("limit", 50))
    return jsonify(get_recent_logs(limit))


@app.route("/api/metrics")
def api_metrics():
    return jsonify(get_metrics(get_task_records()))


@app.route("/api/repos")
def api_repos():
    return jsonify(get_repo_status())


@app.route("/events")
def sse_events():
    """Real-time dashboard updates with named SSE events."""

    def emit(event_name, payload):
        return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    def generate():
        client_id = id(request)
        logger.info("SSE client connected: %s", client_id)
        try:
            while True:
                dashboard = build_dashboard_payload()
                yield emit("dashboard", dashboard)
                yield emit("metrics", dashboard["metrics"])
                yield emit("dag", dashboard["graph"])
                yield emit("tasks", dashboard["tasks"])
                time.sleep(5)
        except GeneratorExit:
            logger.info("SSE client disconnected: %s", client_id)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("ORCHESTRATOR DASHBOARD SERVER STARTING")
    logger.info("Runtime dir: %s", RUNTIME_DIR)
    logger.info("Design source: %s", DESIGN_HTML_PATH)
    logger.info("=" * 60)

    for dir_path in [LOGS_DIR, DATA_DIR, MODELS_DIR, VECTOR_STORE_DIR, STATE_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)

    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
