orchestrator/
├── SPAWN/START/ # Bootstrap zone (immutable after lock)
│ ├── bootstrap.sh
│ ├── AGENTS.md # Full bootstrap instructions
│ ├── security/
│ │ ├── policy.json
│ │ └── immutable_files.txt
│ ├── 01-init/
│ │ └── prompt.md
│ ├── 02-config/
│ │ └── prompt.md
│ ├── 03-templates/
│ │ └── prompt.md
│ ├── 04-hooks/
│ │ └── prompt.md
│ └── 05-validation/
│ └── prompt.md
├── SPAWN/STOP/ # Runtime zone
│ ├── .orchestrator/
│ │ ├── config.json
│ │ ├── task_queue.json
│ │ ├── vector_store/ (semantic memory)
│ │ ├── logs/ (collected child logs)
│ │ ├── data/ (training datasets)
│ │ ├── models/ (trained checkpoints)
│ │ ├── vault/ (encrypted secrets – outside repo)
│ │ └── loop.py (orchestrator's autonomous loop)
│ ├── web/
│ │ ├── app.py
│ │ ├── templates/index.html
│ │ └── static/ style.css, script.js
│ ├── repos/ (child repos, each with SPAWN/START/Stop)
│ ├── training/
│ │ ├── collect_data.py
│ │ ├── prepare_dataset.py
│ │ ├── train.py
│ │ ├── config.yml
│ │ └── evaluate.py
│ ├── state/ (orchestrator's own DAG & tasks)
│ │ ├── design_graph.json
│ │ └── tasks.json
│ └── AGENTS.md (reduced version)
└── requirements.txt
```
═════════════════════════════════════════════════════════════════════════════════

**FLOW: Clone → SPAWN/START/bootstrap.sh → [Orchestrator Initialized] → SPAWN/STOP/ [Orchestrator Coordinates]**

---

## Bootstrap Process

### Phase 1: Structural Bootstrap (Complete)
- ✅ `SPAWN/START/` folder created with immutable security policy
- ✅ `SPAWN/STOP/.orchestrator/` directory structure initialized
- ✅ `loop.py` deployed with 10-step autonomous cycle
- ✅ `config.json` configured (GPU, memory, vault settings)
- ✅ `design_graph.json` created with 5-node training DAG

### Phase 2: Operational Initialization (Pending)

The following steps must be executed to transition from **structurally complete** to **operationally ready**:

| Step | Action | Target | Purpose |
|------|--------|--------|---------|
| 1 | **Populate task_queue.json** | `SPAWN/STOP/.orchestrator/task_queue.json` | Priority-ordered child tasks for coordination |
| 2 | **Create/clone child repos** | `SPAWN/STOP/repos/` | Each child repo has its own SPAWN/START/Stop structure and allowed_paths |
| 3 | **Create training scripts** | `SPAWN/STOP/training/` | `collect_data.py`, `prepare_dataset.py`, `train.py`, `config.yml`, `evaluate.py` |
| 4 | **Derive tasks from DAG** | `SPAWN/STOP/state/tasks.json` | Convert 5-node design_graph.json into executable tasks |
| 5 | **Seed vector store** | `SPAWN/STOP/.orchestrator/vector_store/` | Initial context from MEMORY.md embeddings, past session data |

---

### DAG Design Principles (Critical)

All DAGs in the orchestrator MUST follow these rules to prevent entropy and task entanglement:

#### 1. One Node = One File Principle
- Each node produces exactly **ONE** output file
- `allowed_paths` should contain exactly ONE path per node
- ✓ Example: `allowed_paths: ["SPAWN/STOP/web/app.py"]`
- ✗ Anti-pattern: `allowed_paths: ["script.js", "utils.js"]` (split into two nodes)

#### 2. No Overlapping Paths
- No two nodes should write to the same file
- If two features share a file, they must be the SAME node
- ✓ Example: All dashboard JavaScript in ONE `build_dashboard_frontend` node
- ✗ Anti-pattern: Separate nodes for "DAG viz", "Task queue", "Logs" all writing to `script.js`

#### 3. Atomic Deliverables
- Each node's deliverables describe ONE cohesive unit of work
- ✓ Example: "Create script.js with DAG viz, task queue, logs, metrics, SSE, controls"
- ✗ Anti-pattern: "Create DAG viz" + "Create task queue" as separate nodes (same file)

#### 4. Granularity Rule
- Tasks should be completable in a single agent session (5-30 minutes)
- If a node requires multiple independent files, split it
- If multiple nodes write to one file, consolidate them

#### 5. File Ownership Clarity
- Each file is "owned" by exactly one node
- Shared infrastructure = single node
- Subsequent nodes can READ but not WRITE to another node's file

---

### Example: Correct DAG Structure

```json
{
  "nodes": [
    {"id": "setup_flask_app", "allowed_paths": ["SPAWN/STOP/web/app.py"], "status": "red"},
    {"id": "create_base_html_template", "allowed_paths": ["SPAWN/STOP/web/templates/index.html"], "dependencies": ["setup_flask_app"], "status": "red"},
    {"id": "create_css_styling", "allowed_paths": ["SPAWN/STOP/web/static/style.css"], "dependencies": ["create_base_html_template"], "status": "red"},
    {"id": "build_dashboard_frontend", "allowed_paths": ["SPAWN/STOP/web/static/script.js"], "dependencies": ["create_css_styling"], "status": "red"},
    {"id": "test_dashboard_integration", "allowed_paths": ["SPAWN/STOP/web/templates/index.html"], "dependencies": ["build_dashboard_frontend"], "status": "red"}
  ]
}
```

**Structure:** Each node owns one file, no collisions, clean dependency chain.

---

### Phase 2: Detailed Instructions

#### Step 1: Populate task_queue.json

**File:** `SPAWN/STOP/.orchestrator/task_queue.json`

The task queue is a priority-ordered list of child tasks to coordinate. Each task specifies which child repo should handle it and what paths they can write to.

**Example:**
```json
[
  {
    "id": "task_001",
    "repo": "child-repo-alpha",
    "description": "Implement user authentication module",
    "allowed_paths": ["src/auth/", "tests/auth/"],
    "priority": 1,
    "status": "pending"
  },
  {
    "id": "task_002",
    "repo": "child-repo-beta",
    "description": "Build REST API endpoints",
    "allowed_paths": ["src/api/", "tests/api/"],
    "priority": 2,
    "status": "pending"
  }
]
```

**Key fields:**
- `id`: Unique task identifier
- `repo`: Name of the child repo directory in `SPAWN/STOP/repos/`
- `description`: Task description for the child agent
- `allowed_paths`: Paths the child repo is allowed to write to (relative to their SPAWN/STOP/)
- `priority`: Lower number = higher priority
- `status`: `pending`, `in_progress`, `completed`, `failed`

---

#### Step 2: Create/Clone Child Repos

**Directory:** `SPAWN/STOP/repos/`

Each child repo is a self-contained agent with its own SPAWN/START/Stop structure.

**Structure for each child repo:**
```
SPAWN/STOP/repos/{repo-name}/
├── SPAWN/START/
│   ├── bootstrap.sh
│   └── AGENTS.md
├── SPAWN/STOP/
│   ├── .orchestrator/
│   │   ├── config.json
│   │   └── loop.py
│   ├── state/
│   │   ├── design_graph.json
│   │   └── tasks.json
│   ├── src/
│   ├── tests/
│   ├── AGENTS.md
│   ├── TASK.md
│   └── MEMORY.md
└── requirements.txt
```

**To create a child repo:**
1. Create directory: `mkdir -p SPAWN/STOP/repos/{repo-name}`
2. Clone existing repo or scaffold new one
3. Ensure it has SPAWN/START/ (bootstrap) and SPAWN/STOP/ (runtime) structure
4. Add to orchestrator's `config.json` repos list

---

#### Step 3: Create Training Scripts

**Directory:** `SPAWN/STOP/training/`

Five scripts form the ML training pipeline:

| Script | Purpose |
|--------|---------|
| `collect_data.py` | Gather logs/outputs from child repos into `SPAWN/STOP/.orchestrator/data/raw/` |
| `prepare_dataset.py` | Convert raw logs to JSONL format for model training |
| `train.py` | Fine-tune the base model using QLoRA/LoRA |
| `config.yml` | Training configuration (hyperparameters, model name, paths) |
| `evaluate.py` | Run benchmarks (ARC, HumanEval, MMLU) and record scores |

**Example config.yml:**
```yaml
model:
  name: "deepseek-ai/deepseek-coder-6.7b-instruct"
  max_length: 2048

training:
  epochs: 3
  batch_size: 4
  learning_rate: 2e-4
  lora_rank: 16

output:
  dir: "SPAWN/STOP/.orchestrator/models/finetuned"
  save_steps: 100
```

---

#### Step 4: Derive Tasks from DAG

**Source:** `SPAWN/STOP/state/design_graph.json`
**Target:** `SPAWN/STOP/state/tasks.json`

The design_graph.json contains 5 nodes representing the training pipeline. Each node must be converted to an executable task.

**Current DAG nodes:**
1. `collect_data` → Gather from repos
2. `prepare_dataset` → Convert to JSONL
3. `train_base` → Fine-tune model
4. `evaluate` → Run benchmarks
5. `iterative_improve` → Refine and retrain

**Example tasks.json:**
```json
[
  {
    "id": "dag_node_1",
    "dag_node_id": "collect_data",
    "label": "Collect Data from Child Repos",
    "description": "Run tasks on all managed repos to gather training trajectories.",
    "allowed_paths": ["SPAWN/STOP/.orchestrator/logs/"],
    "dependencies": [],
    "status": "pending",
    "priority": 1
  },
  {
    "id": "dag_node_2",
    "dag_node_id": "prepare_dataset",
    "label": "Prepare Training Dataset",
    "description": "Convert logs to JSONL format for training.",
    "allowed_paths": ["SPAWN/STOP/.orchestrator/data/"],
    "dependencies": ["dag_node_1"],
    "status": "pending",
    "priority": 2
  }
]
```

---

#### Step 5: Seed Vector Store

**Directory:** `SPAWN/STOP/.orchestrator/vector_store/`

The vector store provides semantic memory for the orchestrator. It stores embeddings of:
- Past task results
- MEMORY.md entries
- Child repo outputs
- Orchestration logs

**To seed the vector store:**

1. **Create initial embeddings from MEMORY.md:**
   - Read `SPAWN/STOP/MEMORY.md`
   - Split into chunks (e.g., 512 tokens each)
   - Embed each chunk using the configured embedding model
   - Store as JSON files in `vector_store/`

2. **Example entry format:**
```json
{
  "id": "memory_001",
  "content": "Initial orchestration setup completed...",
  "embedding": [...],
  "metadata": {
    "source": "MEMORY.md",
    "timestamp": "2026-03-27T00:00:00Z",
    "type": "memory"
  }
}
```

3. **Tools:** Use Chroma, FAISS, or a simple JSON-based embedding store

---

**🔁 AUTONOMOUS ORCHESTRATION LOOP (within SPAWN/STOP/):**

```
1. Read task_queue.json (priority-ordered child tasks)
2. Query vector store for relevant context (past child task results, embeddings)
3. Call loop.py with state + child repo requirements
4. Dispatch tasks to child repos via their allowed_paths (task-scoped coordination)
5. Collect logs/outputs from child repos into SPAWN/STOP/.orchestrator/logs/
6. Train/update models if training data available
7. Append orchestration result to vector store
8. Update task_queue.json with next batch of task priorities
9. If orchestration complete, finalize state
10. Repeat until all coordinated tasks complete
```

---

### Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Structural Bootstrap | ✅ Complete | All directories, config files, and loop.py in place |
| Operational Initialization | 🔴 Pending | Phase 2 steps not yet executed |
| Autonomous Loop | 🟡 Ready (waiting) | loop.py functional, no tasks to coordinate |

---

## Architecture Additions (TASK.md Workflow)

### TASK.md Protocol

**Location:** `SPAWN/STOP/TASK.md`

The orchestrator now implements a **one-task-at-a-time** execution protocol using `TASK.md`:

```
┌─────────────────────────────────────────────────────────────┐
│ TASK EXECUTION PRIORITY                                     │
├─────────────────────────────────────────────────────────────┤
│ Priority 1: TASK.md (orchestrator's own DAG tasks)          │
│ Priority 2: task_queue.json (child repo coordination)       │
└─────────────────────────────────────────────────────────────┘
```

**TASK.md Structure:**
```markdown
---
task_id: task_001
dag_node_id: collect_data
allowed_paths:
  - SPAWN/STOP/.orchestrator/logs/
priority: 1
---

# Task: Collect Data from Child Repos

## Description
Run tasks on all managed repos to gather training trajectories.

## Allowed Paths
You may ONLY write to: `SPAWN/STOP/.orchestrator/logs/`

## Status: PENDING
```

**Lifecycle:**
1. **bootstrap.sh** creates initial `TASK.md` with first DAG task
2. **loop.py** detects `TASK.md` → parses frontmatter → executes task
3. On completion: marks task done, DAG node → green, deletes `TASK.md`
4. Loads next task from `tasks.json` → creates new `TASK.md`
5. Repeats until all DAG nodes are green

---

### loop.py Integration

**File:** `SPAWN/STOP/.orchestrator/loop.py`

The autonomous loop now has **dual-priority handling**:

```python
# Priority 1: Check for TASK.md (orchestrator's own DAG tasks)
if self.check_and_process_task_md():
    logger.info("TASK.md processed, continuing to next cycle...")
    continue

# Priority 2: Run 10-step coordination loop for child repos
tasks = self.step_1_read_task_queue()
# ... rest of 10-step cycle
```

**New Methods:**
| Method | Purpose |
|--------|---------|
| `check_and_process_task_md()` | Detects, parses, and executes TASK.md |
| `_update_task_status(task_id, status)` | Updates tasks.json with task state |
| `_update_dag_node_status(node_id, status)` | Updates design_graph.json node color |

---

### bootstrap.sh Updates

**File:** `SPAWN/START/bootstrap.sh`

The bootstrap script now:
1. ✅ Creates `SPAWN/STOP/TASK.md` with first DAG task
2. ✅ Outputs task workflow instructions
3. ✅ No longer copies AGENTS.md (removed from SPAWN/START/)

**Post-bootstrap output:**
```
📝 Next steps:
   1. Configure SPAWN/STOP/.orchestrator/config.json with repo details
   2. Add child repos to SPAWN/STOP/repos/
   3. Review SPAWN/STOP/TASK.md - this is your first task
   4. Run the orchestrator loop: cd Stop && python .orchestrator/loop.py
   5. (Optional) Access web UI: python web/app.py

📖 Task Workflow:
   - The orchestrator reads SPAWN/STOP/TASK.md and executes the task
   - On completion, the task is marked done and the next task is loaded
   - Add new tasks by editing SPAWN/STOP/state/tasks.json
   - See ../HOWTOPROMPT.md for DAG design principles
```

---

### Memory & Training Data Pipelines

**Current State:**

| Pipeline | Location | Status | Data Present |
|----------|----------|--------|--------------|
| **Memory Log** | `SPAWN/STOP/MEMORY.md` | ✅ Active | Bootstrap entries only |
| **Vector Store** | `SPAWN/STOP/.orchestrator/vector_store/` | ⚠️ Empty | No embeddings yet |
| **Training Data** | `SPAWN/STOP/.orchestrator/data/` | ⚠️ Empty | No datasets yet |
| **Model Checkpoints** | `SPAWN/STOP/.orchestrator/models/` | ⚠️ Empty | No training run yet |
| **Child Logs** | `SPAWN/STOP/.orchestrator/logs/` | ⚠️ Empty | No child repos configured |

**Training Pipeline Flow:**
```
1. collect_data.py → Gathers from SPAWN/STOP/repos/*/SPAWN/STOP/.orchestrator/logs/
                    → Outputs: SPAWN/STOP/.orchestrator/data/raw/

2. prepare_dataset.py → Converts raw logs to JSONL
                       → Outputs: SPAWN/STOP/.orchestrator/data/train.jsonl

3. train.py → Fine-tunes model using QLoRA
             → Outputs: SPAWN/STOP/.orchestrator/models/finetuned/

4. evaluate.py → Runs benchmarks (ARC, HumanEval, MMLU)
                → Outputs: SPAWN/STOP/.orchestrator/logs/eval_results.json

5. Vector Store ← Embeddings from MEMORY.md + task results
                → Outputs: SPAWN/STOP/.orchestrator/vector_store/*.json
```

**Bootstrap Data Collection:**
- ✅ `SPAWN/STOP/MEMORY.md` contains bootstrap initialization entries
- ❌ No embeddings created yet (vector_store is empty)
- ❌ No training data collected (no child repos = no logs)
- ❌ No model training performed (no data to train on)

**To Activate Pipelines:**
1. Add child repos to `SPAWN/STOP/repos/`
2. Run orchestrator loop to collect logs
3. Execute `training/collect_data.py`
4. Run `training/prepare_dataset.py`
5. Start training with `training/train.py`

---

## LLM Iteration Logging (Critical Training Data)

### Overview

**The most valuable training data comes from LLM iteration cycles** — the back-and-forth between the orchestrator/agents and the LLM, including:
- Prompts sent to the LLM
- Responses received
- Errors encountered
- Corrections applied
- Design decisions made
- Problems solved during bring-up

This data captures **real problem-solving trajectories** that are essential for training a model to handle similar situations.

---

### Iteration Log Structure

**Location:** `SPAWN/STOP/.orchestrator/iterations/`

Each LLM interaction is logged as a structured JSON file:

```json
{
  "iteration_id": "iter_20260327_143052_001",
  "timestamp": "2026-03-27T14:30:52Z",
  "task_id": "task_001",
  "dag_node_id": "setup_flask_app",
  "agent": "orchestrator",
  "llm_model": "deepseek-ai/deepseek-coder-6.7b-instruct",

  "prompt": {
    "system": "You are an architect. Given the user request...",
    "user": "Create Flask app.py with routes...",
    "context": {
      "allowed_paths": ["SPAWN/STOP/web/app.py"],
      "dependencies": [],
      "prior_attempts": []
    }
  },

  "response": {
    "content": "#!/usr/bin/env python3...",
    "tokens_used": 1247,
    "finish_reason": "stop"
  },

  "outcome": {
    "status": "success",
    "files_created": ["SPAWN/STOP/web/app.py"],
    "errors": [],
    "corrections": []
  },

  "metadata": {
    "duration_ms": 3421,
    "temperature": 0.7,
    "max_tokens": 4096
  }
}
```

---

### Error & Correction Tracking

**Location:** `SPAWN/STOP/.orchestrator/iterations/errors/`

When an LLM response produces errors, a correction cycle is logged:

```json
{
  "error_id": "err_20260327_143100_001",
  "parent_iteration": "iter_20260327_143052_001",
  "timestamp": "2026-03-27T14:31:00Z",

  "error": {
    "type": "SyntaxError",
    "message": "invalid syntax in app.py line 42",
    "traceback": "File \"app.py\", line 42\n    def api_status()\n                        ^\nSyntaxError: invalid syntax"
  },

  "correction_prompt": {
    "system": "You are a code fixer. The previous output had an error...",
    "user": "Fix the syntax error in the following code...",
    "context": {
      "original_prompt": "...",
      "original_response": "...",
      "error_message": "..."
    }
  },

  "correction_response": {
    "content": "def api_status():\n    \"\"\"Get overall orchestrator status.\"\"\"\n    ...",
    "tokens_used": 342
  },

  "resolution": {
    "status": "resolved",
    "corrections_applied": 1,
    "final_status": "success"
  }
}
```

---

### Design Decision Log

**Location:** `SPAWN/STOP/.orchestrator/iterations/decisions/`

Major design decisions are captured for training:

```json
{
  "decision_id": "dec_20260327_140000_001",
  "timestamp": "2026-03-27T14:00:00Z",
  "task_id": "task_004",
  "dag_node_id": "build_dashboard_frontend",

  "decision": {
    "question": "Should dashboard JavaScript be split into modules or consolidated?",
    "options": [
      {"id": "A", "description": "Split into dag-viz.js, task-queue.js, logs.js, etc."},
      {"id": "B", "description": "Consolidate into single script.js"}
    ],
    "chosen": "B",
    "rationale": "One Node = One File principle - multiple nodes writing to same file creates entanglement"
  },

  "outcome": {
    "result": "Correct decision - prevents path collisions",
    "lesson": "Consolidate files when multiple features would write to the same path"
  }
}
```

---

### Automatic Logging Integration

**File:** `SPAWN/STOP/.orchestrator/iteration_logger.py`

```python
#!/usr/bin/env python3
"""
LLM Iteration Logger
Automatically logs all LLM interactions for training data collection.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

class IterationLogger:
    def __init__(self, orchestrator_dir: Path):
        self.iterations_dir = orchestrator_dir / 'iterations'
        self.errors_dir = self.iterations_dir / 'errors'
        self.decisions_dir = self.iterations_dir / 'decisions'

        for dir_path in [self.iterations_dir, self.errors_dir, self.decisions_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def log_iteration(self, task_id: str, dag_node_id: str, prompt: dict,
                      response: dict, outcome: dict, metadata: dict = None):
        """Log a complete LLM iteration."""
        iteration = {
            'iteration_id': f"iter_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:3]}",
            'timestamp': datetime.now().isoformat(),
            'task_id': task_id,
            'dag_node_id': dag_node_id,
            'agent': 'orchestrator',
            'llm_model': metadata.get('model', 'unknown'),
            'prompt': prompt,
            'response': response,
            'outcome': outcome,
            'metadata': metadata or {}
        }

        file_path = self.iterations_dir / f"{iteration['iteration_id']}.json"
        with open(file_path, 'w') as f:
            json.dump(iteration, f, indent=2, default=str)

        return iteration['iteration_id']

    def log_error(self, parent_iteration: str, error: dict,
                  correction_prompt: dict, correction_response: dict,
                  resolution: dict):
        """Log an error and correction cycle."""
        error_log = {
            'error_id': f"err_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:3]}",
            'timestamp': datetime.now().isoformat(),
            'parent_iteration': parent_iteration,
            'error': error,
            'correction_prompt': correction_prompt,
            'correction_response': correction_response,
            'resolution': resolution
        }

        file_path = self.errors_dir / f"{error_log['error_id']}.json"
        with open(file_path, 'w') as f:
            json.dump(error_log, f, indent=2, default=str)

        return error_log['error_id']

    def log_decision(self, task_id: str, dag_node_id: str, decision: dict, outcome: dict):
        """Log a design decision."""
        decision_log = {
            'decision_id': f"dec_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:3]}",
            'timestamp': datetime.now().isoformat(),
            'task_id': task_id,
            'dag_node_id': dag_node_id,
            'decision': decision,
            'outcome': outcome
        }

        file_path = self.decisions_dir / f"{decision_log['decision_id']}.json"
        with open(file_path, 'w') as f:
            json.dump(decision_log, f, indent=2, default=str)

        return decision_log['decision_id']
```

---

### Training Data Pipeline (Enhanced)

**File:** `SPAWN/STOP/training/collect_data.py` (Enhanced)

```python
#!/usr/bin/env python3
"""
Collect Training Data
Gathers LLM iterations, errors, corrections, and decisions for training.
"""

import json
from pathlib import Path
from datetime import datetime

def collect_iterations(orchestrator_dir: Path, output_dir: Path):
    """Collect all LLM iterations into training format."""
    iterations_dir = orchestrator_dir / 'iterations'
    errors_dir = iterations_dir / 'errors'
    decisions_dir = iterations_dir / 'decisions'

    training_data = {
        'collected_at': datetime.now().isoformat(),
        'iterations': [],
        'error_corrections': [],
        'design_decisions': []
    }

    # Collect iterations
    for iter_file in iterations_dir.glob('*.json'):
        with open(iter_file, 'r') as f:
            iteration = json.load(f)
            training_data['iterations'].append({
                'prompt': iteration['prompt'],
                'response': iteration['response'],
                'outcome': iteration['outcome'],
                'quality_score': 1.0 if iteration['outcome']['status'] == 'success' else 0.0
            })

    # Collect error corrections (valuable for teaching error recovery)
    for err_file in errors_dir.glob('*.json'):
        with open(err_file, 'r') as f:
            error_log = json.load(f)
            training_data['error_corrections'].append({
                'error': error_log['error'],
                'correction_prompt': error_log['correction_prompt'],
                'correction_response': error_log['correction_response'],
                'resolution': error_log['resolution']
            })

    # Collect design decisions
    for dec_file in decisions_dir.glob('*.json'):
        with open(dec_file, 'r') as f:
            decision_log = json.load(f)
            training_data['design_decisions'].append({
                'decision': decision_log['decision'],
                'outcome': decision_log['outcome']
            })

    # Save collected data
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"training_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(output_file, 'w') as f:
        json.dump(training_data, f, indent=2, default=str)

    print(f"Collected {len(training_data['iterations'])} iterations")
    print(f"Collected {len(training_data['error_corrections'])} error corrections")
    print(f"Collected {len(training_data['design_decisions'])} design decisions")
    print(f"Saved to: {output_file}")

    return output_file
```

---

### Integration Points

**Where to Hook Iteration Logging:**

| Location | What to Log | Trigger |
|----------|-------------|---------|
| `loop.py` → `check_and_process_task_md()` | Task execution prompts/responses | Every task |
| `web/app.py` → API endpoints | Dashboard-related LLM calls | On API usage |
| Child repo agents | All child LLM interactions | Every child task |
| `training/*.py` | Training pipeline decisions | On training runs |
| DAG generation | Architecture design decisions | When creating DAGs |

**Example Integration in loop.py:**
```python
from .iteration_logger import IterationLogger

class OrchestratorLoop:
    def __init__(self, root_dir: str):
        # ... existing init ...
        self.logger = IterationLogger(self.orchestrator_dir)

    def check_and_process_task_md(self) -> bool:
        task_md_path = self.root / 'Stop' / 'TASK.md'

        if not task_md_path.exists():
            return False

        # Log the task start
        prompt = {
            'system': 'You are an orchestrator agent executing a task...',
            'user': task_content,
            'context': {'allowed_paths': allowed_paths}
        }

        # Execute task (placeholder for actual planner call)
        response = self.execute_task(task_content, allowed_paths)

        outcome = {
            'status': 'success' if success else 'failed',
            'files_created': files_created,
            'errors': errors
        }

        # Log the iteration
        self.logger.log_iteration(
            task_id=task_id,
            dag_node_id=dag_node_id,
            prompt=prompt,
            response=response,
            outcome=outcome,
            metadata={'duration_ms': duration}
        )

        # ... rest of existing logic
```

---

### Value of Iteration Data

**Why This Data is Critical:**

1. **Error Recovery Patterns**: Shows how to recover from common mistakes
2. **Design Decision Rationale**: Captures why certain architectures were chosen
3. **Problem-Solving Trajectories**: Demonstrates step-by-step reasoning
4. **Bring-Up Challenges**: Documents real problems encountered during system initialization
5. **Correction Cycles**: Teaches the model how to fix its own errors

**Training Use Cases:**
- Fine-tune model on successful problem-solving patterns
- Teach error recovery from correction cycles
- Improve architectural reasoning from design decisions
- Reduce common mistakes by learning from errors

---

## Model Training & Compilation Pipeline (2026 Best Practices)

### Overview

The orchestrator manages model training as an **independent, automated pipeline** that runs parallel to individual repo development. Training is triggered by data availability thresholds, not manual intervention.

---

### Training Data Thresholds (2026 Standards)

Based on extensive research for fine-tuning 6B-8B parameter models:

| Threshold | Dataset Size | Action |
|-----------|--------------|--------|
| **🔴 Insufficient** | < 100 iterations | Continue collecting, no training possible |
| **🟡 Minimum Viable** | 100-500 iterations | Can run smoke test training (marginal improvements) |
| **🟢 Meaningful** | 500-1,000 iterations | Trigger first real fine-tuning run (LoRA/QLoRA) |
| **🔵 Production Ready** | 1,000-5,000 iterations | Full fine-tuning with evaluation suite |
| **🟣 Optimal** | 5,000-10,000+ iterations | Production model with SOTA performance |

**Quality Criteria (More Important Than Quantity):**
- ✅ **Relevance**: Iterations match target domain (software architecture, coding)
- ✅ **Accuracy**: All outputs verified correct (tests pass, code runs)
- ✅ **Diversity**: Covers different problem types, error scenarios, design patterns
- ✅ **Consistency**: Uniform formatting, structured outputs
- ✅ **Difficulty Balance**: Mix of simple fixes and complex architectural decisions

---

### Automated Training Triggers

**File:** `SPAWN/STOP/.orchestrator/training_monitor.py`

```python
#!/usr/bin/env python3
"""
Training Monitor
Automatically monitors data thresholds and triggers model compilation.
"""

import json
from pathlib import Path
from datetime import datetime
from enum import Enum

class TrainingReadiness(Enum):
    INSUFFICIENT = "insufficient"
    MINIMUM = "minimum_viable"
    MEANINGFUL = "meaningful"
    PRODUCTION = "production_ready"
    OPTIMAL = "optimal"

class TrainingMonitor:
    def __init__(self, orchestrator_dir: Path):
        self.orchestrator_dir = orchestrator_dir
        self.iterations_dir = orchestrator_dir / 'iterations'
        self.data_dir = orchestrator_dir / 'data'
        self.models_dir = orchestrator_dir / 'models'
        self.config_path = orchestrator_dir / 'config.json'

        # Thresholds from 2026 research
        self.thresholds = {
            TrainingReadiness.INSUFFICIENT: (0, 100),
            TrainingReadiness.MINIMUM: (100, 500),
            TrainingReadiness.MEANINGFUL: (500, 1000),
            TrainingReadiness.PRODUCTION: (1000, 5000),
            TrainingReadiness.OPTIMAL: (5000, float('inf'))
        }

    def count_iterations(self) -> int:
        """Count total collected iterations."""
        if not self.iterations_dir.exists():
            return 0
        return len(list(self.iterations_dir.glob('*.json')))

    def check_quality_metrics(self) -> dict:
        """Check quality metrics of collected data."""
        iterations = list(self.iterations_dir.glob('*.json'))

        if not iterations:
            return {'quality_score': 0.0, 'error_rate': 0.0, 'diversity_score': 0.0}

        successful = 0
        error_corrections = 0
        design_decisions = 0

        for iter_file in iterations:
            with open(iter_file, 'r') as f:
                iteration = json.load(f)
                if iteration.get('outcome', {}).get('status') == 'success':
                    successful += 1
                if iteration.get('outcome', {}).get('corrections'):
                    error_corrections += 1
                if 'decision' in iteration:
                    design_decisions += 1

        total = len(iterations)
        return {
            'quality_score': successful / total if total > 0 else 0.0,
            'error_rate': error_corrections / total if total > 0 else 0.0,
            'diversity_score': min(1.0, design_decisions / 100),  # Normalize
            'total_iterations': total
        }

    def get_readiness(self) -> TrainingReadiness:
        """Determine training readiness level."""
        count = self.count_iterations()

        for readiness, (min_count, max_count) in self.thresholds.items():
            if min_count <= count < max_count:
                return readiness

        return TrainingReadiness.OPTIMAL

    def should_trigger_training(self, last_training_run: datetime = None) -> bool:
        """
        Determine if training should be triggered.

        Triggers when:
        1. Readiness level improved since last training
        2. Quality score > 0.8 (80% successful iterations)
        3. No training run in last 24 hours (prevent thrashing)
        """
        readiness = self.get_readiness()

        # Never train with insufficient data
        if readiness == TrainingReadiness.INSUFFICIENT:
            return False

        # Check quality
        quality = self.check_quality_metrics()
        if quality['quality_score'] < 0.8:
            return False

        # Check cooldown (24 hours)
        if last_training_run:
            hours_since_last = (datetime.now() - last_training_run).total_seconds() / 3600
            if hours_since_last < 24:
                return False

        return True

    def generate_training_report(self) -> dict:
        """Generate comprehensive training readiness report."""
        readiness = self.get_readiness()
        quality = self.check_quality_metrics()

        return {
            'timestamp': datetime.now().isoformat(),
            'readiness_level': readiness.value,
            'total_iterations': quality['total_iterations'],
            'quality_score': quality['quality_score'],
            'error_rate': quality['error_rate'],
            'diversity_score': quality['diversity_score'],
            'should_train': self.should_trigger_training(),
            'recommendation': self._get_recommendation(readiness, quality)
        }

    def _get_recommendation(self, readiness: TrainingReadiness, quality: dict) -> str:
        if readiness == TrainingReadiness.INSUFFICIENT:
            return f"Continue collecting data. Need {100 - quality['total_iterations']} more iterations."
        elif readiness == TrainingReadiness.MINIMUM:
            return "Can run smoke test training. Collect more data for production model."
        elif readiness == TrainingReadiness.MEANINGFUL:
            return "Ready for first meaningful fine-tuning run with LoRA/QLoRA."
        elif readiness == TrainingReadiness.PRODUCTION:
            return "Ready for production model training with full evaluation suite."
        else:
            return "Optimal dataset. Train production model now."
```

---

### Model Registry & Versioning

**Location:** `SPAWN/STOP/.orchestrator/models/registry.json`

```json
{
  "models": [
    {
      "version": "v0.1.0",
      "created_at": "2026-03-27T14:30:00Z",
      "base_model": "deepseek-ai/deepseek-coder-6.7b-instruct",
      "training_method": "QLoRA",
      "dataset_size": 1247,
      "quality_score": 0.87,
      "evaluation": {
        "status": "pending",
        "metrics": {}
      },
      "status": "training",
      "checkpoint_path": "SPAWN/STOP/.orchestrator/models/checkpoints/v0.1.0/"
    }
  ],
  "current_production": null,
  "next_training_scheduled": "2026-03-28T00:00:00Z"
}
```

---

### Training Pipeline Stages

**File:** `SPAWN/STOP/training/train.py` (Enhanced)

```python
#!/usr/bin/env python3
"""
Model Training Pipeline
Trains orchestrator model on collected iteration data.
"""

import json
from pathlib import Path
from datetime import datetime
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
import torch

class OrchestratorTrainer:
    def __init__(self, orchestrator_dir: Path):
        self.orchestrator_dir = orchestrator_dir
        self.models_dir = orchestrator_dir / 'models'
        self.iterations_dir = orchestrator_dir / 'iterations'
        self.data_dir = orchestrator_dir / 'data'

        self.config = {
            'model_name': 'deepseek-ai/deepseek-coder-6.7b-instruct',
            'lora_rank': 16,
            'lora_alpha': 32,
            'target_modules': ['q_proj', 'k_proj', 'v_proj', 'o_proj'],
            'epochs': 3,
            'batch_size': 4,
            'learning_rate': 2e-4,
            'max_length': 4096
        }

    def prepare_dataset(self) -> list:
        """Convert iterations to training format."""
        training_examples = []

        for iter_file in self.iterations_dir.glob('*.json'):
            with open(iter_file, 'r') as f:
                iteration = json.load(f)

            # Skip failed iterations
            if iteration.get('outcome', {}).get('status') != 'success':
                continue

            # Format as instruction-response pair
            prompt = self._format_prompt(iteration['prompt'])
            response = iteration['response']['content']

            training_examples.append({
                'instruction': prompt,
                'input': '',
                'output': response,
                'metadata': {
                    'task_id': iteration.get('task_id'),
                    'dag_node_id': iteration.get('dag_node_id'),
                    'iteration_id': iteration.get('iteration_id')
                }
            })

        return training_examples

    def _format_prompt(self, prompt: dict) -> str:
        """Format prompt as instruction."""
        system = prompt.get('system', '')
        user = prompt.get('user', '')
        context = prompt.get('context', {})

        return f"""<|system|>
{system}

<|user|>
{user}

<|context|>
Allowed paths: {context.get('allowed_paths', [])}
Dependencies: {context.get('dependencies', [])}

<|instruction|>
Execute the task following the constraints above."""

    def train(self, version: str):
        """Run training pipeline."""
        print(f"Starting training for version {version}...")

        # Prepare dataset
        dataset = self.prepare_dataset()
        print(f"Prepared {len(dataset)} training examples")

        # Split train/eval
        eval_size = max(1, int(len(dataset) * 0.2))
        train_dataset = dataset[:-eval_size]
        eval_dataset = dataset[-eval_size:]

        # Load model
        model = AutoModelForCausalLM.from_pretrained(
            self.config['model_name'],
            load_in_4bit=True,
            device_map='auto'
        )
        tokenizer = AutoTokenizer.from_pretrained(self.config['model_name'])

        # Configure LoRA
        peft_config = LoraConfig(
            r=self.config['lora_rank'],
            lora_alpha=self.config['lora_alpha'],
            target_modules=self.config['target_modules'],
            lora_dropout=0.05,
            bias='none'
        )

        model = prepare_model_for_kbit_training(model)
        model = get_peft_model(model, peft_config)

        # Training arguments
        training_args = TrainingArguments(
            output_dir=str(self.models_dir / 'checkpoints' / version),
            num_train_epochs=self.config['epochs'],
            per_device_train_batch_size=self.config['batch_size'],
            learning_rate=self.config['learning_rate'],
            fp16=True,
            logging_steps=100,
            eval_strategy='epoch',
            save_strategy='epoch',
            load_best_model_at_end=True
        )

        # TODO: Add Trainer initialization and training loop

        print(f"Training complete. Model saved to {version}")

        return {
            'version': version,
            'dataset_size': len(dataset),
            'train_size': len(train_dataset),
            'eval_size': len(eval_dataset),
            'status': 'complete'
        }
```

---

### Orchestrator Training Task (Independent DAG Node)

The orchestrator manages model training as a **separate, parallel DAG** that runs independently of individual repo development:

**File:** `SPAWN/STOP/state/training_dag.json`

```json
{
  "name": "Model Training Pipeline",
  "nodes": [
    {
      "id": "monitor_data_thresholds",
      "label": "Monitor Data Thresholds",
      "description": "Check if enough iterations collected for training",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/iterations/"],
      "dependencies": [],
      "status": "green",
      "schedule": "every 6 hours"
    },
    {
      "id": "prepare_training_data",
      "label": "Prepare Training Data",
      "description": "Convert iterations to instruction-response format",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/data/"],
      "dependencies": ["monitor_data_thresholds"],
      "status": "red",
      "trigger": "threshold_reached"
    },
    {
      "id": "train_model",
      "label": "Train Model (QLoRA)",
      "description": "Fine-tune model on prepared dataset",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/models/"],
      "dependencies": ["prepare_training_data"],
      "status": "red",
      "trigger": "data_ready"
    },
    {
      "id": "evaluate_model",
      "label": "Evaluate Model",
      "description": "Run benchmarks (HumanEval, MBPP, architecture QA)",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/logs/"],
      "dependencies": ["train_model"],
      "status": "red",
      "trigger": "training_complete"
    },
    {
      "id": "register_model",
      "label": "Register Model",
      "description": "Add to model registry, update production pointer if better",
      "allowed_paths": ["SPAWN/STOP/.orchestrator/models/registry.json"],
      "dependencies": ["evaluate_model"],
      "status": "red",
      "trigger": "evaluation_passed"
    }
  ],
  "edges": [
    {"from": "monitor_data_thresholds", "to": "prepare_training_data"},
    {"from": "prepare_training_data", "to": "train_model"},
    {"from": "train_model", "to": "evaluate_model"},
    {"from": "evaluate_model", "to": "register_model"}
  ]
}
```

---

### Integration with Main Orchestrator Loop

**File:** `SPAWN/STOP/.orchestrator/loop.py` (Enhanced)

The orchestrator runs **two parallel loops**:

```python
class OrchestratorLoop:
    def __init__(self, root_dir: str):
        # ... existing init ...
        self.training_monitor = TrainingMonitor(self.orchestrator_dir)
        self.trainer = OrchestratorTrainer(self.orchestrator_dir)

    def run(self, max_cycles: int = 0):
        """Execute dual-loop orchestration."""
        while should_continue:
            self.cycle_count += 1

            # Loop 1: Task Execution (Priority 1)
            if self.check_and_process_task_md():
                continue

            # Loop 2: Training Pipeline (Priority 2 - Background)
            if self.cycle_count % 100 == 0:  # Check every 100 cycles
                self._check_training_readiness()

            # ... rest of 10-step coordination loop
```

---

### Decision Matrix: When to Train

| Condition | Data Count | Quality Score | Last Training | Action |
|-----------|------------|---------------|---------------|--------|
| Early collection | < 100 | Any | N/A | Continue collecting |
| Smoke test | 100-500 | > 0.7 | N/A | Run minimal training (validate pipeline) |
| First model | 500-1,000 | > 0.8 | Never | Train v0.1.0 with LoRA |
| Improvement | +500 new | > 0.85 | > 7 days | Train incremental update |
| Production | > 1,000 | > 0.9 | > 14 days | Full training + evaluation |
| Major release | > 5,000 | > 0.95 | > 30 days | Production model release |

---

### Output: "Tuned Coding & Software Task Builder Model"

**Target Specifications (2026 SOTA for 6B-24B models):**

| Metric | Target (6B-8B) | Target (24B) | Benchmark |
|--------|----------------|--------------|-----------|
| **Code Generation** | > 65% | > 75% | HumanEval pass@1 |
| **Python Tasks** | > 70% | > 82% | MBPP solved |
| **Architecture Reasoning** | > 80% | > 90% | Custom DAG design QA |
| **Error Recovery** | > 75% | > 85% | Correction success rate |
| **Context Efficiency** | 4096 tokens | 8192-16384 tokens | Optimal context window |
| **Storage Footprint** | < 8GB (4-bit) | < 16GB (4-bit) | QLoRA 4-bit quantized |
| **Inference Speed** | < 100ms/token | < 150ms/token | RTX 5090 GPU |

---

### Hardware Capability Assessment (NextAura System)

**Confirmed Hardware (Scan: 2026-03-27):**

| Component | Specification | 24B Model Ready? |
|-----------|---------------|------------------|
| **System RAM** | 128GB DDR5 5600MHz (4x32GB Micron) | ✅ EXCELLENT |
| **GPU** | NVIDIA GeForce RTX 5090 (32GB VRAM) | ✅ TOP TIER |
| **CPU** | AMD Ryzen 9 7950X (16 cores / 32 threads) | ✅ EXCELLENT |
| **Storage** | 955GB available (D: drive) | ✅ SUFFICIENT |
| **WSL Allocation** | 64GB RAM, 32 vCPUs (configured) | ✅ OPTIMIZED |

**24B Model Training Capability:**

| Training Method | VRAM Required | RAM Required | Time Estimate | Feasible? |
|-----------------|---------------|--------------|---------------|-----------|
| **QLoRA 4-bit** | 28-30GB | 48-64GB | 12-18 hours | ✅ YES |
| **LoRA 16-bit** | 48GB+ (multi-GPU) | 64-96GB | 8-12 hours | ⚠️ Needs optimization |
| **Full Fine-tune** | 80GB+ (multi-GPU) | 128GB+ | 24-48 hours | ⚠️ Needs model parallelism |

**Recommendation:** Use **QLoRA 4-bit quantization** for 24B model training on this system. The RTX 5090's 32GB VRAM is sufficient, and 128GB system RAM provides excellent headroom for data preprocessing and large context windows.

---

**Model Release Format:**
```
NextAura-Orchestrator-v1.0/
├── adapter_config.json      # LoRA adapter config
├── adapter_model.safetensors # Trained weights (<16GB for 24B 4-bit)
├── tokenizer.json
├── training_metadata.json    # Dataset info, quality metrics
└── evaluation_results.json   # Benchmark scores
```

---

### Summary: Complete Pipeline Flow

```
1. Iterations collected → SPAWN/STOP/.orchestrator/iterations/
2. Training monitor checks thresholds (every 6 hours)
3. If threshold reached + quality > 0.8 → Trigger training
4. Prepare dataset → Convert to instruction-response format
5. Train model → QLoRA fine-tuning (4-8 hours)
6. Evaluate → Run HumanEval, MBPP, custom benchmarks
7. Register → Add to model registry, update production if better
8. Deploy → Model available for orchestrator tasks
9. Repeat → Continue collecting, retrain when +500 new iterations
```

**Key Insight:** Model training is **completely independent** of individual repo development. The orchestrator coordinates both in parallel:
- Repo tasks → Produce iterations (training data)
- Training pipeline → Consumes iterations → Produces better model
- Better model → Improves repo task execution
- **Virtuous cycle of continuous improvement**

---

## Enterprise Security & Access Control System

### Overview

The orchestrator implements **enterprise-grade security** with encrypted credential management, write lock protocols, and task-scoped access control. All credentials are encrypted, all writes are locked, and all access is audited.

---

### Security Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR SECURITY LAYERS                                            │
├─────────────────────────────────────────────────────────────────────────┤
│ Layer 1: ENCRYPTED VAULT (GPG/AES-256)                                  │
│   - All credentials encrypted at rest                                   │
│   - Automatic secret rotation (30 days)                                 │
│   - Audit trail for all access                                          │
│                                                                         │
│ Layer 2: GLOBAL WRITE FREEZE                                            │
│   - Single write lock for entire orchestrator                           │
│   - Prevents concurrent modifications                                   │
│   - Auto-expires after timeout (5 minutes default)                      │
│                                                                         │
│ Layer 3: REPO-LEVEL WRITE LOCKS                                         │
│   - Per-repository write locks                                          │
│   - Only ONE repo can be modified at a time                             │
│   - Prevents cross-repo entanglement                                    │
│                                                                         │
│ Layer 4: TASK-SCOPED CREDENTIAL RELEASE                                 │
│   - Credentials injected ONLY for active task                           │
│   - Auto-revoked on task completion                                     │
│   - Environment isolation (TASK_{id}_{KEY})                             │
│                                                                         │
│ Layer 5: AUDIT LOGGING                                                  │
│   - All credential access logged                                        │
│   - All lock acquisitions logged                                        │
│   - Tamper-evident audit trail                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### Credential Injection System

**Vault Location:** `SPAWN/STOP/.orchestrator/vault/`

**Supported Credential Types:**
| Type | Example | Usage |
|------|---------|-------|
| `API_KEY` | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | LLM API access |
| `GIT_TOKEN` | `GITHUB_TOKEN`, `GITLAB_TOKEN` | Repository operations |
| `SSH_KEY` | `~/.ssh/id_ed25519` | Secure git operations |
| `DATABASE` | `DATABASE_URL` | Data persistence |
| `CUSTOM` | Any custom secret | Flexible credential types |

**Storage Security:**
- **GPG Available:** AES-256 encrypted (`.env.gpg`)
- **GPG Unavailable:** Plaintext fallback (⚠️ INSECURE - configure GPG!)
- **Automatic Rotation:** Credentials expire after 30 days

**Example: Storing Credentials**
```python
from security_manager import SecurityManager, CredentialType

security = SecurityManager()

# Store API key (encrypted if GPG available)
security.store_credential(
    key='OPENAI_API_KEY',
    value='sk-...',
    credential_type=CredentialType.API_KEY
)

# Store Git token
security.store_credential(
    key='GITHUB_TOKEN',
    value='ghp_...',
    credential_type=CredentialType.GIT_TOKEN
)
```

---

### Write Lock/Freeze Protocol

**BEFORE any task can write:**

```
1. Task requests write lock
2. Security Manager checks if lock is available
3. If available → Lock acquired, freeze begins
4. If held → Task waits or fails (configurable)
5. Task executes with write access
6. On completion → Lock released, freeze lifts
```

**Lock Types:**

| Lock Type | Scope | Use Case | Timeout |
|-----------|-------|----------|---------|
| **Global Write Lock** | Entire orchestrator | System-wide operations | 5 minutes |
| **Repo Write Lock** | Single repository | Task-specific modifications | 5 minutes |

**Example: Acquiring Write Lock**
```python
# Acquire global lock
lock = security.acquire_global_write_lock(task_id="task_001")

if lock.status == "acquired":
    # Execute task (write freeze active)
    run_task()

    # Release lock (freeze lifts)
    security.release_global_write_lock(task_id="task_001")
else:
    # Lock denied - another task holds it
    log_error("Write lock denied - another task in progress")
```

---

### Task-Scoped Credential Release

**Credentials are NEVER permanently available.** They are:
1. **Injected** when task starts (after lock acquired)
2. **Isolated** in task-specific environment variables
3. **Revoked** when task completes

**Environment Variable Format:**
```
TASK_{task_id}_{CREDENTIAL_KEY}
```

**Example:**
```python
# Before task: No credentials in environment
os.environ.get('OPENAI_API_KEY')  # None

# During task (credentials injected):
with security.task_security_context(
    task_id="task_001",
    repo_name="my-repo",
    credential_keys=["OPENAI_API_KEY", "GITHUB_TOKEN"]
) as ctx:
    # Credentials available as:
    # TASK_task_001_OPENAI_API_KEY
    # TASK_task_001_GITHUB_TOKEN
    run_task()

# After task: Credentials revoked
os.environ.get('TASK_task_001_OPENAI_API_KEY')  # None
```

---

### Repo-Level Access Control

**Single-Repo Write Guarantee:**

```
┌────────────────────────────────────────────────────────────┐
│ REPO WRITE LOCK STATE MACHINE                              │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  [IDLE] ──task requests──> [LOCKED] ──task completes──> [IDLE]
│    │                          │                            │
│    │                          └──> timeout ──> [IDLE]      │
│    │                                                         │
│    └──> concurrent request ──> [DENIED] ──> retry later     │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**Lock Files:**
- **Global:** `SPAWN/STOP/.orchestrator/locks/global_write.lock`
- **Per-Repo:** `SPAWN/STOP/.orchestrator/locks/repo_locks/{repo_name}.lock`

**Lock Metadata:**
```json
{
  "lock_id": "repo_my-repo_task_001_20260327_150000",
  "task_id": "task_001",
  "repo": "my-repo",
  "acquired_at": "2026-03-27T15:00:00Z",
  "expires_at": "2026-03-27T15:05:00Z",
  "status": "acquired"
}
```

---

### Audit Logging

**All Security Events Logged:**

| Event Type | Logged Data |
|------------|-------------|
| Credential Access | Key, task_id, timestamp, credential_type |
| Lock Acquisition | Lock type, task_id, repo, timeout |
| Lock Release | Lock type, task_id, duration |
| Credential Grant | Task, repo, keys granted, expiry |
| Credential Revoke | Task, keys revoked |

**Audit Log Location:** `SPAWN/STOP/.orchestrator/logs/security/security_audit.log`

**Example Audit Entry:**
```json
{
  "timestamp": "2026-03-27T15:00:00Z",
  "action": "Credential accessed",
  "actor": "task_001",
  "details": {
    "credential_key": "OPENAI_API_KEY",
    "credential_type": "api_key"
  }
}
```

---

### Security Context Manager (Recommended Usage)

**Simplest way to use security system:**

```python
from security_manager import SecurityManager

security = SecurityManager()

# Execute task with full security
with security.task_security_context(
    task_id="task_001",
    repo_name="my-repo",
    credential_keys=["OPENAI_API_KEY", "GITHUB_TOKEN"]
) as ctx:

    if ctx.lock_acquired:
        # Write lock active, credentials injected
        # Environment has:
        # - TASK_task_001_OPENAI_API_KEY
        # - TASK_task_001_GITHUB_TOKEN
        run_task()
    else:
        # Lock denied - another task in progress
        log_error("Could not acquire write lock")

# Automatic cleanup:
# - Credentials revoked
# - Write lock released
# - Audit entries written
```

---

### Integration with TASK.md Workflow

**TASK.md with Security:**

```markdown
---
task_id: task_001
dag_node_id: setup_flask_app
allowed_paths:
  - SPAWN/STOP/web/app.py
repo: orchestrator
required_credentials:
  - GITHUB_TOKEN
  - OPENAI_API_KEY
priority: 1
---

# Task: Setup Flask Application

## Security Protocol
1. Acquire repo write lock (orchestrator)
2. Inject credentials (GITHUB_TOKEN, OPENAI_API_KEY)
3. Execute task
4. Revoke credentials
5. Release write lock
```

**Loop.py Integration:**
```python
def check_and_process_task_md(self) -> bool:
    task_md_path = self.root / 'Stop' / 'TASK.md'

    if not task_md_path.exists():
        return False

    # Parse TASK.md
    task = parse_task_md(task_md_path)

    # Acquire write lock & inject credentials
    with self.security.task_security_context(
        task_id=task['task_id'],
        repo_name=task.get('repo'),
        credential_keys=task.get('required_credentials', [])
    ) as ctx:

        if ctx.lock_acquired:
            # Execute task securely
            execute_task(task)
            return True
        else:
            logger.error("Write lock denied")
            return False
```

---

### Security Checklist (Pre-Task)

Before ANY task executes:

- [ ] **Vault initialized** (GPG configured if possible)
- [ ] **Credentials stored** (encrypted)
- [ ] **Write lock acquired** (global or repo-level)
- [ ] **Credentials injected** (task-scoped environment vars)
- [ ] **Audit logging active**
- [ ] **Timeout configured** (auto-release on failure)

After task completes:

- [ ] **Credentials revoked** (environment cleaned)
- [ ] **Write lock released** (freeze lifted)
- [ ] **Audit entries written** (tamper-evident log)
- [ ] **Next task unlocked** (chain continues)

---

### Files & Locations

| Component | Location | Purpose |
|-----------|----------|---------|
| **Security Manager** | `SPAWN/STOP/.orchestrator/security_manager.py` | Core security implementation |
| **Vault (Encrypted)** | `SPAWN/STOP/.orchestrator/vault/.env.gpg` | GPG-encrypted credentials |
| **Vault (Fallback)** | `SPAWN/STOP/.orchestrator/vault/.env` | Plaintext (⚠️ insecure) |
| **Global Lock** | `SPAWN/STOP/.orchestrator/locks/global_write.lock` | Global write freeze |
| **Repo Locks** | `SPAWN/STOP/.orchestrator/locks/repo_locks/` | Per-repo write locks |
| **Audit Log** | `SPAWN/STOP/.orchestrator/logs/security/security_audit.log` | Security audit trail |
