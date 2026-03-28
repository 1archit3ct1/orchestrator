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
    "integrated": false,
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
      "id": "loop_runtime",
      "label": "T01 Loop Runtime",
      "description": "Keep the orchestrator loop aligned to the SPAWN/STOP child-repo contract so coordination can run from the repo as designed.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/loop.py"],
      "dependencies": [],
      "status": "red",
      "task_name": "loop-runtime",
      "task_id": "T01",
      "display_status": "pending"
    },
    {
      "id": "task_queue_seeded",
      "label": "T02 Task Queue Seeded",
      "description": "Populate task_queue.json with priority-ordered child tasks so the orchestrator has real work to coordinate.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/task_queue.json"],
      "dependencies": ["loop_runtime"],
      "status": "red",
      "task_name": "task-queue",
      "task_id": "T02",
      "display_status": "pending"
    },
    {
      "id": "child_repos_ready",
      "label": "T03 Child Repos Ready",
      "description": "Create or clone child repos with their own SPAWN/STOP runtimes so orchestrated dispatch has real targets.",
      "allowed_paths": ["SPAWN/STOP/repos/"],
      "dependencies": ["loop_runtime"],
      "status": "red",
      "task_name": "child-repos",
      "task_id": "T03",
      "display_status": "pending"
    },
    {
      "id": "training_pipeline_scaffold",
      "label": "T04 Training Pipeline Scaffold",
      "description": "Create the training scripts that collect logs, prepare datasets, train models, and evaluate outputs.",
      "allowed_paths": ["SPAWN/STOP/training/"],
      "dependencies": ["child_repos_ready"],
      "status": "red",
      "task_name": "training-pipeline",
      "task_id": "T04",
      "display_status": "pending"
    },
    {
      "id": "runtime_tasks_derived",
      "label": "T05 Runtime Tasks Derived",
      "description": "Derive executable tasks.json entries from the orchestrator design graph so the loop can advance task ownership cleanly.",
      "allowed_paths": ["SPAWN/STOP/state/tasks.json"],
      "dependencies": ["task_queue_seeded"],
      "status": "red",
      "task_name": "runtime-tasks",
      "task_id": "T05",
      "display_status": "pending"
    },
    {
      "id": "vector_store_seeded",
      "label": "T06 Vector Store Seeded",
      "description": "Seed the vector store with memory and prior orchestration context so retrieval can inform future cycles.",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/vector_store/"],
      "dependencies": ["runtime_tasks_derived", "training_pipeline_scaffold"],
      "status": "red",
      "task_name": "vector-store",
      "task_id": "T06",
      "display_status": "pending"
    }
  ],
  "edges": [
    { "from": "loop_runtime", "to": "task_queue_seeded" },
    { "from": "loop_runtime", "to": "child_repos_ready" },
    { "from": "child_repos_ready", "to": "training_pipeline_scaffold" },
    { "from": "task_queue_seeded", "to": "runtime_tasks_derived" },
    { "from": "runtime_tasks_derived", "to": "vector_store_seeded" },
    { "from": "training_pipeline_scaffold", "to": "vector_store_seeded" }
  ]
}
EOF

cat > "$STOP_DIR/state/tasks.json" <<'EOF'
[]
EOF

cat > "$STOP_DIR/TASK.md" <<'EOF'
---
task_id: task_002
dag_node_id: task_queue_seeded
allowed_paths:
  - SPAWN/STOP/.orchestrator/task_queue.json
priority: 2
---

# Task: Seed Task Queue

## Description
Populate `SPAWN/STOP/.orchestrator/task_queue.json` with priority-ordered child tasks so the orchestrator can start coordinating real repo work.

## Allowed Paths
You may ONLY write to: `SPAWN/STOP/.orchestrator/task_queue.json`

## Context
The loop runtime is structural. The next real gap in the original plan is giving the orchestrator actual child tasks to read, prioritize, and dispatch.

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
echo "  - 1. Read task_queue.json (priority-ordered child tasks)"
echo "  - 2. Query vector store for relevant context"
echo "  - 3. Call loop.py with state + child repo requirements"
echo "  - 4. Dispatch tasks to child repos via allowed_paths"
echo "  - 5. Collect child logs into SPAWN/STOP/.orchestrator/logs/"
echo "  - 6. Train or update models if training data is available"
echo "  - 7. Append orchestration results to the vector store"
echo "  - 8. Update task_queue.json with next priorities"
echo "  - 9. Finalize state when orchestration completes"
echo "  - 10. Repeat until all coordinated tasks complete"
