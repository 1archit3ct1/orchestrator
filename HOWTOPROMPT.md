Per‑Repo Agent Architecture – Final Overview

The per‑repo agent is a self‑bootstrapping, secure, model‑agnostic system that lives inside a single repository. It consists of two top‑level folders:

```
repo/
├── SPAWN/START/ # Bootstrap zone (locked after setup)
└── SPAWN/STOP/ # Runtime zone (agent operates here)
```

Bootstrap (6 Steps)

The SPAWN/START/ folder contains scripts and prompts that set up the agent. After bootstrap:

· SPAWN/START/ becomes read‑only (immutable security).
· SPAWN/STOP/ contains the agent’s runtime: .agent/ (tools, loop, vector store), state/ (DAG, tasks, memory), and AGENTS.md (reduced perennial prompt).

---

How the Agent Ingests a Raw Prompt

1. The User Provides the Prompt

The user (or orchestrator) writes a task description into SPAWN/STOP/TASK.md. This is a simple markdown file:

```markdown
---
# optional frontmatter (can be empty)
---
Build a REST API for a todo list with SQLite.
```

The agent’s autonomous loop (SPAWN/STOP/.agent/loop.py) continuously checks for the existence of this file.

2. The Loop Detects TASK.md

The loop loads the file and reads its content.

3. The Agent Checks for an Existing Design DAG

The first thing the loop does is look for SPAWN/STOP/state/design_graph.json.

· If it does NOT exist → the agent enters design mode.
· If it exists → the agent skips design mode and goes straight to task execution.

This simple file‑based check makes the system robust: the user can inject a pre‑made DAG at any time, and the agent will respect it.

4. Design Mode: Generating the DAG

If no DAG exists, the agent calls its planner (the same pluggable planner used for coding) with a special meta‑prompt:

```
You are an architect. Given the user request and the current codebase, output a JSON DAG that describes the components needed to fulfill the request.
```

The planner returns a JSON structure like:

```json
{
"nodes": [
{
"id": "database",
"label": "Database Models",
"description": "SQLite models for todos",
"allowed_paths": ["src/db/"],
"dependencies": [],
"status": "red"
},
{
"id": "api",
"label": "API Endpoints",
"description": "FastAPI handlers for CRUD",
"allowed_paths": ["src/api/"],
"dependencies": ["database"],
"status": "red"
}
],
"edges": [
{ "from": "api", "to": "database", "type": "depends_on" }
]
}
```

This DAG is saved as SPAWN/STOP/state/design_graph.json.

---

### CRITICAL: DAG Design Principles

When generating a DAG, the agent MUST follow these rules:

#### 1. One Node = One File Principle
- **Each node produces exactly ONE output file**
- The `allowed_paths` for each node should contain exactly ONE path (or one directory for that node's exclusive use)
- Example: `allowed_paths: ["src/models.py"]` ✓
- Anti-pattern: `allowed_paths: ["src/main.js", "src/utils.js"]` ✗ (split into two nodes)

#### 2. No Overlapping Paths
- **No two nodes should write to the same file**
- If two features share a file, they must be the SAME node
- Example: If both "DAG Visualization" and "Task Queue" write to `script.js`, they should be ONE node
- Anti-pattern: Task 4 writes to `script.js`, Task 5 also writes to `script.js` ✗

#### 3. Atomic Deliverables
- Each node's `deliverables` array should describe ONE cohesive unit of work
- If a deliverable list spans multiple unrelated concerns, split the node
- Example: `deliverables: ["Create user model with username, email, password"]` ✓
- Anti-pattern: `deliverables: ["Create user model", "Create API routes", "Add tests"]` ✗ (three nodes)

#### 4. Granularity Rule
- Tasks should be small enough that failure of one doesn't block unrelated work
- Rule of thumb: A node should be completable in a single agent session (5-30 minutes of work)
- If a node requires multiple independent files, split it

#### 5. Dependency Chain Integrity
- Dependencies should reflect true blocking relationships
- Ask: "Can task B start if task A fails completely?" If yes, they're not truly dependent
- Avoid false dependencies that create artificial bottlenecks

#### 6. File Ownership Clarity
- Each file in the project should be "owned" by exactly one node
- Shared infrastructure (like `script.js` for frontend) should be a SINGLE node
- Subsequent nodes that READ (but don't write) can reference the file

---

### Example: Correct vs Incorrect DAG Design

**INCORRECT (what we did for Dashboard GUI):**
```json
{
  "nodes": [
    {
      "id": "build_dag_viz",
      "allowed_paths": ["SPAWN/STOP/web/static/script.js"],
      "deliverables": ["DAG renderer in script.js"]
    },
    {
      "id": "build_task_queue",
      "allowed_paths": ["SPAWN/STOP/web/static/script.js"],
      "deliverables": ["Task queue logic in script.js"]
    }
  ]
}
```
**Problem:** Both nodes write to `script.js` — this creates entanglement and violates task-scoped writes.

**CORRECT:**
```json
{
  "nodes": [
    {
      "id": "build_frontend_core",
      "allowed_paths": ["SPAWN/STOP/web/static/script.js"],
      "deliverables": ["Complete dashboard JavaScript: DAG viz, task queue, logs, metrics, SSE, controls"],
      "description": "Single comprehensive script.js implementing all dashboard features"
    }
  ]
}
```

**ALTERNATIVE CORRECT (if modularity is desired):**
```json
{
  "nodes": [
    {
      "id": "build_dag_viz",
      "allowed_paths": ["SPAWN/STOP/web/static/dag-viz.js"],
      "deliverables": ["Standalone DAG visualization module"]
    },
    {
      "id": "build_task_queue",
      "allowed_paths": ["SPAWN/STOP/web/static/task-queue.js"],
      "deliverables": ["Standalone task queue module"]
    },
    {
      "id": "integrate_modules",
      "allowed_paths": ["SPAWN/STOP/web/static/script.js"],
      "dependencies": ["build_dag_viz", "build_task_queue"],
      "deliverables": ["Main script.js that imports and coordinates modules"]
    }
  ]
}
```

5. Deriving Tasks from the DAG

From the DAG, the agent creates a task list (SPAWN/STOP/state/tasks.json). Each node becomes a task with its allowed_paths and dependencies. Tasks are ordered topologically so that dependencies are built first.

### Task Derivation Rules

1. **One Node = One Task**: Each DAG node becomes exactly one task in tasks.json
2. **Inherit allowed_paths**: Tasks inherit the `allowed_paths` from their parent node
3. **Preserve Dependencies**: Task dependencies must match the DAG node dependencies
4. **Add Metadata**: Each task should include:
   - `id`: Unique task identifier
   - `dag_node_id`: Reference to parent DAG node
   - `status`: Starts as "pending"
   - `priority`: Derived from topological order

### Example Task Derivation

**DAG Node:**
```json
{
  "id": "create_api",
  "label": "Create API",
  "allowed_paths": ["src/api.py"],
  "dependencies": ["create_models"],
  "status": "red"
}
```

**Derived Task:**
```json
{
  "id": "task_002",
  "dag_node_id": "create_api",
  "label": "Create API",
  "description": "Create API",
  "allowed_paths": ["src/api.py"],
  "dependencies": ["task_001"],
  "status": "pending",
  "priority": 2
}
```

---

### TASK.md Lifecycle Protocol

**CRITICAL: Only ONE task is active at a time**

```
┌─────────────────────────────────────────────────────────────┐
│ TASK EXECUTION CYCLE                                        │
├─────────────────────────────────────────────────────────────┤
│ 1. Find next pending task with satisfied dependencies       │
│ 2. Write task to TASK.md (with frontmatter allowed_paths)   │
│ 3. Execute task (writes ONLY to allowed_paths)              │
│ 4. On success:                                              │
│    - Mark task as "completed" in tasks.json                 │
│    - Mark DAG node as "green" in design_graph.json          │
│    - Append to MEMORY.md                                    │
│    - Delete TASK.md                                         │
│ 5. Repeat from step 1                                       │
│                                                             │
│ ANTI-PATTERN TO AVOID:                                      │
│ - Creating one file that satisfies multiple tasks           │
│ - Writing to paths not in current task's allowed_paths      │
│ - Marking multiple tasks complete without individual cycles │
└─────────────────────────────────────────────────────────────┘
```

**Example TASK.md:**
```markdown
---
task_id: task_001
dag_node_id: create_models
allowed_paths:
  - src/models.py
priority: 1
---

# Task: Create Database Models

## Description
Create SQLite models for the todo application.

## Allowed Paths
You may ONLY write to: `src/models.py`

## Status: IN PROGRESS
```

6. Entering the Task Execution Loop

After generating the DAG and tasks, the agent exits (or continues). On the next loop iteration, because the DAG now exists, it proceeds to execute tasks.

The loop:

· Loads the current task list.
· Finds the next open task whose dependencies are satisfied (i.e., all dependency nodes are green in the DAG).
· Writes that task into TASK.md with its allowed_paths in the frontmatter.
· Calls the planner with the task description to get actions.
· Executes the actions, enforcing that any write operation stays within the allowed paths.
· If successful, marks the task as done, updates the DAG node to green, and appends a memory entry.
· Deletes TASK.md (or marks it done) and continues to the next task.

This continues until all DAG nodes are green.

7. User‑Injected DAG (or Manual Intervention)

If the user already has a DAG (e.g., a system architecture diagram), they can place it directly in SPAWN/STOP/state/design_graph.json before starting the agent. Then the loop will skip generation and go straight to execution. The DAG can also be edited later – the agent will respect the new structure on the next iteration.

---

Key Components of the Runtime

· loop.py – The main orchestrator of the autonomous loop.
· planner.sh (or any executable) – The model‑agnostic interface that reads state and returns actions (JSON).
· Vector memory – Stores embeddings of past tasks, successes, errors; retrieved before each task.
· security/ (in Start) – Immutable policy that enforces write restrictions and task scope.
· allowed_paths – Defined per task (from the DAG), the agent can only write to those locations.

---

Flow Diagram (Simplified)

```
User places prompt in TASK.md
│
▼
Loop.py reads TASK.md
│
▼
Check: design_graph.json exists?
│
┌────┴────┐
▼ ▼
No Yes
│ │
▼ │
Generate DAG │
from prompt │
│ │
▼ │
Create tasks │
│ │
└────┬────┘
▼
Execute tasks one by one
(respecting allowed_paths)
│
▼
Update DAG (red → green)
│
▼
Repeat until all nodes green
```

---

Code Snippet for the DAG Check (in loop.py)

```python
DESIGN_GRAPH = STOP_DIR / "state" / "design_graph.json"

# Inside the main loop
if not DESIGN_GRAPH.exists():
print("No design DAG found. Generating from prompt...")
generate_dag_from_prompt(body)
derive_tasks_from_dag()
print("Design DAG created. Please restart the loop to begin tasks.")
break
```

This is the only addition needed to make the agent accept a pre‑injected DAG.

---

Summary

The per‑repo agent is now complete:

· Bootstraps itself with immutable security.
· Waits for a TASK.md file.
· If no DAG exists, generates one using the planner.
· If a DAG exists (either generated or user‑injected), executes tasks in dependency order, respecting scoped writes.
· Uses vector memory to persist knowledge across tasks.
· All actions are logged and can be collected for training a custom model.

---

## DAG Validation Checklist

Before beginning task execution, validate the DAG:

### Structural Validation
- [ ] Each node has exactly ONE `allowed_paths` entry (or one directory for exclusive use)
- [ ] No two nodes share the same `allowed_paths` file
- [ ] All dependencies reference valid node IDs
- [ ] No circular dependencies exist
- [ ] At least one node has no dependencies (entry point)

### Semantic Validation
- [ ] Each node's `deliverables` describe ONE cohesive unit of work
- [ ] Dependencies reflect true blocking relationships (not artificial splits)
- [ ] Granularity is appropriate (5-30 min per task)
- [ ] File ownership is clear (one file = one owning node)

### Common Anti-Patterns to Reject
- [ ] **Entropy Introduction**: One file satisfying multiple nodes
- [ ] **False Modularity**: Splitting what should be one node into multiple
- [ ] **Path Collisions**: Multiple nodes writing to same file
- [ ] **Dependency Chains**: Artificial dependencies that create bottlenecks
- [ ] **Granularity Mismatch**: Nodes that are too large (>1 hour) or too small (<5 min)

### Validation Questions
Ask before executing:
1. "If I complete node A, will node B be unblocked?" (tests dependency validity)
2. "Can node C be written independently of node D?" (tests file ownership)
3. "Does this node produce one file or many?" (tests atomicity)
4. "What breaks if this task fails?" (tests granularity)

---

You now have the full picture. Build nonstop.
