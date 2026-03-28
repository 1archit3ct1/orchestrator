#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPAWN_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$SPAWN_DIR")"
STOP_DIR="$SPAWN_DIR/STOP"
VAULT_DIR="$STOP_DIR/.orchestrator/vault"
GITIGNORE_FILE="$REPO_ROOT/.gitignore"
DASHBOARD_LOG="$STOP_DIR/.orchestrator/logs/dashboard.log"
DASHBOARD_PID_FILE="$STOP_DIR/.orchestrator/dashboard.pid"
DASHBOARD_URL="http://localhost:5000"

echo "[BOOTSTRAP] Orchestrator bootstrap starting..."
echo
echo "[PATHS] SPAWN: $SPAWN_DIR"
echo "        START: $SCRIPT_DIR"
echo "        STOP:  $STOP_DIR"
echo

mkdir -p "$STOP_DIR/.orchestrator/logs"
mkdir -p "$STOP_DIR/.orchestrator/data"
mkdir -p "$STOP_DIR/.orchestrator/models"
mkdir -p "$STOP_DIR/.orchestrator/vector_store"
mkdir -p "$STOP_DIR/.orchestrator/locks"
mkdir -p "$STOP_DIR/.orchestrator/security"
mkdir -p "$STOP_DIR/.orchestrator/iterations"
mkdir -p "$STOP_DIR/.orchestrator/vault"
mkdir -p "$STOP_DIR/web"
mkdir -p "$STOP_DIR/repos"
mkdir -p "$STOP_DIR/training"
mkdir -p "$STOP_DIR/state"

echo "[SECURITY] Initializing secure vault..."
if [ ! -f "$VAULT_DIR/.env.gpg" ] && [ ! -f "$VAULT_DIR/.env" ]; then
  echo "Provide initial secrets if available. Press Enter to skip each one."
  read -r -s -p "OPENAI_API_KEY: " openai_key
  echo
  read -r -s -p "ANTHROPIC_API_KEY: " anthropic_key
  echo
  read -r -s -p "GITHUB_TOKEN: " github_token
  echo

  cat > "$VAULT_DIR/.env.tmp" <<EOF
# Orchestrator Vault - Created $(date -Iseconds)
# WARNING: Plaintext storage - configure GPG for production.

OPENAI_API_KEY=$openai_key
ANTHROPIC_API_KEY=$anthropic_key
GITHUB_TOKEN=$github_token
EOF

  if command -v gpg >/dev/null 2>&1; then
    if gpg --symmetric --cipher-algo AES256 -o "$VAULT_DIR/.env.gpg" "$VAULT_DIR/.env.tmp" 2>/dev/null; then
      rm -f "$VAULT_DIR/.env.tmp"
      echo "[SECURITY] Vault encrypted with GPG."
    else
      mv "$VAULT_DIR/.env.tmp" "$VAULT_DIR/.env"
      echo "[SECURITY] GPG encryption failed, using plaintext vault."
    fi
  else
    mv "$VAULT_DIR/.env.tmp" "$VAULT_DIR/.env"
    echo "[SECURITY] GPG not available, using plaintext vault."
  fi
fi

echo "[TOOLS] Checking GitHub CLI..."
if command -v gh >/dev/null 2>&1; then
  echo "[TOOLS] GitHub CLI already installed."
else
  echo "[TOOLS] GitHub CLI not found."
  if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update && sudo apt-get install -y gh
    elif command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y gh
    else
      echo "[TOOLS] Install gh manually: https://cli.github.com/"
    fi
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v brew >/dev/null 2>&1; then
      brew install gh
    else
      echo "[TOOLS] Install gh manually for macOS."
    fi
  else
    echo "[TOOLS] Install gh manually for this platform."
  fi
fi

echo "[GIT] Configuring Git identity..."
if [ -z "$(git config --global user.name || true)" ]; then
  read -r -p "Git user name: " git_name
  git config --global user.name "$git_name"
fi
if [ -z "$(git config --global user.email || true)" ]; then
  read -r -p "Git user email: " git_email
  git config --global user.email "$git_email"
fi
echo "[GIT] Using $(git config --global user.name) <$(git config --global user.email)>"

echo "[GIT] Securing runtime files in .gitignore..."
if [ ! -f "$GITIGNORE_FILE" ]; then
  cat > "$GITIGNORE_FILE" <<'EOF'
# Orchestrator Git Ignore
EOF
fi

append_gitignore_line() {
  local line="$1"
  if ! grep -Fqx "$line" "$GITIGNORE_FILE" 2>/dev/null; then
    echo "$line" >> "$GITIGNORE_FILE"
  fi
}

append_gitignore_line ""
append_gitignore_line "# Security: Vault credentials and runtime logs"
append_gitignore_line "SPAWN/STOP/.orchestrator/vault/.env"
append_gitignore_line "SPAWN/STOP/.orchestrator/vault/.env.tmp"
append_gitignore_line "SPAWN/STOP/.orchestrator/vault/.env.gpg"
append_gitignore_line "SPAWN/STOP/.orchestrator/logs/security/"
append_gitignore_line "SPAWN/STOP/.orchestrator/dashboard.pid"

for step in 01-init 02-config 03-templates 04-hooks 05-validation; do
  echo "[STEP] Running $step..."
  step_dir="$SCRIPT_DIR/$step"
  if [ -f "$step_dir/prompt.md" ]; then
    cat "$step_dir/prompt.md"
    echo
  else
    echo "[STEP] No prompt.md in $step_dir, skipping."
  fi
done

cat > "$STOP_DIR/.orchestrator/config.json" <<'EOF'
{
  "repos": [],
  "global_memory_enabled": true,
  "vault_enabled": true,
  "secret_rotation_days": 30,
  "cycle_count": 0,
  "gpu_enabled": false,
  "training_config": {
    "model_name": "deepseek-ai/deepseek-coder-6.7b-instruct",
    "output_dir": "SPAWN/STOP/.orchestrator/models/finetuned"
  }
}
EOF

cat > "$STOP_DIR/.orchestrator/task_queue.json" <<'EOF'
[]
EOF

cat > "$STOP_DIR/state/design_graph.json" <<'EOF'
{
  "nodes": [
    {
      "id": "auth_api",
      "label": "T01 Auth API",
      "description": "Ship the authentication API surface that establishes the guarded entry point for spawned work.",
      "allowed_paths": ["SPAWN/STOP/web/app.py"],
      "dependencies": [],
      "status": "green",
      "task_name": "auth-api",
      "task_id": "T01",
      "display_status": "complete"
    },
    {
      "id": "dash_shell",
      "label": "T02 Dashboard Shell",
      "description": "Build the dashboard shell that hosts orchestration state, task views, and system panels.",
      "allowed_paths": ["SPAWN/STOP/web/templates/index.html"],
      "dependencies": ["auth_api"],
      "status": "green",
      "task_name": "dash-shell",
      "task_id": "T02",
      "display_status": "complete"
    },
    {
      "id": "dag_monitor",
      "label": "T03 DAG Monitor",
      "description": "Render and monitor live DAG execution so the active task, progress, and queue state stay visible.",
      "allowed_paths": ["SPAWN/STOP/web/static/script.js"],
      "dependencies": ["dash_shell"],
      "status": "red",
      "task_name": "dag-monitor",
      "task_id": "T03",
      "display_status": "active",
      "progress": 61
    },
    {
      "id": "llm_audit",
      "label": "T04 LLM Audit",
      "description": "Capture autonomous model actions, blocked writes, and policy violations for operator review.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/logs/security/"],
      "dependencies": ["dag_monitor"],
      "status": "red",
      "task_name": "llm-audit",
      "task_id": "T04",
      "display_status": "pending"
    },
    {
      "id": "sec_layer",
      "label": "T05 Security Layer",
      "description": "Enforce the orchestrator security layer that validates protected actions and hardened runtime behavior.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/security_manager.py"],
      "dependencies": ["llm_audit"],
      "status": "red",
      "task_name": "sec-layer",
      "task_id": "T05",
      "display_status": "pending"
    },
    {
      "id": "spawn_gate",
      "label": "T06 Spawn Gate",
      "description": "Gate task dispatch so spawned agents only receive work through the approved queue and policy flow.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/task_queue.json"],
      "dependencies": ["sec_layer"],
      "status": "red",
      "task_name": "spawn-gate",
      "task_id": "T06",
      "display_status": "pending"
    },
    {
      "id": "write_mutex",
      "label": "T07 Write Mutex",
      "description": "Add the repository write lock that serializes file mutation and blocks stray writes outside task scope.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/locks/repo_locks"],
      "dependencies": ["spawn_gate"],
      "status": "red",
      "task_name": "write-mutex",
      "task_id": "T07",
      "display_status": "pending"
    },
    {
      "id": "vec_memory",
      "label": "T08 Vector Memory",
      "description": "Persist retrieval-ready execution memory so prior outcomes can be embedded and reused in planning.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/vector_store/"],
      "dependencies": ["write_mutex"],
      "status": "red",
      "task_name": "vec-memory",
      "task_id": "T08",
      "display_status": "pending"
    },
    {
      "id": "model_eta",
      "label": "T09 Model ETA",
      "description": "Project training milestones from current trace throughput and expose ETA signals to the dashboard.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/models/"],
      "dependencies": ["vec_memory"],
      "status": "red",
      "task_name": "model-eta",
      "task_id": "T09",
      "display_status": "pending"
    },
    {
      "id": "trace_pipe",
      "label": "T10 Trace Pipe",
      "description": "Pipe loop, task, and memory events into append-only traces for exports, steering, and replay.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/iteration_logger.py"],
      "dependencies": ["model_eta"],
      "status": "red",
      "task_name": "trace-pipe",
      "task_id": "T10",
      "display_status": "pending"
    },
    {
      "id": "train_pipeline",
      "label": "T11 Training Pipeline",
      "description": "Turn captured traces into the model-training pipeline that exports datasets and powers iterative learning.",
      "allowed_paths": ["SPAWN/STOP/training/"],
      "dependencies": ["trace_pipe"],
      "status": "red",
      "task_name": "train-pipeline",
      "task_id": "T11",
      "display_status": "pending"
    }
  ],
  "edges": [
    { "from": "auth_api", "to": "dash_shell" },
    { "from": "dash_shell", "to": "dag_monitor" },
    { "from": "dag_monitor", "to": "llm_audit" },
    { "from": "llm_audit", "to": "sec_layer" },
    { "from": "sec_layer", "to": "spawn_gate" },
    { "from": "spawn_gate", "to": "write_mutex" },
    { "from": "write_mutex", "to": "vec_memory" },
    { "from": "vec_memory", "to": "model_eta" },
    { "from": "model_eta", "to": "trace_pipe" },
    { "from": "trace_pipe", "to": "train_pipeline" }
  ]
}
EOF

cat > "$STOP_DIR/state/tasks.json" <<'EOF'
[]
EOF

cat > "$STOP_DIR/TASK.md" <<'EOF'
---
task_id: task_001
dag_node_id: auth_api
allowed_paths:
  - SPAWN/STOP/web/app.py
priority: 1
---

# Task: Auth API

## Description
Ship the authentication API surface that establishes the guarded entry point for spawned work.

## Allowed Paths
You may ONLY write to: `SPAWN/STOP/web/app.py`

## Context
This is the first task in the orchestrator DAG. The live dashboard is expected to reflect runtime state as the graph progresses.

## Status: PENDING
EOF

if [[ "$OSTYPE" == "linux-gnu"* ]] || [[ "$OSTYPE" == "darwin"* ]]; then
  chmod -R 555 "$SCRIPT_DIR" 2>/dev/null || true
  echo "[LOCK] START directory locked read-only."
fi

echo "[DASHBOARD] Starting live dashboard..."

port_available() {
  python3 - <<'PY'
import socket
sock = socket.socket()
try:
    sock.bind(("127.0.0.1", 5000))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

if port_available; then
  (
    cd "$STOP_DIR"
    nohup python3 web/app.py > "$DASHBOARD_LOG" 2>&1 &
    echo $! > "$DASHBOARD_PID_FILE"
  )
  sleep 2
  echo "[DASHBOARD] Live view started at $DASHBOARD_URL"
else
  echo "[DASHBOARD] Port 5000 already in use. Reusing existing service if present."
fi

if command -v wslview >/dev/null 2>&1; then
  wslview "$DASHBOARD_URL" >/dev/null 2>&1 || true
elif command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -NoProfile -Command "Start-Process '$DASHBOARD_URL'" >/dev/null 2>&1 || true
fi

echo
echo "[DONE] Bootstrap complete."
echo
echo "[NEXT]"
echo "  1. Configure SPAWN/STOP/.orchestrator/config.json with repo details"
echo "  2. Add child repos to SPAWN/STOP/repos/"
echo "  3. Review SPAWN/STOP/TASK.md"
echo "  4. Run the orchestrator loop: cd SPAWN/STOP && python3 .orchestrator/loop.py"
echo "  5. Live dashboard: $DASHBOARD_URL"
echo
echo "[WORKFLOW]"
echo "  - The orchestrator reads SPAWN/STOP/TASK.md and executes the task"
echo "  - On completion, the task is marked done and the next task is loaded"
echo "  - The dashboard auto-renders the live state from repo files"
echo "  - Add new tasks by editing SPAWN/STOP/state/tasks.json"
