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


def ensure_json_exists(path: Path, data):
    if not path.exists():
        write_json_if_changed(path, data)


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


def load_training_artifact(path: Path):
    if not path.exists():
        return {}
    return load_json(path, {})


def estimate_text_tokens(path: Path):
    text = read_text(path, default="")
    if not text:
        return 0
    words = re.findall(r"\S+", text)
    if words:
        return max(1, math.ceil(len(words) * 1.3))
    return max(1, math.ceil(len(text) / 4))


def verify_dashboard_integrations(runtime_dir: Path):
    orchestrator_dir = runtime_dir / ".orchestrator"
    web_dir = runtime_dir / "web"
    state_dir = runtime_dir / "state"
    template_dir = runtime_dir / "web" / "templates"
    app_path = web_dir / "app.py"
    design_path = template_dir / "repo_truth.html"
    app_text = read_text(app_path)
    design_text = read_text(design_path) + "\n" + app_text

    checks = {
        "gui_nav_panels": {
            "live": "function handleNavPanel" in app_text and "view-chip" in design_text,
            "reason": "dashboard surface routing works from the repo-truth shell with explicit view controls and full-page fallback"
            if "function handleNavPanel" in app_text and "view-chip" in design_text
            else "dashboard surface routing is not wired to the repo-truth shell",
        },
        "gui_dag_task_details": {
            "live": "Execution DAG" not in design_text and "/api/task/<task_id>" not in app_text and "@app.route(\"/api/dag\")" not in app_text,
            "reason": "repo-truth routing depends on queue summaries and no old DAG task list panel remains"
            if "Execution DAG" not in design_text and "/api/task/<task_id>" not in app_text and "@app.route(\"/api/dag\")" not in app_text
            else "an old DAG task list panel is still present in the repo-truth frontend or backend routes",
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
            "live": "function bindExportButtons" in app_text and "/api/export/jsonl" in app_text,
            "reason": "JSONL export button is wired to a real export endpoint"
            if "function bindExportButtons" in app_text and "/api/export/jsonl" in app_text
            else "JSONL export is not wired to repo-backed export logic",
        },
        "gui_export_alpaca": {
            "live": "function bindExportButtons" in app_text and "/api/export/alpaca" in app_text,
            "reason": "Alpaca export button is wired to a real export endpoint"
            if "function bindExportButtons" in app_text and "/api/export/alpaca" in app_text
            else "Alpaca export is not wired to repo-backed export logic",
        },
        "gui_export_sharegpt": {
            "live": "function bindExportButtons" in app_text and "/api/export/sharegpt" in app_text,
            "reason": "ShareGPT export button is wired to a real export endpoint"
            if "function bindExportButtons" in app_text and "/api/export/sharegpt" in app_text
            else "ShareGPT export is not wired to repo-backed export logic",
        },
        "gui_export_steering": {
            "live": "function bindExportButtons" in app_text and "/api/export/steering" in app_text,
            "reason": "Steering-only export button is wired to a real export endpoint"
            if "function bindExportButtons" in app_text and "/api/export/steering" in app_text
            else "Steering-only export is not wired to repo-backed export logic",
        },
        "gui_repo_freeze_toggle": {
            "live": 'data-control="repo-freeze"' in app_text and "/api/control/repo-freeze" in app_text,
            "reason": "repo freeze toggle can mutate live freeze state through Flask"
            if 'data-control="repo-freeze"' in app_text and "/api/control/repo-freeze" in app_text
            else "repo freeze toggle is display-only and has no control endpoint",
        },
        "gui_spawn_loop_controls": {
            "live": "spawn-start-btn" in app_text and "spawn-pause-btn" in app_text and "/api/control/spawn-loop" in app_text,
            "reason": "spawn loop controls are wired to a live Flask control plane"
            if "spawn-start-btn" in app_text and "spawn-pause-btn" in app_text and "/api/control/spawn-loop" in app_text
            else "spawn loop controls are not wired to a control endpoint",
        },
        "gui_audit_log_details": {
            "live": "audit-body" in app_text and "/api/audit/events" in app_text and "function renderAuditPanels" in app_text,
            "reason": "audit log panel opens repo-backed audit event details"
            if "audit-body" in app_text and "/api/audit/events" in app_text and "function renderAuditPanels" in app_text
            else "audit log panel is not wired to detailed audit events",
        },
        "gui_stray_monitor_details": {
            "live": "stray-mon-body" in app_text and "/api/stray/events" in app_text and "function renderStrayLog" in app_text,
            "reason": "stray monitor panel opens repo-backed stray event details"
            if "stray-mon-body" in app_text and "/api/stray/events" in app_text and "function renderStrayLog" in app_text
            else "stray monitor panel is not wired to detailed stray events",
        },
        "gui_readiness_tracker_live": {
            "live": 'data-readiness-key="' in design_text and "function renderReadinessTracker" in app_text,
            "reason": "readiness tracker rows are rendered from canonical repo state"
            if 'data-readiness-key="' in design_text and "function renderReadinessTracker" in app_text
            else "readiness tracker is still mostly static text and not a live function surface",
        },
        "gui_training_run_details": {
            "live": "data-training-run-root" in app_text and "/api/training/run" in app_text and "function renderTrainingRunDetails" in app_text,
            "reason": "training run section opens detailed repo-backed training state"
            if "data-training-run-root" in app_text and "/api/training/run" in app_text and "function renderTrainingRunDetails" in app_text
            else "training run panel is not wired to detailed repo-backed training state",
        },
        "gui_dataset_details": {
            "live": "data-dataset-root" in app_text and "/api/dataset/details" in app_text and "function renderDatasetDetails" in app_text,
            "reason": "dataset section opens detailed repo-backed dataset state"
            if "data-dataset-root" in app_text and "/api/dataset/details" in app_text and "function renderDatasetDetails" in app_text
            else "dataset panel is not wired to detailed repo-backed dataset state",
        },
        "gui_eta_tracker_live": {
            "live": "data-eta-root" in app_text and "function renderEtaTracker" in app_text,
            "reason": "ETA tracker renders detailed canonical ETA state"
            if "data-eta-root" in app_text and "function renderEtaTracker" in app_text
            else "ETA tracker is not wired to canonical repo-backed ETA detail rendering",
        },
        "gui_scale_analysis_page": {
            "live": "scale-analysis-body" in app_text and "function renderScaleAnalysis" in app_text,
            "reason": "scale analysis page renders repo-backed recommendations, thresholds, and viability guidance"
            if "scale-analysis-body" in app_text and "function renderScaleAnalysis" in app_text
            else "scale analysis page is not wired to repo-backed viability rendering",
        },
        "gui_trace_capture_details": {
            "live": "trace-body" in app_text and "/api/traces" in app_text and "function renderTraceCapture" in app_text,
            "reason": "trace capture section opens detailed repo-backed trace history"
            if "trace-body" in app_text and "/api/traces" in app_text and "function renderTraceCapture" in app_text
            else "trace capture section is not wired to detailed repo-backed trace history",
        },
        "gui_steering_log_details": {
            "live": 'data-steering-root="true"' in app_text and "/api/steering/events" in app_text and "function renderSteeringDetails" in app_text,
            "reason": "steering log surface renders detailed repo-backed steering events"
            if 'data-steering-root="true"' in app_text and "/api/steering/events" in app_text and "function renderSteeringDetails" in app_text
            else "steering log surface is not wired to detailed repo-backed steering events",
        },
        "gui_mutex_lock_details": {
            "live": "function openMutexLockDetails" in app_text and "/api/repo-freeze/state" in app_text,
            "reason": "mutex status box opens detailed live lock ownership and gating state"
            if "function openMutexLockDetails" in app_text and "/api/repo-freeze/state" in app_text
            else "mutex status box is not wired to detailed live lock state",
        },
        "gui_model_status_panel": {
            "live": 'data-model-status-root' in design_text and "/api/model/status" in app_text and "function renderModelStatusDetails" in app_text,
            "reason": "model status surface is a first-class repo-backed function with readiness, graph rendering, and training-scale state"
            if 'data-model-status-root' in design_text and "/api/model/status" in app_text and "function renderModelStatusDetails" in app_text
            else "model status surface is not wired to explicit repo-backed status rendering",
        },
    }
    return checks
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


def build_activity_feed(runtime_dir: Path, logs_dir: Path, iterations_dir: Path, data_dir: Path, retrieval_log: Path, memory_path: Path, limit=12):
    events = []

    def push(ts: float, text: str, trace_type: str, tag: str):
        events.append(
            {
                "timestamp": datetime.fromtimestamp(ts).strftime("%H:%M:%S"),
                "text": text,
                "type": trace_type,
                "tag": tag,
                "ts": ts,
            }
        )

    for path in sorted(iterations_dir.glob("iter_*.json"))[-limit:]:
        payload = load_json(path, {})
        summary = payload.get("summary") or payload.get("type") or path.stem
        push(path.stat().st_mtime, f"iteration artifact captured - {summary}", "task", "TASK")

    decisions_dir = iterations_dir / "decisions"
    for path in sorted(decisions_dir.glob("dec_*.json"))[-limit:]:
        payload = load_json(path, {})
        decision = payload.get("decision", {})
        if isinstance(decision, dict):
            question = decision.get("question") or payload.get("summary") or path.stem
        else:
            question = str(decision or payload.get("summary") or path.stem)
        push(path.stat().st_mtime, f"steering decision logged - {question}", "model", "MODEL")

    for path in sorted(data_dir.glob("*.jsonl"))[-limit:]:
        payload_lines = tail_lines(path, 1)
        summary = path.stem
        if payload_lines:
            try:
                payload = json.loads(payload_lines[-1])
                summary = payload.get("summary") or payload.get("miss_type") or summary
            except json.JSONDecodeError:
                pass
        push(path.stat().st_mtime, f"dataset event stored - {summary}", "mem", "MEM")

    if retrieval_log.exists():
        lines = tail_lines(retrieval_log, min(limit, 6))
        for index, line in enumerate(lines):
            push(retrieval_log.stat().st_mtime + (index * 0.001), f"retrieval log updated - {line[:96]}", "mem", "MEM")

    if memory_path.exists():
        push(memory_path.stat().st_mtime, "memory ledger updated", "mem", "MEM")

    task_queue_path = runtime_dir / ".orchestrator" / "task_queue.json"
    if task_queue_path.exists():
        push(task_queue_path.stat().st_mtime, "queue state updated", "task", "TASK")

    events.sort(key=lambda item: item["ts"])
    return [{key: value for key, value in item.items() if key != "ts"} for item in events[-limit:]]


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


def build_memory_files(memory_md: Path, vector_dir: Path, retrieval_log: Path, agents_md: Path, task_queue_path: Path):
    files = []
    if memory_md.exists():
        files.append({"name": "MEMORY.md", "size": f"append-only - {format_bytes(memory_md.stat().st_size)}"})
    if vector_dir.exists():
        files.append({"name": "vector_store/", "size": f"{count_files(vector_dir, '*.json')} entries - {format_bytes(directory_size(vector_dir))}"})
    if agents_md.exists():
        files.append({"name": "AGENTS.md", "size": f"runtime prompt - {format_bytes(agents_md.stat().st_size)}"})
    if retrieval_log.exists():
        files.append({"name": "retrieval_log.jsonl", "size": f"{format_bytes(retrieval_log.stat().st_size)}"})
    if task_queue_path.exists():
        files.append({"name": "task_queue.json", "size": format_bytes(task_queue_path.stat().st_size)})
    return files


def ensure_projection_runtime_files(state_dir: Path):
    projection_files = {
        "extraction.json": {
            "canonical": True,
            "mode": "projection-first",
            "stage": "extractor",
            "status": "draft",
            "generated_at": None,
            "structures": [],
            "warnings": [],
            "source": "pending_extractor_output",
        },
        "operator_overrides.json": {
            "canonical": True,
            "mode": "projection-first",
            "updated_at": None,
            "renames": [],
            "merges": [],
            "splits": [],
            "suppressions": [],
            "notes": [],
        },
        "projected_tasks.json": {
            "canonical": True,
            "mode": "projection-first",
            "generated_at": None,
            "approval_state": "draft",
            "tasks": [],
        },
        "projection_graph.json": {
            "canonical": True,
            "mode": "projection-first",
            "generated_at": None,
            "approval_state": "draft",
            "nodes": [],
            "edges": [],
        },
        "projection_pipeline.json": {
            "canonical": True,
            "mode": "projection-first",
            "active_stage": "extractor",
            "approved": False,
            "promotion_ready": False,
            "prompt_handoff_ready": False,
            "stages": [
                {"id": "extractor", "label": "Extractor", "status": "active"},
                {"id": "operator_review", "label": "Operator Review", "status": "pending"},
                {"id": "task_generation", "label": "Task Generator", "status": "pending"},
                {"id": "promotion_gate", "label": "Promotion Gate", "status": "pending"},
                {"id": "prompt_handoff", "label": "Prompt Handoff", "status": "pending"},
            ],
            "notes": [
                "Projection state must remain separate from canonical execution state until approval and promotion complete."
            ],
        },
    }
    for name, payload in projection_files.items():
        ensure_json_exists(state_dir / name, payload)


def ensure_repo_truth_runtime_files(state_dir: Path):
    repo_truth_files = {
        "repo_truth_frontend.json": {
            "canonical": True,
            "mode": "repo-truth-frontend",
            "status": "live",
            "default_route": "/",
            "notes": [
                "The repo-truth frontend must read canonical backend state domains directly.",
                "The repo-truth frontend is the single live dashboard surface.",
            ],
        },
        "frontend_state_views.json": {
            "canonical": True,
            "mode": "repo-truth-frontend",
            "views": [
                {"id": "summary", "label": "Execution Summary", "endpoint": "/api/repo-truth/summary"},
                {"id": "queue", "label": "Strategic Queue", "endpoint": "/api/repo-truth/queue"},
                {"id": "projection", "label": "Projection Pipeline", "endpoint": "/api/projection/state"},
                {"id": "runtime", "label": "Backend Runtime", "endpoint": "/api/runtime/mirror"},
                {"id": "memory", "label": "Memory and Vector", "endpoint": "/api/repo-truth/memory"},
                {"id": "training", "label": "Training State", "endpoint": "/api/repo-truth/training"},
                {"id": "misses", "label": "Miss Detection", "endpoint": "/api/runtime/misses"},
            ],
            "generated_at": None,
        },
    }
    for name, payload in repo_truth_files.items():
        ensure_json_exists(state_dir / name, payload)


def build_projection_state(state_dir: Path):
    extraction = load_json(state_dir / "extraction.json", {})
    overrides = load_json(state_dir / "operator_overrides.json", {})
    projected_tasks = load_json(state_dir / "projected_tasks.json", {})
    projection_graph = load_json(state_dir / "projection_graph.json", {})
    pipeline = load_json(state_dir / "projection_pipeline.json", {})

    stages = pipeline.get("stages", []) if isinstance(pipeline, dict) else []
    active_stage = pipeline.get("active_stage", "extractor") if isinstance(pipeline, dict) else "extractor"
    notes = pipeline.get("notes", []) if isinstance(pipeline, dict) else []
    structures = extraction.get("structures", []) if isinstance(extraction, dict) else []
    warnings = extraction.get("warnings", []) if isinstance(extraction, dict) else []
    tasks = projected_tasks.get("tasks", []) if isinstance(projected_tasks, dict) else []
    nodes = projection_graph.get("nodes", []) if isinstance(projection_graph, dict) else []

    return {
        "canonical": True,
        "mode": "projection-first",
        "active_stage": active_stage,
        "approved": bool(pipeline.get("approved", False)) if isinstance(pipeline, dict) else False,
        "promotion_ready": bool(pipeline.get("promotion_ready", False)) if isinstance(pipeline, dict) else False,
        "prompt_handoff_ready": bool(pipeline.get("prompt_handoff_ready", False)) if isinstance(pipeline, dict) else False,
        "approval_state": projected_tasks.get("approval_state", "draft") if isinstance(projected_tasks, dict) else "draft",
        "counts": {
            "structures": len(structures),
            "warnings": len(warnings),
            "overrides": sum(
                len(overrides.get(key, []))
                for key in ("renames", "merges", "splits", "suppressions", "notes")
                if isinstance(overrides, dict)
            ),
            "projected_tasks": len(tasks),
            "graph_nodes": len(nodes),
        },
        "stages": stages,
        "notes": notes,
        "structures": structures,
        "warnings": warnings,
        "projected_tasks": tasks,
    }


def build_repo_truth_state(state_dir: Path, dashboard_state: dict):
    frontend = load_json(state_dir / "repo_truth_frontend.json", {})
    views = load_json(state_dir / "frontend_state_views.json", {})
    task_queue = dashboard_state.get("task_queue", [])
    task_status_counts = {}
    for item in task_queue:
        status = item.get("status", "pending")
        task_status_counts[status] = task_status_counts.get(status, 0) + 1

    return {
        "canonical": True,
        "mode": frontend.get("mode", "repo-truth-frontend"),
        "status": frontend.get("status", "staged"),
        "default_route": frontend.get("default_route", "/truth"),
        "views": views.get("views", []),
        "notes": frontend.get("notes", []),
        "queue_counts": task_status_counts,
    }


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
        ("MEMORY.md", runtime_dir / "MEMORY.md"),
        ("AGENTS.md", runtime_dir / "AGENTS.md"),
    ]
    for label, path in stop_map:
        if path.exists():
            stop_items.append({"name": label, "detail": "dir" if path.is_dir() else format_bytes(path.stat().st_size)})

    return {"start": start_items, "stop": stop_items}


def build_readiness_state(model_integrated: bool, warnings: list[str], verification: dict, actionable_tasks: list[dict]):
    controls_live = bool(
        verification.get("gui_spawn_loop_controls", {}).get("live")
        and verification.get("gui_repo_freeze_toggle", {}).get("live")
    )
    queue_synced = not actionable_tasks and not warnings
    return [
        {
            "label": "Canonical State",
            "value": "LIVE",
            "status": "live",
        },
        {
            "label": "Training Stack Ready",
            "value": "LIVE" if model_integrated else "PENDING",
            "status": "live" if model_integrated else "pending",
        },
        {
            "label": "Flask Controls Live",
            "value": "LIVE" if controls_live else "PENDING",
            "status": "live" if controls_live else "pending",
        },
        {
            "label": "Queue Sync",
            "value": "ALIGNED" if queue_synced else ("ATTENTION" if warnings else "PENDING"),
            "status": "live" if queue_synced else ("warn" if warnings else "pending"),
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
    metrics = load_training_artifact(data_dir / "clean_dataset_metrics.json")
    framework_contract = load_training_artifact(data_dir / "training_framework_contract.json")
    storage_contract_payload = load_training_artifact(data_dir / "trace_storage_contract.json")
    storage_index_payload = load_training_artifact(data_dir / "trace_storage_index.json")
    vram_profile = load_training_artifact(training_dir.parent / ".orchestrator" / "logs" / "vram_profile.json")
    jsonl_files = sorted(data_dir.glob("*.jsonl")) if data_dir.exists() else []
    training_scripts = sorted(training_dir.rglob("*")) if training_dir.exists() else []
    decision_files = sorted((iterations_dir / "decisions").glob("dec_*.json")) if (iterations_dir / "decisions").exists() else []
    dataset_rows = sum(count_lines(path) for path in jsonl_files)
    vector_entries = count_files(vector_dir, "*.json")
    iteration_files = len(list(iterations_dir.glob("iter_*.json"))) if iterations_dir.exists() else 0
    trace_files = iteration_files + len(decision_files)
    clean_dataset_rows = int(metrics.get("clean_records", 0) or 0)
    duplicate_count = int(metrics.get("duplicate_count", 0) or 0)
    clean_ratio = float(metrics.get("clean_ratio", 0.0) or 0.0)
    framework_name = framework_contract.get("framework")
    base_model = config.get("training_config", {}).get("base_model")

    known = {
        "D01": "Storage contract is codified in trace_storage_contract.json with explicit downstream guarantees.",
        "D02": "Canonical JSONL records include record_id, timestamp, instruction, output, signal, source_type, and source_path.",
        "D03": "Storage index is codified in trace_storage_index.json across data, vector, iterations, and memory.",
        "D04": "Steering traces are explicitly labeled in canonical_traces.jsonl and separated in iterations/decisions.",
        "C01": "Dedup uses canonical content_hash signatures with duplicate counts reported in clean_dataset_metrics.json.",
        "C02": "Quality thresholds are codified in config.json and clean_dataset_metrics.json.",
        "C03": f"Clean dataset metric is live at {clean_dataset_rows:,} accepted rows after dedup/filtering.",
        "T01": f"Fine-tuning framework is selected as {framework_name or 'axolotl'}.",
        "T02": f"Base model is selected as {base_model or 'unset'}.",
        "T04": "Live VRAM profiling is available from .orchestrator/logs/vram_profile.json.",
    }
    partial = {
        "T03": "Smoke-test training flow validates dataset, config, artifact, and VRAM contracts, but no weight-updating fine-tune run has been executed yet.",
    }
    unknown = {}

    nine_b_target_bytes = int(9_000_000_000 * 20 * 4)
    nine_b_minimum_tuning_bytes = int(max(50_000_000, 9_000_000_000 // 10) * 4)
    current_bytes = int(memory_progress.get("collected_bytes", 0))
    current_tokens = int(memory_progress.get("collected_tokens", 0))
    clean_dataset_ready = bool(clean_dataset_rows)
    framework_ready = bool(framework_name and base_model)
    training_scripts_present = any(item.is_file() for item in training_scripts)
    can_train_from_scratch = False
    fine_tune_path_ready = bool(jsonl_files)

    recommendation = "Fine-tune-first path is realistic; from-scratch training is not justified by current repo readiness."
    if not fine_tune_path_ready:
        recommendation = "Data pipeline still needs normalization before even a fine-tune-first path is reliable."

    rows = [
        {
            "label": "Dataset Rows",
            "value": f"{dataset_rows:,}",
            "status": "live" if dataset_rows else "pending",
        },
        {
            "label": "Clean Rows",
            "value": f"{clean_dataset_rows:,}",
            "status": "live" if clean_dataset_rows else "pending",
        },
        {
            "label": "Retrieval Rows",
            "value": f"{int(memory_progress.get('retrieval_lines', 0)):,}",
            "status": "live" if memory_progress.get("retrieval_lines", 0) else "pending",
        },
        {
            "label": "Vector Entries",
            "value": f"{vector_entries:,}",
            "status": "live" if vector_entries else "pending",
        },
        {
            "label": "Trace Files",
            "value": f"{trace_files:,}",
            "status": "live" if trace_files else "pending",
        },
        {
            "label": "Duplicates Removed",
            "value": f"{duplicate_count:,}",
            "status": "live" if duplicate_count else "pending",
        },
    ]

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
        "current_dataset_rows": dataset_rows,
        "current_clean_dataset_rows": clean_dataset_rows,
        "current_decision_files": len(decision_files),
        "current_vector_entries": vector_entries,
        "current_trace_files": trace_files,
        "duplicate_count": duplicate_count,
        "clean_ratio": clean_ratio,
        "training_scripts_present": training_scripts_present,
        "clean_dataset_ready": clean_dataset_ready,
        "framework_ready": framework_ready,
        "fine_tune_path_ready": fine_tune_path_ready,
        "can_train_from_scratch": can_train_from_scratch,
        "framework": framework_name,
        "base_model": base_model,
        "vram_profile": vram_profile,
        "storage_contract": storage_contract_payload,
        "storage_index": storage_index_payload,
        "target_24b_bytes": int(memory_progress.get("target_bytes", 0)),
        "target_24b_minimum_tuning_bytes": int(memory_progress.get("minimum_tuning_bytes", 0)),
        "target_9b_bytes": nine_b_target_bytes,
        "target_9b_minimum_tuning_bytes": nine_b_minimum_tuning_bytes,
        "recommendation": recommendation,
        "rows": rows,
    }


def sync_dashboard_state(runtime_dir: Path):
    runtime_dir = Path(runtime_dir)
    orchestrator_dir = runtime_dir / ".orchestrator"
    state_dir = runtime_dir / "state"
    start_dir = runtime_dir.parent / "START"
    config_path = orchestrator_dir / "config.json"
    task_queue_path = orchestrator_dir / "task_queue.json"
    memory_path = runtime_dir / "MEMORY.md"
    vector_dir = orchestrator_dir / "vector_store"
    data_dir = orchestrator_dir / "data"
    models_dir = orchestrator_dir / "models"
    logs_dir = orchestrator_dir / "logs"
    iterations_dir = orchestrator_dir / "iterations"
    training_dir = runtime_dir / "training"
    locks_dir = orchestrator_dir / "locks"
    locks_path = locks_dir / "repo_locks"
    security_log = logs_dir / "security" / "security_audit.log"
    orchestrator_log = logs_dir / "orchestrator.log"
    iteration_log = logs_dir / "iteration_logger.log"
    retrieval_log = runtime_dir / "retrieval_log.jsonl"
    ensure_projection_runtime_files(state_dir)
    ensure_repo_truth_runtime_files(state_dir)
    config = load_json(config_path, {})
    training_config = config.get("training_config", {})
    task_queue = load_json(task_queue_path, [])
    if not isinstance(task_queue, list):
        task_queue = []
    verification = verify_dashboard_integrations(runtime_dir)
    loop_cycles = int(config.get("cycle_count", 0) or 0)
    tasks = sorted(task_queue, key=lambda item: (item.get("priority", 9999), item.get("id", "")))
    task_counts = task_status_counts(tasks)
    actionable_statuses = {"pending", "in_progress", "active"}
    actionable_tasks = [item for item in tasks if item.get("status", "pending") in actionable_statuses]
    state_warnings = []
    active_task = actionable_tasks[0] if actionable_tasks else None
    completed_count = task_counts["completed"]
    total_count = task_counts["total"]
    queue_progress = round((completed_count / total_count) * 100, 1) if total_count else 100.0
    graph = {
        "status": "queued" if actionable_tasks else "complete",
        "last_cycle": loop_cycles,
        "last_updated": datetime.now().isoformat(),
        "summary": {
            "total_items": total_count,
            "completed_items": completed_count,
            "actionable_items": len(actionable_tasks),
            "progress": queue_progress,
        },
    }

    success_traces = len(list(iterations_dir.glob("iter_*.json"))) if iterations_dir.exists() else 0
    error_traces = len(list((iterations_dir / "errors").glob("err_*.json"))) if (iterations_dir / "errors").exists() else 0
    steering_traces = len(list((iterations_dir / "decisions").glob("dec_*.json"))) if (iterations_dir / "decisions").exists() else 0
    total_training_traces = success_traces + error_traces + steering_traces
    steering_events = parse_steering_events(iterations_dir / "decisions")

    vector_entries = count_files(vector_dir, "*.json")
    vector_size = directory_size(vector_dir)
    training_data_files = count_files(data_dir)
    model_files = len(list(models_dir.rglob("*.pt"))) + len(list(models_dir.rglob("*.bin"))) + len(list(models_dir.rglob("*.safetensors"))) if models_dir.exists() else 0
    log_files = count_files(logs_dir, "*.log")
    security_events = parse_security_events([security_log, orchestrator_log], limit=6)
    security_events.extend(state_warnings)
    security_events = security_events[-6:]
    trace_entries = parse_trace_entries([orchestrator_log, iteration_log], limit=6)
    activity_feed = build_activity_feed(runtime_dir, logs_dir, iterations_dir, data_dir, retrieval_log, memory_path, limit=12)
    if not trace_entries:
        trace_entries = activity_feed[-6:]

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
            "memory": str(memory_path),
            "task_queue": str(task_queue_path),
        },
        "state_warnings": state_warnings,
        "verification": verification,
        "graph": graph,
        "tasks": tasks,
        "active_task": active_task,
        "metrics": {
            "cycles": loop_cycles,
            "dag_progress": {
                "total": total_count,
                "green": completed_count,
                "red": 0,
                "yellow": len(actionable_tasks),
                "progress": queue_progress,
            },
            "task_status": task_counts,
            "vector_store_entries": vector_entries,
            "vector_store_size_bytes": vector_size,
            "training_data_files": training_data_files,
            "model_checkpoints": model_files,
            "log_files": log_files,
            "gpu_enabled": bool(config.get("gpu_enabled", False)),
            "timestamp": datetime.now().isoformat(),
            "model_name": model_name,
            "model_integrated": model_integrated,
        },
        "summary": {
            "loops_executed": loop_cycles,
            "training_traces": total_training_traces,
            "dag_total": total_count,
            "dag_pending": task_counts["pending"],
            "dag_active": len(actionable_tasks),
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
        ] or [
            {
                "source": "activity-feed",
                "content": entry["text"],
                "timestamp": entry["timestamp"],
            }
            for entry in activity_feed[-6:]
        ],
        "trace_entries": trace_entries,
        "activity_feed": activity_feed,
        "stray_events": security_events,
        "steering_events": steering_events,
        "repos": [],
        "bootstrap_steps": build_bootstrap_steps(start_dir),
        "repo_structure": build_repo_structure(runtime_dir, start_dir),
        "vector_phases": build_vector_phases(vector_dir, iterations_dir),
        "memory_files": build_memory_files(
            memory_path,
            vector_dir,
            retrieval_log,
            runtime_dir / "AGENTS.md",
            task_queue_path,
        ),
        "repo_freeze": {
            "mutex_held": (
                lock_is_active(locks_dir / "global_write.lock")
                or (locks_path.exists() and any(lock_is_active(path) for path in locks_path.glob("*.lock")))
            ),
            "lock_path": str(locks_dir),
            "allowed_paths": active_task.get("allowed_paths", []) if active_task else [],
        },
        "spawn_loop": {
            "state": config.get("spawn_loop", {}).get("state", "stopped"),
            "started_at": config.get("spawn_loop", {}).get("started_at"),
            "paused_at": config.get("spawn_loop", {}).get("paused_at"),
            "active_spawns": 1 if config.get("spawn_loop", {}).get("state") == "running" else 0,
            "runner_running": False,  # Updated by Flask app.py at runtime
        },
        "readiness": build_readiness_state(model_integrated, state_warnings, verification, actionable_tasks),
        "projection": build_projection_state(state_dir),
        "task_queue": tasks,
    }
    dashboard_state["repo_truth"] = build_repo_truth_state(state_dir, dashboard_state)

    return dashboard_state
