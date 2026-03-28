#!/usr/bin/env python3
"""
Canonical dashboard state builder.

The dashboard must read from repo state files, not inferred placeholder values.
This module consolidates repo state into an in-memory dashboard payload.
"""

from __future__ import annotations

import json
import math
import re
import hashlib
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


def has_all(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def count_lines(path: Path):
    if not path.exists():
        return 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def estimate_text_tokens(path: Path):
    text = read_text(path, default="")
    if not text:
        return 0
    words = re.findall(r"\S+", text)
    if words:
        return max(1, math.ceil(len(words) * 1.3))
    return max(1, math.ceil(len(text) / 4))


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
    app_path = web_dir / "app.py"
    design_path = state_dir / "design.html"
    app_text = read_text(app_path)
    design_text = read_text(design_path)

    checks = {
        "gui_nav_panels": {
            "live": has_all(design_text, "data-nav=", "data-panel=") and "function handleNavPanel" in app_text,
            "reason": "sidebar navigation routes between dashboard panels from repo-backed hooks"
            if has_all(design_text, "data-nav=", "data-panel=") and "function handleNavPanel" in app_text
            else "sidebar nav items are still visual-only and lack panel routing hooks",
        },
        "gui_dag_task_details": {
            "live": 'data-dag-node="' in design_text and "function openDagTaskDetails" in app_text,
            "reason": "task DAG rows open repo-backed task detail state"
            if 'data-dag-node="' in design_text and "function openDagTaskDetails" in app_text
            else "task DAG rows are still visual-only and do not open task details",
        },
        "gui_bootstrap_step_details": {
            "live": 'data-boot-step="' in design_text and "function openBootstrapStep" in app_text,
            "reason": "bootstrap steps open repo-backed status details"
            if 'data-boot-step="' in design_text and "function openBootstrapStep" in app_text
            else "bootstrap steps are clickable shells without drilldown behavior",
        },
        "gui_repo_structure_details": {
            "live": 'data-structure-node="' in design_text and "function openRepoStructureNode" in app_text,
            "reason": "repo structure panel exposes repo-backed node details"
            if 'data-structure-node="' in design_text and "function openRepoStructureNode" in app_text
            else "repo structure panel has no clickable node drilldowns",
        },
        "gui_vector_phase_details": {
            "live": 'data-vec-phase="' in design_text and "function openVectorPhase" in app_text,
            "reason": "vector memory phases expose repo-backed drilldown state"
            if 'data-vec-phase="' in design_text and "function openVectorPhase" in app_text
            else "vector memory phases are not wired to drilldowns",
        },
        "gui_memory_file_open": {
            "live": 'data-memory-file="' in design_text and "function openMemoryFile" in app_text,
            "reason": "memory file rows open real repo file detail state"
            if 'data-memory-file="' in design_text and "function openMemoryFile" in app_text
            else "memory file rows are not wired to repo-backed file details",
        },
        "gui_export_jsonl": {
            "live": 'data-export-format="jsonl"' in design_text and "/api/export/jsonl" in app_text,
            "reason": "JSONL export button is wired to a real export endpoint"
            if 'data-export-format="jsonl"' in design_text and "/api/export/jsonl" in app_text
            else "JSONL export is not wired to repo-backed export logic",
        },
        "gui_export_alpaca": {
            "live": 'data-export-format="alpaca"' in design_text and "/api/export/alpaca" in app_text,
            "reason": "Alpaca export button is wired to a real export endpoint"
            if 'data-export-format="alpaca"' in design_text and "/api/export/alpaca" in app_text
            else "Alpaca export is not wired to repo-backed export logic",
        },
        "gui_export_sharegpt": {
            "live": 'data-export-format="sharegpt"' in design_text and "/api/export/sharegpt" in app_text,
            "reason": "ShareGPT export button is wired to a real export endpoint"
            if 'data-export-format="sharegpt"' in design_text and "/api/export/sharegpt" in app_text
            else "ShareGPT export is not wired to repo-backed export logic",
        },
        "gui_export_steering": {
            "live": 'data-export-format="steering"' in design_text and "/api/export/steering" in app_text,
            "reason": "Steering-only export button is wired to a real export endpoint"
            if 'data-export-format="steering"' in design_text and "/api/export/steering" in app_text
            else "Steering-only export is not wired to repo-backed export logic",
        },
        "gui_repo_freeze_toggle": {
            "live": 'data-control="repo-freeze"' in design_text and "/api/control/repo-freeze" in app_text,
            "reason": "repo freeze toggle can mutate live freeze state through Flask"
            if 'data-control="repo-freeze"' in design_text and "/api/control/repo-freeze" in app_text
            else "repo freeze toggle is display-only and has no control endpoint",
        },
        "gui_spawn_loop_controls": {
            "live": 'data-control="spawn-loop"' in design_text and "/api/control/spawn-loop" in app_text,
            "reason": "spawn loop controls are wired to a live Flask control plane"
            if 'data-control="spawn-loop"' in design_text and "/api/control/spawn-loop" in app_text
            else "spawn loop controls are not wired to a control endpoint",
        },
        "gui_audit_log_details": {
            "live": 'data-panel="audit-log"' in design_text and "/api/audit/events" in app_text,
            "reason": "audit log panel opens repo-backed audit event details"
            if 'data-panel="audit-log"' in design_text and "/api/audit/events" in app_text
            else "audit log panel is not wired to detailed audit events",
        },
        "gui_stray_monitor_details": {
            "live": 'data-panel="stray-monitor"' in design_text and "/api/stray/events" in app_text,
            "reason": "stray monitor panel opens repo-backed stray event details"
            if 'data-panel="stray-monitor"' in design_text and "/api/stray/events" in app_text
            else "stray monitor panel is not wired to detailed stray events",
        },
        "gui_readiness_tracker_live": {
            "live": 'data-readiness-key="' in design_text and "function renderReadinessTracker" in app_text,
            "reason": "readiness tracker rows are rendered from canonical repo state"
            if 'data-readiness-key="' in design_text and "function renderReadinessTracker" in app_text
            else "readiness tracker is still mostly static text and not a live function surface",
        },
        "gui_training_run_details": {
            "live": 'data-panel="training-run"' in design_text and "/api/training/run" in app_text,
            "reason": "training run section opens detailed repo-backed training state"
            if 'data-panel="training-run"' in design_text and "/api/training/run" in app_text
            else "training run panel is not wired to detailed repo-backed training state",
        },
        "gui_dataset_details": {
            "live": 'data-panel="dataset"' in design_text and "/api/dataset/details" in app_text,
            "reason": "dataset section opens detailed repo-backed dataset state"
            if 'data-panel="dataset"' in design_text and "/api/dataset/details" in app_text
            else "dataset panel is not wired to detailed repo-backed dataset state",
        },
        "gui_eta_tracker_live": {
            "live": 'data-panel="eta-tracker"' in design_text and "function renderEtaTracker" in app_text,
            "reason": "ETA tracker renders detailed canonical ETA state"
            if 'data-panel="eta-tracker"' in design_text and "function renderEtaTracker" in app_text
            else "ETA tracker is not wired to canonical repo-backed ETA detail rendering",
        },
        "gui_trace_capture_details": {
            "live": 'data-panel="trace-capture"' in design_text and "/api/traces" in app_text,
            "reason": "trace capture section opens detailed repo-backed trace history"
            if 'data-panel="trace-capture"' in design_text and "/api/traces" in app_text
            else "trace capture section is not wired to detailed repo-backed trace history",
        },
        "gui_steering_log_details": {
            "live": 'data-panel="steering-log"' in design_text and "/api/steering/events" in app_text,
            "reason": "steering log section opens detailed repo-backed steering events"
            if 'data-panel="steering-log"' in design_text and "/api/steering/events" in app_text
            else "steering log section is not wired to detailed repo-backed steering events",
        },
        "gui_mutex_lock_details": {
            "live": 'data-panel="mutex-lock"' in design_text and "/api/repo-freeze/state" in app_text,
            "reason": "mutex status box opens detailed live lock ownership and gating state"
            if 'data-panel="mutex-lock"' in design_text and "/api/repo-freeze/state" in app_text
            else "mutex status box is not wired to detailed live lock state",
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
    processed = set()
    for path in log_paths:
        processed_path = path.parent / "processed_stray_events.json"
        payload = load_json(processed_path, [])
        if isinstance(payload, list):
            processed.update(str(item) for item in payload)

    events = []
    interesting = ("stray", "blocked", "policy", "outside", "halt", "denied")
    for path in log_paths:
        for line in tail_lines(path, limit * 3):
            lowered = line.lower()
            signature = hashlib.sha1(line.strip().encode("utf-8")).hexdigest()
            if any(token in lowered for token in interesting) and signature not in processed:
                events.append(line)
    return events[-limit:]


def parse_steering_events(decisions_dir: Path, limit=None):
    events = []
    if not decisions_dir.exists():
        return events

    paths = sorted(decisions_dir.glob("dec_*.json"))
    if limit is not None:
        paths = paths[-limit:]

    for path in paths:
        payload = load_json(path, {})
        if isinstance(payload, dict):
            decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else payload
            if decision.get("question") and decision.get("chosen"):
                rationale = decision.get("rationale")
                summary = f"{decision.get('question')} Chosen: {decision.get('chosen')}."
                if rationale:
                    summary += f" {rationale}"
            elif payload.get("type") == "steering_decision":
                summary = payload.get("decision") or payload.get("topic") or payload.get("title") or path.stem
            else:
                summary = payload.get("summary") or decision.get("summary") or decision.get("title") or path.stem
            events.append(str(summary))
        else:
            events.append(path.stem)
    return events


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


def build_repo_structure(runtime_dir: Path, start_dir: Path):
    start_items = []
    stop_items = []

    for name in ["prompt.md", "AGENTS.md"]:
        path = start_dir / name
        if path.exists():
            start_items.append({"name": name, "detail": format_bytes(path.stat().st_size)})
    for name in ["01-init", "02-config", "03-templates", "04-hooks", "05-validation"]:
        path = start_dir / name
        if path.exists():
            start_items.append({"name": name, "detail": "dir"})

    stop_map = [
        (".orchestrator/loop.py", runtime_dir / ".orchestrator" / "loop.py"),
        (".orchestrator/planner.sh", runtime_dir / ".orchestrator" / "planner.sh"),
        (".orchestrator/vector_store/", runtime_dir / ".orchestrator" / "vector_store"),
        ("TASK.md", runtime_dir / "TASK.md"),
        ("MEMORY.md", runtime_dir / "MEMORY.md"),
        ("AGENTS.md", runtime_dir / "AGENTS.md"),
    ]
    for label, path in stop_map:
        if path.exists():
            stop_items.append({"name": label, "detail": "dir" if path.is_dir() else format_bytes(path.stat().st_size)})

    return {"start": start_items, "stop": stop_items}


def build_readiness_state(model_integrated: bool, graph: dict, task_md: dict | None, warnings: list[str], verification: dict):
    controls_live = bool(
        verification.get("gui_spawn_loop_controls", {}).get("live")
        and verification.get("gui_repo_freeze_toggle", {}).get("live")
    )
    task_md_aligned = bool(task_md and any(node.get("id") == task_md.get("dag_node_id") for node in graph.get("nodes", [])))
    return [
        {
            "label": "Canonical State",
            "value": "LIVE",
            "status": "live",
        },
        {
            "label": "Model Integrated",
            "value": "LIVE" if model_integrated else "PENDING",
            "status": "live" if model_integrated else "pending",
        },
        {
            "label": "Flask Controls Live",
            "value": "LIVE" if controls_live else "PENDING",
            "status": "live" if controls_live else "pending",
        },
        {
            "label": "TASK.md Alignment",
            "value": "ALIGNED" if task_md_aligned and not warnings else ("ATTENTION" if warnings else "PENDING"),
            "status": "live" if task_md_aligned and not warnings else ("warn" if warnings else "pending"),
        },
    ]


def build_memory_progress(memory_path: Path, retrieval_log: Path, vector_dir: Path, data_dir: Path, iterations_dir: Path, config: dict):
    target_model_params = int(config.get("training_config", {}).get("target_model_params", 24_000_000_000) or 24_000_000_000)
    target_tokens = int(config.get("training_config", {}).get("target_data_tokens", target_model_params * 20) or (target_model_params * 20))
    estimated_bytes_per_token = float(config.get("training_config", {}).get("estimated_bytes_per_token", 4.0) or 4.0)
    minimum_tuning_tokens = int(config.get("training_config", {}).get("minimum_tuning_tokens", max(50_000_000, target_model_params // 10)) or max(50_000_000, target_model_params // 10))
    events = []
    collected_bytes = 0

    if memory_path.exists():
        file_bytes = memory_path.stat().st_size
        collected_bytes += file_bytes
        events.append({"ts": memory_path.stat().st_mtime, "type": "memory", "tokens": estimate_text_tokens(memory_path), "bytes": file_bytes})
    if retrieval_log.exists():
        file_bytes = retrieval_log.stat().st_size
        collected_bytes += file_bytes
        events.append({"ts": retrieval_log.stat().st_mtime, "type": "retrieval", "tokens": estimate_text_tokens(retrieval_log), "bytes": file_bytes})
    if vector_dir.exists():
        for path in vector_dir.glob("*.json"):
            file_bytes = path.stat().st_size
            collected_bytes += file_bytes
            events.append({"ts": path.stat().st_mtime, "type": "vector", "tokens": estimate_text_tokens(path), "bytes": file_bytes})
    if data_dir.exists():
        for path in data_dir.glob("*"):
            if path.is_file():
                file_bytes = path.stat().st_size
                collected_bytes += file_bytes
                events.append({"ts": path.stat().st_mtime, "type": "data", "tokens": estimate_text_tokens(path), "bytes": file_bytes})
    if iterations_dir.exists():
        for path in iterations_dir.glob("iter_*.json"):
            file_bytes = path.stat().st_size
            collected_bytes += file_bytes
            events.append({"ts": path.stat().st_mtime, "type": "iteration", "tokens": estimate_text_tokens(path), "bytes": file_bytes})
        decisions_dir = iterations_dir / "decisions"
        if decisions_dir.exists():
            for path in decisions_dir.glob("dec_*.json"):
                file_bytes = path.stat().st_size
                collected_bytes += file_bytes
                events.append({"ts": path.stat().st_mtime, "type": "decision", "tokens": estimate_text_tokens(path), "bytes": file_bytes})

    events.sort(key=lambda item: item["ts"])
    points = []
    running_total = 0
    for event in events:
        running_total += int(event.get("tokens", 0))
        points.append(
            {
                "timestamp": datetime.fromtimestamp(event["ts"]).isoformat(),
                "count": running_total,
                "type": event["type"],
            }
        )

    collected_tokens = running_total
    retrieval_lines = count_lines(retrieval_log)
    percent = min(100.0, (collected_tokens / target_tokens) * 100) if target_tokens else 0.0
    if percent >= 1:
        percent_display = f"{percent:.1f}"
    elif percent >= 0.01:
        percent_display = f"{percent:.2f}"
    else:
        percent_display = f"{percent:.4f}"

    return {
        "percent": percent,
        "percent_display": percent_display,
        "collected_tokens": collected_tokens,
        "target_tokens": target_tokens,
        "target_model_params": target_model_params,
        "collected_bytes": int(collected_bytes),
        "target_bytes": int(target_tokens * estimated_bytes_per_token),
        "minimum_tuning_bytes": int(minimum_tuning_tokens * estimated_bytes_per_token),
        "minimum_tuning_tokens": minimum_tuning_tokens,
        "retrieval_lines": retrieval_lines,
        "points": points[-24:],
    }


def build_scale_analysis(config: dict, data_dir: Path, vector_dir: Path, iterations_dir: Path, training_dir: Path, memory_progress: dict):
    jsonl_files = sorted(data_dir.glob("*.jsonl")) if data_dir.exists() else []
    training_scripts = sorted(training_dir.rglob("*")) if training_dir.exists() else []
    decision_files = sorted((iterations_dir / "decisions").glob("dec_*.json")) if (iterations_dir / "decisions").exists() else []

    known = {
        "D01": "Mixed storage today: JSONL training artifacts plus JSON vector/iteration files and MEMORY.md.",
        "D03": "All traces are stored on local repo disk under SPAWN/STOP/.orchestrator and MEMORY.md.",
        "C01": "Dedup uses canonical content signatures, not timestamps alone.",
        "T03": "No smoke-test fine-tune run is present yet.",
    }
    partial = {
        "D02": "Current JSONL records include timestamp/type/instruction/input/output, but no enforced global schema with signal, node_id, and session_id.",
        "D04": "Steering traces are partly separated in iterations/decisions, but the training dataset is not fully partitioned or weighted yet.",
        "C03": "Raw collected artifacts are visible, but a clean post-filter training metric is not yet computed.",
    }
    unknown = {
        "C02": "No acceptance/rejection quality thresholds are codified yet.",
        "T01": "No fine-tuning framework is selected in repo config.",
        "T02": "Base model choice is still unresolved, including 24B vs 9B direction.",
        "T04": "No live VRAM profiling or RTX 5090 headroom metric exists yet.",
    }

    nine_b_target_bytes = int(9_000_000_000 * 20 * 4)
    nine_b_minimum_tuning_bytes = int(max(50_000_000, 9_000_000_000 // 10) * 4)
    current_bytes = int(memory_progress.get("collected_bytes", 0))
    current_tokens = int(memory_progress.get("collected_tokens", 0))
    clean_dataset_ready = False
    framework_ready = False
    training_scripts_present = any(item.is_file() for item in training_scripts)
    can_train_from_scratch = False
    fine_tune_path_ready = bool(jsonl_files)

    recommendation = "Fine-tune-first path is realistic; from-scratch training is not justified by current repo readiness."
    if not fine_tune_path_ready:
        recommendation = "Data pipeline still needs normalization before even a fine-tune-first path is reliable."

    return {
        "questions_scanned": 11,
        "known_count": len(known),
        "partial_count": len(partial),
        "unknown_count": len(unknown),
        "known": known,
        "partial": partial,
        "unknown": unknown,
        "current_collected_bytes": current_bytes,
        "current_collected_tokens": current_tokens,
        "current_jsonl_files": len(jsonl_files),
        "current_decision_files": len(decision_files),
        "training_scripts_present": training_scripts_present,
        "clean_dataset_ready": clean_dataset_ready,
        "framework_ready": framework_ready,
        "fine_tune_path_ready": fine_tune_path_ready,
        "can_train_from_scratch": can_train_from_scratch,
        "target_24b_bytes": int(memory_progress.get("target_bytes", 0)),
        "target_24b_minimum_tuning_bytes": int(memory_progress.get("minimum_tuning_bytes", 0)),
        "target_9b_bytes": nine_b_target_bytes,
        "target_9b_minimum_tuning_bytes": nine_b_minimum_tuning_bytes,
        "recommendation": recommendation,
    }


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
    training_dir = runtime_dir / "training"
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
    steering_events = parse_steering_events(iterations_dir / "decisions")

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
    memory_progress = build_memory_progress(
        memory_path,
        retrieval_log,
        vector_dir,
        data_dir,
        iterations_dir,
        config,
    )
    scale_analysis = build_scale_analysis(
        config,
        data_dir,
        vector_dir,
        iterations_dir,
        training_dir,
        memory_progress,
    )

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
            "name": f"{memory_progress['percent_display']}% OF 24B GOAL DATA COLLECTED",
            "sub": "LIVE MEMORY INJECTION TOWARD 24B CODING MODEL TARGET",
            "eta_days": None,
            "collection_progress": memory_progress["percent"],
            "success_traces": success_traces,
            "steering_traces": steering_traces,
            "error_traces": error_traces,
            "integrated": model_integrated,
            "memory_graph": memory_progress["points"],
            "memory_collected_tokens": memory_progress["collected_tokens"],
            "memory_target_tokens": memory_progress["target_tokens"],
            "memory_collected_bytes": memory_progress["collected_bytes"],
            "memory_target_bytes": memory_progress["target_bytes"],
            "minimum_tuning_bytes": memory_progress["minimum_tuning_bytes"],
            "minimum_tuning_tokens": memory_progress["minimum_tuning_tokens"],
            "target_model_params": memory_progress["target_model_params"],
            "collection_percent_display": memory_progress["percent_display"],
            "retrieval_lines": memory_progress["retrieval_lines"],
        },
        "scale_analysis": scale_analysis,
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
        "repo_structure": build_repo_structure(runtime_dir, start_dir),
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
        "readiness": build_readiness_state(model_integrated, graph, task_md, state_warnings, verification),
        "task_queue": load_json(task_queue_path, []),
    }

    return dashboard_state
