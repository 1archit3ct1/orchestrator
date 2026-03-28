Orchestrator Structure

The original multi-repo scaffold document has been retired.

The active runtime is local-first and lives entirely inside `SPAWN/STOP/`.

Use these files instead of older child-repo diagrams:

- `README.md`
- `SPAWN/START/prompt.md`
- `SPAWN/STOP/.orchestrator/loop.py`
- `SPAWN/STOP/.orchestrator/dashboard_state.py`
- `SPAWN/STOP/.orchestrator/task_queue.json`

Retired structure:

- `SPAWN/STOP/repos/`
- child-repo dispatch and handoff flows
- child-repo log aggregation assumptions

Any future expansion beyond the local runtime should be introduced as a new documented architecture, not by reusing the retired pilot described in earlier revisions of this file.
