# SPAWN Point Architecture

**Location:** `SPAWN/` (forced LLM spawn point)

---

## Overview

All LLM interactions **MUST** originate from within `SPAWN/`. This is a forced constraint that ensures:

- ✅ Consistent working directory for all agents
- ✅ Centralized security and access control
- ✅ Unified audit logging
- ✅ Clear separation from documentation and config files

---

## Structure

```
orchestrator/
├── SPAWN/                      ← LLMs spawn ONLY here
│   ├── START/                  ← Bootstrap (run once)
│   │   └── bootstrap.sh
│   └── STOP/                   ← Runtime (work happens here)
│       ├── .orchestrator/      ← Core systems
│       ├── web/                ← Dashboard
│       ├── repos/              ← Child repos
│       ├── training/           ← ML pipeline
│       ├── state/              ← DAG & tasks
│       ├── TASK.md             ← Current task
│       └── MEMORY.md           ← Execution memory
├── HOWTOPROMPT.md              ← Documentation
├── orchestratorgraph.md        ← Documentation
└── Orchestratorstructure.md    ← Documentation
```

---

## Flow

```
Clone → SPAWN/START/bootstrap.sh → [Initialized] → SPAWN/STOP/ [Work Here]
```

---

## LLM Spawn Constraint

**Rule:** LLMs can ONLY access files within `SPAWN/`

**Enforcement:**
1. `START/` becomes immutable after bootstrap
2. All task execution happens in `STOP/`
3. Security manager enforces write locks
4. Audit logging tracks all access

**Working Directory:**
```bash
# Correct: Working from SPAWN
cd D:\NextAura\orchestrator\SPAWN
cd STOP
python .orchestrator/loop.py

# Incorrect: Working from root
cd D:\NextAura\orchestrator  ← WRONG
```

---

## Bootstrap (One-Time)

```bash
# From orchestrator root
cd SPAWN/START
./bootstrap.sh

# After bootstrap:
# - START/ becomes read-only
# - STOP/ is ready for work
# - Security vault initialized
# - Write locks available
```

---

## Runtime (Ongoing)

```bash
# All work happens in SPAWN/STOP/
cd SPAWN/STOP

# Run orchestrator loop
python .orchestrator/loop.py

# Or start web dashboard
python web/app.py
```

---

## Security Integration

**Security Manager Path:** `SPAWN/STOP/.orchestrator/security_manager.py`

**Usage:**
```python
from .orchestrator.security_manager import SecurityManager

security = SecurityManager()

with security.task_security_context(
    task_id="task_001",
    repo_name="my-repo",
    credential_keys=["OPENAI_API_KEY"]
) as ctx:
    # Execute task securely
    run_task()
```

---

## Iteration Logging

**Logger Path:** `SPAWN/STOP/.orchestrator/iteration_logger.py`

**Logs Location:** `SPAWN/STOP/.orchestrator/iterations/`

**Usage:**
```python
from .orchestrator.iteration_logger import IterationLogger

logger = IterationLogger()

logger.log_iteration(
    task_id="task_001",
    dag_node_id="setup_flask_app",
    prompt={"system": "...", "user": "..."},
    response={"content": "..."},
    outcome={"status": "success"}
)
```

---

## File Paths (SPAWN-Aware)

All paths in the system are now relative to `SPAWN/STOP/`:

| Component | Path |
|-----------|------|
| Vault | `SPAWN/STOP/.orchestrator/vault/` |
| Locks | `SPAWN/STOP/.orchestrator/locks/` |
| Iterations | `SPAWN/STOP/.orchestrator/iterations/` |
| Audit Logs | `SPAWN/STOP/.orchestrator/logs/security/` |
| Training Data | `SPAWN/STOP/.orchestrator/data/` |
| Models | `SPAWN/STOP/.orchestrator/models/` |

---

## Migration Notes

**Previous Structure:**
```
orchestrator/
├── START/
└── STOP/
```

**New Structure:**
```
orchestrator/
└── SPAWN/
    ├── START/
    └── STOP/
```

**Reason:** Forces all LLM spawn points to a single location for consistent security and access control.

---

**ENFORCEMENT:** All future LLM interactions MUST originate from `SPAWN/`. Any attempt to work outside this directory should be rejected.
