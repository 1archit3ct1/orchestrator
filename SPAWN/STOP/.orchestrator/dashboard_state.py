#!/usr/bin/env python3
"""
Canonical dashboard state builder.

The dashboard must read from repo state files, not inferred placeholder values.
This module consolidates repo state into an in-memory dashboard payload.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def load_json(path: Path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except (json.JSONDecodeError, OSError):
        pass
    return default


def write_json_if_changed(path: Path, data):
    rendered = json.dumps(data, indent=2, default=str) + "\n"
    current = read_text(path, default=None)
    if current != rendered:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")


def read_text(path: Path, default=""):
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return default


def tail_lines(path: Path, limit=20):
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return [line.rstrip() for line in handle.readlines()[-limit:]]
    except OSError:
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


def count_files(path: Path, pattern="*"):
    if not path.exists():
        return 0
    return len(list(path.rglob(pattern)))


def directory_size(path: Path):
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def normalize_tasks(graph, tasks):
    if isinstance(tasks, list) and tasks:
        normalized = []
        for index, task in enumerate(tasks, start=1):
            normalized.append(
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
                    "progress": task.get("progress"),
                }
            )
        return normalized

    normalized = []
    for index, node in enumerate(graph.get("nodes", []), start=1):
        display_status = node.get("display_status")
        if not display_status:
            if node.get("status") == "green":
                display_status = "completed"
            elif node.get("status") == "yellow":
                display_status = "active"
            else:
                display_status = "pending"

        normalized.append(
            {
                "id": f"task_{index:03d}",
                "task_id": node.get("task_id", f"T{index:02d}"),
                "dag_node_id": node.get("id"),
                "label": node.get("task_name") or node.get("label") or node.get("id"),
                "description": node.get("description", ""),
                "allowed_paths": node.get("allowed_paths", []),
                "dependencies": node.get("dependencies", []),
                "status": display_status,
                "priority": index,
                "progress": node.get("progress"),
            }
        )
    return normalized


def verify_dashboard_integrations(runtime_dir: Path):
    orchestrator_dir = runtime_dir / ".orchestrator"
    web_dir = runtime_dir / "web"
    state_dir = runtime_dir / "state"
    repos_dir = runtime_dir / "repos"
    training_dir = runtime_dir / "training"
    task_queue_path = orchestrator_dir / "task_queue.json"
    tasks_path = state_dir / "tasks.json"
    vector_dir = orchestrator_dir / "vector_store"
    loop_path = orchestrator_dir / "loop.py"

    loop_text = read_text(loop_path)
    task_queue = load_json(task_queue_path, [])
    derived_tasks = load_json(tasks_path, [])

    training_files = [
        training_dir / "collect_data.py",
        training_dir / "prepare_dataset.py",
        training_dir / "train.py",
        training_dir / "config.yml",
        training_dir / "evaluate.py",
    ]
    child_repo_ready = False
    if repos_dir.exists():
        for repo_dir in repos_dir.iterdir():
            if (repo_dir / "SPAWN" / "STOP").exists():
                child_repo_ready = True
                break

    checks = {
        "loop_runtime": {
            "live": (
                loop_path.exists()
                and "repo_path / 'SPAWN' / 'STOP' / 'state' / 'tasks.json'" in loop_text
                and "repo_log_dir = self.repos_dir / repo_name / 'SPAWN' / 'STOP' / '.orchestrator' / 'logs'" in loop_text
                and "root_dir = script_dir.parent.parent.parent" in loop_text
            ),
            "reason": "orchestration loop matches SPAWN/STOP path contract"
            if (
                loop_path.exists()
                and "repo_path / 'SPAWN' / 'STOP' / 'state' / 'tasks.json'" in loop_text
                and "repo_log_dir = self.repos_dir / repo_name / 'SPAWN' / 'STOP' / '.orchestrator' / 'logs'" in loop_text
                and "root_dir = script_dir.parent.parent.parent" in loop_text
            )
            else "loop.py still needs path-contract alignment for child orchestration",
        },
        "task_queue_seeded": {
            "live": isinstance(task_queue, list) and len(task_queue) > 0,
            "reason": "task_queue.json contains child tasks"
            if isinstance(task_queue, list) and len(task_queue) > 0
            else "task_queue.json is still empty",
        },
        "child_repos_ready": {
            "live": child_repo_ready,
            "reason": "at least one child repo has SPAWN/STOP runtime scaffolding"
            if child_repo_ready
            else "no child repos are scaffolded under repos/",
        },
        "training_pipeline_scaffold": {
            "live": all(path.exists() for path in training_files),
            "reason": "training pipeline scaffold files are present"
            if all(path.exists() for path in training_files)
            else "training pipeline scaffold is incomplete",
        },
        "runtime_tasks_derived": {
            "live": isinstance(derived_tasks, list) and len(derived_tasks) > 0,
            "reason": "tasks.json contains derived executable tasks"
            if isinstance(derived_tasks, list) and len(derived_tasks) > 0
            else "tasks.json has not been derived from the design graph yet",
        },
        "vector_store_seeded": {
            "live": count_files(vector_dir, "*.json") > 0,
            "reason": "vector store contains seeded context entries"
            if count_files(vector_dir, "*.json") > 0
            else "vector store is still empty",
        },
    }
    return checks


def apply_verification_to_graph(graph, verification, task_md):
    active_node_id = task_md.get("dag_node_id") if task_md else None
    graph = json.loads(json.dumps(graph))

    for node in graph.get("nodes", []):
        node_id = node.get("id")
        result = verification.get(node_id, {"live": False, "reason": "no verification rule"})
        node["verified_live"] = result["live"]
        node["verification_reason"] = result["reason"]

        if result["live"]:
            node["status"] = "green"
            node["display_status"] = "complete"
            node["progress"] = None
        elif active_node_id and node_id == active_node_id:
            node["status"] = "yellow"
            node["display_status"] = "active"
        else:
            node["status"] = "red"
            node["display_status"] = "pending"
            node["progress"] = None

    return graph


def parse_task_md(task_md_path: Path):
    if not task_md_path.exists():
        return None

    content = read_text(task_md_path)
    if not content.startswith("---"):
        return None

    end = content.find("---", 3)
    if end <= 0:
        return None

    frontmatter = content[3:end].strip()
    body = content[end + 3 :].strip()
    record = {
        "task_id": None,
        "dag_node_id": None,
        "priority": None,
        "allowed_paths": [],
        "description": "",
        "status": "pending",
    }

    in_allowed_paths = False
    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if stripped == "allowed_paths:":
            in_allowed_paths = True
            continue

        if in_allowed_paths and stripped.startswith("- "):
            record["allowed_paths"].append(stripped[2:].strip())
            continue

        in_allowed_paths = False
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key in record:
                record[key] = value

    match = re.search(r"## Description\s*(.+?)(?:\n## |\Z)", body, flags=re.S)
    if match:
        record["description"] = " ".join(match.group(1).split())

    status_match = re.search(r"## Status:\s*([A-Z_]+)", body)
    if status_match:
        record["status"] = status_match.group(1).lower()

    return record


def task_status_counts(tasks):
    total = len(tasks)
    pending = sum(1 for task in tasks if task.get("status") == "pending")
    active = sum(1 for task in tasks if task.get("status") in {"active", "in_progress"})
    completed = sum(1 for task in tasks if task.get("status") in {"completed", "complete"})
    return {
        "total": total,
        "pending": pending,
        "in_progress": active,
        "completed": completed,
    }


def parse_trace_entries(log_paths, limit=6):
    entries = []
    for path in log_paths:
        for line in tail_lines(path, limit * 2):
            line = line.strip()
            if not line:
                continue

            timestamp = ""
            text = line
            match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\[[A-Z]+\]\s+(.*)", line)
            if match:
                timestamp = match.group(1).split(" ")[1]
                text = match.group(2)

            lowered = text.lower()
            tag = "LOOP"
            trace_type = "loop"
            if "task" in lowered:
                tag = "TASK"
                trace_type = "task"
            elif "memory" in lowered or "vector" in lowered:
                tag = "MEM"
                trace_type = "mem"
            elif "model" in lowered or "train" in lowered:
                tag = "MODEL"
                trace_type = "model"

            entries.append(
                {
                    "timestamp": timestamp,
                    "text": text,
                    "tag": tag,
                    "type": trace_type,
                }
            )

    return entries[-limit:]


def parse_security_events(log_paths, limit=6):
    events = []
    interesting = ("stray", "blocked", "policy", "outside", "halt", "denied")
    for path in log_paths:
        for line in tail_lines(path, limit * 3):
            lowered = line.lower()
            if any(token in lowered for token in interesting):
                events.append(line)
    return events[-limit:]


def parse_steering_events(decisions_dir: Path, limit=6):
    events = []
    if not decisions_dir.exists():
        return events

    for path in sorted(decisions_dir.glob("dec_*.json"))[-limit:]:
        payload = load_json(path, {})
        if isinstance(payload, dict):
            decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else payload
            if decision.get("question") and decision.get("chosen"):
                rationale = decision.get("rationale")
                summary = f"{decision.get('question')} Chosen: {decision.get('chosen')}."
                if rationale:
                    summary += f" {rationale}"
            else:
                summary = payload.get("summary") or decision.get("summary") or decision.get("title") or path.stem
            events.append(str(summary))
        else:
            events.append(path.stem)
    return events[-limit:]


def lock_is_active(lock_path: Path):
    if not lock_path.exists():
        return False
    payload = load_json(lock_path, {})
    if not isinstance(payload, dict):
        return False
    expires_at = payload.get("expires_at")
    status = payload.get("status")
    if status and status != "acquired":
        return False
    if not expires_at:
        return True
    try:
        return datetime.fromisoformat(expires_at) >= datetime.now()
    except ValueError:
        return False


def build_bootstrap_steps(start_dir: Path):
    steps = []
    for idx, name in enumerate(["01-init", "02-config", "03-templates", "04-hooks", "05-validation"], start=1):
        step_dir = start_dir / name
        status = "complete" if step_dir.exists() else "missing"
        prompt_exists = (step_dir / "prompt.md").exists()
        steps.append(
            {
                "id": f"{idx:02d}",
                "name": name.replace("01-", "").replace("02-", "").replace("03-", "").replace("04-", "").replace("05-", ""),
                "path": str(step_dir),
                "status": status,
                "has_prompt": prompt_exists,
            }
        )
    return steps


def build_vector_phases(vector_dir: Path, iterations_dir: Path):
    vector_entries = count_files(vector_dir, "*.json")
    iteration_entries = len(list(iterations_dir.glob("iter_*.json"))) if iterations_dir.exists() else 0
    decision_entries = len(list((iterations_dir / "decisions").glob("dec_*.json"))) if (iterations_dir / "decisions").exists() else 0

    return [
        {
            "name": "BOOTSTRAP INDEX",
            "status": "complete" if vector_entries else "pending",
            "detail": f"{vector_entries} vector entries present",
        },
        {
            "name": "RUNTIME QUERY",
            "status": "complete" if vector_entries else "pending",
            "detail": "Runtime retrieval depends on vector entries and planner injection logs",
        },
        {
            "name": "POST-TASK EMBED",
            "status": "complete" if (iteration_entries + decision_entries) else "pending",
            "detail": f"{iteration_entries + decision_entries} iteration artifacts captured",
        },
    ]


def build_memory_files(runtime_dir: Path, task_md: Path, memory_md: Path, vector_dir: Path, retrieval_log: Path, agents_md: Path, tasks_path: Path):
    files = []
    if memory_md.exists():
        files.append({"name": "MEMORY.md", "size": f"append-only - {format_bytes(memory_md.stat().st_size)}"})
    if vector_dir.exists():
        files.append({"name": "vector_store/", "size": f"{count_files(vector_dir, '*.json')} entries - {format_bytes(directory_size(vector_dir))}"})
    if task_md.exists():
        files.append({"name": "TASK.md", "size": f"active - {format_bytes(task_md.stat().st_size)}"})
    if agents_md.exists():
        files.append({"name": "AGENTS.md", "size": f"runtime prompt - {format_bytes(agents_md.stat().st_size)}"})
    if retrieval_log.exists():
        files.append({"name": "retrieval_log.jsonl", "size": f"{format_bytes(retrieval_log.stat().st_size)}"})
    if tasks_path.exists():
        files.append({"name": "tasks.json", "size": format_bytes(tasks_path.stat().st_size)})
    return files


def sync_dashboard_state(runtime_dir: Path):
    runtime_dir = Path(runtime_dir)
    orchestrator_dir = runtime_dir / ".orchestrator"
    state_dir = runtime_dir / "state"
    start_dir = runtime_dir.parent / "START"
    config_path = orchestrator_dir / "config.json"
    task_queue_path = orchestrator_dir / "task_queue.json"
    design_graph_path = state_dir / "design_graph.json"
    tasks_path = state_dir / "tasks.json"
    task_md_path = runtime_dir / "TASK.md"
    memory_path = runtime_dir / "MEMORY.md"
    vector_dir = orchestrator_dir / "vector_store"
    data_dir = orchestrator_dir / "data"
    models_dir = orchestrator_dir / "models"
    logs_dir = orchestrator_dir / "logs"
    iterations_dir = orchestrator_dir / "iterations"
    repos_dir = runtime_dir / "repos"
    locks_dir = orchestrator_dir / "locks"
    locks_path = locks_dir / "repo_locks"
    security_log = logs_dir / "security" / "security_audit.log"
    orchestrator_log = logs_dir / "orchestrator.log"
    iteration_log = logs_dir / "iteration_logger.log"
    retrieval_log = runtime_dir / "retrieval_log.jsonl"
    config = load_json(config_path, {})
    training_config = config.get("training_config", {})
    base_graph = load_json(design_graph_path, {"nodes": [], "edges": []})
    task_md = parse_task_md(task_md_path)
    verification = verify_dashboard_integrations(runtime_dir)
    graph = apply_verification_to_graph(base_graph, verification, task_md)
    loop_cycles = int(base_graph.get("last_cycle", 0) or 0)
    if task_md:
        graph["status"] = "awaiting_task_completion"
    elif any(node.get("status") != "green" for node in graph.get("nodes", [])):
        graph["status"] = "waiting_for_work"
    else:
        graph["status"] = "complete"
    graph["last_cycle"] = loop_cycles
    graph["last_updated"] = base_graph.get("last_updated")
    write_json_if_changed(design_graph_path, graph)
    tasks = normalize_tasks(graph, load_json(tasks_path, []))
    task_counts = task_status_counts(tasks)

    graph_node_ids = {node.get("id") for node in graph.get("nodes", [])}
    graph_nodes = {node.get("id"): node for node in graph.get("nodes", [])}
    state_warnings = []
    active_task = None
    if task_md and task_md.get("dag_node_id") in graph_node_ids:
        node = graph_nodes.get(task_md.get("dag_node_id"), {})
        active_task = {
            "task_id": task_md.get("task_id") or "--",
            "dag_node_id": task_md.get("dag_node_id"),
            "label": node.get("task_name") or node.get("label") or task_md.get("dag_node_id") or "task-md",
            "description": task_md.get("description", "") or node.get("description", ""),
            "allowed_paths": task_md.get("allowed_paths", []),
            "status": task_md.get("status", "pending"),
            "progress": None,
            "source": "TASK.md",
        }
    elif task_md:
        state_warnings.append(
            f"TASK.md references dag_node_id '{task_md.get('dag_node_id')}' which is not present in design_graph.json"
        )
    else:
        for task in tasks:
            if task.get("status") in {"active", "in_progress"}:
                active_task = dict(task)
                active_task["source"] = "tasks-or-graph"
                break
    node_count = len(graph.get("nodes", []))
    green_count = sum(1 for node in graph.get("nodes", []) if node.get("status") == "green")
    dag_progress = round((green_count / node_count) * 100, 1) if node_count else 0.0

    success_traces = len(list(iterations_dir.glob("iter_*.json"))) if iterations_dir.exists() else 0
    error_traces = len(list((iterations_dir / "errors").glob("err_*.json"))) if (iterations_dir / "errors").exists() else 0
    steering_traces = len(list((iterations_dir / "decisions").glob("dec_*.json"))) if (iterations_dir / "decisions").exists() else 0
    total_training_traces = success_traces + error_traces + steering_traces
    steering_events = parse_steering_events(iterations_dir / "decisions", limit=6)

    vector_entries = count_files(vector_dir, "*.json")
    vector_size = directory_size(vector_dir)
    training_data_files = count_files(data_dir)
    model_files = len(list(models_dir.rglob("*.pt"))) + len(list(models_dir.rglob("*.bin"))) + len(list(models_dir.rglob("*.safetensors"))) if models_dir.exists() else 0
    child_repos = len([item for item in repos_dir.iterdir() if item.is_dir()]) if repos_dir.exists() else 0
    log_files = count_files(logs_dir, "*.log")
    security_events = parse_security_events([security_log, orchestrator_log], limit=6)
    security_events.extend(state_warnings)
    security_events = security_events[-6:]
    trace_entries = parse_trace_entries([orchestrator_log, iteration_log], limit=6)

    repos = []
    if repos_dir.exists():
        for repo in sorted(item for item in repos_dir.iterdir() if item.is_dir()):
            repos.append({"name": repo.name, "status": "configured", "current_task": None})

    model_integrated = bool(training_config.get("integrated", False))
    model_name = training_config.get("model_name") if model_integrated else None

    dashboard_state = {
        "generated_at": datetime.now().isoformat(),
        "canonical": True,
        "canonical_sources": {
            "config": str(config_path),
            "design_graph": str(design_graph_path),
            "tasks": str(tasks_path),
            "task_md": str(task_md_path),
            "memory": str(memory_path),
            "task_queue": str(task_queue_path),
        },
        "state_warnings": state_warnings,
        "verification": verification,
        "graph": graph,
        "tasks": tasks,
        "task_md": task_md,
        "active_task": active_task,
        "metrics": {
            "cycles": max(int(config.get("cycle_count", 0) or 0), loop_cycles),
            "dag_progress": {
                "total": node_count,
                "green": green_count,
                "red": sum(1 for node in graph.get("nodes", []) if node.get("status") == "red"),
                "yellow": sum(1 for node in graph.get("nodes", []) if node.get("status") == "yellow"),
                "progress": dag_progress,
            },
            "task_status": task_counts,
            "vector_store_entries": vector_entries,
            "vector_store_size_bytes": vector_size,
            "training_data_files": training_data_files,
            "model_checkpoints": model_files,
            "child_repos": child_repos,
            "log_files": log_files,
            "gpu_enabled": bool(config.get("gpu_enabled", False)),
            "timestamp": datetime.now().isoformat(),
            "model_name": model_name,
            "model_integrated": model_integrated,
        },
        "summary": {
            "loops_executed": max(int(config.get("cycle_count", 0) or 0), loop_cycles),
            "training_traces": total_training_traces,
            "dag_total": task_counts["total"],
            "dag_pending": task_counts["pending"],
            "dag_active": task_counts["in_progress"],
            "stray_count": len(security_events),
        },
        "model": {
            "name": model_name,
            "sub": "MODEL NOT INTEGRATED" if not model_integrated else "CANONICAL REPO STATE",
            "eta_days": None,
            "collection_progress": dag_progress,
            "success_traces": success_traces,
            "steering_traces": steering_traces,
            "error_traces": error_traces,
            "integrated": model_integrated,
        },
        "logs": [
            {
                "source": "orchestrator.log",
                "content": entry["text"],
                "timestamp": entry["timestamp"] or datetime.now().strftime("%H:%M:%S"),
            }
            for entry in trace_entries
        ],
        "trace_entries": trace_entries,
        "stray_events": security_events,
        "steering_events": steering_events,
        "repos": repos,
        "bootstrap_steps": build_bootstrap_steps(start_dir),
        "vector_phases": build_vector_phases(vector_dir, iterations_dir),
        "memory_files": build_memory_files(
            runtime_dir,
            task_md_path,
            memory_path,
            vector_dir,
            retrieval_log,
            runtime_dir / "AGENTS.md",
            tasks_path,
        ),
        "repo_freeze": {
            "mutex_held": (
                lock_is_active(locks_dir / "global_write.lock")
                or (locks_path.exists() and any(lock_is_active(path) for path in locks_path.glob("*.lock")))
            ),
            "lock_path": str(locks_dir),
            "allowed_paths": task_md.get("allowed_paths", []) if task_md else [],
        },
        "task_queue": load_json(task_queue_path, []),
    }

    return dashboard_state
