#!/usr/bin/env python3
"""
Orchestrator Dashboard - Flask Backend

Serves the designed dashboard from `state/design.html` and hydrates it with
live orchestrator state so the browser always reflects the repo as-built.
"""

import json
import logging
import os
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
      .card-operational .stat-val {
        text-shadow: 0 0 22px var(--green-glow) !important;
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
        + '<div class="' + taskRowClass(task) + '">'
        + '<span class="task-id">' + escapeHtml(task.task_id || task.id) + '</span>'
        + '<span class="task-name">' + escapeHtml(task.label) + '</span>'
        + '<span class="task-status ' + taskStatusClass(task) + '">' + escapeHtml(taskStatusLabel(task)) + '</span>'
        + progress
        + '</div>';
    }).join('');
    setOperational(dagList.closest('.card'), Array.isArray(data.tasks) && data.tasks.length > 0);
  }

  function renderModelPanel(data) {
    setText(qs('.model-name'), textOr(data.model.name, '0.0% MODEL DATA COLLECTED'));
    setText(qs('.model-sub'), textOr(data.model.sub, 'LIVE MEMORY INJECTION TOWARD 24B CODING GOAL'));
    setText(qs('.eta-num'), String((data.model && data.model.memory_collected_units) || 0));
    setText(qs('.eta-unit'), 'UNITS');
    setText(qs('.eta-label'), 'REPO-BACKED MEMORY INJECTIONS TOWARD MODEL GOAL');
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
    if (traceLabels[0]) setText(traceLabels[0], 'MEMORY INJECTIONS');
    if (traceLabels[1]) setText(traceLabels[1], 'TARGET UNITS');
    if (traceVals[0]) setText(traceVals[0], ((data.model && data.model.memory_collected_units) || 0).toLocaleString());
    if (traceVals[1]) setText(traceVals[1], ((data.model && data.model.memory_target_units) || 0).toLocaleString());

    const traceSplit = qs('.trace-split');
    if (traceSplit) {
      let graph = qs('.memory-graph');
      if (graph) graph.remove();
      traceSplit.insertAdjacentHTML('afterend', buildMemoryGraph(data.model && data.model.memory_graph));
    }
  }

  function renderAuditPanels(data) {
    const auditBody = qs('.audit-body');
    if (auditBody) {
      const message = data.stray_events[0] || 'No stray writes detected in recent security logs.';
      auditBody.innerHTML = ''
        + '<div class="stray-alert">'
        + '<div class="stray-hdr"><span class="stray-icon">!</span> '
        + escapeHtml(data.summary.stray_count ? 'STRAY EVENT DETECTED' : 'AUDIT LOG CLEAR')
        + '</div>'
        + '<div class="stray-body">' + escapeHtml(message) + '</div>'
        + '</div>';
    }

    setOperational(auditBody ? auditBody.closest('.card') : null, Array.isArray(data.stray_events));

    const warnBadge = qs('.panel-badge.warn');
    if (warnBadge) setText(warnBadge, String((data.summary.stray_count || 0) + ' ALERT'));

    const steeringBody = qs('.steering-body');
    if (steeringBody) {
      const steeringText = (data.steering_events && data.steering_events[0]) || 'No high-priority steering trace has been captured yet.';
      steeringBody.innerHTML = ''
        + '<div class="steering-entry">'
        + '<div class="steering-tags"><span class="stag stag-arch">LIVE</span><span class="stag stag-resolved">STATE</span></div>'
        + '<div class="steering-text">' + escapeHtml(steeringText) + '</div>'
        + '<div class="steering-note">Trace: NEXTAURA // ORCHESTRATOR · ' + escapeHtml(formatClock(data.generated_at)) + '</div>'
        + '</div>';
    }
    setOperational(steeringBody ? steeringBody.closest('.card') : null, Array.isArray(data.steering_events));
  }

  function renderSpawnPanel(data) {
    const values = qsa('.spawn-body .spawn-val');
    const activeTask = data.active_task || {};
    if (values[0]) setText(values[0], String(data.summary.dag_active || 0));
    if (values[1]) setText(values[1], data.summary.dag_active ? 'RUNNING' : 'IDLE');
    if (values[2]) setText(values[2], (activeTask.task_id || '--') + ' -> ' + (activeTask.label || 'waiting'));
    if (values[3]) setText(values[3], activeTask.progress === null || activeTask.progress === undefined ? '--' : String(activeTask.progress) + '%');
    setText(qs('.spawn-label-text'), data.summary.dag_active ? 'SPAWN ACTIVE' : 'SPAWN IDLE');
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

  function renderRepoFreeze(data) {
    const mutexBadge = qs('.repo-lock .mutex-badge');
    const mutexDot = qs('.repo-lock .mutex-dot');
    const freezeLabel = qs('.freeze-label');
    const freezeNote = qs('.freeze-note');
    const toggle = qs('.toggle-wrap');
    const toggleThumb = qs('.toggle-thumb');
    const held = !!(data.repo_freeze && data.repo_freeze.mutex_held);

    if (mutexBadge) mutexBadge.innerHTML = '<div class="mutex-dot"></div>' + (held ? 'MUTEX HELD' : 'MUTEX OPEN');
    if (mutexDot) {
      mutexDot.style.background = held ? 'var(--red)' : 'var(--green)';
      mutexDot.style.boxShadow = held ? '0 0 8px var(--red-glow)' : '0 0 8px var(--green-glow)';
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
  }

  function renderTraceCapture(data) {
    const traceBody = qs('.trace-body');
    if (!traceBody) return;
    traceBody.innerHTML = data.trace_entries.map(function (entry) {
      return ''
        + '<div class="trace-entry">'
        + '<span class="trace-time">' + escapeHtml(textOr(entry.timestamp, formatClock(data.generated_at))) + '</span>'
        + '<span class="trace-event">' + escapeHtml(entry.text) + '</span>'
        + '<span class="trace-tag ' + traceTagClass(entry.type) + '">' + escapeHtml((entry.type || 'loop').toUpperCase()) + '</span>'
        + '</div>';
    }).join('');

    const tracePanelBadge = qsa('.bento3 .panel-badge');
    if (tracePanelBadge[0]) setText(tracePanelBadge[0], '+' + String(data.trace_entries.length) + ' canonical');
  }

  function renderMemoryFiles(data) {
    const container = qs('.mem-files');
    if (!container) return;
    container.innerHTML = data.memory_files.map(function (item) {
      return ''
        + '<div class="mem-file">'
        + '<span class="mem-file-icon">[]</span>'
        + '<span class="mem-file-name">' + escapeHtml(item.name) + '</span>'
        + '<span class="mem-file-size">' + escapeHtml(item.size) + '</span>'
        + '</div>';
    }).join('');
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

  function applyState(data) {
    ensureOperationalStyles();
    bindNavPanels();
    renderTopBar(data);
    renderStatRow(data);
    renderDagList(data);
    renderModelPanel(data);
    renderAuditPanels(data);
    renderSpawnPanel(data);
    renderRepoFreeze(data);
    renderPolicyAndStray(data);
    renderTraceCapture(data);
    renderMemoryFiles(data);
    renderStatusbar(data);
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
